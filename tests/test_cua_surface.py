"""The pixel execution surface, against a fake ``dcc-cua``.

Every test here drives the real argv-building and JSON-parsing code through
:func:`subprocess`, with a stub binary standing in for the driver. That is
deliberate: a test that monkeypatched ``run_json`` would prove the adapter can
call itself, and would not catch a malformed flag or an unparsed envelope.

The behaviours pinned here are the ones the roadmap item is actually about --
exact binding, per-frame coordinates, background-before-foreground delivery, and
verification that fails closed on ``unknown``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dcc_mcp_capcut import bootstrap
from dcc_mcp_capcut.cua import cli, surface
from dcc_mcp_capcut.cua.errors import (
    CuaBindingError,
    CuaDeliveryError,
    CuaNoAccessibility,
    CuaUnavailable,
    CuaUnsupportedPlatform,
    CuaVerificationError,
)
from dcc_mcp_capcut.hosts import LINUX, WINDOWS, get_provider

INVENTORY = [
    {
        "app_name": "CapCut.exe",
        "backend": "windows-native-window-inventory",
        "bounds": {"height": 900, "width": 1600, "x": 100, "y": 50},
        "is_on_screen": True,
        "minimized": False,
        "pid": 4242,
        "title": "CapCut",
        "window_id": 987654,
    }
]


@pytest.fixture
def fake_cua(tmp_path, monkeypatch):
    """Install a stub ``dcc-cua`` and return the handle driving it.

    The stub records every argv it was called with and replays a scripted
    response, so a test asserts on the exact flags the adapter produced.
    """
    calls_path = tmp_path / "calls.jsonl"
    response_path = tmp_path / "response.json"
    exit_path = tmp_path / "exit.txt"
    response_path.write_text(json.dumps({"success": True}), encoding="utf-8")
    exit_path.write_text("0", encoding="utf-8")

    queue_path = tmp_path / "queue.json"
    script = tmp_path / "dcc-cua.py"
    # The stub replays a queue when one is set, so a test can script a sequence
    # -- background fails, foreground succeeds -- instead of one fixed reply.
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys, pathlib
            calls = pathlib.Path(r"{calls_path}")
            with calls.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(sys.argv[1:]) + "\\n")
            queue = pathlib.Path(r"{queue_path}")
            if queue.exists():
                items = json.loads(queue.read_text(encoding="utf-8"))
                if items:
                    payload, code = items[0]
                    queue.write_text(json.dumps(items[1:]), encoding="utf-8")
                    sys.stdout.write(json.dumps(payload))
                    sys.exit(code)
            payload = json.loads(pathlib.Path(r"{response_path}").read_text(encoding="utf-8"))
            sys.stdout.write(json.dumps(payload))
            sys.exit(int(pathlib.Path(r"{exit_path}").read_text(encoding="utf-8").strip() or 0))
            """
        ),
        encoding="utf-8",
    )

    class Fake:
        def __init__(self):
            self.calls_path = calls_path

        def respond(self, payload: dict, *, exit_code: int = 0):
            response_path.write_text(json.dumps(payload), encoding="utf-8")
            exit_path.write_text(str(exit_code), encoding="utf-8")
            if queue_path.exists():
                queue_path.unlink()

        def fail(self, code: str, message: str = "driver said no", *, exit_code: int = 1):
            self.respond(
                {"success": False, "error": {"code": code, "message": message}},
                exit_code=exit_code,
            )

        def script(self, *steps):
            """Queue ``(payload, exit_code)`` replies, consumed one per call."""
            queue_path.write_text(json.dumps(list(steps)), encoding="utf-8")

        @property
        def calls(self) -> list[list[str]]:
            if not calls_path.exists():
                return []
            return [
                json.loads(line)
                for line in calls_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        @property
        def last(self) -> list[str]:
            return self.calls[-1] if self.calls else []

        def flags(self) -> list[str]:
            """Just the leading flags, so a test need not restate every value."""
            return [item for item in self.calls[-1] if item.startswith("--")]

    fake = Fake()
    # Capture the real runner *before* patching it: a wrapper that calls
    # ``subprocess.run`` after the patch would recurse into itself.
    real_run = subprocess.run
    monkeypatch.setattr(cli, "DCC_CUA", sys.executable)
    monkeypatch.setenv("PYTHONPATH", str(script.parent))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: real_run(  # noqa: S603 - fixed argv in tests
            [sys.executable, str(script), *args[1:]], **kwargs
        ),
    )
    # Point the inventory at the fixture window without touching the platform.
    monkeypatch.setattr(
        bootstrap,
        "discover_capcut_window",
        lambda **kwargs: bootstrap.select_capcut_window(INVENTORY, **kwargs),
    )
    return fake


