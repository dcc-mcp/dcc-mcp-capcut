from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.editplan import PLAN_SCHEMA, plan_from_otio


@skill_entry
def main(source: str, fps: float = None, width: int = None, height: int = None):
    """Read OTIO JSON (or an ``.otio`` file path) into a canonical edit plan.

    This is the import direction of the interchange link. Timings, trims, gaps,
    track structure and caption markers survive the conversion; advisory
    presentation fields are not representable in OTIO and are reported as
    dropped rather than reconstructed.
    """
    plan = plan_from_otio(source, fps=fps, width=width, height=height)
    return skill_success(
        f"Read {PLAN_SCHEMA} from the supplied OTIO.",
        schema=plan["schema"],
        plan=plan,
        duration_frames=plan["duration_frames"],
        fps=plan["fps"],
        clip_count=sum(len(track["clips"]) for track in plan["tracks"]),
        caption_count=len(plan["captions"]),
        media_paths=sorted({clip["media"] for track in plan["tracks"] for clip in track["clips"]}),
        limitations=[
            "Advisory presentation fields (audio volume/fades, caption style, subtitle "
            "file, output path) are not representable in OTIO and are not "
            "reconstructed on import; keep the plan document as the authoritative copy.",
            "Canvas values are read from the dcc_mcp_capcut metadata block; a foreign "
            "OTIO file requires explicit fps, width and height.",
        ],
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
