from dcc_mcp_capcut.skills._shared.scripts.common import make_entry

# configure_environment mutates bridge config, so it is consent-gated: the
# grant is checked here rather than only on the host side.
main = make_entry("configure_environment", require_grant=True)

if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