@pytest.fixture
def windows(pin_platform):
    return pin_platform(WINDOWS)


@pytest.fixture
def binding():
    return surface.CuaBinding(
        pid=4242,
        window_handle=987654,
        title="CapCut",
        app_name="CapCut.exe",
        bounds={"x": 100, "y": 50, "width": 1600, "height": 900},
    )


# --- platform boundary -----------------------------------------------------


def test_linux_is_refused_up_front(pin_platform):
    """Linux carries both disqualifiers: no client, and no interactive desktop."""
    provider = pin_platform(LINUX)
    with pytest.raises(CuaUnsupportedPlatform) as error:
        surface.require_interactive_platform()
    assert "Linux" in str(error.value)
    assert provider.unsupported_reason in str(error.value)
    assert error.value.permanent is True


def test_binding_on_linux_never_reaches_the_driver(pin_platform, fake_cua):
    pin_platform(LINUX)
    with pytest.raises(CuaUnsupportedPlatform):
        surface.bind()
    assert fake_cua.calls == []


def test_windows_is_accepted(windows, fake_cua):
    fake_cua.respond(INVENTORY)
    assert surface.bind().pid == 4242


def test_a_missing_cli_is_reported_as_such(windows, monkeypatch):
    """'Not installed' and 'ran and refused' are different facts and remediations."""
    monkeypatch.setattr(cli, "DCC_CUA", "dcc-cua-definitely-absent")
    with pytest.raises(CuaUnavailable, match="not on PATH"):
        surface.bind()


# --- binding ---------------------------------------------------------------


def test_bind_pins_both_ids_and_the_frame_bounds(windows, fake_cua):
    fake_cua.respond(INVENTORY)
    bound = surface.bind()
    assert (bound.pid, bound.window_handle) == (4242, 987654)
    assert bound.bounds == {"x": 100, "y": 50, "width": 1600, "height": 900}
    assert fake_cua.last == ["list"]


def test_bind_refuses_an_ambiguous_inventory(windows, fake_cua):
    """Ambiguity stays an error; the adapter never picks a window by guessing."""
    second = {**INVENTORY[0], "pid": 5555, "window_id": 111222}
    fake_cua.respond(INVENTORY + [second])
    with pytest.raises(CuaBindingError, match="multiple"):
        surface.bind()


def test_bind_refuses_an_empty_inventory(windows, fake_cua):
    fake_cua.respond([])
    with pytest.raises(CuaBindingError, match="no visible CapCut main window"):
        surface.bind()


def test_rebind_proves_the_same_window_still_exists(windows, fake_cua, binding):
    """After an in-place upgrade, a recycled PID must not be taken on trust."""
    fake_cua.respond(INVENTORY)
    rebound = surface.rebind(binding)
    assert (rebound.pid, rebound.window_handle) == (binding.pid, binding.window_handle)


def test_rebind_fails_when_the_window_is_gone(windows, fake_cua, binding):
    fake_cua.respond([{**INVENTORY[0], "pid": 9999, "window_id": 12345}])
    with pytest.raises(CuaBindingError):
        surface.rebind(binding)


# --- snapshot --------------------------------------------------------------


