# Batch production and templates

One template plus N variable sets becomes N rendered CapCut projects, each with
its own artifact receipt. This is the layer above the 52 single-shot tools: they
edit one timeline, and `capcut-batch` delivers many.

Implementation: `src/dcc_mcp_capcut/batch.py` (host-free) and
`src/dcc_mcp_capcut/skills/capcut-batch/` (the tools).

## The shape

```
template (a canonical plan or vlog recipe carrying {{placeholders}})
      +  variables[0..N-1]
      =  N canonical plans -> N assemblies -> N exports -> N receipts
```

A template is an ordinary plan document, so every rule in
[`edit-plan.md`](edit-plan.md) applies to every variant, after substitution.

## Placeholders

`{{ name }}`, optional inner padding. Two forms:

| Form | Result | Use |
| --- | --- | --- |
| `"{{length}}"` — the whole field | the variable's own type | durations, `fps`, `width`/`height`, booleans |
| `"clips/{{lang}}/a.mp4"` | the variable interpolated as text | paths, names, subtitle files |

Rules, all fail-closed:

- An undeclared variable, and a malformed double-brace one (`{{ lang`, `{{}}`),
  are errors naming the field. A placeholder never survives into the rendered
  plan as literal text — a typo would otherwise silently import the wrong file.
  Single braces are ordinary text: `{lang}` stays `{lang}`.
- Only strings and numbers interpolate into a longer string. A boolean or
  `null` there would become the text `True` or `None`, which is never intended.
- A whole-value placeholder takes a scalar only. A variable that injects an
  object or a list would let a variable set rewrite the template's shape, which
  is not templating.
- Substitution runs **before** compilation, so a variable cannot smuggle in a
  traversal path, an overlapping clip or an out-of-bounds caption that the plan
  rules would have rejected in a hand-written plan.

## Delivery size and reframing

`aspect_ratio` picks the canvas from the shared presets (`9:16` → 1080x1920,
`16:9` → 1920x1080, `1:1` → 1080x1080). Changing the canvas reframes the
picture, and the adapter will not do that silently — `output.reframe` says how:

| `fit` | Behaviour | Cost |
| --- | --- | --- |
| `contain` (default) | The whole authored frame fits inside the canvas. Never crops. | Bars, reported in pixels. |
| `cover` | The frame fills the canvas; the overflow is cropped. **Requires `safe_area`.** | Picture lost. |

`safe_area` is the fraction of the source frame that must survive, as a centered
rectangle. `0.9` means the outer 10% may go. A `cover` fit that would crop into
it is an **error**, not a warning, and the message names both fractions.
Omitting `safe_area` under `cover` is also an error: with nothing to check the
crop against, the adapter refuses to crop at all.

`source_aspect_ratio` is the aspect the template was authored for. It defaults
to the delivery aspect, which means "no reframing needed"; declare it to make
the report mean something.

`output.export` declares the encode (`format`, `codec`, `bitrate_mbps`, `fps`,
`audio`, and a `width`/`height` smaller than the canvas). The canvas is the
default for every unset value. An export size whose aspect disagrees with the
canvas is rejected: that is a reframe, and it belongs under `reframe`, where
the safe area is checked.

### What the adapter does and does not apply

The canvas and the export size are dispatched. **Per-clip reframing is not** —
the CapCut bridge exposes no clip transform action, so the adapter computes and
reports the geometry instead of moving your clips into it. `cover` is therefore
a statement of intent you bake into the media.

## Failure isolation and resume

A batch fails one item at a time.

| Stage | What happens |
| --- | --- |
| Build | Every variable set is rendered up front. One that does not compile is recorded as `failed` with the reason; the rest still build. |
| Dispatch | An item that fails at the host keeps its error and the batch moves on. `continue_on_error=false` stops instead and marks the remainder `skipped`. |
| Write | The manifest at `manifest_path` is rewritten atomically after every item — and again the moment an export is submitted — so an interruption costs at most the item in flight, and never loses the job that item was rendering. |

Resume with `run_batch(manifest_path=..., resume=true)`: delivered items are
left alone, `pending`, `failed`, `skipped` and the item a crash left `running`
are attempted again — the `skipped` ones being the items a stopped batch never
reached, without which a batch that stopped once could never be finished. A
fresh run never overwrites an existing manifest — that file is the record of
renders already paid for.

Every resumed item that carries a job — a `job_id`, or an `in_flight` marker
saying an export went out unnamed — is reconciled with the host before anything
is dispatched, so no destination ever takes a second export. See
[`capcut-batch`](../src/dcc_mcp_capcut/skills/capcut-batch/SKILL.md#failure-isolation-and-resume)
for the table, and for the two ways out of an item the reconciliation cannot
settle: `verify_output=false` to accept the render without proof, and
`force_rerender=true` to pay for a new one.

## Receipts

Each delivered item carries the host's export receipt, requested through the
same `verify_output` flag a single export uses (see
[`README.md`](../README.md#export-receipt)). Two things are batch-specific:

1. **The receipt is required.** An item whose host cannot produce one is
   `failed`, not delivered-with-a-warning. Forty renders whose only proof is
   "the host said done" is forty chances to ship a missing file.
2. **The receipt is bound to the item's destination.** `get_export_status`
   carries no `output_path`, so a single export cannot tell whether the receipt
   describes this render or the previous one. Batch knows the destination it
   submitted and refuses a mismatch.

Field-level validation is not re-implemented here: `export_receipt` owns what a
receipt means, and batch calls it.

## Host constraints

Rendering is **sequential and host-bound**. CapCut exposes one bound foreground
window and no unattended render path in this adapter, so a batch of 20 takes
roughly 20 renders and the window must stay visible and bound throughout. There
is no headless mode to discover here; whether a draft-level path is feasible is
still an open question, and nothing in this skill assumes the answer.

## See also

- [`edit-plan.md`](edit-plan.md) — the canonical plan, including the `output` block.
- [`skills/references/export-and-verification.md`](../src/dcc_mcp_capcut/skills/references/export-and-verification.md) — the readback and export contract.
- [`skills/capcut-batch/SKILL.md`](../src/dcc_mcp_capcut/skills/capcut-batch/SKILL.md) — the tool contract.
