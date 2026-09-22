# ADR 0002: One canonical edit plan, and assembly owned by the adapter

- Status: Proposed
- Date: 2026-09-22

## Context

The adapter had two plan formats and no import direction.

- `docs/interchange.md` defined a frame-based EDL/OTIO export
  (`export_otio`), host-independent.
- `demo/vlog_recipe.json` defined `capcut-vlog-recipe/v1`
  (seconds-based) for the vlog demo.

They disagreed. The shipped recipe placed two video clips at `0/4.5` and
`4.2/8.0` — a 0.3 s overlap on one picture track. `demo/validate_recipe.py`
accepted it; `export_otio` rejected it with "clips must be ordered and
non-overlapping within a track". The same media had two verdicts depending on
which script you happened to run. Incidentally the recipe also disagreed with
`demo/render_vlog.py`, which concatenated the clips at 4.5 s.

The 11 skills / 47 tools were all single-shot actions, so an upstream system
that had already decided a cut still had to orchestrate dozens of calls
itself. The external signal behind this work is that the adapter's competitive
surface is being a *reliable receiving end*: one machine-consumable assembly
contract, not more single actions.

## Spike: can the host place a plan in one shot?

**Question.** Can the host side place tracks and captions from a plan in one
call, or does assembly have to be composed from the existing single-shot
actions?

**Evidence.** All of it is in this repository; no CapCut host was reachable
from the development environment, so nothing here is a live acceptance result.

- `capcut_panel/HOST_API.md` specifies the host surface as exactly
  `window.CapCut.dispatch(action, params) -> Promise<object>` — one typed
  action at a time.
- `capcut_panel/panel.js` is a thin forwarder: it drains `/next`, calls
  `dispatch`, posts the result to `/result`. It adds no batching.
- No bundled skill declares a batch/plan action. The catalog is 47
  single-shot actions.
- Every mutating action must return `verification: {ok: true, ...}`, and
  timeline mutations must put the authoritative readback under
  `verification.timeline`. The fail-closed contract in `contracts.py` rejects
  anything weaker.
- `import_media`'s contract guarantees a single `media_id` per call — the
  plural `media_ids` is host-provided data the adapter does not enforce (see
  `capcut-media/SKILL.md`).

**Conclusion: (b) — feasible, with the adapter owning the orchestration.** Not
(a), because there is no host batch action to call today and shipping one is
host-side work with its own release cadence. Not (c), because the host surface
is sufficient: the adapter can lower a plan to an ordered sequence of actions
that already exist and already carry verified readback.

So both paths are built, selected at runtime:

- **`host`** — one `apply_edit_plan` action carrying the whole plan, for a
  host that implements it. One round trip, one receipt, one
  `verification.timeline`. This is the path a host *should* take up.
- **`composed`** — the adapter walks the action script itself, using only
  actions an existing host already supports.
- **`auto`** (default) — try the batch action, fall back to the composed walk
  only when the host rejects the batch action as *unsupported*. Any other
  error is raised, never retried as a different edit.

Two consequences of the evidence that shaped the details:

- Media is imported **one file per `import_media` call**, not as one
  multi-path call, because the contract only guarantees one `media_id` and a
  multi-path import cannot be mapped back to individual clips.
- A composed run that fails part-way is reported with the steps it already
  applied. Host mutations are not transactional and the adapter does not
  pretend otherwise.

**Not yet verified.** Neither path has run against a live `window.CapCut`.
The batch action has no host implementation. The composed walk has been
exercised only against recorded host receipts in `tests/test_assemble.py`.
The offline half — plan compilation, validation, media resolution, action
script generation — is fully covered and host-free.

## Decision

1. One canonical plan contract, `dcc-mcp-capcut/edit-plan/v1`, documented in
   [`docs/edit-plan.md`](../edit-plan.md) and implemented in
   `src/dcc_mcp_capcut/editplan.py`. Frame-based; the authoritative form.
2. `capcut-vlog-recipe/v1` becomes a **profile over** that contract rather
   than a parallel format: `compile_plan` accepts either shape and returns the
   canonical one.
3. `export_otio` and the new assembly tool both become consumers of the
   canonical plan, and both share the validators in `editplan.py` — including
   the portable media-path rule, which `interchange.py` now imports from there
   instead of defining its own copy. That is what makes the two verdicts one.
4. New import/assembly direction: `apply_edit_plan` in a new
   `capcut-assemble` skill, over the existing bridge. No new protocol.
5. New `export_otio`/`import_otio` round trip in `capcut-interchange`, both
   host-free.
6. `demo/validate_recipe.py` and `demo/render_vlog.py` consume the same
   contract. The demo recipe's 0.3 s overlap is corrected to 4.5 s, which is
   what the renderer already did.

## Consequences

### Benefits

- One verdict. A plan the contract accepts is a plan every link accepts.
- One call replaces a hand-orchestrated sequence, which is the structural fix
  for "the adapter can only add single features".
- Assembly is validated host-free before the first mutation, so a bad plan
  costs nothing but an error. "Every referenced file" covers the subtitle file
  as well as clip media: it is handed to the host as a path, so it is checked
  in the same pass rather than failing at `import_subtitles` once the timeline
  has already been populated.
- `dry_run` makes the whole edit inspectable before it is dispatched.

### Costs and limits

- A 12th skill (`capcut-assemble`) to maintain, lint and release.
- Two dispatch strategies to keep working until hosts implement the batch
  action; the fallback depends on hosts rejecting unsupported actions with a
  recognisable marker, documented in `capcut_panel/HOST_API.md`.
- Advisory fields (audio volume/fades, caption style, subtitle file, output
  path) have no home in OTIO and are dropped on export rather than
  reconstructed on import. The plan document is the authoritative copy.
- One `import_media` call per media file instead of one per plan.
- Assembly is not transactional.

## Alternatives considered

1. **Host-side batch action only** — cleanest result, but no host implements
   it and the adapter cannot ship host code. Rejected as the *only* path.
2. **Make OTIO the canonical form** — it cannot represent CapCut presentation
   (volume, fades, text style), so an assembly path would have to invent
   metadata. Rejected; OTIO stays the portable * interchange* format and the
   plan stays authoritative.
3. **Silently split an overlapping picture track into an overlay track** —
   makes every plan "valid" by changing its meaning. Rejected: the contract
   reports the overlap and lets the author decide.
4. **Keep `validate_recipe.py` stdlib-only with its own rules** — preserves
   CI's dependency-free demo job but preserves the two-verdict bug by design.
   Rejected; that job now installs the package.

## Rollout

1. Land the contract, the two new tools, and the demo migration together, so
   no intermediate state has two verdicts.
2. Document the `apply_edit_plan` batch action in
   `capcut_panel/HOST_API.md` so a host can take it up; until then `auto`
   resolves to the composed walk.
3. **Acceptance to run on a live host** (not yet done): with
   `demo/output/free-travel-vlog.plan.json`, run `apply_edit_plan` with
   `strategy="composed"` and **`media_dir` set to `demo/`** against a CapCut
   build whose panel is connected, then confirm `verification.timeline` matches
   the plan's `duration_frames` (375) and 3 clips, and that the saved project
   reopens with the media online. `demo/` is the delivery root: the plan's
   portable paths are `assets/<media>` and `galaxy_zh.srt`, so
   `media_dir=demo/assets/` resolves to `demo/assets/assets/<media>` and fails
   before dispatch, naming the files it could not find. Repeat with
   `strategy="host"` once a host implements the batch action.
