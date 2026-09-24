---
name: capcut-setup
description: Detect CapCut, execute a consent-gated install-and-bind flow, configure the bridge, and verify readiness.
license: MIT
compatibility: "Windows CapCut/JianyingPro Desktop, macOS CapCut/JianyingPro (剪映专业版) bundles; Linux unsupported; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.2.0", layer: infrastructure, stage: setup, tags: "capcut, install, setup, readiness", tools: tools.yaml}  # x-release-please-version
---

Run this skill **first**, before any other `capcut-*` skill. Everything else in
this catalog assumes an installed CapCut, a reachable bridge, and an exactly
bound window; this skill is what establishes and proves that state.

## When to use

- The adapter has just been installed, or moved to a new machine.
- Any other skill fails with a bridge, panel, or window-binding error.
- You need evidence that setup actually completed, rather than an assumption.

## Host platforms

Detection, install planning and the doctor verdict all dispatch through a
platform provider. Read the row for the host you are on before interpreting a
result.

| Platform | Discovery | Install plan | Doctor `capcut_executable` |
| --- | --- | --- | --- |
| Windows | `CapCut.exe` / `JianyingPro.exe` under `%LOCALAPPDATA%\<app>\Apps` and `%PROGRAMFILES%\<app>` | exact `winget install` command | `ok` / `fail` |
| macOS | `CapCut.app` / `JianyingPro.app` bundles under `/Applications` and `~/Applications`, with the `Info.plist` bundle version | `brew install --cask` where a cask exists, otherwise the official download page | `ok` / `fail` |
| Linux | none — no official client exists | none; `status: unsupported` with the reason | `skip`, reported as `unsupported` |

## Prerequisites

- A **Windows or macOS** host that owns the CapCut or 剪映专业版 window. Linux
  has no official client, so the adapter cannot bind a host there.
- macOS window binding additionally needs **Accessibility permission** for the
  controlling app (System Settings > Privacy & Security > Accessibility). It is
  a user-side grant: the adapter reports it, never requests or bypasses it.
- `dcc-cua` on `PATH` for the read-only window inventory (Windows). macOS
  support for the inventory CLI is still being validated, so the doctor warns
  instead of failing when it is absent.
- No grant is needed for `detect_installation`, `installation_plan`, or
  `verify_installation`. `install_capcut`, `auto_setup_capcut`, and
  `configure_environment` are consent-gated and require an operator-owned
  `ui_control__system_operation` grant and its `grant_id`.

## Tools

