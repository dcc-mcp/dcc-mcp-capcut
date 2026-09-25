---
name: capcut-export
description: Export, monitor, cancel, and validate CapCut renders.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.5.0", layer: domain, stage: delivery, tags: "capcut, export, render", tools: tools.yaml}  # x-release-please-version
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
| `export_video` | yes | yes | Async submit. `output_path` plus optional `timeline_id`, `format` (`mp4`, `mov`), `codec` (`h264`, `h265`, `prores`), size, `fps`, `bitrate_mbps`, `audio`. Returns `job_id` or `output_path`; only a returned `job_id` makes `get_export_status` and `cancel_export` usable. Carries **no** receipt — the file does not exist yet. |
| `get_export_status` | no | yes | Progress and terminal state for a `job_id`. Add `verify_output: true` to also require a probed output receipt. Completeness is only proved by a reported success **and** an on-disk file. |
| `cancel_export` | yes | yes | `job_id` of a running job — only usable when the submit call returned one. Idempotent: cancelling twice is safe. Needs `verification.ok: true`; returns no stable ID, so confirm the terminal state with `get_export_status`. |
| `export_thumbnail` | yes | yes | Still frame at `time`; returns `job_id` or `output_path`. Add `verify_output: true` to also require a probed still-image receipt. |
| `build_vlog_demo` | yes | no | Async submit. `media` (list) plus optional `project_name`, `music`, `captions`, `output_path`, `aspect_ratio`. Not idempotent. Has no required result ID, so pass an explicit `output_path`: a `job_id` is not guaranteed. Carries **no** receipt. |

### Opt-in export receipt (`verify_output`)

The default export contract only proves a job was accepted. Pass
`verify_output: true` on **`export_thumbnail`** or **`get_export_status`** to
raise it to a probed receipt: the host must return `verification.output` with
`path`, `exists: true`, `size_bytes`, `duration_sec` (timed media) and a
non-empty `streams` list, and the call fails closed when it does not. The
default stays `false`, so no existing caller is held to the stricter contract.

**The two asynchronous submits do not take the flag.** `export_video` and
`build_vlog_demo` return a job acknowledgement — the artifact does not exist
when they return, so demanding a receipt from them would only cost the caller
the `job_id` it needs to poll.

**Poll first, then ask for the receipt.** A running job has no artifact to
probe, so `get_export_status` with `verify_output: true` fails closed until the
job is terminal. Poll it *without* the flag until it reports a terminal state,
then make the flagged call:

1. `get_export_status(job_id=…)` — repeat until it reports a terminal state.
2. `get_export_status(job_id=…, verify_output=True)` — one call, once terminal.

Asking on every poll turns the first one into an error and you never see
progress.

The receipt is bound to the artifact: when the result carries an
`output_path`, the receipt's `path` must describe that same file (folded
case- and separator-insensitively, in a platform-independent way), so a stale
probe from an earlier render — or the previous item in a batch — cannot stand
in for this one. A result with no `output_path` skips the comparison rather
than guessing one; one whose `output_path` is not a usable path is an error,
not a skipped check.

```json
"verification": {
  "ok": true,
  "output": {
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
}
```

`export_thumbnail` renders a still, so it must report an `image` stream, no
`video`/`audio` stream, and no `duration_sec`. `get_export_status` accepts
whichever picture the job produced — it only holds a `job_id` and cannot know
in advance. The full field table lives in
[export and verification](../references/export-and-verification.md).

`export_video` and `build_vlog_demo` only acknowledge a job on return: the
`output_path` they carry back is the requested destination, not proof that a file
exists. A submit result that carries no `job_id` cannot be polled or cancelled at
all — the destination file plus an independent `ffprobe` is the only completion
evidence left. See the submit/completion contract in
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
| Submit returned no `job_id` | The host reported only `output_path`, or nothing. There is nothing to poll and nothing to cancel. | Wait for the file to appear at `output_path` and probe it with `ffprobe`. Re-submit with an explicit `output_path` next time. |
| `CapCut action 'get_export_status' export receipt must be an object under verification.output` | `verify_output: true` was requested but the host never probed the artifact. | Drop `verify_output` and fall back to an independent `ffprobe`, or fix the host integration per `capcut_panel/HOST_API.md`. |
| `... export receipt lacks stream info` / `... has no video or image stream` | The host returned a size but no real stream description. | Same as above: the host must run a probe, not restate the export arguments. |
| `... export receipt describes X, but export_thumbnail was asked to produce Y` | The receipt describes a different file than the one this call produced — usually a stale probe or the previous item in a batch. | Treat the receipt as void; re-probe the artifact at `Y`. |
| `CapCut action 'get_export_status' cannot report an export receipt without verification.ok: true` | The host returned a receipt under a readback it did not vouch for. | The host must set `verification.ok: true` alongside `verification.output`. |

## Acceptance

- `output_path` points at a file that exists on disk, with a non-trivial size,
  and — when the submit result carried a `job_id` — `get_export_status` also
  reports success. With no `job_id`, the file plus `ffprobe` is the whole proof.
- The artifact is probed independently with `ffprobe` (duration, streams,
  dimensions). ffprobe is an external dependency and is not bundled.
- Duration and dimensions match the project settings and the export arguments.
- When `verify_output: true` was passed, `verification.output` also carries `exists: true`, a non-zero `size_bytes`, `duration_sec` for timed media, and a non-empty `streams` list — and, **when this call's result also carries an `output_path`**, a `path` naming that same file. A result with no `output_path` (the usual case for `get_export_status`) skips that last comparison rather than guessing a path; one that carries an `output_path` which is not a usable path is an error, not a skipped check.
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
