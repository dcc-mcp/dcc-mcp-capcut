"""Render a template against N variable sets without touching the host.

This is the check to run *before* spending an hour of render time. It compiles
every variable set into a canonical plan, computes the reframe arithmetic and
the encode preset for each, and reports the failures it found -- per item, not
as one aborting exception, because a batch with three bad variable sets out of
forty is still thirty-seven deliverables.

Nothing here writes a file, dispatches an action, or reads media.
"""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.batch import build_batch, summarize


@skill_entry
def main(
    template: dict = None,
    variables: list = None,
    fps: float = 30.0,
    media_index: dict = None,
):
    if template is None:
        raise ValueError(
            "template is required: a canonical plan or vlog recipe carrying {{placeholder}} fields"
        )
    if variables is None:
        raise ValueError("variables is required: a nonempty list of variable objects")

    # require_output is off here on purpose: inspecting a plan that has not
    # decided where it renders to yet is a legitimate use of this tool, and
    # "no destination" is a fact about the plan rather than a compile error.
    manifest = build_batch(
        template, variables, fps=fps, media_index=media_index, require_output=False
    )
    summary = summarize(manifest)
    failures = [item for item in manifest["items"] if item["state"] == "failed"]
    message = (
        f"Rendered {len(manifest['items'])} variable set(s); {len(failures)} failed to compile."
        if failures
        else f"Rendered {len(manifest['items'])} variable set(s); every one compiled."
    )
    return skill_success(
        message,
        total=summary["total"],
        counts=summary["counts"],
        items=summary["items"],
        # The full plans, so a caller can feed one straight to
        # apply_edit_plan or export_otio without rendering it twice.
        plans=[item["plan"] for item in manifest["items"]],
        reframes=[item["reframe"] for item in manifest["items"]],
        exports=[item["export"] for item in manifest["items"]],
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
