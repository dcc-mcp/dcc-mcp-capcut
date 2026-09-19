# Export and verification

## The verification contract

Every mutating action must return authoritative readback before it can report
success. A bare acknowledgement such as `{accepted: true}` is an **error**, not a
success. The adapter enforces this server-side and raises instead of returning a
half-truth.

A mutation result must satisfy all three rules that apply to it:

1. `result` is a JSON object (`CapCut action '<action>' returned a non-object result`).
2. `verification` is an object and `verification.ok` is `true`
   (`CapCut action '<action>' lacks verified post-operation readback`).
3. The action's required stable ID is present and non-empty:

| Action | Required ID |
| --- | --- |
| `add_audio` | `audio_id` |
| `add_clip` | `clip_id` |
| `add_text` | `text_id` |
| `add_transition` | `transition_id` |
| `apply_effect` | `effect_id` |
| `auto_captions` | `caption_ids` or `job_id` |
| `create_project` | `project_id` |
| `create_timeline` | `timeline_id` |
| `export_thumbnail` | `job_id`, `output_path` |
| `export_video` | `job_id`, `output_path` |
| `generate_proxy` | `job_id`, `proxy_id` |
| `import_media` | `media_id` |
| `import_subtitles` | `caption_ids` |
| `remove_background` | `job_id`, `clip_id` |
| `stabilize_clip` | `job_id`, `clip_id` |

Timeline mutations must additionally put the authoritative timeline readback
under `verification.timeline`: `add_audio`, `add_audio_fade`, `add_clip`,
`add_text`, `add_transition`, `apply_effect`, `auto_captions`, `color_adjust`,
`delete_clip`, `import_subtitles`, `move_clip`, `remove_audio`,
`remove_effect`, `remove_text`, `set_audio_volume`, `split_clip`, `trim_clip`,
`update_text`.

Read-only and non-mutating actions are exempt from the readback rules but must
still return a JSON object.

## Acceptance checklist for a mutating call

1. Call the tool with the smallest arguments that express the intent.
2. Re-read the affected state with the matching read-only tool
   (`inspect_project`, `list_media`, `list_timelines`) and compare it with the
   returned readback. Do not trust the returned IDs alone.
3. For `import_subtitles`, confirm non-empty `caption_ids` **and** an editable
   text track in the timeline readback. A file landing in the asset browser is
   not a completed import.
4. Only then proceed to the next mutation.

## Export

- `export_video` and `build_vlog_demo` are asynchronous. They return a `job_id`;
  poll `get_export_status` with it rather than assuming completion.
  `timeout_hint_secs` is 600 for `export_video` and 900 for `build_vlog_demo`.
- `cancel_export` is destructive and idempotent: cancelling twice is safe, and a
  cancelled job still reports through `get_export_status`.
- `export_thumbnail` returns `job_id` and `output_path`; it writes a still frame
  from the active timeline at the requested time.
- Acceptance: `get_export_status` reports success **and** `output_path` points at
  a file that exists on disk. Independently probe the artifact with `ffprobe`
  (duration, streams, dimensions) before declaring a render delivered. ffprobe
  is an external dependency and is not bundled.

## Portable OpenTimelineIO export

`export_otio` and the `python -m dcc_mcp_capcut.interchange` CLI convert explicit
frame-based edit decisions to OTIO JSON. They never read or change a live CapCut
project, and the CLI refuses to overwrite an existing file.

Returns: `otio_json`, `duration_frames`, `fps`, `clip_count`, `media_paths`, and
explicit `limitations`.

Constraints the caller owns:

- All times are integer frames at the declared `fps`.
- Clips within a track must be ordered and non-overlapping; overlays go on
  separate tracks. Separate tracks may overlap.
- Media paths must be portable relative paths — no scheme, host, absolute path,
  traversal, or percent escapes.
- Bake unsupported effects into the supplied media; unknown fields fail instead
  of being dropped.
- Captions become markers, not native subtitle clips. Ship an SRT alongside for
  editable subtitles.
- Ship every referenced media file with the OTIO file and resolve relative paths
  from that directory.
- Requires the `interchange` extra: `pip install 'dcc-mcp-capcut[interchange]'`.

## Demo recipe

- `python demo/fetch_assets.py` downloads the assets recorded in
  `demo/assets.json` (see `dependencies-and-notices.md` for license facts).
- `python demo/validate_recipe.py demo/vlog_recipe.json` checks the recipe
  contract; CI runs the same command.
- `python demo/render_vlog.py` renders the offline 9:16 proof to
  `demo/output/free-travel-vlog.mp4`. It needs `ffmpeg` and `ffprobe` on `PATH`.

## See also

- `host-boundary.md` — the external-bridge boundary.
- `dependencies-and-notices.md` — licenses and redistribution facts.
- `troubleshooting.md` — symptom to cause to remediation.
