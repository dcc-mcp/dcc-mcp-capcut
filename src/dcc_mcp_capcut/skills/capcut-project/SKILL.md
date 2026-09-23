---
name: capcut-project
description: Manage CapCut projects and project-level settings through the typed bridge.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.2.0", layer: domain, stage: scene, tags: "capcut, project, video", tools: tools.yaml}  # x-release-please-version
---

Project lifecycle and canvas settings. Call `inspect_project` before any
mutation here or in another `capcut-*` skill, so you are editing the project you
think you are editing.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- Matching `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on the adapter and the panel.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `inspect_project` | no | yes | Open project, active timeline, media counts. |
| `create_project` | yes | no | Requires `name`; accepts `width`, `height`, `fps`. Returns `project_id`. |
| `save_project` | yes | yes | Optional `path`; returns the saved path. |
| `close_project` | yes | no | `save` defaults to `true`. |
| `get_project_settings` | no | yes | Canvas, frame rate, color, export defaults. |
| `set_project_settings` | yes | yes | Canvas and frame rate; idempotent, safe to re-apply. |

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel in the CapCut extension host, confirm `/health` shows `panel_connected: true`, retry. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action 'create_project' did not return project_id` | The host acknowledged without a stable ID. | Fix the host integration per `capcut_panel/HOST_API.md`; the adapter refuses to report success without it. |
| `CapCut action '<action>' lacks verified post-operation readback` | Acknowledgement-only result. | Same as above — a bare `{accepted: true}` is an error, not a success. |
| `save_project` returns an unexpected path | The host redirected the save location. | Treat the returned path as authoritative; do not assume the requested path. |

## Acceptance

- `inspect_project` reflects the intended state after every mutation. Re-read it
  rather than trusting the mutation's return value alone.
- `create_project` returned a `project_id`; `set_project_settings` is confirmed
  by a follow-up `get_project_settings` showing the new canvas and frame rate.
- `save_project` returned a concrete saved path and `close_project` completed
  with the save decision you intended (`save` defaults to `true`).

## Boundaries

- Mutating results must carry `verification: {ok: true, ...}`; the adapter raises
  instead of reporting a half-truth.
- `close_project` discards unsaved work when `save: false`. Ask the user before
  passing it.
- No tool here exposes raw script execution or a generic automation fallback.
- Changing project settings does not re-conform existing media; source frame
  rates must be conformed before interchange.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [troubleshooting](../references/troubleshooting.md)
