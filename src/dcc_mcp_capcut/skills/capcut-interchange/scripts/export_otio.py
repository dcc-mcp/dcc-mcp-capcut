from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.editplan import plan_to_edl
from dcc_mcp_capcut.interchange import export_otio


@skill_entry
def main(timeline=None, plan=None):
    """Export OTIO from either a frame EDL or a canonical edit plan.

    ``plan`` is the canonical contract (``dcc-mcp-capcut/edit-plan/v1``) and is
    lowered with :func:`plan_to_edl`, so the OTIO link and the assembly link
    apply the same overlap, bounds and media-path rules.
    """
    if (timeline is None) == (plan is None):
        raise ValueError("supply exactly one of 'timeline' (frame EDL) or 'plan' (edit plan)")
    if plan is not None:
        return skill_success(
            "Portable OTIO created from a canonical edit plan.", **export_otio(plan_to_edl(plan))
        )
    return skill_success(
        "Portable OTIO created from supplied edit decisions.", **export_otio(timeline)
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
