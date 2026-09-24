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

The dispatch itself lives in :mod:`dcc_mcp_capcut.assemble`, because batch
delivery assembles one project per item through the same decision and must not
carry a second copy of the walk.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.assemble import STRATEGIES, assemble, resolve_subtitle_alignment
from dcc_mcp_capcut.editplan import compile_plan, plan_to_actions


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
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of: {', '.join(STRATEGIES)}")

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

    # Resolve alignment once, for both strategies. It happens after the dry run
    # because resolving it writes a file, and a dry run promises to touch
    # nothing; and before the strategy is chosen so the host batch action never
    # sees a directive it would either reject or silently ignore.
    script = resolve_subtitle_alignment(script)
    for subtitle in compiled.get("subtitles", []):
        subtitle.pop("align", None)
        subtitle.pop("output_path", None)

    result = assemble(compiled, script, media_dir, strategy=strategy)
    message = (
        "CapCut assembled the edit plan in one host action."
        if result["strategy"] == "host"
        else "CapCut assembled the edit plan one verified action at a time."
    )
    return skill_success(message, **summary, **result, dispatched=True)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
