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
  `width`, `height`, `fps`, `bitrate_mbps`, `audio`. `timeout_hint_secs` is 600.
  The submit result is accepted when it carries `job_id` **or** `output_path`,
  so a host that returns only the destination path is not an error.
- `build_vlog_demo` — submit arguments: `media` (required list of supplied
  media objects), plus optional `project_name`, `music`, `captions`,
  `output_path`, `aspect_ratio` (`9:16`, `16:9`, `1:1`). `timeout_hint_secs` is
  900. It is not idempotent: re-running builds another project and render. It
  has **no required result ID of its own** — the adapter accepts it on
  `verification.ok: true` alone — so it may return neither `job_id` nor
  `output_path`.
- Neither call is complete on return. The response only proves the job was
  accepted, and an `output_path` in it is the **requested destination**, not
  evidence that a file exists. Nothing is written to that path until the job
  finishes — and it may still fail afterward (codec, disk, host error).

### Reading an export to completion

`get_export_status` and `cancel_export` both take `job_id` as a required
argument, so whatever the submit result carried decides which completion path
you actually have. Read the submit result first and take the matching row:

| Submit result carries | How to read it to completion | How to cancel |
| --- | --- | --- |
| `job_id`, with or without `output_path` | Poll `get_export_status` with the `job_id` until it reports a terminal state. | `cancel_export` with the `job_id`. |
| `output_path` only | **No handle, so there is nothing to poll and nothing to cancel.** The destination is the only evidence available: wait for the file to appear at `output_path` and probe it independently. Let the job run out rather than trying to stop it. | Not cancellable through this catalog. |
| neither — `build_vlog_demo` without an `output_path` argument | Nothing to poll and nothing to check on disk; the render is unreachable from the caller. | Not cancellable through this catalog. |

Always pass an explicit `output_path` to `build_vlog_demo`, and treat a missing
`job_id` on `export_video` as a degradation you plan for rather than an error:
the adapter lets it through, and the adapter never synthesises a `job_id` on the
host's behalf (see `capcut_panel/HOST_API.md`).

Other rules for reading a job out:

- `get_export_status` reports progress and output validation. Treat only a
  reported success as a finished render, and only together with an on-disk
  check of `output_path`.
- `cancel_export` is destructive and idempotent: cancelling twice is safe, a
  cancelled job still reports through `get_export_status`, and the cancel call
  itself needs `verification.ok: true` but returns no stable ID.
- `export_thumbnail` is a synchronous still-frame render: it returns `job_id` or
  `output_path` and writes the frame from the active timeline at the requested
  time.
- Acceptance, all three together:
  1. `output_path` points at a file that exists on disk.
  2. An independent `ffprobe` of that file succeeds (duration, streams,
     dimensions). ffprobe is an external dependency and is not bundled.
  3. When the submit result carried a `job_id`, `get_export_status` also
     reports success.

   A host that returns only `output_path` satisfies 1 and 2 and skips 3 — for
   that path the file plus `ffprobe` *is* the whole completion proof.

## Export receipt (opt-in)

The default export contract proves only that a job was accepted. A caller that
wants proof about the artifact asks for it: pass `verify_output: true` to
`export_thumbnail` or `get_export_status`.

**The asynchronous submits do not take the flag.** `export_video` and
`build_vlog_demo` return a job acknowledgement and the artifact does not exist
when they return, so a receipt cannot be demanded of them — doing so would cost
the caller the `job_id` it needs to poll. Read a video export out with
`get_export_status(verify_output: true)` once the job reaches a terminal state.

The flag is strictly opt-in and defaults to `false`, so a caller that never
passes it keeps exactly the contract it has today. When it is passed, the host
must probe the rendered file and return the receipt under
`verification.output`, and the adapter fails closed when the receipt is missing
or incomplete.

Two rules apply to every opted-in call, including the read-only one:

- `verification.ok` must be `true`. `get_export_status` is exempt from the
  mutation rules, but a receipt sitting under a readback the host did not vouch
  for is not evidence. It gets its own error text rather than the mutation
  wording, since "post-operation readback" points the wrong way for a poll.
