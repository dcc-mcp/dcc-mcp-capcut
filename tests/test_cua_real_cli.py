"""Contract test against the real ``dcc-cua`` binary.

Every other test in this suite drives a scripted fake, which proves the adapter
is self-consistent and proves nothing about whether the driver agrees: if
``dcc-cua`` renames ``--window-id`` or stops emitting ``coordinate_space``, the
fake keeps happily agreeing with itself and CI stays green.

These tests close that loop by asserting the flags and response fields the
adapter depends on against the **real** CLI's own ``--help`` output and tool
schema. They skip when ``dcc-cua`` is not installed, so CI runners without it
are unaffected -- but on a machine that has it, a driver release that breaks the
contract fails here rather than in production.

Nothing here binds or drives a window: the help text and tool schema are
read-only and need no interactive desktop.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from dcc_mcp_capcut.cua import cli

pytestmark = pytest.mark.skipif(
    shutil.which(cli.DCC_CUA) is None,
    reason=f"{cli.DCC_CUA} is not installed; the driver contract cannot be verified here",
)


@pytest.fixture(scope="module")
def real_help() -> str:
    """The real CLI's usage text, read once for the module."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [cli.DCC_CUA, "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return completed.stdout or ""


def test_the_cli_reports_a_version():
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [cli.DCC_CUA, "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip()


def test_every_subcommand_the_adapter_uses_exists(real_help):
    """A renamed or removed subcommand must fail here, not at a driver timeout."""
    for subcommand in ("list", "snapshot", "act", "verify"):
        assert subcommand in real_help, f"the real CLI no longer documents {subcommand!r}"


def test_every_flag_the_adapter_builds_exists(real_help):
    """These are exactly the flags :mod:`cua.cli` puts on the command line."""
    for flag in (
        "--pid",
        "--window-id",
        "--pixels-only",
        "--action-json",
        "--expect-json",
        "--observation-width",
        "--observation-height",
        "--timeout-ms",
        "--stable-samples",
    ):
        assert flag in real_help, f"the real CLI no longer documents {flag!r}"


def test_pixels_only_is_still_window_scoped(real_help):
    """The guarantee a pixel receipt is about one window, not the whole desktop."""
    assert "--pixels-only" in real_help
    assert "never falls back to a whole-desktop screenshot" in real_help


def test_coordinate_space_is_still_the_field_the_adapter_reads(real_help):
    """``snapshot()`` parses ``coordinate_space``; a rename would silently zero it."""
    assert "coordinate_space" in real_help
    assert "observation_width" in real_help
    assert "observation_height" in real_help


@pytest.fixture(scope="module")
def real_tools() -> dict[str, dict]:
    """The real CLI's tool schema, keyed by tool name."""
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [cli.DCC_CUA, "tools"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    tools = payload if isinstance(payload, list) else payload.get("tools", [])
    return {tool["name"]: tool for tool in tools if isinstance(tool, dict)}


def test_verify_state_still_accepts_the_expect_shape_the_adapter_builds(real_tools):
    """``build_expectations`` emits ``expect: [{window, element}]``; confirm it fits."""
    schema = real_tools.get("verify_state")
    assert schema is not None, "the real CLI no longer exposes verify_state"
    expect = schema.get("inputSchema", schema).get("properties", {}).get("expect", {})
    items = expect.get("items", {})
    properties = items.get("properties", {})
    assert "window" in properties, "verify_state no longer accepts a window predicate"
    assert "element" in properties, "verify_state no longer accepts an element predicate"


def test_verify_state_still_caps_predicates(real_tools):
    """The adapter enforces the same ceiling; confirm the driver still states one."""
    schema = real_tools.get("verify_state")
    expect = schema.get("inputSchema", schema).get("properties", {}).get("expect", {})
    assert "maxItems" in expect, "verify_state no longer documents a predicate ceiling"


def test_click_still_accepts_pixel_coordinates(real_tools):
    """Coordinates are the only addressing mode left on an opaque canvas."""
    schema = real_tools.get("click")
    assert schema is not None, "the real CLI no longer exposes click"
    properties = schema.get("inputSchema", schema).get("properties", {})
    for field in ("x", "y", "delivery_mode", "button"):
        assert field in properties, f"click no longer accepts {field!r}"


def test_delivery_mode_still_makes_background_mandatory_first(real_tools):
    """Background-first is the adapter's rule because the driver demands it.

    The driver states the default in prose rather than as a schema ``default``
    key, so assert on both the enum and the wording that makes background the
    mandatory first attempt -- that wording is what the adapter's escalation
    logic is built on.
    """
    schema = real_tools.get("click")
    properties = schema.get("inputSchema", schema).get("properties", {})
    delivery = properties.get("delivery_mode", {})
    assert set(delivery.get("enum", [])) == {"background", "foreground"}
    description = delivery.get("description", "")
    assert "background" in description and "default" in description
    assert "mandatory first attempt" in description


def test_the_adapter_never_invents_a_flag_the_cli_does_not_have(real_help):
    """Guard against an adapter flag that the real CLI would reject outright."""
    built = set()
    for args in (
        cli.list_args(),
        cli.snapshot_args(pid=1, window_handle=2),
        cli.act_args(pid=1, window_handle=2, action_json="{}"),
        cli.verify_args(pid=1, window_handle=2, expect_json="{}"),
    ):
        built.update(item for item in args if item.startswith("--"))
    documented = set(real_help.split())
    missing = {flag for flag in built if flag not in documented}
    assert not missing, f"the adapter builds flags the real CLI does not document: {missing}"
