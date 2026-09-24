---
name: capcut-batch
description: Turn one template plus N variable sets into N rendered, individually receipted CapCut deliverables, with failure isolation and resume.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.4.0", layer: domain, stage: delivery, tags: "capcut, batch, template, render", tools: tools.yaml}  # x-release-please-version
---

Batch production. The other skills edit one timeline; this one delivers many.
One template plus N variable sets becomes N projects and N renders, each with
its own artifact receipt, each failure isolated to the item that earned it.

The template is an ordinary canonical edit plan (or vlog recipe) with
`{{placeholder}}` fields, so everything [`capcut-interchange`](../capcut-interchange/SKILL.md)
already validates — media paths, per-track overlap, bounds — is validated per
variant, after substitution, before anything is dispatched.

## Two constraints before you start

1. **Rendering is sequential and host-bound.** CapCut exposes one bound
   foreground window and no unattended render path in this adapter, so a batch
   of 20 takes roughly 20 renders, and the window must stay visible and bound
   for the whole run. There is no headless mode to discover here.
2. **A batch is a file.** Pass `manifest_path` and the manifest is rewritten
   after every item. That file is what makes an interrupted batch resumable and
   what `batch_status` reads. Without it, a crash at item 31 of 40 loses
   everything.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `render_batch_template` | no | yes | Template plus variable sets in, every compiled plan, reframe report and encode preset out. No host, no files. Run this first. |
| `run_batch` | yes | yes | Assembles and exports each item in turn. Writes the manifest after every item and again when an export is submitted. `dry_run=true` dispatches nothing; `force_rerender=true` re-exports items that a resume would otherwise settle from a job they already have. |
| `batch_status` | no | yes | Reads a manifest back: per-item state, output path, receipt, error. |

`run_batch` is idempotent per output path: a delivered item is never
re-rendered, and `resume=true` retries only what is not finished.

## The template contract

Placeholders are `{{ name }}`. A field that is *exactly* one placeholder keeps
the variable's own type, which is how a template declares a duration, a canvas
size or an fps rather than only text:

```json
{
  "schema": "capcut-vlog-recipe/v1",
  "project_name": "promo {{lang}} {{aspect}}",
  "aspect_ratio": "{{aspect}}",
  "output_path": "out/promo_{{lang}}_{{aspect}}.mp4",
  "media": [{"id": "a", "path": "clips/{{lang}}/a.mp4", "start": 0, "duration": "{{length}}"}],
  "subtitle_files": ["subs/{{lang}}.srt"],
  "reframe": {"fit": "contain", "source_aspect_ratio": "16:9"},
  "export": {"codec": "h264", "bitrate_mbps": 12}
}
```

Variables are one object per item, and every placeholder the template uses must
be declared in each:

```json
[
  {"lang": "en", "aspect": "16:9", "length": 12},
  {"lang": "zh", "aspect": "9:16", "length": 12},
  {"lang": "de", "aspect": "1:1",  "length": 12}
]
```

Rules:

- An undeclared placeholder, a malformed double-brace one such as `{{ name`,
  or a variable that would inject an object or list into a whole-value field is
  an error naming the field — never a literal `{{lang}}` in a filename. Single
  braces are ordinary text: `{lang}` stays `{lang}`.
- Only strings and numbers interpolate into the middle of a string; a boolean
  or `null` there is an error rather than the text `True` or `None`.
- Substitution happens **before** compilation, so a variable cannot smuggle in
  a traversal path or an overlapping clip that the plan rules would have
  rejected in a hand-written plan.

## Delivery size, reframing and safe areas

`aspect_ratio` selects the canvas from the shared presets: `9:16` → 1080x1920,
`16:9` → 1920x1080, `1:1` → 1080x1080. Changing the canvas is what reframes the
picture, and the adapter refuses to do that silently — `output.reframe` says
how:

| `fit` | Behaviour | Cost |
| --- | --- | --- |
| `contain` (default) | The whole authored frame fits inside the delivery canvas. Nothing is cropped. | Bars. The report says exactly how many pixels, horizontal or vertical. |
| `cover` | The frame fills the canvas and the overflow is cropped. | Picture lost. **Requires `safe_area`.** |

`safe_area` is the fraction of the source frame that must survive, as a centered
rectangle: `0.9` means "you may crop the outer 10%". A `cover` fit that would
crop into it is an **error**, not a warning — the message names both fractions.
Omitting `safe_area` under `cover` is also an error: without it there is nothing
to check the crop against.

