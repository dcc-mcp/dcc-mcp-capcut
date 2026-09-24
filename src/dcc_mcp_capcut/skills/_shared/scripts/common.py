"""Shared typed-skill helper."""

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_capcut.bridge import call_bridge
from dcc_mcp_capcut.contracts import validate_host_result

GRANT_REQUIRED = "grant_id is required; obtain it from an operator-owned ui_control system grant"


def make_entry(action: str, *, require_grant: bool = False):
    """Build a typed skill entry that forwards one action to the bridge.

    ``require_grant`` marks the action as consent-gated: the grant is checked
    locally, before dispatch, so the caller gets the documented refusal instead
    of waiting out a bridge timeout the host would reject anyway.
    """

    @skill_entry
    def main(**kwargs):
        if require_grant and not kwargs.get("grant_id"):
            raise ValueError(GRANT_REQUIRED)
        # The request is passed to the validator so an opt-in flag such as
        # verify_output can tighten this call's contract without tightening
        # anybody else's.
        result = validate_host_result(action, call_bridge(action, kwargs), params=kwargs)
        return skill_success(f"CapCut action '{action}' completed.", action=action, **result)

    return main
