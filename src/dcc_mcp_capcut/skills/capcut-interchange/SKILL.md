---
name: capcut-interchange
description: Export explicit frame-based edit decisions to portable OpenTimelineIO JSON.
license: MIT
compatibility: "dcc-mcp-capcut[interchange]; no CapCut host dispatch required"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: delivery, tags: "capcut, otio, interchange", tools: tools.yaml}
---

Use `export_otio` with explicit edit decisions. All times are integer frames
at the declared fps. Clips must be sorted and non-overlapping per track;
overlays belong on separate tracks. Media paths are relative to the exported
timeline directory. Include the referenced media alongside the OTIO file.

The tool returns JSON and does not write files or mutate the host. It never
claims to have read a live CapCut project. Effects must be baked into supplied
media. Captions become timeline markers; supply SRT for editable subtitles.
Unsupported fields fail rather than silently dropping effects or retiming.

## Prerequisites

- The `interchange` extra: `pip install 'dcc-mcp-capcut[interchange]'` (OpenTimelineIO
  `>=0.16,<1`, Apache-2.0).
- A **supplied** frame-based edit decision list. This skill converts what you
  give it; it does not read a live CapCut project.
- Portable relative media paths — no scheme, host, absolute path, traversal, or
  percent escapes.
- Effects already baked into the referenced media, and an SRT alongside if the
  consumer needs editable subtitles.
- No bridge, panel, or CapCut window is required: this is the one skill in the
  catalog that runs host-free.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `export_otio` | no | yes | Returns `otio_json`, `duration_frames`, `fps`, `clip_count`, `media_paths`, `limitations`. Saving is the caller's responsibility. |

The host-free CLI is equivalent and refuses to overwrite an existing file:

```powershell
python -m dcc_mcp_capcut.interchange --input edit.json --output timeline.otio
```

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `Install dcc-mcp-capcut[interchange] for OTIO support` | The optional extra is missing. | `pip install 'dcc-mcp-capcut[interchange]'`. The doctor reports this as a `warn` on the `opentimelineio` check. |
| `timeline has unsupported fields: [...]` | An unknown key (including speed changes or effects) was supplied. | Remove or bake it. Unknown fields fail explicitly instead of being dropped. |
| `clips must be ordered and non-overlapping within a track` | Two clips in one track overlap or are out of order. | Move the overlay to a separate track — separate tracks may overlap. |
| `clip exceeds timeline or media duration` | `start + duration` or `source_in + duration` runs past the declared bounds. | Correct `duration_frames` or the clip's `media_duration`. |
| `media must be a portable relative path without traversal or URL escapes` | An absolute, traversing, escaped, or URL-like path. | Use a relative path and ship the media next to the OTIO file. |
| `FileExistsError` from the CLI | The output file already exists. | Choose a new path or delete the old file deliberately. The CLI will not overwrite. |
| Consumer imports the timeline but media is offline | Relative paths resolve from the OTIO file's directory. | Ship the media alongside it, preserving the relative layout. |

## Acceptance

- The call returned `otio_json` plus `duration_frames`, `fps`, `clip_count`, and
  `media_paths`, and no exception was raised.
- `media_paths` is a complete list of portable relative paths, and every one of
  them ships with the OTIO file.
- `clip_count` matches the supplied edit list, and `duration_frames` matches the
  requested timeline length.
- Gaps, source trims, separate tracks, and fractional frame rates survived the
  conversion.
- The returned `limitations` are passed on to whoever consumes the file, not
  discarded.

## Boundaries

- This is export from supplied edit decisions, **not** a readback of a live
  CapCut project. Never describe the output as "the CapCut timeline".
- Only straight cuts, gaps, external media, and markers are represented. Effects,
  speed changes, and native subtitle tracks are out of scope.
- Captions become OTIO markers, not editable text tracks.
- Canvas metadata is advisory; configure the target editor's sequence to the
  specified dimensions and fps.
- Consumers may need their own OTIO importer.

## References

- [export and verification](../references/export-and-verification.md)
- [dependencies and notices](../references/dependencies-and-notices.md)
- [troubleshooting](../references/troubleshooting.md)