`source_aspect_ratio` is what the template was *authored* for. It defaults to
the delivery aspect, which means "no reframing needed"; declare it to make the
report mean something.

Every item's report is on the item, under `reframe`:

```json
{
  "fit": "cover", "source_aspect_ratio": "16:9",
  "target": {"width": 1080, "height": 1920}, "scale": 213.333333, "cropped": true,
  "visible_source_fraction": {"width": 0.316406, "height": 1.0},
  "safe_area": 0.3, "safe_area_preserved": true
}
```

Read with `safe_area: 0.5`, the same 16:9 → 9:16 cover is refused: only 31.6% of
the source width survives, and half of it was declared protected.

**The reframe is reported, not applied per clip.** The CapCut bridge exposes no
clip transform action, so the adapter sets the canvas and export size and tells
you the geometry; it does not and cannot move your clips into it. Bake the
framing into the media when `cover` is what you actually want.

`output.export` declares the encode: `format` (`mp4`, `mov`), `codec` (`h264`,
`h265`, `prores`), `bitrate_mbps`, `fps`, `audio`, and `width`/`height` for a
delivery size smaller than the canvas. The canvas is the default for every
unset value, and an export size whose aspect disagrees with the canvas is
rejected — that is a reframe, and it belongs under `reframe`, where the safe
area is checked.

## Failure isolation and resume

A batch fails one item at a time:

- A variable set that **does not compile** is failed at build time, before any
  dispatch. The rest of the batch still builds, so you learn about item 31
  before paying for items 1–30.
- Two items may not render to the **same** `output_path`. The second render
  would overwrite the first, and because each receipt is bound to the
  destination its item asked for, both would pass — the batch would report
  every item delivered while only the last render exists. The collision is
  failed at build time instead.
- An export that **overruns** `item_timeout_secs` stops the batch. That job is
  still rendering host-side and holds the one bound window, so the next item
  cannot be dispatched into it. Read the job with `get_export_status` or
  `cancel_export` it, then resume.
- An item that **fails at dispatch** keeps its error on the item and the batch
  moves on. `continue_on_error=false` stops instead and marks the remainder
  `skipped`.
- `manifest_path` is rewritten atomically after every item — and again the
  moment an export is submitted, before the wait for it starts — so an
  interruption — crash, timeout, closed laptop — costs at most the item in
  flight, and never loses the job that item was rendering.

To continue: `run_batch(manifest_path=..., resume=true)`. Delivered items are
left alone; `pending`, `failed`, `skipped` **and the item a crash left
`running`** are attempted again — the `skipped` ones being the items a stopped
batch never reached, which is the whole point, since a batch that stopped is
otherwise unfinishable. A fresh run will never overwrite an existing manifest —
that file is the record of renders you have already paid for.

A resumed item that still carries a job is asked about before anything is
re-rendered, because that job may still be out there:

| The abandoned job reports | What the resume does |
| --- | --- |
| `done` | Settles the item from that render. No second export. |
| `failed` / `cancelled` / `error` | The job is over, so the item is re-rendered. |
| still running | Refuses to continue, and names the job holding the window. |
| no `state` at all | The host answered the poll without a verdict, so the job cannot be read to completion. Fails that item only and keeps its `job_id`, so the next resume asks again. |
| submitted but never named | Refuses that item only, and names the destination. See below. |

That last pair is what matters: two exports to one destination through one
bound window would silently overwrite the first render.

**An export the host acknowledged but never gave a `job_id` for cannot be
asked about.** The host exposes no way to look a job up by the destination it
was submitted for, so a resume leaves that item failed rather than re-exporting
into a file a render may still be writing. Check the destination and the CapCut
window yourself; when you want the item rendered anyway, resume with
`force_rerender=true`.

`force_rerender=true` is the explicit way to spend a render on an item that is
otherwise settled: one that is stuck on a job the host reports as `done` but
cannot produce a receipt for, or one whose job was never named. It is refused
while that job is still rendering — cancel it first — because there is one bound
window and no flag makes dispatching into a busy one safe.

The cheap exit for an unreceiptable render is the other direction:
`resume=true, verify_output=false` settles the item from the render that exists,
without proof and without paying for another one.

## Prerequisites

- CapCut Desktop running with its main window visible and restored, for the
  entire batch.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- Every file every rendered plan references, present under `media_dir`.
  A per-language asset that is missing on disk fails that one item.
