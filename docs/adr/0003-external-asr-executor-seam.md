# ADR 0003: An external ASR executor seam, and subtitles as plan content

- Status: Proposed
- Date: 2026-09-22

## Context

Subtitles are among the most-requested CapCut automations, and they sit exactly
on the seam of the two-stage workflow the external signal describes: an upstream
tool decomposes video and generates material, the skill renders that material
into CapCut. Transcripts are the most common thing the upstream produces.

`capcut-text` already had `auto_captions` and `import_subtitles`, but:

1. **No external ASR seam.** The only way to get speech into text was the
   host's own `auto_captions`, so the engine choice was the host's, not the
   user's.
2. **No batch path.** Multi-language delivery meant N tool calls, and a failure
   on the last one left the timeline half-populated.
3. **No alignment choice.** `import_subtitles` took an `offset` and nothing
   else, so a transcript whose timecodes belonged to a different cut could not
   be laid out by order.

The reference implementation in the wild (`yichen-jianying-edit`) uses
`scripts/asr_once.py` plus a `YICHEN_ASR_EXECUTOR` environment variable pointing
at the user's own transcribe script, falling back to a local script when unset.
The pattern worth copying is **the seam shape** -- the user picks the engine --
not its fixed-hash gating.

## Decision

### 1. The adapter defines the contract, never the engine

`src/dcc_mcp_capcut/asr.py` is the seam. `DCC_MCP_CAPCUT_ASR_EXECUTOR` names an
executable; the adapter validates the request, runs it as an argv list with
`shell=False`, and normalises the result. No model is bundled, no weights are
downloaded, no heavy dependency is added.

Failure modes are **distinct exception types** rather than one error with a
different message, because the caller's next action differs: an unconfigured
executor is a setup step, a timeout is a bigger budget or a faster engine, and
unparseable output is a bug in the user's script. `AsrNotConfiguredError`,
`AsrExecutorMissingError`, `AsrTimeoutError`, `AsrFormatError`,
`AsrExecutionError`.

An empty stdout is an `AsrFormatError`, **not** an empty transcript. Silence
from an executor is a failure the user must see, not a successful transcription
of nothing.

**Rejected alternative: bundling a model or an optional `dcc-mcp-capcut[asr]`
extra.** It would pick a winner in a fast-moving field, add a large dependency
to a package whose value is being a small, reliable receiving end, and still not
match whatever the upstream pipeline already runs.

### 2. The executor path comes from the operator, never from data

A plan document is data. Data never names an executable. The path is read from
the environment or an explicit call argument only.

### 3. Alignment is resolved offline, in the adapter

`import_subtitles` gains `align`: `timecode` (default, unchanged behaviour) or
`sequence` (discard the absolute timecodes, pack cues back to back). Under
`sequence` the adapter parses the file, re-times it, writes SRT and imports
**that**.

**Rejected alternative: pass `align` to the host and let it decide.** A host
that silently ignores an unknown parameter is indistinguishable from one that
implemented it, so a plan that was validated offline could import unaligned and
look like it worked. Resolving it in the adapter makes the verdict identical on
every host build, and makes it testable in CI with no host at all.

`align` and `output_path` are stripped before dispatch: they are adapter-side
directives. Forwarding them would either be rejected by a strict host or
silently dropped by a permissive one -- and the second case is precisely how
"the alignment never happened" goes unnoticed.

`align: sequence` in a plan **requires** `output_path`. The plan is host-free
and cannot choose a write location on the user's disk.

### 4. Subtitles become a list on the canonical plan

The plan gains `subtitles: [...]`, with `subtitle` (the singular form introduced
one PR earlier in Stage 2) kept as an input alias. The canonical document
carries **only** the list, because Stage 2's whole purpose was eliminating two
shapes for one thing; adding a second subtitle shape would have regressed the
fix. The two are mutually exclusive at input and normalisation is idempotent --
`apply_edit_plan` normalises twice, so the output has to re-normalise cleanly.

One `import_subtitles` step per file. `caption_ids` comes back **per call**, so
a merged import could not be mapped to the language it came from.

ASS is deliberately not parsed offline: its timing is event-based, and reducing
it to start/end/text would discard more than it preserves. Asking for offline
alignment on one raises rather than guessing.

## Consequences

**Good**

- The engine choice stays with the user, and swapping engines is one
  environment variable.
- Multi-language delivery is one call (`import_subtitles_batch`) or one plan,
  validated offline by `dry_run` before anything touches the host.
- Every alignment verdict is settled host-free, so it is testable in CI on all
  three platforms.
- `doctor` reports `asr_executor: warn` when unset -- visible, actionable, and
  not a preflight failure, because transcription is optional.

**Cost / accepted**

- An extra skill (`capcut-asr`, 13 total) and a new document to maintain.
- `normalize_plan` now emits `subtitles` instead of `subtitle`, which is a
  change to the canonical document shape. The singular form still compiles, so
  no plan in the repo or the demo had to change; one internal test assertion
  was updated.
- `import_subtitles_batch` is not transactional. A part-way failure reports what
  landed and is never silently undone: deleting caption items by id to roll back
  risks destroying a track this call did not create.
- An executor is a subprocess the operator named. That is the seam's purpose,
  and it is why the path never comes from data.

## Not done

- No bundled, default or recommended engine.
- No speaker diarisation or translation -- both are the executor's business.
- No ASS parsing (see above).
