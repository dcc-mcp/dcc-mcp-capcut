# Loading the bundled panel

This file explains what the bundled panel is, what it needs in order to run,
and how to confirm it is connected. Read it before trying to drive any
host-bound capability: without a running panel, every host action fails with a
bridge timeout.

## Why this is required

The adapter never talks to CapCut directly. It is an **external-bridge**
adapter: an MCP tool call is placed on a loopback queue, and the panel drains
that queue, performs the edit inside CapCut, and posts the result back.

```
MCP client -> dcc-mcp-capcut server -> bridge queue (/call)
                                            |
                                    panel polls /next  <-- must run INSIDE CapCut
                                            |
                                    window.CapCut.dispatch(action, params)
```

Without the panel nothing drains the queue. After `BRIDGE_TIMEOUT_SECONDS`
(30 s) the bridge abandons the request and the action fails.

## What the panel is

`capcut_panel/` is a **static web page**, not a native plugin:

| File | Role |
| --- | --- |
| `index.html` | Minimal host page; renders the connection status. |
| `panel.js` | Polls `/next` every 100 ms, calls `window.CapCut.dispatch(...)`, posts the outcome to `/result`. |
| `HOST_API.md` | The contract the **host integration** must satisfy (written for whoever implements `window.CapCut`, not for the operator loading the panel). |

It is served over loopback HTTP only. Both URLs and the token are overridable
from the page's `window` scope:

```js
const baseUrl = window.DCC_MCP_CAPCUT_BRIDGE_URL || "http://127.0.0.1:47410";
const token   = window.DCC_MCP_CAPCUT_BRIDGE_TOKEN || "dev-token";
```

## What the panel requires

The page is inert on its own. It needs to run in a JavaScript context
**inside the CapCut process** where a host integration has injected:

```js
window.CapCut = { dispatch(action, params) -> Promise<object> }
```

If `window.CapCut` is missing, the panel does not guess or fall back — it
reports the failure back to MCP:

```js
throw new Error("CapCut host API is unavailable; install the matching panel build");
```

Two consequences worth stating plainly:

- Opening `index.html` in an ordinary browser (Edge, Chrome) is **not** enough.
  The page will load and poll the bridge, but every action fails with the
  "host API is unavailable" error because no `window.CapCut` exists there.
- The panel must therefore be loaded through whatever web-content host the
  CapCut build exposes. CapCut Desktop is CEF/WebView2 based (its install
  directory ships `CefCreator.dll`, a `cef/` directory and `PlatinumWebView.dll`,
  and runs `msedgewebview2.exe` child processes), so it can host web content —
  but **the loader that places this page into that host is supplied by the
  CapCut-side host integration, not by this package.**

## Status: no loader ships with this package

**This repository does not currently ship a supported, automatic way to inject
the panel into CapCut.** The `capcut-setup` skill documents `install_capcut`
and `auto_setup_capcut` as installing CapCut and configuring the bridge, but
the panel-injection step is explicitly left to the operator and is
consent-gated: the adapter never edits the registry, never writes into the
CapCut install tree, and never silently installs software.

That is deliberate. Injecting code into a third-party application without an
explicit, operator-owned grant would be exactly the behaviour this adapter is
designed to avoid.

So the practical position today:

- The panel **can** be built and verified as a payload (see below).
- Getting it running inside CapCut requires a CapCut-side host integration,
  which is operator/owner work and is out of scope for this package.
- Until that integration exists, `panel_connected` stays `false` and all
  host-bound capabilities remain unverifiable.

## Verifying the panel payload

`dcc-mcp-capcut-doctor` checks that the payload is complete. It does **not**
check that CapCut is hosting it:

```
[  ok]  panel_files   the bundled panel payload is complete
```

Expected files, relative to the installed package's `capcut_panel/` directory:
`HOST_API.md`, `index.html`, `panel.js`.

## Verifying the panel is actually connected

The authoritative signal is the bridge health endpoint, which reports whether a
panel has been seen within the lease window:

```bash
curl -H "X-DCC-MCP-Token: $DCC_MCP_CAPCUT_BRIDGE_TOKEN" \
     http://127.0.0.1:47410/health
```

```json
{"ok": true, "pending": 0, "panel_connected": true}
```

- `panel_connected: true` — a panel polled `/next` within the lease window.
  Host actions will be dispatched.
- `panel_connected: false` — nothing is draining the queue. Host actions will
  time out after 30 s.

`verify_installation()` reports the same value as `panel_connected`, and its
`ready` flag requires it. A successful end-to-end setup therefore looks like:

```
[  ok]  capcut_executable  found C:\Users\...\CapCut\Apps\CapCut.exe
[  ok]  dcc_cua            exactly one visible CapCut main window (pid=..., hwnd=...)
[  ok]  bridge_port        127.0.0.1:47410 is free
[  ok]  panel_files        the bundled panel payload is complete
```

with `panel_connected: true` once the panel is hosted.

## Troubleshooting

| Symptom | Meaning | Action |
| --- | --- | --- |
| `HTTP Error 503: Service Unavailable` | No panel drained the queue within 30 s. | Confirm a panel is running **inside** CapCut and re-check `/health`. |
| `CapCut bridge did not respond; open the bundled panel` (response body) | Same cause. Note the adapter surfaces only `HTTP Error 503`, not this string. | Same as above. |
| `CapCut host API is unavailable; install the matching panel build` | The panel is loaded but `window.CapCut` is not injected — typically opened in a normal browser rather than inside CapCut. | Load it through a CapCut-side host integration that provides `window.CapCut`. |
| `panel_files` fails in doctor | The payload is incomplete in the installed package. | Reinstall; check `capcut_panel/` contains all three files. |
| `/health` returns 403 | Token mismatch between the panel and the bridge. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides. |

## Security notes

- The bridge listens on loopback only and requires `X-DCC-MCP-Token`.
- The default token is `dev-token`, intended for local development. Set
  `DCC_MCP_CAPCUT_BRIDGE_TOKEN` to a per-user secret for anything else.
- No tool in this catalog exposes raw script execution or a generic automation
  fallback; the panel can only invoke the typed actions in `HOST_API.md`.
