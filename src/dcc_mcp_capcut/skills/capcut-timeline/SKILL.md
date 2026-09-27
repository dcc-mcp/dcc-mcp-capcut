---
name: capcut-timeline
description: Build and edit CapCut timelines with typed clip and transition operations.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.5.0", layer: domain, stage: scene, tags: "capcut, timeline, edit", tools: tools.yaml}  # x-release-please-version
---

Timeline assembly and clip editing. This is the most state-dependent skill in
the catalog: every mutation must be confirmed against a fresh timeline readback
before you build on it.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- An open project and, for clip operations, media already imported
  (`capcut-media`) so you have real `media_id` values.
- A target timeline: reuse one from `list_timelines`, or create one with
  `create_timeline`.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `create_timeline` | yes | no | `name` plus optional `width`, `height`, `fps`; returns `timeline_id`. |
| `list_timelines` | no | yes | Durations and track counts; use it to resolve `timeline_id`. |
| `add_clip` | yes | no | `media_id`, `track_type` (`video`, `overlay`, `audio`), `start`; returns `clip_id`. |
| `move_clip` | yes | no | `clip_id`, new `start`, optional `track_index`. |
| `trim_clip` | yes | yes | Sets `source_in` / `source_out`; safe to re-apply. |
| `split_clip` | yes | no | Splits at an absolute timeline time. |
| `delete_clip` | yes | no | Removes from the timeline; source media is preserved. |
| `add_transition` | yes | yes | Between `left_clip_id` and `right_clip_id`; returns `transition_id`. |

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, retry. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action 'add_clip' lacks timeline readback` | A timeline mutation omitted `verification.timeline`. | Fix the host integration per `capcut_panel/HOST_API.md`. |
| `CapCut action 'add_clip' did not return clip_id` | Acknowledgement without a stable ID. | Same as above. |
| `clip_id` not found on a later call | The ID is stale — the clip moved, split, or was deleted. | Re-read with `list_timelines`; `split_clip` and `delete_clip` invalidate prior IDs. |
| Clip lands on the wrong track | `track_index` and `track_type` resolve differently than assumed. | Re-read the timeline and pass an explicit `track_index`. |
| `split_clip` appears to do nothing | The absolute time falls outside the clip. | Confirm the clip's current bounds from the timeline readback before splitting. |

## Acceptance

- `list_timelines` shows the expected duration and track counts.
- Every mutation returned its required ID — `clip_id` for `add_clip`,
  `timeline_id` for `create_timeline`, `transition_id` for `add_transition` —
  together with `verification: {ok: true, ...}` and an authoritative
  `verification.timeline`.
- Placement is confirmed by re-reading the timeline, not by the return value
  alone.
- `delete_clip` removed only the timeline clip; the source media is still in the
  bin.

## Boundaries

- Non-idempotent tools (`add_clip`, `move_clip`, `split_clip`, `delete_clip`)
  will duplicate or destroy edits if retried blindly. Re-read state between
  attempts.
- Time arguments are numeric; keep them consistent with the project frame rate
  and verify placement by readback rather than by arithmetic.
- No tool here exposes raw script execution or a generic automation fallback.
- Timeline editing does not prove exportability; validate the render with
  `capcut-export`.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [troubleshooting](../references/troubleshooting.md)
