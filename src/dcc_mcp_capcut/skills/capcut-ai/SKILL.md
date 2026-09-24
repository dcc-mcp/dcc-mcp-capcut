---
name: capcut-ai
description: Optional CapCut AI-assisted operations exposed as explicit typed actions.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.4.0", layer: domain, stage: scene, tags: "capcut, ai, captions", tools: tools.yaml}  # x-release-please-version
---

Two host-side assisted operations, exposed as explicit typed actions rather than
as a general "AI" surface.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- An open project with a timeline and an existing clip; resolve `clip_id` from
  `capcut-timeline`'s readback.
- Host-side support for the operation. These are optional features; a host that
  does not support them must reject with a structured error.
- Patience: both tools are asynchronous host jobs. The result is accepted on
  `job_id` **or** `clip_id`, so a host may lawfully return only the `clip_id`
  you already supplied and no job handle.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `remove_background` | yes | yes | `clip_id` plus `mode` (`auto`, `chroma`); returns `job_id` or `clip_id`. |
| `stabilize_clip` | yes | yes | `clip_id` plus `strength` (`recommended`, `minimum`, `maximum`); returns `job_id` or `clip_id`. |

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, retry. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action '<action>' did not return job_id or clip_id` | The host acknowledged without the required identifiers. | Fix the host integration per `capcut_panel/HOST_API.md`. |
| `CapCut action '<action>' lacks verified post-operation readback` | Acknowledgement-only result. | Same as above. |
| Job returned but the clip is unchanged | Host-side processing may still be running, or the operation is unsupported for that media. | Re-read the timeline and the clip's effect list; wait, then re-check before retrying. |
| `remove_background` leaves an edge halo | The clip is not suited to the chosen `mode`. | Retry with `chroma` on a clean key background, or reshoot/replace the media. Do not stack repeated passes. |

## Acceptance

- The call returned a non-empty `job_id` or `clip_id` together with
  `verification: {ok: true, ...}` — the adapter accepts either one alone;
  requiring both would wrongly fail a legal result.
- The result is confirmed by re-reading the clip and its effect list in the
  timeline readback — **this catalog has no dedicated AI job-status tool**, so
  readback is the only confirmation available.
- The rendered result is checked on an exported still or clip, not only on a
  preview surface, before it is delivered.

## Boundaries

- These are opaque host features, not local inference. No model, weight, or
  dataset ships with this package, and no user media leaves the loopback bridge.
- Results are assistive and must be reviewed; do not present them as ground
  truth.
- Both tools are declared destructive because they rewrite clip state. They are
  idempotent per clip, but re-running after a manual edit will overwrite that
  edit.
- These features do not survive portable OTIO export. Bake them into the media
  before using `capcut-interchange`.
- No tool here exposes raw script execution or a generic automation fallback.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [troubleshooting](../references/troubleshooting.md)
