from dcc_mcp_capcut.skills._shared.scripts.common import make_entry

main = make_entry("configure_environment")

if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