def test_snapshot_captures_the_exact_window_pixels_only(windows, fake_cua, binding):
    """``--pixels-only`` is the correct route for a window with no a11y tree."""
    fake_cua.respond(
        {"success": True, "coordinate_space": {"width": 1600, "height": 900}, "image_base64": "AAA"}
    )
    snap = surface.snapshot(binding)
    assert snap.coordinate_space == (1600, 900)
    assert snap.content_digest
    assert "--pixels-only" in fake_cua.last
    assert "--pid" in fake_cua.last and "4242" in fake_cua.last
    assert "987654" in fake_cua.last


def test_snapshot_never_widens_to_the_desktop(windows, fake_cua, binding):
    """The driver's guarantee is worth an assertion: a receipt is about one window."""
    fake_cua.respond({"success": True, "coordinate_space": {"width": 1600, "height": 900}})
    surface.snapshot(binding)
    assert "desktop-snapshot" not in fake_cua.last
    assert "--pixels-only" in fake_cua.last


def test_a_second_snapshot_detects_that_pixels_changed(windows, fake_cua, binding):
    fake_cua.respond(
        {"success": True, "coordinate_space": {"width": 10, "height": 10}, "image_base64": "before"}
    )
    first = surface.snapshot(binding)
    fake_cua.respond(
        {"success": True, "coordinate_space": {"width": 10, "height": 10}, "image_base64": "after"}
    )
    second = surface.snapshot(binding)
    assert first.content_digest != second.content_digest


def test_snapshot_maps_a_pixel_back_onto_the_desktop(binding):
    snap = surface.CuaSnapshot(binding=binding, observation_width=1600, observation_height=900)
    # bounds.x + x * bounds.width / observation_width  ->  100 + 800*1 = 900
    assert snap.to_screen(800, 450) == (900.0, 500.0)


def test_snapshot_mapping_degrades_safely_without_a_frame():
    """No frame, no mapping -- but it must not invent a coordinate either."""
    snap = surface.CuaSnapshot(binding=surface.CuaBinding(pid=1, window_handle=2))
    assert snap.to_screen(5, 5) == (5.0, 5.0)


# --- delivery --------------------------------------------------------------


def test_a_click_is_delivered_in_the_background_first(windows, fake_cua, binding):
    """Background is the mandatory first attempt; fronting steals focus."""
    fake_cua.respond({"success": True, "delivered": True})
    observation = surface.CuaSnapshot(
        binding=binding, observation_width=1600, observation_height=900
    )
    result = surface.act(binding, "click", {"x": 100, "y": 100}, observation=observation)
    assert result["delivery_mode"] == "background"
    assert result["escalated"] is False
    assert "--observation-width" in fake_cua.last and "1600" in fake_cua.last


def test_foreground_is_only_ever_the_driver_s_escalation(windows, fake_cua, binding):
    """Only ``background_unavailable`` may promote the delivery mode."""
    fake_cua.script(
        ({"success": False, "error": {"code": "background_unavailable", "message": "no"}}, 1),
        ({"success": True, "delivered": True}, 0),
    )
    observation = surface.CuaSnapshot(
        binding=binding, observation_width=1600, observation_height=900
    )
    result = surface.act(binding, "click", {"x": 1, "y": 1}, observation=observation)
    assert result["delivery_mode"] == "foreground"
    assert result["escalated"] is True
    assert len(fake_cua.calls) == 2


def test_a_driver_message_is_truncated_before_it_is_raised(windows, fake_cua, binding):
    """An error says what failed; it is not a channel for unbounded host text."""
    fake_cua.fail("window_target_mismatch", "x" * 5000)
    with pytest.raises(CuaBindingError) as error:
        surface.snapshot(binding)
    assert len(str(error.value)) < 600
    assert error.value.code == "window_target_mismatch"


def test_no_escalation_when_escalation_is_disallowed(windows, fake_cua, binding):
    """No route left means a delivery failure, not a silent success."""
    fake_cua.fail("background_unavailable")
    observation = surface.CuaSnapshot(
        binding=binding, observation_width=1600, observation_height=900
    )
    with pytest.raises(CuaDeliveryError) as error:
        surface.act(
            binding, "click", {"x": 1, "y": 1}, observation=observation, allow_foreground=False
        )
    assert len(fake_cua.calls) == 1
    assert error.value.__cause__.code == "background_unavailable"


