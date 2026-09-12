"""Shared typed-skill helper."""

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.bridge import call_bridge
from dcc_mcp_capcut.contracts import validate_host_result


def make_entry(action: str):
    @skill_entry
    def main(**kwargs):
        result = validate_host_result(action, call_bridge(action, kwargs))
        return skill_success(f"CapCut action '{action}' completed.", action=action, **result)

    return main
