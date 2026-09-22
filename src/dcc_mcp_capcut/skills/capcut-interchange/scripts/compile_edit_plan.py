from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.editplan import PLAN_SCHEMA, compile_plan, plan_to_actions


@skill_entry
def main(document: dict, fps: float = 30.0, media_index: dict = None):
    """Compile either accepted plan format into the canonical edit plan.

    The verdict this returns is the verdict every other link applies: the same
    document is what ``export_otio`` lowers, what ``apply_edit_plan``
    assembles, and what rejects an overlap or an out-of-bounds clip.
    """
    plan = compile_plan(document, fps=fps, media_index=media_index)
    script = plan_to_actions(plan)
    return skill_success(
        f"Compiled {PLAN_SCHEMA} from the supplied plan document.",
        schema=plan["schema"],
        plan=plan,
        duration_frames=plan["duration_frames"],
        fps=plan["fps"],
        clip_count=sum(len(track["clips"]) for track in plan["tracks"]),
        caption_count=len(plan["captions"]),
        media_paths=sorted({clip["media"] for track in plan["tracks"] for clip in track["clips"]}),
        actions=script["actions"],
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
