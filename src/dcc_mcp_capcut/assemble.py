"""Host-facing assembly, shared by the assemble skill and batch delivery.

A canonical plan becomes a CapCut project either through the optional host
``apply_edit_plan`` action or through the adapter's own composed walk over the
single-shot actions. Batch delivery needs the identical decision -- every item
in a batch is one assembly followed by one export -- so the walk lives here
rather than being copied into a second script, where the two copies would drift
the first time one of them was fixed.

Nothing here decides *what* to assemble: :func:`dcc_mcp_capcut.editplan.plan_to_actions`
renders the script, and this module plays it.
"""

from __future__ import annotations

from typing import Any, Optional

from dcc_mcp_capcut.bridge import call_bridge
from dcc_mcp_capcut.contracts import validate_host_result
from dcc_mcp_capcut.editplan import (
    CLIP_PLACEHOLDER,
    MEDIA_PLACEHOLDER,
    TIMELINE_PLACEHOLDER,
    is_unsupported_action,
    substitute_placeholders,
)
from dcc_mcp_capcut.subtitles import prepare_import_params

#: The strategies a caller may name. ``auto`` is the default and the honest one:
#: a host that implements the batch action is one round trip and one receipt,
#: and a host that does not is walked action by action.
STRATEGIES = ("auto", "host", "composed")


def dispatch(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """One host call, held to the result contract before it is believed.

    Every caller in this adapter that dispatches a single action needs the same
    two steps, and skipping the second one is how a half-truth becomes a
    reported success -- so the pair lives here instead of being re-typed in each
    script.
    """
    return validate_host_result(action, call_bridge(action, params))


def capture_ids(action: str, result: dict[str, Any], step: dict[str, Any]) -> dict[str, str]:
    """Record the stable ids a host receipt returned so later steps can use them."""
    if action == "import_media":
        # The contract guarantees a single media_id per call, which is why the
        # script imports one file per step.
        media_id = result.get("media_id")
        reference = step.get("media_ref")
        if not media_id or not reference:
            raise RuntimeError(
                "import_media returned no media_id for a step that needs one; "
                "cannot map media to the placed clips"
            )
        return {f"{MEDIA_PLACEHOLDER}{reference}": str(media_id)}
    if action == "create_timeline":
        timeline_id = result.get("timeline_id")
        return {TIMELINE_PLACEHOLDER: str(timeline_id)} if timeline_id else {}
    if action == "add_clip" and step.get("clip_ref"):
        clip_id = result.get("clip_id")
        return {f"{CLIP_PLACEHOLDER}{step['clip_ref']}": str(clip_id)} if clip_id else {}
    return {}


def resolve_subtitle_alignment(script: dict[str, Any]) -> dict[str, Any]:
    """Rewrite every ``import_subtitles`` step so the directives are gone.

    Called once, before the strategy is chosen, so the host batch action and the
    composed walk dispatch the *same* rewritten file. Resolving it only on the
    composed path would leak ``align`` to a host that implements the batch
    action -- and ``auto`` tries that host first, so a permissive one would
    import the unaligned source and report success.
    """
    for step in script["actions"]:
        if step["action"] == "import_subtitles":
            step["params"] = prepare_import_params(step["params"])
    return script


def run_composed_script(script: dict[str, Any]) -> dict[str, Any]:
    """Walk the action script, failing closed and reporting partial progress."""
    ids: dict[str, str] = {}
    executed: list[str] = []
    timeline_readback: Optional[dict[str, Any]] = None
    readback_from: Optional[str] = None

    for step in script["actions"]:
        action = step["action"]
        params = substitute_placeholders(step["params"], ids)
        try:
            result = validate_host_result(action, call_bridge(action, params))
        except (RuntimeError, OSError) as error:
            raise RuntimeError(
                f"apply_edit_plan stopped at step {len(executed)} ({action}): {error}. "
                f"Steps already applied: {executed or ['none']}. The host is not rolled "
                "back -- inspect the project before retrying."
            ) from error
        executed.append(action)
        verification = result.get("verification")
        if isinstance(verification, dict) and isinstance(verification.get("timeline"), dict):
            timeline_readback = verification["timeline"]
            readback_from = action
        ids.update(capture_ids(action, result, step))

    if timeline_readback is None:
        raise RuntimeError(
            "apply_edit_plan completed but no step returned a timeline readback; "
            "the assembled state cannot be proven"
        )
    return {
        "timeline_id": ids.get(TIMELINE_PLACEHOLDER),
        "executed": executed,
        "verification": {
            "ok": True,
            "timeline": timeline_readback,
            "readback_from": readback_from,
            "steps": len(executed),
        },
    }


def run_host_plan(plan: dict[str, Any], script: dict[str, Any], media_dir: str) -> dict[str, Any]:
    """Hand the whole plan to the host in one ``apply_edit_plan`` action."""
    payload = {"plan": plan, "media_dir": media_dir, "script": script}
    result = validate_host_result("apply_edit_plan", call_bridge("apply_edit_plan", payload))
    # Only the fields the contract guarantees are spread into the tool result.
    # The rest of the receipt is nested: a host is free to echo back the `plan`
    # or `script` it received, and spreading that straight into the result would
    # collide with the summary keys and raise TypeError -- reporting a failure
    # for an assembly that actually succeeded.
    return {
        "timeline_id": result.get("timeline_id"),
        "verification": result["verification"],
        "host_result": result,
        "executed": ["apply_edit_plan"],
    }


def assemble(
    plan: dict[str, Any],
    script: dict[str, Any],
    media_dir: str,
    *,
    strategy: str = "auto",
) -> dict[str, Any]:
    """Assemble a plan, choosing the dispatch strategy.

    Returns the winning result plus the ``strategy`` that produced it and, when
    the host rejected the batch action, the ``fallback_reason``. Any failure
    other than a clean "this action is not implemented" is raised, never retried
    as a different edit: replaying a partly applied plan as a composed script
    over a timeline the batch action may already have populated is not a
    recovery, it is a second edit.

    A composed run that fails part-way is reported with the steps it already
    applied; the host is not rolled back.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of: {', '.join(STRATEGIES)}")

    fallback_reason = None
    if strategy in ("auto", "host"):
        try:
            result = run_host_plan(plan, script, media_dir)
        except (RuntimeError, OSError) as error:
            if strategy == "host" or not is_unsupported_action(error, "apply_edit_plan"):
                raise
            fallback_reason = str(error)
        else:
            result["strategy"] = "host"
            result["fallback_reason"] = None
            return result

    result = run_composed_script(script)
    result["strategy"] = "composed"
    result["fallback_reason"] = fallback_reason
    return result
