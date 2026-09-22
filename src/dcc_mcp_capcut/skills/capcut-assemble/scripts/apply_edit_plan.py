"""Assemble a canonical edit plan into a CapCut project.

One call replaces the hand-orchestrated sequence of single-shot tools. The plan
is compiled and lowered to an ordered bridge action script **host-free**, so the
whole edit is validated -- media present, no per-track overlap, nothing out of
bounds -- before the first host mutation is dispatched.

Two dispatch strategies exist because the host side is version-dependent:

* ``host`` -- one ``apply_edit_plan`` action carrying the whole plan, for a host
  that implements it. Preferred when available: one round trip, one receipt.
* ``composed`` -- the adapter walks the action script itself, using only actions
  an existing host already supports (``import_media``, ``create_timeline``,
  ``add_clip``, ``add_text``/``import_subtitles``, ``save_project``).

``auto`` (the default) tries the host action and falls back to the composed walk
only when the host rejects the batch action as unsupported. Any other failure is
raised, never retried as a different edit. A composed run that fails part-way is
reported with the steps it already applied: the host is not rolled back.
"""

from __future__ import annotations

from typing import Any

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.bridge import call_bridge
from dcc_mcp_capcut.contracts import validate_host_result
from dcc_mcp_capcut.editplan import (
    CLIP_PLACEHOLDER,
    MEDIA_PLACEHOLDER,
    TIMELINE_PLACEHOLDER,
    compile_plan,
    is_unsupported_action,
    plan_to_actions,
    substitute_placeholders,
)


def _capture_ids(
    action: str, result: dict[str, Any], step: dict[str, Any], script: dict[str, Any]
) -> dict[str, str]:
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


def _run_composed(script: dict[str, Any]) -> dict[str, Any]:
    """Walk the action script, failing closed and reporting partial progress."""
    ids: dict[str, str] = {}
    executed: list[str] = []
    timeline_readback: dict[str, Any] | None = None
    readback_from: str | None = None

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
        ids.update(_capture_ids(action, result, step, script))

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


def _run_host(plan: dict[str, Any], script: dict[str, Any], media_dir: str) -> dict[str, Any]:
    payload = {"plan": plan, "media_dir": media_dir, "script": script}
    result = validate_host_result("apply_edit_plan", call_bridge("apply_edit_plan", payload))
    return {**result, "executed": ["apply_edit_plan"]}


@skill_entry
def main(
    plan: dict = None,
    recipe: dict = None,
    media_dir: str = None,
    fps: float = 30.0,
    media_index: dict = None,
    strategy: str = "auto",
    export: bool = False,
    dry_run: bool = False,
):
    if plan is not None and recipe is not None:
        raise ValueError("supply exactly one of 'plan' or 'recipe'")
    document = plan if plan is not None else recipe
    if document is None:
        raise ValueError(
            "supply either 'plan' (dcc-mcp-capcut/edit-plan/v1) or 'recipe' (capcut-vlog-recipe/v1)"
        )
    if strategy not in ("auto", "host", "composed"):
        raise ValueError("strategy must be one of: auto, host, composed")

    compiled = compile_plan(document, fps=fps, media_index=media_index)
    script = plan_to_actions(compiled, media_dir=media_dir, export=export)
    summary = {
        "schema": compiled["schema"],
        "plan": compiled,
        "script": script,
        "duration_frames": compiled["duration_frames"],
        "fps": compiled["fps"],
        "step_count": len(script["actions"]),
    }

    if dry_run:
        return skill_success(
            "Edit plan compiled and validated; no host action was dispatched.",
            **summary,
            dispatched=False,
            strategy="none",
        )

    if media_dir is None:
        raise ValueError(
            "media_dir is required unless dry_run is true: the plan stores portable "
            "relative media paths and they must resolve to real files before dispatch"
        )

    fallback_reason = None
    if strategy in ("auto", "host"):
        try:
            result = _run_host(compiled, script, media_dir)
        except (RuntimeError, OSError) as error:
            if strategy == "host" or not is_unsupported_action(error, "apply_edit_plan"):
                raise
            result = None
            fallback_reason = str(error)
        else:
            return skill_success(
                "CapCut assembled the edit plan in one host action.",
                **summary,
                **result,
                dispatched=True,
                strategy="host",
            )

    result = _run_composed(script)
    return skill_success(
        "CapCut assembled the edit plan one verified action at a time.",
        **summary,
        **result,
        dispatched=True,
        strategy="composed",
        fallback_reason=fallback_reason,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
