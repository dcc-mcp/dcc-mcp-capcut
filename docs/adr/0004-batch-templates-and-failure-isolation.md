# ADR 0004: Batch delivery as template plus variables, isolated per item

- Status: Proposed
- Date: 2026-09-24

## Context

The 52 single-shot tools cover editing *actions* — add a clip, add a subtitle,
set a level, export. The most frequent automation an editor actually wants is
none of those: it is the same cut delivered as 16:9, 9:16 and 1:1, the same
promo in three languages, the same weekly episode every Monday. Every one of
those had to be orchestrated by hand out of single-shot calls.

`build_vlog_demo` was the closest thing to a batch path and it is a single
demo: no template, no variable sets, no per-item result, and a failure on the
last item left the host half-populated with no record of what had been done.

Two constraints shaped everything that follows:

1. **The host exposes one bound foreground window and no unattended render.**
   A batch is therefore inherently sequential, and an item can take minutes.
   Losing a batch at item 31 of 40 is not an inconvenience, it is the dominant
   failure mode.
2. **The plan is already the canonical unit.** ADR 0002 made one document the
   thing every link agrees on. A template that was a *new* format would have
   re-created the two-formats-disagree bug ADR 0002 exists to remove.

## Decision

### 1. A template is a plan with placeholders, not a new format

A template is a canonical plan or a vlog recipe carrying `{{placeholder}}`
fields. Substitution runs **before** compilation, so every rendered variant is
validated by the same media-path, overlap and bounds rules as a hand-written
plan — a variable cannot smuggle in a traversal path or an overlapping clip by
arriving late.

A field that is exactly one placeholder keeps the variable's type, which is how
a template declares a duration, an fps or a canvas size instead of textifying a
number and hoping the compile re-parses it. A placeholder that injects a list
or an object is rejected: that would let a variable set rewrite the plan's
*shape*, which is not templating.

### 2. Failure isolation starts at compile time

Every variable set is rendered when the batch is built, before any dispatch.
One that does not compile is recorded as `failed` with the reason and the rest
still build.

This is the same guarantee the run provides at dispatch time, moved one step
earlier. Discovering on item 31 that item 31 never compiled — before thirty
renders have been spent — is worth more than a stack trace that names the first
problem and abandons the other thirty-nine.

### 3. The manifest is the batch, and it is written after every item

Batch state lives in a JSON file the caller names, rewritten atomically
(temp-file plus `os.replace`) after each item. Delivered items are never
re-rendered; a resume retries only what is not finished.

Atomic replacement rather than an in-place write: a crash between truncate and
write leaves a file that is not JSON, and the batch — every render already paid
for — becomes unresumable. Refusing to overwrite an existing manifest on a
fresh run is the same rule from the other side.

### 4. Cropping is declared, never silent

Changing the canvas reframes the picture, which is the one thing a batch can do
to a cut that its author did not ask for. `contain` (the default) never crops
and reports the bars it produced. `cover` crops, so it **requires** a
`safe_area` — the fraction of the source frame that must survive — and a crop
that would eat that safe area is an error, not a warning.

Omitting `safe_area` under `cover` is also an error. Without a declared safe
area there is nothing to check a crop against, and "we cropped 44% off the
sides and hoped" is the exact failure this module exists to prevent.

The reframe is **reported, not applied per clip**: the CapCut bridge exposes no
clip transform action, so the adapter sets the canvas and the export size and
reports the geometry. Claiming otherwise would be a false capability.

### 5. One receipt per item, bound to that item's destination

Each delivered item carries the export receipt a single export produces,
requested through the same `verify_output` flag. Two things are batch-specific:

* The receipt is **required**. An item whose host cannot produce one is
  `failed`, not delivered with a warning.
* The receipt is **bound to the output path that item asked for**.
  `get_export_status` carries no `output_path`, so a single export cannot tell
  whether a well-formed receipt describes this render or the previous one.

Field-level validation is not re-implemented: `export_receipt` owns what a
receipt means, and batch calls it.

### 6. Host-free core, dispatching shell

`batch.py` performs no IO beyond the manifest file and no dispatch at all, so
the parts that decide what a batch *means* — substitution, reframe arithmetic,
the encode preset, the state machine — are provable in CI. The skill script
owns the bridge, the polling, the sleeping and the failure-isolation policy.

`assemble.py` was extracted from `apply_edit_plan` for the same reason: batch
delivery assembles one project per item through the identical host/composed
decision, and a second copy of that walk would drift the first time one of them
was fixed.

## Consequences

- Rendering is sequential and host-bound, and the skill says so in its
  prerequisites rather than implying parallelism it cannot deliver.
- `run_batch` is a long call (N × one render). The manifest is what makes that
  survivable, and `batch_status` is what makes it observable while it runs.
- The canonical plan gained two optional `output` fields (`reframe`, `export`).
  Both are additive and both are dropped by `plan_to_edl`, so the OTIO round
  trip is unchanged.
- A template that declares `cover` still needs its media baked to that framing;
  the adapter will not claim a transform it cannot dispatch.