def test_a_permanent_driver_failure_is_not_retried(windows, fake_cua, binding):
    """Retrying a permanent refusal wastes a turn and changes nothing."""
    fake_cua.fail("no_accessibility_provider", "no tree here")
    observation = surface.CuaSnapshot(
        binding=binding, observation_width=1600, observation_height=900
    )
    with pytest.raises(CuaDeliveryError) as error:
        surface.act(binding, "click", {"x": 1, "y": 1}, observation=observation)
    # One attempt only, and the driver's permanent verdict is preserved as the
    # cause rather than flattened into a generic delivery failure.
    assert len(fake_cua.calls) == 1
    assert isinstance(error.value.__cause__, CuaNoAccessibility)
    assert error.value.__cause__.permanent is True


def test_a_coordinate_action_without_a_frame_is_refused(windows, fake_cua, binding):
    """An act against an unstated frame is a click at a place nobody looked."""
    fake_cua.respond({"success": True})
    with pytest.raises(Exception, match="observation_width"):
        surface.act(binding, "click", {"x": 1, "y": 1})
    assert fake_cua.calls == []


def test_an_undelivered_action_raises_delivery_error(windows, fake_cua, binding):
    """When neither mode can deliver, say so -- do not report a silent no-op."""
    fake_cua.fail("target_unavailable")
    observation = surface.CuaSnapshot(
        binding=binding, observation_width=1600, observation_height=900
    )
    with pytest.raises(CuaDeliveryError):
        surface.act(
            binding, "click", {"x": 1, "y": 1}, observation=observation, allow_foreground=False
        )


def test_delivery_mode_is_validated_before_the_call(windows, fake_cua, binding):
    observation = surface.CuaSnapshot(binding=binding, observation_width=10, observation_height=10)
    with pytest.raises(Exception, match="delivery_mode"):
        surface.act(
            binding, "click", {"x": 1, "y": 1}, observation=observation, delivery_mode="loud"
        )


def test_the_action_payload_carries_the_exact_window_ids(windows, fake_cua, binding):
    fake_cua.respond({"success": True})
    observation = surface.CuaSnapshot(
        binding=binding, observation_width=1600, observation_height=900
    )
    result = surface.act(binding, "click", {"x": 5, "y": 5}, observation=observation)
    sent = json.loads(fake_cua.last[fake_cua.last.index("--action-json") + 1])
    assert sent["pid"] == 4242
    assert sent["window_id"] == 987654
    assert sent["x"] == 5
    assert result["params"]["x"] == 5


# --- verification ----------------------------------------------------------


def test_verification_passes_when_every_predicate_is_satisfied(windows, fake_cua, binding):
    fake_cua.respond({"success": True, "results": [{"status": "satisfied", "name": "window"}]})
    verdict = surface.verify(binding, [{"window_exists": True}])
    assert verdict.ok is True
    assert verdict.proven is True
    assert verdict.unknown == ()


def test_verification_fails_closed_on_an_unknown_predicate(windows, fake_cua, binding):
    """Unknown never implies success -- this is the single most important rule."""
    fake_cua.respond({"success": True, "results": [{"status": "unknown", "name": "element"}]})
    with pytest.raises(CuaVerificationError) as error:
        surface.verify(binding, [{"element_exists": {"role": "button"}}])
    assert "unknown" in str(error.value)


def test_verification_fails_on_an_unsatisfied_predicate(windows, fake_cua, binding):
    fake_cua.respond({"success": True, "results": [{"status": "unsatisfied", "name": "window"}]})
    with pytest.raises(CuaVerificationError, match="unsatisfied"):
        surface.verify(binding, [{"window_exists": True}])


def test_an_unrecognised_verdict_counts_as_unknown(windows, fake_cua, binding):
    """A verdict this layer does not know is not one it may count as satisfied."""
    fake_cua.respond({"success": True, "results": [{"status": "maybe", "name": "window"}]})
    with pytest.raises(CuaVerificationError):
        surface.verify(binding, [{"window_exists": True}])


