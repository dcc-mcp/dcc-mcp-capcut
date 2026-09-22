# Troubleshooting

## First move

Run the read-only preflight before changing anything:

```powershell
dcc-mcp-capcut-doctor             # human-readable summary
dcc-mcp-capcut-doctor --fix-hints # add remediation steps
dcc-mcp-capcut-doctor --json      # machine-readable report
```

Exit code `0` means nothing failed (warnings and skips are tolerated); `1` means
at least one check failed. Each check is `ok`, `warn`, `fail`, or `skip`. Checks
run in this order: `python`, `dcc_mcp_core`, `runtime_handshake`,
`capcut_executable`, `dcc_cua`, `bridge_port`, `bridge_token`, `panel_files`,
`qt_probe`, `opentimelineio`. The doctor installs, writes and mutates nothing.

## Symptom to cause to remediation

| Symptom | Cause | Remediation |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. The broker is up; the CapCut-side consumer is not. | Load the bundled panel in the CapCut extension host, confirm `GET /health` reports `panel_connected: true`, then retry. The panel lease is 35 s — an idle panel expires. |
| `forbidden` (HTTP 403) | `X-DCC-MCP-Token` mismatch between the adapter and the panel. | Set the same `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| HTTP 503 from `/call` | The broker rejected the payload (`action` missing or `params` not an object). | Fix the caller; the typed skills already supply a dict. |
| `CapCut action '<action>' lacks verified post-operation readback` | The panel returned an acknowledgement instead of `verification: {ok: true, ...}`. | Fix the host integration per `capcut_panel/HOST_API.md`. Do not retry hoping for a different verdict. |
| `CapCut action '<action>' did not return <id>` | A required stable ID is missing. | Return the ID listed in `export-and-verification.md` for that action. |
| `CapCut action '<action>' lacks timeline readback` | A timeline mutation omitted `verification.timeline`. | Return the authoritative timeline readback. |
| `CapCut action '<action>' returned a non-object result` | The host returned a scalar, list, or null. | Return a JSON object. |
| `127.0.0.1:<port> is already in use` (doctor `bridge_port`) | Another instance owns the loopback port. | Stop that instance, or set `DCC_MCP_CAPCUT_BRIDGE_PORT` to a free port and restart. |
| `DCC_MCP_CAPCUT_BRIDGE_TOKEN` unset or the insecure default (doctor `bridge_token`, `warn`) | No per-user secret configured. | Set a per-user secret, e.g. `python -c "import secrets;print(secrets.token_urlsafe(32))"`. |
| `the bundled panel payload is incomplete` (doctor `panel_files`) | The wheel was installed without its payload. | Reinstall the adapter wheel; the panel ships inside the package. |
| `no visible CapCut main window was found` | CapCut is not running, is minimized, or its main window is off-screen. | Launch CapCut Desktop, complete first-run prompts manually, and leave the main window visible and restored. |
| `multiple visible CapCut main windows were found` | The binding is ambiguous and is refused rather than guessed. | Close the other CapCut windows so exactly one main window remains. |
| `dcc-cua window inventory is unavailable` / `dcc-cua returned invalid window inventory JSON` | `dcc-cua` is missing, hung, or emitting a non-array. | Install `dcc-cua` on `PATH`, restart a hung process, then re-run the doctor. |
| `no CapCut executable found` (Windows) | CapCut Desktop is not installed at any known candidate path. | Call `capcut-setup`'s `installation_plan`, then execute it with an operator-owned grant. |
| `no CapCut or JianyingPro application bundle found` (macOS) | Neither `/Applications` nor `~/Applications` holds a 剪映/CapCut bundle. | Run `installation_plan` for the `brew install --cask capcut` route or the official download page, then approve it with an operator grant. |
| `CapCut Desktop is unsupported on Linux` (`skip`) | ByteDance publishes no official Linux client, so the prerequisite does not apply. | Run the adapter on the Windows or macOS host that owns the window. There is no Linux package to install. |
| `dcc-cua is not installed or not on PATH; window binding is unverified` (`warn`, macOS) | macOS support for the inventory CLI is still being validated, so binding is unproven rather than broken. | Install a macOS `dcc-cua` build if one is available and grant Accessibility permission to the controlling app. |
| `Qt probe is not configured; no native capabilities established` | `DCC_CAPCUT_PROBE_ENDPOINT` or a >=32-byte `DCC_CAPCUT_PROBE_TOKEN` is missing. | Configure the probe environment, or use the panel-backed skills instead. The probe is optional. |
| `Qt probe requires an explicit host PID and executable SHA-256` | Missing/invalid `DCC_CAPCUT_PROBE_EXE_SHA256` (64 lowercase hex) or `DCC_MCP_CAPCUT_PID`. | Supply both for the bound host. |
| `Qt probe endpoint does not match the bound host` / `Qt probe response does not match the bound host` | The endpoint file or response describes a different PID, executable hash, protocol, or backend. | Restart the host to write a fresh endpoint file; delete stale endpoint files after the host exits. |
| `Qt probe rejected the metadata request` | The probe refused the operation (unsupported op, bad limits, or failed authorization). | Check `max_nodes`/`max_depth` bounds and the shared token. |
| `DCC_MCP_RUNTIME_MISSING` | The verified `dcc-mcp-runtime` bundle is not installed. | Install it, or start the adapter with the plain `dcc-mcp-capcut` entry point, which does not need it. |
| `DCC_MCP_RUNTIME_HANDSHAKE_INVALID` / `DCC_MCP_RUNTIME_ADAPTER_VERSION_MISMATCH` | The runtime manifest is stale or lacks handshake metadata. | Reinstall the runtime bundle and the matching adapter wheel. |
| `Install dcc-mcp-capcut[interchange] for OTIO support` / doctor `opentimelineio` `warn` | The optional OTIO extra is missing. | `pip install 'dcc-mcp-capcut[interchange]'`. Only `capcut-interchange` is affected. |
| `grant_id is required; obtain it from an operator-owned ui_control system grant` | A consent-gated action was called without a grant. | Obtain the operator-owned grant; the adapter will not install or configure anything without it. |
| `ffmpeg and ffprobe are required to render the offline demo` | External binaries missing from `PATH`. | Install FFmpeg, or skip the offline demo and use the CapCut-backed export path. |

## Escalation

Attach `dcc-mcp-capcut-doctor --json` output to any bug report. If a diagnostic
itself fails, the doctor records it as a `fail` with
`the diagnostic itself failed: ...` — treat that as a bug in the adapter, not in
the host.

## See also

- `host-boundary.md` — the external-bridge boundary and the bridge contract.
- `dependencies-and-notices.md` — licenses and redistribution facts.
- `export-and-verification.md` — the post-operation readback contract.
