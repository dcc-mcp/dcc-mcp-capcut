---
name: capcut-text
description: Add styled text, import editable subtitle tracks, and generate auto-captions in CapCut.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.5.0", layer: domain, stage: scene, tags: "capcut, text, captions", tools: tools.yaml}  # x-release-please-version
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
- For `import_subtitles_batch`: one file per entry, each becoming its own text
  track. The files may be different languages of the same cut.
- For `auto_captions`: audio on the timeline. Allow up to the 300 s
  `timeout_hint_secs`.

Transcripts come from outside this skill. Use `capcut-asr`'s `transcribe` to
run your own ASR executor, then import the SRT it writes.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `add_text` | yes | no | `text`, `start`, `duration`, plus optional style and animations; returns `text_id`. |
| `update_text` | yes | yes | Change content or style on an existing `text_id`; safe to re-apply. |
| `remove_text` | yes | no | Removes an overlay or caption track item. |
| `auto_captions` | yes | no | `language` defaults to `zh-CN`; returns `caption_ids` or `job_id`. |
| `import_subtitles` | yes | no | SRT/LRC/ASS plus `offset`, `language`, and `align`; returns `caption_ids`. |
| `import_subtitles_batch` | yes | no | A list of subtitle requests, one text track each; returns per-file `imported` and the combined `caption_ids`. |

### Timeline alignment (`align`)

`align` decides how a file's timecodes map onto the timeline, and the adapter
resolves it *before* dispatch rather than asking the host to:

| `align` | Behaviour |
| --- | --- |
| `timecode` (default) | Honour the file's own clock and shift the whole track by `offset`. Nothing is read or rewritten. |
| `sequence` | Parse the file offline, discard the absolute timecodes, and pack the cues back to back starting at `offset`, each keeping its own duration clamped to 0.2-5 s. The re-timed SRT is written to `output_path` (default: a sibling `.aligned.srt`) and *that* file is imported. |

`sequence` is for a transcript whose timecodes belong to a different cut than
the one being assembled. Offline resolution is what makes it mean the same
thing on every host build -- a host that silently ignored an `align` parameter
would be indistinguishable from one that implemented it.

`align` and `output_path` are adapter-side directives: they are stripped before
the call reaches the host.

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, retry. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action 'import_subtitles' did not return caption_ids` | The file reached the asset browser but produced no caption items. | Fix the host integration per `capcut_panel/HOST_API.md`. A browser import is not a completed import. |
| `import_subtitles_batch stopped at item N (<path>): ...` | One file of a multi-file import failed part-way. | Read `Items already imported`; the host is **not** rolled back, so inspect the project before retrying. |
| `subtitle file not found: ...` | `align: sequence` could not read the source to re-time it. | Fix the path. Offline alignment reads the file; it cannot align what it cannot open. |
| `offline subtitle parsing supports ['srt', 'lrc'], not 'ass'` | `align: sequence` was asked for an ASS file. | ASS timing is event-based and is not parsed offline. Import it with `align: timecode` and let the host handle it. |
| `CapCut action '<action>' lacks timeline readback` | A timeline mutation omitted `verification.timeline`. | Same as above. |
| Captions land at the wrong time | The subtitle `offset` or timeline frame rate does not match the source. | Re-export the subtitle file at the project frame rate and re-import with an explicit `offset`. |
| `auto_captions` returns few or no captions | The target timeline has no usable audio track. | Import or add audio first, then re-run. |
| CJK text renders as boxes | The requested font lacks the glyphs. | Choose a font that covers the language; do not silently transliterate. |

## Acceptance

- `add_text` returned a `text_id`; `auto_captions` and `import_subtitles`
  returned non-empty `caption_ids`.
- For `import_subtitles_batch`: `imported` has one entry per requested file,
  each with a non-empty `caption_ids`, and `caption_count` is the total.
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
  Running your own ASR engine is `capcut-asr`'s `transcribe`, which is the
  documented seam for that.
- `import_subtitles_batch` is not transactional: a part-way failure reports what
  landed and is never silently undone.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [troubleshooting](../references/troubleshooting.md)