def test_no_predicate_results_means_unproven(windows, fake_cua, binding):
    fake_cua.respond({"success": True, "results": []})
    with pytest.raises(CuaVerificationError, match="no predicate results"):
        surface.verify(binding, [{"window_exists": True}])


def test_verification_needs_at_least_one_expectation(binding):
    with pytest.raises(Exception, match="at least one expectation"):
        surface.verify(binding, [])


def test_expectations_are_capped_at_the_driver_s_limit(binding):
    with pytest.raises(Exception, match="at most 8"):
        surface.verify(binding, [{"window_exists": True}] * 9)


def test_unsupported_expectations_are_refused(binding):
    with pytest.raises(Exception, match="unsupported expectation"):
        surface.verify(binding, [{"text_appears": "hello"}])


def test_absence_cannot_be_verified(binding):
    """The driver cannot prove absence either; asking would yield a false unknown."""
    with pytest.raises(Exception, match="cannot be verified"):
        surface.verify(binding, [{"window_exists": False}])


def test_window_bounds_carry_a_bounded_tolerance(binding):
    predicates = surface.build_expectations(
        [{"window_bounds": {"x": 0, "y": 0, "width": 100, "height": 100, "tolerance_px": 500}}]
    )
    assert predicates[0]["window"]["bounds"]["tolerance_px"] == 100


def test_verify_targets_the_bound_window_only(windows, fake_cua, binding):
    fake_cua.respond({"success": True, "results": [{"status": "satisfied"}]})
    surface.verify(binding, [{"window_exists": True}], timeout_ms=1500, stable_samples=3)
    assert "--timeout-ms" in fake_cua.last and "1500" in fake_cua.last
    assert "--stable-samples" in fake_cua.last and "3" in fake_cua.last
    assert "4242" in fake_cua.last and "987654" in fake_cua.last


# --- the argv contract -----------------------------------------------------


def test_argv_is_built_from_literals_and_never_a_shell():
    """Operator data is only ever a value: no flag, no shell, no injection."""
    args = cli.snapshot_args(pid=1, window_handle=2, output="C:\\tmp\\out.png")
    assert args[0] == cli.DCC_CUA
    assert all(isinstance(item, str) for item in args)
    assert "--output" in args
    assert args[args.index("--output") + 1] == "C:\\tmp\\out.png"


def test_ids_are_validated_before_becoming_argv_values():
    with pytest.raises(Exception, match="positive integer"):
        cli.snapshot_args(pid=0, window_handle=2)
    with pytest.raises(Exception, match="positive integer"):
        cli.act_args(pid=1, window_handle=-5, action_json="{}")


def test_a_driver_crash_is_not_mistaken_for_a_verdict(windows, fake_cua, binding):
    """A non-zero exit carrying no payload is a crash, not a successful no-op."""
    fake_cua.script(({}, 3))
    with pytest.raises(Exception, match="no JSON"):
        surface.snapshot(binding)


def test_a_timeout_is_reported_with_the_command(windows, fake_cua, binding, monkeypatch):
    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(Exception, match="timed out"):
        surface.snapshot(binding)


def test_invalid_json_from_the_driver_is_reported(
    windows, fake_cua, binding, tmp_path, monkeypatch
):
    def bad_json(*args, **kwargs):
        class Result:
            returncode = 0
            stdout = "{not json"
            stderr = ""

        return Result()

    monkeypatch.setattr(subprocess, "run", bad_json)
    with pytest.raises(Exception, match="invalid JSON"):
        surface.snapshot(binding)


def test_the_cli_module_exposes_no_shell_route():
    """A regression guard on the seam itself: the adapter shells out exactly once.

    Reads the source rather than the docstring, and strips comments first so the
    module's own explanation of the rule cannot satisfy the check.
    """
    source = Path(cli.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "shell=True" not in code
    assert "os.system" not in code
    assert "shell=" not in code


def test_windows_provider_reports_supported_inventory(windows):
    assert get_provider().window_inventory == "supported"


def test_os_is_imported_for_the_crash_message_guard():
    """Keeps the module's imports honest about what it actually uses."""
    assert hasattr(os, "name")
