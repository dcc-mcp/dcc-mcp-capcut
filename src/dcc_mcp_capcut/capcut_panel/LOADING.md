# Loading the bundled panel

This file explains what the bundled panel is, what it needs in order to run,
and how to confirm it is connected. Read it before trying to drive any
host-bound capability: without a working panel, no host action can complete.

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

Without the panel nothing drains the queue, so the request is eventually
abandoned. `CapCutBridge.submit()` waits on the result event with a `timeout`
parameter whose default is 30 s (`src/dcc_mcp_capcut/bridge.py`); skill calls
reach it through `call_bridge()`, whose `urlopen(..., timeout=35)` bounds the
whole round trip. Neither value is an environment variable or config setting —
both are hard-coded keyword defaults, so there is nothing to tune.

A poller that is alive but has no `window.CapCut` does **not** hit that timeout:
it takes the job and fails it immediately. Do not treat "it failed fast" as
evidence that a panel was connected.

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

  That description comes from inspecting CapCut Desktop installs, not from
  anything this repository tests, so verify it on your own machine before
  relying on it. Take the install directory from the doctor's
  `capcut_executable` line and probe it:

  ```powershell
  where.exe /R "<CapCut install directory>" CefCreator.dll PlatinumWebView.dll
  ```

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
- Until that integration exists, no host-bound capability can complete —
  either nothing polls the bridge (so `panel_connected` stays `false`), or a
  page polls it from outside CapCut (so `panel_connected` turns `true` while
  every action still fails immediately). Reading `panel_connected` alone does
  not distinguish those two cases; see the next section.

## Verifying the panel payload

`dcc-mcp-capcut-doctor` checks that the payload is complete. It does **not**
check that CapCut is hosting it:

```
[  ok]  panel_files   the bundled panel payload is complete
```

Expected files, relative to the installed package's `capcut_panel/` directory:
`HOST_API.md`, `index.html`, `panel.js`.

## Verifying the panel is actually connected

The bridge health endpoint reports whether a panel has been seen within the
lease window:

```bash
curl -H "X-DCC-MCP-Token: $DCC_MCP_CAPCUT_BRIDGE_TOKEN" \
     http://127.0.0.1:47410/health
```

```json
{"ok": true, "pending": 0, "panel_connected": true}
```

`panel_connected` is a **liveness signal for a poller**, not a readiness
prognosis for the host. `CapCutBridge.next()` records the poll timestamp as soon
as `/next` is called, before the panel ever looks at `window.CapCut`, so any
page that can reach the bridge turns this flag on — including the panel opened
in a normal browser, which can never dispatch anything.

- `panel_connected: true` — a page polled `/next` within the lease window
  (`CapCutBridge.PANEL_LEASE_SECONDS`, 35 s). Host actions will be picked up
  and *attempted*. They still fail immediately if that page has no
  `window.CapCut`, so this flag does **not** mean "connected to CapCut".
- `panel_connected: false` — nothing has polled `/next` within the lease
  window, so nothing is draining the queue. Host actions stay queued until the
  request timeout expires.

The two states a poller can be in — inside CapCut with a working
`window.CapCut`, or outside it without one — both report `panel_connected:
true`. The only evidence that separates them is a host action that actually
succeeds.

`verify_installation()` reports the same value as `panel_connected`, and its
`ready` flag requires it. A successful end-to-end setup therefore looks like:

```
[  ok]  capcut_executable  found C:\Users\...\CapCut\Apps\CapCut.exe
[  ok]  dcc_cua            exactly one visible CapCut main window (pid=..., hwnd=...)
[  ok]  bridge_port        127.0.0.1:47410 is free
[  ok]  panel_files        the bundled panel payload is complete
```

with `panel_connected: true` once the panel is polling — remembering that this
flag alone does not prove the host API is reachable.

## Troubleshooting

`call_bridge()` uses `urlopen`, which raises on a non-2xx status without
reading the body, so a failed action always surfaces as `HTTP Error 503: Service
Unavailable` no matter which of the two causes below produced it. `/health`
cannot separate them either: in the host-API case it happily reports
`panel_connected: true`. To see which message the bridge actually returned, call
it directly and read the body:

```bash
curl -i -H "Content-Type: application/json" \
     -H "X-DCC-MCP-Token: ${DCC_MCP_CAPCUT_BRIDGE_TOKEN:-dev-token}" \
     -d '{"action":"<action>","params":{}}' \
     http://127.0.0.1:47410/call
```

| Symptom | Meaning | Action |
| --- | --- | --- |
| `HTTP Error 503: Service Unavailable` | The action did not complete. Either nothing polled the bridge within the request timeout, or the poller had no `window.CapCut`. | Read the `/call` response body (command above) to tell the two apart. |
| `CapCut bridge did not respond; open the bundled panel` (response body) | No panel drained the queue within 30 s. Note the adapter surfaces only `HTTP Error 503`, not this string. | Confirm a panel is polling **inside** CapCut, then retry. |
| `CapCut host API is unavailable; install the matching panel build` (response body) | A page is polling the bridge, but `window.CapCut` is not injected — typically the panel was opened in a normal browser rather than inside CapCut. The adapter surfaces only `HTTP Error 503`, not this string. | Load it through a CapCut-side host integration that provides `window.CapCut`. |
| `/health` shows `panel_connected: true`, but every action fails | The poller is alive and takes each job, then fails before any CapCut edit. This is the normal-browser case, and `/health` is not able to rule it out. | Read the `/call` response body to confirm which of the two strings above came back; only a successful action proves the host is real. |
| `panel_files` fails in doctor | The payload is incomplete in the installed package. | Reinstall; check `capcut_panel/` contains all three files. |
| `/health` returns 403 | Token mismatch between the panel and the bridge. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides. |

## Security notes

- The bridge listens on loopback only and requires `X-DCC-MCP-Token`.
- The default token is `dev-token`, intended for local development. Set
  `DCC_MCP_CAPCUT_BRIDGE_TOKEN` to a per-user secret for anything else.
- No tool in this catalog exposes raw script execution or a generic automation
  fallback; the panel can only invoke the typed actions in `HOST_API.md`.
