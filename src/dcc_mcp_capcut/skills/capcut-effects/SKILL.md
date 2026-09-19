---
name: capcut-effects
description: Apply, configure, and remove CapCut effects and color adjustments.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.19+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: scene, tags: "capcut, effects, color", tools: tools.yaml}
---

Video effects and color correction on clips and track ranges.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- An open project with a timeline and at least one clip; resolve `clip_id` from
  `capcut-timeline`'s readback.
- Effect names and parameter keys come from the host. Unsupported names must
  reject with a structured error rather than being silently ignored.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `apply_effect` | yes | no | `effect` plus `target_id`; optional `start`, `duration`, `parameters`; returns `effect_id`. |
| `remove_effect` | yes | no | Removes one effect instance by `effect_id`. |
| `color_adjust` | yes | yes | `exposure`, `contrast`, `saturation`, `temperature`, `tint`, `lut`; re-applying is safe. |

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, retry. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action 'apply_effect' did not return effect_id` | The host acknowledged without a stable ID. | Fix the host integration per `capcut_panel/HOST_API.md`. |
| `CapCut action '<action>' lacks timeline readback` | A timeline mutation omitted `verification.timeline`. | Same as above. |
| Unknown effect or parameter rejected | The host does not support that name or key in this CapCut release. | Check the host's supported set. Unsupported fields must fail explicitly — never retry with a renamed guess. |
| `remove_effect` reports the effect still present | Multiple instances overlap on the same clip. | Re-read the clip's effect list and remove each `effect_id`. |
| `color_adjust` looks wrong on delivery | A LUT or a host-wide color pipeline overrides the clip correction. | Verify against an exported still, not only the program monitor. |

## Acceptance

- `apply_effect` returned an `effect_id`; every mutation carried
  `verification: {ok: true, ...}` and, for the two timeline mutations, an
  authoritative `verification.timeline`.
- The clip's effect list in the readback contains exactly the intended
  instances — no duplicates from a retried call.
- `remove_effect` is confirmed by the effect list no longer containing that
  `effect_id`.
- Visual results are checked on a rendered frame or export, not only on a
  preview surface.

## Boundaries

- `apply_effect` and `remove_effect` are not idempotent; re-read state between
  attempts.
- Effects are host-defined. This catalog does not invent a CapCut effect API or
  guarantee a name exists across releases.
- Effects do not survive portable OTIO export. Bake them into the media before
  using `capcut-interchange`.
- No tool here exposes raw script execution or a generic automation fallback.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [troubleshooting](../references/troubleshooting.md)
