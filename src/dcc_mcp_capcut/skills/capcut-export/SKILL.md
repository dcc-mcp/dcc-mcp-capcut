---
name: capcut-export
description: Export, monitor, cancel, and validate CapCut renders.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.19+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: delivery, tags: "capcut, export, render", tools: tools.yaml}
---

Render delivery. A render is not delivered until the artifact exists on disk and
has been probed independently.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- A finished timeline. Exporting an incomplete edit only produces a faster
  mistake.
- A writable `output_path` whose parent directory exists, with enough free space
  for the chosen codec and bitrate.
- Patience: `export_video` allows 600 s and `build_vlog_demo` 900 s. Poll
  `get_export_status` instead of assuming completion.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `export_video` | yes | yes | Async. `output_path` plus optional `timeline_id`, `format` (`mp4`, `mov`), `codec` (`h264`, `h265`, `prores`), size, `fps`, `bitrate_mbps`, `audio`. Returns `job_id` or `output_path`; poll `get_export_status` with the `job_id`. |
| `get_export_status` | no | yes | Progress and terminal state for a `job_id`, plus output validation. Completeness is only proved by a reported success **and** an on-disk file. |
| `cancel_export` | yes | yes | `job_id` of a running job. Idempotent: cancelling twice is safe. Needs `verification.ok: true`; returns no stable ID, so confirm the terminal state with `get_export_status`. |
| `export_thumbnail` | yes | yes | Still frame at `time`; returns `job_id` or `output_path`. |
| `build_vlog_demo` | yes | no | Async. `media` (list) plus optional `project_name`, `music`, `captions`, `output_path`, `aspect_ratio`. Not idempotent. |

`export_video` and `build_vlog_demo` only acknowledge a job on return: the
`output_path` they carry back is the requested destination, not proof that a file
exists. See the submit/completion contract in
`references/export-and-verification.md`.

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, then re-check `get_export_status` before re-submitting. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action 'export_video' did not return job_id or output_path` | The host acknowledged without the required identifiers. | Fix the host integration per `capcut_panel/HOST_API.md`. |
| Job stuck at the same progress | Host-side render is stalled or waiting on a codec. | Poll once more, then `cancel_export` and re-submit with different codec or bitrate settings. |
| Export reported success but the file is missing or truncated | The host wrote elsewhere, or the render did not finish. | Trust `get_export_status` plus an on-disk check, and probe with `ffprobe`. Never trust the success flag alone. |
| Wrong dimensions or aspect ratio | Canvas, export size, and `aspect_ratio` disagree. | Re-check `get_project_settings` and the export arguments, then re-export. |
| `build_vlog_demo` produced an empty timeline | Supplied media paths did not resolve on the host. | Import the media first (`capcut-media`) and pass the resulting identifiers. |

## Acceptance

- `get_export_status` reports success **and** `output_path` points at a file that
  exists on disk, with a non-trivial size.
- The artifact is probed independently with `ffprobe` (duration, streams,
  dimensions). ffprobe is an external dependency and is not bundled.
- Duration and dimensions match the project settings and the export arguments.
- Audio presence matches the requested `audio` flag, and the whole mix is
  checked, not a soloed track.
- `export_thumbnail` produced an image at the requested time in the requested
  format (`png` or `jpg`).

## Boundaries

- `build_vlog_demo` is not idempotent: re-running creates another project and
  render rather than updating the first one.
- A successful export says nothing about editorial correctness. Verify content,
  captions, and audio before delivery.
- Export does not validate third-party rights in the rendered media. Check
  `demo/assets.json` and the license notes before publishing anything.
- No tool here exposes raw script execution or a generic automation fallback.

## References

- [export and verification](../references/export-and-verification.md)
- [dependencies and notices](../references/dependencies-and-notices.md)
- [host boundary](../references/host-boundary.md)
- [troubleshooting](../references/troubleshooting.md)
