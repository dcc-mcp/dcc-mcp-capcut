---
name: capcut-text
description: Add styled text, import editable subtitle tracks, and generate auto-captions in CapCut.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.19+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: scene, tags: "capcut, text, captions", tools: tools.yaml}
---

Text overlays, subtitle import, and auto-captions.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- An open project with a timeline. Resolve `timeline_id` from
  `capcut-timeline`'s `list_timelines`, or omit it to act on the active timeline.
- For `import_subtitles`: an SRT, LRC, or ASS file readable by the CapCut host.
- For `auto_captions`: audio on the timeline. Allow up to the 300 s
  `timeout_hint_secs`.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `add_text` | yes | no | `text`, `start`, `duration`, plus optional style and animations; returns `text_id`. |
| `update_text` | yes | yes | Change content or style on an existing `text_id`; safe to re-apply. |
| `remove_text` | yes | no | Removes an overlay or caption track item. |
| `auto_captions` | yes | no | `language` defaults to `zh-CN`; returns `caption_ids` and `job_id`. |
| `import_subtitles` | yes | no | SRT/LRC/ASS plus `offset` and `language`; returns `caption_ids`. |

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, retry. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action 'import_subtitles' did not return caption_ids` | The file reached the asset browser but produced no caption items. | Fix the host integration per `capcut_panel/HOST_API.md`. A browser import is not a completed import. |
| `CapCut action '<action>' lacks timeline readback` | A timeline mutation omitted `verification.timeline`. | Same as above. |
| Captions land at the wrong time | The subtitle `offset` or timeline frame rate does not match the source. | Re-export the subtitle file at the project frame rate and re-import with an explicit `offset`. |
| `auto_captions` returns few or no captions | The target timeline has no usable audio track. | Import or add audio first, then re-run. |
| CJK text renders as boxes | The requested font lacks the glyphs. | Choose a font that covers the language; do not silently transliterate. |

## Acceptance

- `add_text` returned a `text_id`; `auto_captions` and `import_subtitles`
  returned non-empty `caption_ids`.
- Every mutation carried `verification: {ok: true, ...}` and, for the timeline
  mutations, an authoritative `verification.timeline`.
- For `import_subtitles` specifically: the timeline readback proves an **editable
  text track** exists. A file sitting in the asset browser is not success.
- Spot-check the rendered overlay or caption timing in the timeline readback
  before declaring the step done.

## Boundaries

- `auto_captions` output is machine-generated. Do not present it as a verified
  transcript without review, especially for publication.
- `remove_text` on a caption track item is destructive and non-idempotent.
- Captions exported through `capcut-interchange` become OTIO **markers**, not
  native subtitle clips. Ship the SRT alongside the timeline for editable
  subtitles.
- No tool here exposes raw script execution or a generic automation fallback.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [troubleshooting](../references/troubleshooting.md)