- When the result also carries an `output_path`, the receipt's `path` must
  describe that same file. Paths are folded before comparison — backslashes are
  treated as separators, `.` and `..` components collapse, and case is ignored
  — so spelling does not reject an honest host, but a stale probe from an
  earlier render, or the previous item in a batch, cannot stand in. The fold is
  platform-independent: it does not use `os.path`, which would make the same
  two spellings compare equal on Windows and unequal on a Linux runner.

The adapter never synthesises a receipt and never probes the file itself:
duration and stream facts come from a probe the **host** runs (`ffprobe` or an
equivalent). That is also why the receipt is opt-in — a host that cannot probe
must be able to decline instead of failing every export for every caller.

### `verification.output` fields

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `path` | string | yes | Non-empty path of the artifact that was probed. |
| `exists` | boolean | yes | Must be `true`. A receipt for a file that is not on disk is not a receipt. |
| `size_bytes` | integer | yes | Size on disk. Must be `>= 1`; a zero-byte file is a failed render. |
| `duration_sec` | number or null | conditional | Duration. Must be a **finite** number `> 0` when any stream is `video` or `audio`; must be omitted or `null` otherwise. `NaN` and `Infinity` are rejected. |
| `streams` | array | yes | Non-empty list of stream objects. Which kinds are required depends on the action — see the stream-kind rules below. |
| `width` | integer or null | no | Picture width, when the host knows it. Must be `>= 1` when present. |
| `height` | integer or null | no | Picture height, when the host knows it. Must be `>= 1` when present. |
| `probe` | object or null | no | How the receipt was measured. Optional, but a present `probe.tool` must be a non-empty string. |

### `streams[]` fields

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `kind` | string | yes | One of `video`, `audio`, `image`, `subtitle`, `data`. |
| `codec` | string | yes | Non-empty codec name. |
| `width` | integer | for `video` and `image` | Must be `>= 1`. |
| `height` | integer | for `video` and `image` | Must be `>= 1`. |
| `fps` | number | no | Frames per second. Must be `> 0` when present. |
| `channels` | integer | no | Audio channel count. Must be `>= 1` when present. |
| `sample_rate_hz` | integer | no | Audio sample rate. Must be `>= 1` when present. |
| `duration_sec` | number | no | Stream duration. Must be `> 0` when present. |
| `bit_rate` | integer | no | Bitrate in bits per second. Must be `>= 0` when present. |

Three cross-field rules do the real work:

- **A deliverable has a picture.** A receipt whose streams are all `audio`,
  `subtitle` or `data` is rejected: an audio-only artifact is not the video the
  caller asked to export.
- **The picture has to match the action.** `export_thumbnail` renders a still,
  so it must report an `image` stream and no `video` or `audio` stream —
  otherwise a host could satisfy a video export with a frame, or a thumbnail
  with a whole clip. `get_export_status` is deliberately exempt from this rule:
  it only holds a `job_id` and cannot know in advance whether the job renders
  a video or a still, so it accepts either picture kind.
- **Stills have no duration.** `duration_sec` is required exactly when a
  `video` or `audio` stream is present. `export_thumbnail` reports one `image`
  stream and omits it; a still that carries a duration is rejected rather than
  ignored, because it means the host reported the timeline duration instead of
  probing the file.

`size_bytes` and every numeric field must be **finite**: `NaN` and `Infinity`
are rejected. `json.loads` accepts those literals by default, so a host
forwarding an `ffprobe` field reported as `N/A` would otherwise walk a
non-value through every range check.

### A video receipt

```json
{
  "path": "C:/out/vlog.mp4",
  "exists": true,
  "size_bytes": 18345921,
  "duration_sec": 42.5,
  "width": 1080,
  "height": 1920,
  "streams": [
    {"kind": "video", "codec": "h264", "width": 1080, "height": 1920, "fps": 30.0},
    {"kind": "audio", "codec": "aac", "channels": 2, "sample_rate_hz": 48000}
  ],
  "probe": {"tool": "ffprobe", "version": "6.0"}
}
```

### A still receipt

```json
{
  "path": "C:/out/frame.png",
  "exists": true,
  "size_bytes": 204813,
  "width": 1920,
  "height": 1080,
  "streams": [{"kind": "image", "codec": "png", "width": 1920, "height": 1080}],
  "probe": {"tool": "ffprobe", "version": "6.0"}
}
```

Batch delivery reports one of these per rendered item and reuses this field set
verbatim, so the shape above is the contract to depend on rather than a
per-caller dialect.

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
