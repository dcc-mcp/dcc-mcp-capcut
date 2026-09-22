---
name: capcut-assemble
description: Assemble a canonical edit plan plus a media directory into a CapCut project in one call, instead of orchestrating single-shot tools.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: scene, tags: "capcut, assembly, edit-plan, import", tools: tools.yaml}
---

This is the import/assembly direction of the adapter: one plan document plus a
media directory becomes a populated CapCut timeline. It is the tool to reach for
when an upstream system has already decided the cut and what is left is getting
it *into* CapCut.

`apply_edit_plan` accepts either the canonical plan
(`dcc-mcp-capcut/edit-plan/v1`, frame-based) or a vlog recipe
(`capcut-vlog-recipe/v1`, seconds-based) and compiles whatever it is given into
the canonical plan first. Use `dry_run: true` to get the validated plan and the
exact action script without touching the host — that is also how you verify a
plan before you commit to it.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- A `media_dir` containing **every** file the plan references, at the portable
  relative paths the plan records. Missing media fails before any host mutation.
- `dry_run: true` needs none of the above: it is host-free.

If any host-side prerequisite is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `apply_edit_plan` | yes (unless `dry_run`) | no | `plan` or `recipe`, plus `media_dir`. `dry_run` returns the script; `strategy` selects host batch vs composed walk. |

### What one call does

The plan is lowered to an ordered action script and every step is dispatched
with the same fail-closed contract the single-shot tools use:

1. `import_media` — every referenced file, resolved against `media_dir`.
2. `create_timeline` — canvas and frame rate from the plan.
3. `add_clip` — one per clip, base picture track first, further picture tracks
   as `overlay` tracks, audio tracks last.
4. `set_audio_volume` / `add_audio_fade` — only for clips carrying advisory
   audio presentation.
5. `import_subtitles` when the plan names a subtitle file, otherwise `add_text`
   per caption.
6. `export_video` when `export: true`, then `save_project`.

### Strategies

| `strategy` | Behaviour |
| --- | --- |
| `auto` (default) | Try one host `apply_edit_plan` action carrying the whole plan; fall back to the composed walk only if the host rejects that action as unsupported. |
| `host` | Require the host batch action. Any error is raised — no fallback. |
| `composed` | Walk the action script through actions any current host already supports. |

A host that does not implement the batch action must reject it with an
`unsupported action` marker (see `capcut_panel/HOST_API.md`). That is the only
error that triggers the fallback; everything else is a real failure.

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained an action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, retry. |
| `media_dir does not contain every referenced file: ...` | A plan path did not resolve. | Fix the relative paths or point `media_dir` at the delivery root. Nothing was dispatched. |
| `track '...': clips overlap at frame N` | Two clips in one track overlap. | Move the later clip to a separate picture track; overlays are legal across tracks, never within one. |
| `clip '...' exceeds media duration` | `source_in + duration` runs past `media_duration`. | Correct the trim or supply the true `media_duration`. |
| `apply_edit_plan stopped at step N (<action>): ...` | The composed walk failed part-way. | Read `Steps already applied`; the host is **not** rolled back, so inspect the project before retrying. |
| `import_media returned N ids for M requested paths` | The host did not report one id per path. | Reconcile with `list_media` (see `capcut-media`) before placing clips. |
| `completed but no step returned a timeline readback` | The host acknowledged without proof. | Fix the host integration; the adapter refuses to claim success. |
| `strategy: "host"` fails with an unsupported-action error | The host build has no batch action. | Use `auto` or `composed`. |

## Acceptance

- `dry_run: true` returned the canonical plan, the media map, and the full
  action script, and reported `dispatched: false`.
- Every referenced media file existed under `media_dir`, verified before the
  first dispatch.
- The result reports `strategy` (`host` or `composed`), and when composed also
  `fallback_reason`.
- `verification.ok` is `true` and `verification.timeline` is the authoritative
  readback of the assembled timeline (`readback_from` names the step that
  produced it).
- `save_project` ran, so the assembly survives a host restart.

## Boundaries

- The plan is validated host-free, but assembly itself mutates a live project
  and is **not** transactional: a part-way failure is reported with the steps
  already applied, never silently undone.
- Only straight cuts, gaps, external media, caption/subtitle placement, and
  advisory audio volume/fades are assembled. Effects and speed changes must be
  baked into the media.
- `save_project` is always appended; the tool never closes the project or
  overwrites an existing export.
- The canonical contract, its units, and what counts as advisory live in
  `docs/edit-plan.md`.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [dependencies and notices](../references/dependencies-and-notices.md)
- [troubleshooting](../references/troubleshooting.md)
