# CapCut host API contract

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
