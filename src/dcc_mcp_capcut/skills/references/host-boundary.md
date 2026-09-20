# Host boundary

Read this before calling any `capcut-*` skill. It defines what this adapter may
touch, what it may never touch, and which component owns the CapCut host API.

## The adapter is an external bridge, not an embedded plugin

CapCut Desktop has no stable public Python API. The adapter therefore runs
out-of-process as an **external-bridge adapter** (`instance_type=gui`):

```text
MCP client -> dcc-mcp-capcut (typed tools) -> loopback bridge -> bundled panel -> CapCut host API
```

- Typed skills enqueue one action; they never execute host code themselves.
- The bundled panel (`dcc_mcp_capcut/capcut_panel`) is **the only component
  allowed to invoke CapCut host APIs**, through `window.CapCut.dispatch(action,
  params)`. See the panel's `HOST_API.md` for the contract it must satisfy.
- No MCP tool exposes raw script execution, an arbitrary shell, or a generic
  computer-automation fallback.

## Consent and side effects

- `install_capcut`, `auto_setup_capcut`, and `configure_environment` are
  consent-gated. They require an operator-owned `ui_control__system_operation`
  grant and its `grant_id`; the adapter never shells out to an installer, never
  edits the registry, and never silently installs software.
- The adapter never claims readiness before the CapCut process, bridge health,
  panel load, and exact PID/HWND binding are all verified.
- Read-only tools (`detect_installation`, `verify_installation`,
  `inspect_project`, `list_media`, `list_timelines`, `get_export_status`,
  `describe_qt_host`, `inspect_qt_objects`, `export_otio`) install, write and
  mutate nothing.

## Exact-window binding

The adapter binds **one** visible, restored (non-minimized) CapCut main window.
PID and HWND must be supplied together and must be positive; ambiguity is
rejected rather than resolved by guessing.

| Variable | Set by | Meaning |
| --- | --- | --- |
| `DCC_MCP_CAPCUT_PID` | the adapter from the binding | exact CapCut process id |
| `DCC_MCP_CAPCUT_WINDOW_HANDLE` | the adapter from the binding | exact CapCut main-window handle |
| `DCC_MCP_UI_CONTROL_PROCESS_ID` | the adapter | same PID for project-owned UI control |
| `DCC_MCP_UI_CONTROL_WINDOW_HANDLE` | the adapter | same HWND for project-owned UI control |
| `DCC_MCP_CAPCUT_WINDOW_TITLE` | operator (default `CapCut`) | window title to match |

Window discovery uses `dcc-cua list`, the project-owned, read-only inventory
CLI. UI verification must go through the project-owned `dcc-cua` / `ui-control`
route with the exact PID and HWND; never substitute a generic computer-use
provider.

## Bridge contract

| Variable | Default | Meaning |
| --- | --- | --- |
| `DCC_MCP_CAPCUT_BRIDGE_PORT` | `47410` | loopback port of the broker |
| `DCC_MCP_CAPCUT_BRIDGE_URL` | `http://127.0.0.1:47410` | base URL; `/call`, `/next`, `/result`, `/health` |
| `DCC_MCP_CAPCUT_BRIDGE_TOKEN` | `dev-token` | shared secret sent as `X-DCC-MCP-Token` |

- The broker listens on `127.0.0.1` only and rejects requests without a matching
  token.
- `GET /health` reports broker health and `panel_connected`. The panel lease is
  35 s: a panel that has not polled `/next` within that window counts as
  disconnected even while the broker is up.
- A submitted action waits 30 s for the panel to drain and post a result. Past
  that, the caller gets `CapCut bridge did not respond; open the bundled panel`.
- Set `DCC_MCP_CAPCUT_BRIDGE_TOKEN` to a per-user secret for anything beyond
  local development. `dcc-mcp-capcut-doctor` warns on the default token.

## Runtime bundle

`dcc-mcp-capcut-runtime` starts through the separately verified shared
`dcc-mcp-runtime` bundle and refuses to start when it is missing, when its
CapCut manifest is stale, or when handshake metadata is absent. The plain
`dcc-mcp-capcut` entry point does not require the bundle.

## What installing a skill does not grant

- No access to CapCut source, a CapCut SDK, or any CapCut license. CapCut is a
  closed-source run-time dependency and is **not** redistributed here.
- No access to the `dcc-mcp-core` repository or its internals; only the
  published PyPI package is a dependency.
- No right to install software, mutate the host, or act on a window that was not
  explicitly bound.

## See also

- `dependencies-and-notices.md` — third-party licenses and redistribution facts.
- `export-and-verification.md` — the post-operation readback contract.
- `troubleshooting.md` — symptom to cause to remediation.
