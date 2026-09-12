from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.bridge import call_bridge


@skill_entry
def main(**kwargs):
    if not kwargs.get("grant_id"):
        raise ValueError(
            "grant_id is required; obtain it from an operator-owned ui_control system grant"
        )
    return skill_success(
        "CapCut install request submitted to the host grant.",
        **call_bridge("install_capcut", kwargs),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
