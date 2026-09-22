# CapCut host API contract

This file is written for whoever **implements** `window.CapCut` — the CapCut-side
host integration. If you are instead trying to *load* the panel as an operator,
read [`LOADING.md`](LOADING.md) first.

The bundled panel intentionally depends on a host-provided `window.CapCut`
object. The object must expose:

```js
window.CapCut = { dispatch(action, params) -> Promise<object> }
```

`dispatch` should map each typed action name from the skill catalog to the
supported CapCut Desktop SDK/UI integration for that release. Unsupported
actions must reject with a structured error. The MCP bridge will surface that
error to the caller; it never treats an acknowledgement as a completed edit.

For `install_capcut`, the host integration must invoke the core
`ui_control__system_operation` capability using the supplied operator-owned
`grant_id` and the exact WinGet command from `installation_plan`. It must not
run an arbitrary shell command or infer consent. `configure_environment` must
similarly use the approved system-operation grant (or a CapCut-managed settings
API) and return a readback of the effective bridge URL, port, and panel path.

For `auto_setup_capcut`, the host integration must execute the same sequence as
the individual setup actions: inspect the supplied detection evidence, request
the exact WinGet install only when `install_required` is true, configure the
shared `dcc-mcp-runtime` bridge/panel, then return phase-by-phase readback. The
action is idempotent and must remain consent-gated by the supplied `grant_id`;
the panel must never silently install software or claim readiness before the
CapCut process, bridge health, panel load, and exact PID/HWND binding are
verified.

### Batch assembly: `apply_edit_plan`

`apply_edit_plan` is an **optional** action: one call carries a whole
`dcc-mcp-capcut/edit-plan/v1` document (see `docs/edit-plan.md`) and places it
as a project. A host that implements it should:

1. Execute the supplied `script.actions` in order, resolving `media_dir`
   against the plan's portable relative paths.
2. Return `timeline_id`, `verification.ok: true`, and the authoritative
   timeline readback under `verification.timeline`.
3. Be atomic where the host allows it, and return a structured error when it
   cannot be, naming the steps it already applied.

**A host that does not implement it must reject it with this exact shape:**

```text
Unsupported action: apply_edit_plan
```

The adapter matches the marker `unsupported action` (or `unsupported_action` in
a structured payload), a colon, then the action name. The panel stringifies
rejections, so the text has to carry all of it.

**Be precise about which failure you are reporting.** A host that *does*
implement the action and rejects one of its arguments must **not** use that
shape -- put the qualifier before the colon, as in
`Unsupported action parameter for apply_edit_plan: media_dir`. The two cases are
distinguished on purpose:

| Host situation | Correct message | Adapter behaviour |
| --- | --- | --- |
| Action not implemented | `Unsupported action: apply_edit_plan` | Falls back to composing the plan from the individual actions. |
| Action implemented, argument invalid | `Unsupported action parameter for apply_edit_plan: media_dir` | Reported as a real failure. Never retried as a different edit. |

Getting this wrong in the first direction is the expensive one: a parameter
error that looks like "not implemented" makes the adapter replay the whole plan
as a composed script over a timeline the batch action may already have partly
assembled, and the composed walk does not roll back. A host that under-reports
"not implemented" merely loses the fast path and still works via composition.
Rejecting for any other reason is treated as a real failure and is never retried
as a different edit.

The adapter's fallback walks the action script itself, so a host can adopt the
batch action at its own pace; until then `auto` resolves to the composed path.

The host implementation should return stable IDs (`media_id`, `timeline_id`,
`clip_id`, `text_id`, `effect_id`, `job_id`) and include a post-operation
readback (`project`, `timeline`, or `export`) so acceptance can verify the real
state. Keep this file alongside the panel when adapting it to a CapCut release.

Every mutating action must also return `verification: {ok: true, ...}`. Timeline
mutations must put the authoritative timeline readback under
`verification.timeline`; a bare acknowledgement such as `{accepted: true}` is
an error. In particular, `import_subtitles` is complete only after the host
returns non-empty `caption_ids` and the timeline readback proves an editable
text track exists. Merely importing an SRT/LRC/ASS file into the asset browser
must not be reported as success.
