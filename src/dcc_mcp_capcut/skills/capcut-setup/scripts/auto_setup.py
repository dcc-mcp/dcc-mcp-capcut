"""Consent-gated CapCut installation and runtime binding orchestration."""

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.bridge import call_bridge
from dcc_mcp_capcut.installer import detect_installation


@skill_entry
def main(**kwargs):
    grant_id = kwargs.get("grant_id")
    if not grant_id:
        raise ValueError(
            "grant_id is required; obtain it from an operator-owned ui_control system grant"
        )
    detection = detect_installation()
    request = {
        **kwargs,
        "install_required": not detection["installed"],
        "bind_runtime": True,
        "detection": detection,
    }
    return skill_success(
        "CapCut installation and shared-runtime binding requested.",
        **call_bridge("auto_setup_capcut", request),
    )


if __name__ == "__main__":  # pragma: no cover
    from dcc_mcp_core.skill import run_main

    run_main(main)