| Tool | Side effects | Notes |
| --- | --- | --- |
| `detect_installation` | none | Read-only discovery through the platform provider, for **both** shipped editions. Windows: `%LOCALAPPDATA%\<app>\Apps\<exe>` and `%PROGRAMFILES%\<app>\<exe>`, where `<app>`/`<exe>` is `CapCut`/`CapCut.exe` or `JianyingPro`/`JianyingPro.exe`. macOS: `CapCut.app` and `JianyingPro.app` under `/Applications` and `~/Applications`, with the `Info.plist` bundle version. Reports `provider` and `supported`; on Linux reports `unsupported` with a reason. |
| `installation_plan` | none | A reviewable per-platform plan: the exact WinGet command on Windows, `brew install --cask capcut` or the official download page on macOS, and an explicit `unsupported` verdict on Linux. Never installs anything. |
| `install_capcut` | installs software | Requires `grant_id`; runs through the host grant, never a local shell. |
| `auto_setup_capcut` | installs + binds | One consent-gated flow: install when missing, configure the shared runtime, load the panel, verify. Idempotent. |
| `configure_environment` | mutates bridge config | Requires `grant_id`; returns the effective bridge URL, port, and panel path. |
| `verify_installation` | none | Read-only readiness evidence. |

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `grant_id is required; obtain it from an operator-owned ui_control system grant` | A consent-gated tool was called without a grant. | Obtain the operator grant. Never substitute a local shell command or infer consent. |
| `no CapCut executable found` (Windows) | CapCut Desktop is not installed at any known candidate path. | Run `installation_plan`, have an operator approve it, then `install_capcut` with the grant. |
| `no CapCut or JianyingPro application bundle found` (macOS) | Neither `/Applications` nor `~/Applications` holds a CapCut or 剪映专业版 bundle. | Run `installation_plan` for the `brew install --cask capcut` route or the official download page, then approve it with an operator grant. |
| `CapCut Desktop is unsupported on Linux` | ByteDance publishes no official Linux client, so there is no host to bind. | Run the adapter on the Windows or macOS host that owns the window. Do not look for a Linux package; none exists. |
| `dcc-cua is not installed or not on PATH; window binding is unverified` (macOS) | macOS support for the inventory CLI is not validated yet, so binding is unproven rather than broken. | Install `dcc-cua` if a macOS build is available and grant Accessibility; the adapter still runs host-free skills. |
| `no visible CapCut main window was found` | Installed but not running, or minimized/off-screen. | Launch CapCut and complete first-run prompts manually; leave the main window visible and restored. |
| `multiple visible CapCut main windows were found` | The binding is ambiguous and is deliberately refused. | Close the extra CapCut windows. |
| `dcc-cua window inventory is unavailable` | The inventory CLI is missing or hung. | Install `dcc-cua` on `PATH`, restart a hung process, re-run the doctor. |
| `the bundled panel payload is incomplete` | The wheel was installed without its panel payload. | Reinstall the adapter wheel. |
| `CapCut bridge did not respond; open the bundled panel` | The broker is up but no panel drained the action within 30 s. | Load the panel in the CapCut extension host, confirm `/health` shows `panel_connected: true`, retry. |
| `127.0.0.1:<port> is already in use` | Another instance owns the loopback port. | Stop it, or set `DCC_MCP_CAPCUT_BRIDGE_PORT` to a free port and restart. |
| `<edition> <version> on <platform> is not in the verified host matrix` | The installed build is not one the adapter was acceptance-tested against. | The adapter still binds and starts; run a smoke edit and record the version so it can be added to the matrix. |
| `the installed <edition> version on <platform> could not be read` | The build is installed but its version is not discoverable on this platform. | Read the version from the CapCut about box and record it; the doctor cannot grade a build it cannot see. |

## Acceptance

`verify_installation` reports `ready: true` only when **all** of the following
hold. Do not treat a partial result as readiness:

- `installed` — the CapCut executable or macOS application bundle exists.
- `exact_window_bound` — both `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` resolve to positive integers.
- `bridge_reachable` — `GET /health` answers `ok`.
- `panel_connected` — the panel polled `/next` within the 35 s lease.

The token is deliberately **not** one of the gates. `ready` answers whether the
adapter can bind this host and reach the panel on the token actually in force,
and the documented default `dev-token` is a token that works, so it cannot turn
a working setup into `ready: false`. A weak token is a security warning, not a
wiring fault, and the two token facts are reported separately:

- `bridge_token_configured` — an operator-set token exists.
- `token_is_default` — the token in force is the shared default. This is True
  both when the token is unset and when it is explicitly `dev-token`, because
  in both cases the bridge speaks the default.

Treat `token_is_default: true` as an action item, not as a setup failure: set
`DCC_MCP_CAPCUT_BRIDGE_TOKEN` to a per-user secret before production use. The
doctor grades it as `warn` through `check_bridge_token`.

Then confirm with `inspect_project` from `capcut-project` before any mutation.

## Boundaries

- This skill never shells out to an installer, never edits the registry, and
  never installs software silently. Installation runs only through an
  operator-owned grant.
- `auto_setup_capcut` must not report readiness before the process, bridge
  health, panel load, and exact PID/HWND binding are all verified.
- Installing this adapter grants no CapCut license. CapCut is a closed-source
  run-time dependency and is not redistributed here.

## References

- [host boundary](../references/host-boundary.md) — includes the platform support matrix
- [platform providers](../references/host-platforms.md)
- [dependencies and notices](../references/dependencies-and-notices.md)
- [troubleshooting](../references/troubleshooting.md)
