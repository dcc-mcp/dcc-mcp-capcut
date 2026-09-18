# dcc-mcp-capcut

Typed MCP adapter for CapCut Desktop. CapCut has no stable public Python API,
so this adapter uses a localhost, token-authenticated bridge and a bundled
CapCut-side panel. MCP calls remain typed and auditable; the panel is the only
component allowed to invoke CapCut host APIs.

## Capabilities

The bundled skills cover project lifecycle/settings, media import/relink and
proxies, timeline/clip editing, transitions, text and auto-captions, audio
mixing/fades, effects and color, AI helpers (background removal/stabilization),
video/thumbnail export, and a complete `build_vlog_demo` recipe.

## Run locally

```powershell
uv sync --extra dev
uv run pytest
uv run python -c "from dcc_mcp_capcut import start_server; start_server()"
```

## Guided installation and environment setup

The `capcut-setup` skill is built in. Call `detect_installation` and then
`installation_plan` when CapCut is missing. `auto_setup_capcut` executes the
full install-and-bind flow after receiving an operator-owned
`ui_control__system_operation` grant: it installs `ByteDance.CapCut` when
needed, configures the shared runtime/bridge, loads the panel, and verifies the
exact CapCut process. The adapter never shells out, edits the registry, or
silently installs software.

Install/load the panel from `src/dcc_mcp_capcut/capcut_panel` in the supported
CapCut extension host, then verify `GET /health` on the bridge URL. Set
`DCC_MCP_CAPCUT_BRIDGE_TOKEN` to a per-user secret for production use.

## Vlog demo

`demo/assets.json` records NASA/JPL public-domain source pages and attribution
notes. Run `python demo/fetch_assets.py`, then `python demo/render_vlog.py` for
an offline 9:16 proof in `demo/output/free-travel-vlog.mp4`. When CapCut is
available, call `auto_setup_capcut`, import the same assets, and replay
`demo/vlog_recipe.json` through `build_vlog_demo` for a native project export.

## Portable OpenTimelineIO export

Install `dcc-mcp-capcut[interchange]` to enable the `capcut-interchange`
skill's `export_otio` tool, or use the host-independent CLI:

```powershell
python -m dcc_mcp_capcut.interchange --input edit.json --output timeline.otio
```

The input is an explicit frame-based edit decision list, with `name`, `fps`,
`width`, `height`, `duration_frames`, and `tracks`. Each track has `name`,
`kind` (`Video` or `Audio`), and ordered `clips`. Each clip specifies `name`,
relative `media` path, timeline `start`, optional `source_in` (default 0),
`duration`, and `media_duration`; all time values are integer frames at `fps`.
Optional `captions` contain `text`, `start`, and `duration` and become markers.
See [the interchange contract](docs/interchange.md) for a complete example.

The exporter preserves gaps, source trims, separate tracks and fractional
frame rates. It rejects overlaps, out-of-range edits, absolute/traversing media
paths and unknown fields. The CLI refuses to overwrite an existing file.

This is export from supplied edit decisions, not a readback of a live CapCut
project. Bake unsupported effects into media and include SRT for editable
subtitles. Ship all referenced media with the OTIO file, and resolve relative
paths from its directory. Other applications may require an OTIO importer.

## Preflight diagnostics

`dcc-mcp-capcut-doctor` is a read-only preflight entry point. It collects the
evidence the adapter needs before it binds a window, so a failed start reports
one diagnosable cause plus a remediation instead of a traceback:

```powershell
dcc-mcp-capcut-doctor             # human-readable summary
dcc-mcp-capcut-doctor --fix-hints # add remediation steps
dcc-mcp-capcut-doctor --json      # machine-readable report
```

It checks the Python version, `dcc_mcp_core` against the CI-verified floor, the
runtime bundle handshake, the CapCut executable, `dcc-cua` availability and
window uniqueness, the bridge port and token, the bundled panel payload, the
optional Qt probe configuration, and `opentimelineio`.

Every check is `ok`, `warn` (the adapter still starts, but degraded or with an
optional feature disabled), `fail` (the adapter cannot start in this state), or
`skip` (not applicable to this platform). The exit code is `0` when nothing
failed and `1` when at least one check failed. The doctor never installs,
writes, or mutates anything.

## Runtime boundary

The adapter is an external-bridge (`instance_type=gui`) service. It does not
invent a CapCut API, use raw script execution, or silently fall back to generic
computer automation. For UI verification use the project-owned `dcc-cua` /
`ui-control` route with an exact CapCut PID and HWND.

`dcc-mcp-runtime` is distributed as a separately verified runtime bundle, not
as a PyPI dependency. The `dcc-mcp-capcut-runtime` entry point refuses to start
when that runtime is missing, its CapCut manifest is stale, or required
handshake metadata is absent.
