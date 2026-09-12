from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.installer import installation_plan


@skill_entry
def main(**_kwargs):
    return skill_success("CapCut installation plan generated.", **installation_plan())


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
