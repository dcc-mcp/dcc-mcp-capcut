from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.installer import verify_installation


@skill_entry
def main(**_kwargs):
    return skill_success("CapCut installation verified.", **verify_installation())


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
