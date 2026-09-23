---
name: capcut-audio
description: Add, remove, mix, and fade audio tracks in a CapCut timeline.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: scene, tags: "capcut, audio, mix", tools: tools.yaml}  # x-release-please-version
---

Audio placement, level, and fades.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- An open project with a timeline, and audio already imported (`capcut-media`)
  so you have a real `media_id`.
- A `clip_id` for the level and fade tools — resolve it from the timeline
  readback rather than remembering one across calls.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `add_audio` | yes | no | `media_id` and `start`; optional `source_in`, `source_out`, `beat_sync`; returns `audio_id`. |
| `set_audio_volume` | yes | yes | `clip_id` plus `volume` in `0..4` inclusive (`1.0` is unity), optional `keyframes`; re-applying is safe. |
| `add_audio_fade` | yes | yes | `fade_in` / `fade_out` in seconds; re-applying is safe. |
| `remove_audio` | yes | no | Removes the clip from the timeline. |

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, retry. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action 'add_audio' did not return audio_id` | The host acknowledged without a stable ID. | Fix the host integration per `capcut_panel/HOST_API.md`. |
| `CapCut action '<action>' lacks timeline readback` | A timeline mutation omitted `verification.timeline`. | Same as above. |
| Volume request rejected | `volume` outside the `0..4` range; the call fails closed instead of being adjusted. | Never clamp silently. Report the rejected value, confirm the intended level with whoever asked for the mix, then re-submit an in-range `volume`. `1.0` is unity. |
| Audio duplicated | `add_audio` is not idempotent and was retried after a partial failure. | Re-read the timeline, delete the duplicate, then re-add once. |
| `set_audio_volume` has no audible effect | A keyframe envelope or a downstream track gain overrides the clip level. | Inspect the envelope and the track's own level; do not keep raising the clip gain. |

## Acceptance

- `add_audio` returned an `audio_id`, and the timeline readback shows the clip at
  the requested `start` on an audio track.
- `set_audio_volume` and `add_audio_fade` are confirmed by re-reading the clip
  and its envelope, not by the return value alone.
- Every mutation carried `verification: {ok: true, ...}` and an authoritative
  `verification.timeline`.
- Levels are checked on the full mix, not on a soloed track, before delivery.
- A rejected `volume` was re-submitted with an explicitly confirmed value, not
  with a silently clamped one.

## Boundaries

- `add_audio` and `remove_audio` are not idempotent. Re-read the timeline between
  attempts; never retry blindly.
- `remove_audio` removes the clip from the timeline; it does not delete the
  source media from the bin or from disk.
- `beat_sync` is a host-side heuristic. Verify the result by readback; do not
  present it as beat-accurate without checking.
- No tool here exposes raw script execution or a generic automation fallback.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [troubleshooting](../references/troubleshooting.md)