- Disk space for N renders, and time: `item_timeout_secs` (default 600 s) is
  per item, so budget N × that.

If the first three are unproven, run `capcut-setup` first.

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained an action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, then resume the batch. |
| `uses undeclared variable 'lang'` | A variable set is missing a placeholder the template uses. | Fix that variable set; `render_batch_template` shows all of them at once. |
| `has a malformed placeholder` | A malformed double-brace placeholder such as `{{ lang` or `{{}}`. | Fix the template. A mistyped placeholder never renders as literal text; single-brace text such as `{lang}` stays literal, so use `{{lang}}` to substitute. |
| `fit='cover' requires safe_area` | A cropping reframe with no declared safe area. | Declare `safe_area`, or use `fit='contain'` and take bars. |
| `would crop into the declared safe area` | The requested crop eats protected picture. | Lower `safe_area`, change the source aspect, or use `contain`. |
| `output.export size ... does not match the canvas` | An encode size of another aspect. | Reframe under `output.reframe`, where the safe area is checked. |
| `export_video acknowledged the job without a job_id` | The host gave nothing to poll, so the export cannot be read or cancelled. | That item cannot be proven. Check the destination by hand and fix the host integration; a resume will **not** re-export it, because one may already be running. When the destination is clear, resume with `force_rerender=true`. |
| `export job '...' finished in state 'failed'` | The render itself failed. | Fix the cause, then `resume=true` with `retry_failed=true`. |
| `returned no artifact receipt under verification.output` | The host cannot prove the file exists. | Verify the file yourself. To settle the item without proof, resume with `verify_output=false`; to render it again, resume with `force_rerender=true`. Resuming unchanged asks the same finished job the same question, so it will not spend a render by itself. |
| `may already have an export in flight to '...'` | The last run dispatched an export to that path and died before its `job_id` came back. | Nothing was dispatched to it. Check the destination and the CapCut window, then resume with `force_rerender=true`. |
| `did not reach a terminal state within ...` | One item's export overran its timeout. | The batch stopped: that job is still rendering and holds the bound window. Read it with `get_export_status` or `cancel_export` it, then resume. |
| `still has export job ... in state 'running'` | A resume found the abandoned job still rendering. | Nothing was dispatched. Read that job with `get_export_status` or `cancel_export` it, then resume again. `force_rerender=true` does not override this — cancel the job first. |
| `returned no 'state' for job '...'` | The host answered the poll without the one field that says whether the job is over. | A status with no verdict is not evidence that the window is busy, so that item fails and the batch goes on. It stays failed and keeps its `job_id`; fix the host integration so it returns `state`, then resume. `force_rerender=true` does not bypass this check — the abandoned job may still be writing to that destination. |
| `output.path ... is already used by item N` | Two variable sets render to one destination. | Give each item a distinct `output_path`, usually by putting a variable in the template's `output_path`. |
| `manifest_path ... already exists` | A fresh run aimed at an existing batch. | Pass `resume=true` to continue it, or pick a new path. |

## Acceptance

- `run_batch` reports `counts.done` equal to the number of variable sets, and
  `counts.failed` and `counts.skipped` both zero.
- Every delivered item carries a `receipt` from the host describing the
  artifact it actually produced — and the adapter has already bound that
  receipt to the destination this item asked for, so it cannot be a
  description of some other item's render.
- Every item's `output_path` is distinct, and a file exists at each.
- The `reframe` report on each item matches what the canvas preset says, and
  any `cropped: true` item names the `safe_area` that permitted it.
- Injecting one failing variable set leaves the other items delivered: the
  failing item carries the reason, the rest carry receipts.

## Boundaries

- **No unattended rendering.** This skill drives the same visible, bound
  foreground window every other host tool does. It does not start CapCut, does
  not hide it, and does not work without it.
- Reframes are **reported, not applied per clip**: the bridge has no clip
  transform action. `cover` is a statement of intent you must bake into the
  media.
- A receipt proves an artifact exists and has the reported streams. It does not
  prove editorial correctness — check content, captions and audio before
  delivery.
- No tool here uploads, publishes, or touches anything outside `media_dir` and
  the declared output paths.
- `run_batch` is not parallel and will not become parallel while the host
  exposes a single bound window.

## References

- [export and verification](../references/export-and-verification.md)
- [host boundary](../references/host-boundary.md)
- [troubleshooting](../references/troubleshooting.md)
