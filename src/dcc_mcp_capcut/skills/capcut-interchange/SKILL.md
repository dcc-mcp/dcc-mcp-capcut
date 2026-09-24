---
name: capcut-interchange
description: Convert between the canonical CapCut edit plan and portable OpenTimelineIO, in both directions, without a host.
license: MIT
compatibility: "dcc-mcp-capcut[interchange]; no CapCut host dispatch required"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.3.0", layer: domain, stage: delivery, tags: "capcut, otio, interchange, edit-plan", tools: tools.yaml}  # x-release-please-version
---

This skill owns the **canonical edit plan** (`dcc-mcp-capcut/edit-plan/v1`), the
one plan document the whole adapter agrees on. `compile_edit_plan` normalises
either accepted input into it, `export_otio` lowers it to OTIO, and
`import_otio` reads OTIO back into it. `capcut-assemble` is the consumer that
plays a plan into CapCut.

Use `export_otio` with explicit edit decisions, or with a `plan` document and
it will lower that plan for you. All times are integer frames at the declared
fps. Clips must be sorted and non-overlapping per track; overlays belong on
separate tracks. Media paths are relative to the exported timeline directory.
Include the referenced media alongside the OTIO file.

Every tool returns JSON, writes no files, and does not mutate the host. None of
them claims to have read a live CapCut project. Effects must be baked into
supplied media. Captions become timeline markers; supply SRT for editable
subtitles. Unsupported fields fail rather than silently dropping effects or
retiming.

## The canonical plan

`compile_edit_plan` accepts either shape and returns the canonical one:

- **Canonical plan** (`schema: dcc-mcp-capcut/edit-plan/v1`) — a document with
  `tracks`; frame-based; the authoritative form.
- **Vlog recipe** (`capcut-vlog-recipe/v1`) — a document with `media`;
  seconds-based; compiled to frames at `fps`.

The verdict it returns is the verdict every link applies. A plan that
`compile_edit_plan` rejects is also rejected by `export_otio` and by
`apply_edit_plan`, because all three validate against the same rules.

Advisory fields — audio `volume`/`fade_in`/`fade_out`, caption `style`,
`subtitle`, `output` — are consumed by the CapCut assembly direction and are
intentionally **not** representable in OTIO. `export_otio` drops them rather than
encoding a guess; keep the plan document as the authoritative copy.

## Prerequisites

- The `interchange` extra for `export_otio` and `import_otio`:
  `pip install 'dcc-mcp-capcut[interchange]'` (OpenTimelineIO `>=0.16,<1`,
  Apache-2.0). `compile_edit_plan` is stdlib-only and needs no extra.
- A **supplied** edit decision list or canonical plan. This skill converts what
  you give it; it does not read a live CapCut project.
- Portable relative media paths — no scheme, host, absolute path, traversal, or
  percent escapes.
- Effects already baked into the referenced media, and an SRT alongside if the
  consumer needs editable subtitles.
- No bridge, panel, or CapCut window is required: this is the one skill in the
  catalog that runs host-free.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `compile_edit_plan` | no | yes | Plan or recipe in, canonical plan out, plus the CapCut action script it lowers to. No extra required. |
| `export_otio` | no | yes | Takes `timeline` (frame EDL) or `plan`; returns `otio_json`, `duration_frames`, `fps`, `clip_count`, `media_paths`, `limitations`. Saving is the caller's responsibility. |
| `import_otio` | no | yes | OTIO JSON or `.otio` path in, canonical plan out. Canvas values come from the `dcc_mcp_capcut` metadata block; pass `fps`/`width`/`height` for foreign files. |

The host-free CLI is equivalent to `export_otio` and refuses to overwrite an
existing file:

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
| `supply exactly one of 'timeline' (frame EDL) or 'plan' (edit plan)` | Both or neither was passed. | Pass one input shape. |
| `plan must carry either 'tracks' (canonical plan) or 'media' (vlog recipe)` | The document shape was not recognised. | Pass a plan with `tracks`, or a recipe with `media`. |
| `recipe media N needs 'path', or 'id' with a media_index entry` | An id-only entry (usually the music bed) had no path. | Pass `media_index` mapping the asset id to its relative path. |
| `clip '...' has no media_duration; probe the media ... before exporting OTIO` | A plan clip cannot prove its source bounds. | Probe the media and set `media_duration`; the exporter will not claim bounds it cannot prove. |
| `this OTIO file carries no dcc_mcp_capcut canvas metadata` | A foreign OTIO file has no canvas to read. | Pass `fps`, `width` and `height` explicitly. |

## Acceptance

- `compile_edit_plan` returned `schema: dcc-mcp-capcut/edit-plan/v1` and the
  same document assembles without a second verdict. For OTIO export it also
  needs `media_duration` on every clip: the exporter will not claim an
  `available_range` it cannot prove.
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
- Advisory presentation fields do not survive an OTIO round trip. This is a
  declared limit of the portable format, not something to reconstruct on import.

## References

- [export and verification](../references/export-and-verification.md)
- [dependencies and notices](../references/dependencies-and-notices.md)
- [troubleshooting](../references/troubleshooting.md)
