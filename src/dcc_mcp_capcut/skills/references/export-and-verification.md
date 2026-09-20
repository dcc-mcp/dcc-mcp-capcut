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
3. The action's required stable ID is present and non-empty. Where a row lists
   two alternatives joined by **or**, either one satisfies the check — the
   adapter accepts the result when **at least one** of the named keys carries a
   non-empty value, so an action is never rejected for supplying only one of them:

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
| `export_thumbnail` | `job_id` or `output_path` |
| `export_video` | `job_id` or `output_path` |
| `generate_proxy` | `job_id` or `proxy_id` |
| `import_media` | `media_id` |
| `import_subtitles` | `caption_ids` |
| `remove_background` | `job_id` or `clip_id` |
| `stabilize_clip` | `job_id` or `clip_id` |

   `cancel_export` is a mutation with no required stable ID of its own: it only
   needs `verification.ok: true`, and its terminal state is read back with
   `get_export_status`.

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

### Submitting an asynchronous export

- `export_video` — submit arguments: `output_path` (required), plus optional
  `timeline_id`, `format` (`mp4`, `mov`), `codec` (`h264`, `h265`, `prores`),
  `width`, `height`, `fps`, `bitrate_mbps`, `audio`. The submit result is
  accepted when it carries `job_id` or `output_path`; poll with the `job_id` when
  the host returns one. `timeout_hint_secs` is 600.
- `build_vlog_demo` — submit arguments: `media` (required list of supplied
  media objects), plus optional `project_name`, `music`, `captions`,
  `output_path`, `aspect_ratio` (`9:16`, `16:9`, `1:1`). `timeout_hint_secs` is
  900. It is not idempotent: re-running builds another project and render.
- Neither call is complete on return. The response only proves the job was
  accepted, and an `output_path` in it is the **requested destination**, not
  evidence that a file exists. Nothing is written to that path until the job
  finishes — and it may still fail afterwards (codec, disk, host error).

### Reading an export to completion

- Poll `get_export_status` with the `job_id` until it reports a terminal state.
  Treat only a reported success as a finished render, and only together with an
  on-disk check of `output_path`.
- `cancel_export` takes `job_id`, is destructive and idempotent: cancelling twice
  is safe, a cancelled job still reports through `get_export_status`, and the
  cancel call itself needs `verification.ok: true` but returns no stable ID.
- `export_thumbnail` is a synchronous still-frame render: it returns `job_id` or
  `output_path` and writes the frame from the active timeline at the requested
  time.
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
