"""The end-to-end loop: bind -> snapshot -> input -> verify.

The contract this file exists to protect is the last one in the chain, and the
easiest to get wrong: **a changed pixel is not a verified edit.** A digest
difference proves the window changed; it does not prove the requested change
happened, because a dialog appearing and the edit landing look identical from a
digest. So ``ok`` tracks the predicate verdict alone, and ``pixel_changed`` rides
alongside it as evidence that is never allowed to satisfy it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from dcc_mcp_capcut import cua
from dcc_mcp_capcut.cua import cli, surface
from dcc_mcp_capcut.cua.errors import CuaUnsupportedPlatform, CuaVerificationError
from dcc_mcp_capcut.hosts import LINUX, WINDOWS

INVENTORY = [
    {
        "app_name": "CapCut.exe",
        "bounds": {"height": 900, "width": 1600, "x": 0, "y": 0},
        "is_on_screen": True,
        "minimized": False,
        "pid": 4242,
        "title": "CapCut",
        "window_id": 987654,
    }
]

FRAME = {"success": True, "coordinate_space": {"width": 1600, "height": 900}, "image_base64": "A"}


@pytest.fixture
def fake_cua(tmp_path, monkeypatch):
    """A scriptable ``dcc-cua`` that answers per subcommand."""
    calls_path = tmp_path / "calls.jsonl"
    state_path = tmp_path / "state.json"
    script = tmp_path / "dcc-cua.py"

    # The queue lives in a file, not the environment: a child process cannot
    # mutate its parent's env, so an env-based queue would replay item 0
    # forever and every call would answer the same way.
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys, pathlib
            calls = pathlib.Path(r"{calls_path}")
            with calls.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(sys.argv[1:]) + "\\n")
            state = pathlib.Path(r"{state_path}")
            table = json.loads(state.read_text(encoding="utf-8"))
            subcommand = sys.argv[1] if len(sys.argv) > 1 else ""
            queue = table.get(subcommand) or table.get("*") or []
            if not queue:
                sys.stdout.write(json.dumps({{"success": False,
                    "error": {{"code": "no_window_target", "message": "unscripted "
                    + subcommand}}}}))
                sys.exit(1)
            payload, code = queue[0]
            table[subcommand] = queue[1:]
            state.write_text(json.dumps(table), encoding="utf-8")
            sys.stdout.write(json.dumps(payload))
            sys.exit(code)
            """
        ),
        encoding="utf-8",
    )

    real_run = subprocess.run

    class Fake:
        def script(self, **subcommands):
            """Queue ``(payload, exit_code)`` replies per subcommand."""
            state_path.write_text(
                json.dumps({key: list(value) for key, value in subcommands.items()}),
                encoding="utf-8",
            )
            return self

        @property
        def calls(self) -> list[list[str]]:
            if not calls_path.exists():
                return []
            return [
                json.loads(line)
                for line in calls_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        def subcommands(self) -> list[str]:
            return [call[0] for call in self.calls if call]

    fake = Fake()
    fake.script(**{"*": [({"success": True}, 0)]})
    monkeypatch.setattr(cli, "DCC_CUA", sys.executable)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: real_run(  # noqa: S603 - fixed argv in tests
            [sys.executable, str(script), *args[1:]], **kwargs
        ),
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
        bounds={"x": 0, "y": 0, "width": 1600, "height": 900},
    )


def test_the_loop_runs_bind_snapshot_act_verify_in_order(windows, fake_cua, binding):
    """The four steps the roadmap named, in the order that makes them meaningful."""
    fake_cua.script(
        list=[(INVENTORY, 0)],
        snapshot=[(FRAME, 0), ({**FRAME, "image_base64": "B"}, 0)],
        act=[({"success": True, "delivered": True}, 0)],
        verify=[({"success": True, "results": [{"status": "satisfied", "name": "window"}]}, 0)],
    )
    result = cua.execute("click", {"x": 100, "y": 200}, expectations=[{"window_exists": True}])
    assert [call for call in fake_cua.subcommands()] == [
        "list",
        "snapshot",
        "act",
        "snapshot",
        "verify",
    ]
    assert result.ok is True
    assert result.verified is True


def test_a_changed_pixel_is_never_a_verified_edit(windows, fake_cua, binding):
    """The core rule: evidence of change is not proof of the intended change."""
    fake_cua.script(
        snapshot=[(FRAME, 0), ({**FRAME, "image_base64": "totally-different"}, 0)],
        act=[({"success": True}, 0)],
        verify=[({"success": True, "results": [{"status": "unknown", "name": "element"}]}, 0)],
    )
    with pytest.raises(CuaVerificationError):
        cua.execute(
            binding=binding,
            action="click",
            params={"x": 1, "y": 1},
            expectations=[{"element_exists": {"role": "button"}}],
        )


def test_an_unverified_action_is_not_reported_as_a_success(windows, fake_cua, binding):
    """No expectations means no proof; the receipt must not manufacture one."""
    fake_cua.script(
        snapshot=[(FRAME, 0), ({**FRAME, "image_base64": "B"}, 0)],
        act=[({"success": True}, 0)],
    )
    result = cua.execute("click", {"x": 1, "y": 1}, binding=binding)
    assert result.verified is False
    assert result.ok is False
    assert result.pixel_changed is True


def test_pixel_change_is_reported_alongside_the_verdict(windows, fake_cua, binding):
    fake_cua.script(
        snapshot=[(FRAME, 0), ({**FRAME, "image_base64": "B"}, 0)],
        act=[({"success": True}, 0)],
        verify=[({"success": True, "results": [{"status": "satisfied", "name": "w"}]}, 0)],
    )
    result = cua.execute(
        "click", {"x": 1, "y": 1}, binding=binding, expectations=[{"window_exists": True}]
    )
    assert result.pixel_changed is True
    assert result.verification.proven is True


def test_an_unchanged_frame_is_reported_as_unchanged(windows, fake_cua, binding):
    fake_cua.script(
        snapshot=[(FRAME, 0), (FRAME, 0)],
        act=[({"success": True}, 0)],
        verify=[({"success": True, "results": [{"status": "satisfied"}]}, 0)],
    )
    result = cua.execute(
        "click", {"x": 1, "y": 1}, binding=binding, expectations=[{"window_exists": True}]
    )
    assert result.pixel_changed is False


def test_linux_is_refused_before_anything_runs(pin_platform, fake_cua):
    pin_platform(LINUX)
    with pytest.raises(CuaUnsupportedPlatform):
        cua.execute("click", {"x": 1, "y": 1})
    assert fake_cua.calls == []


def test_the_receipt_is_serialisable(windows, fake_cua, binding):
    """A receipt travels in a log and a report, so it must be JSON-safe."""
    fake_cua.script(
        snapshot=[(FRAME, 0), ({**FRAME, "image_base64": "B"}, 0)],
        act=[({"success": True}, 0)],
        verify=[({"success": True, "results": [{"status": "satisfied"}]}, 0)],
    )
    result = cua.execute(
        "click", {"x": 1, "y": 1}, binding=binding, expectations=[{"window_exists": True}]
    )
    payload = json.dumps(result.as_dict())
    assert "pixel_changed" in payload and "verified" in payload


def test_a_malformed_action_is_refused_before_input_is_delivered(windows, fake_cua, binding):
    """Validation happens before delivery, so a bad call cannot become a click."""
    fake_cua.script(snapshot=[(FRAME, 0)], act=[({"success": True}, 0)])
    with pytest.raises(Exception, match="outside the captured frame"):
        cua.execute("click", {"x": 99999, "y": 1}, binding=binding)
    # One snapshot, then refusal: the act never went out.
    assert "act" not in fake_cua.subcommands()


def test_the_after_capture_can_be_skipped(windows, fake_cua, binding):
    fake_cua.script(snapshot=[(FRAME, 0)], act=[({"success": True}, 0)])
    result = cua.execute("click", {"x": 1, "y": 1}, binding=binding, capture_after=False)
    assert result.after is None
    assert result.pixel_changed is False
    assert fake_cua.subcommands() == ["snapshot", "act"]


def test_a_note_records_when_change_detection_is_impossible(windows, fake_cua, binding):
    """A driver that returns no digest must say so, not imply nothing changed."""
    frameless = {"success": True, "coordinate_space": {"width": 1600, "height": 900}}
    fake_cua.script(snapshot=[(frameless, 0), (frameless, 0)], act=[({"success": True}, 0)])
    result = cua.execute("click", {"x": 1, "y": 1}, binding=binding)
    assert result.pixel_changed is False
    assert any("no pixel digest" in note for note in result.notes)


def test_escalation_is_visible_in_the_receipt(windows, fake_cua, binding):
    fake_cua.script(
        snapshot=[(FRAME, 0), ({**FRAME, "image_base64": "B"}, 0)],
        act=[
            ({"success": False, "error": {"code": "background_unavailable", "message": "no"}}, 1),
            ({"success": True, "delivered": True}, 0),
        ],
        verify=[({"success": True, "results": [{"status": "satisfied"}]}, 0)],
    )
    result = cua.execute(
        "click", {"x": 1, "y": 1}, binding=binding, expectations=[{"window_exists": True}]
    )
    assert result.delivery["delivery_mode"] == "foreground"
    assert result.delivery["escalated"] is True


def test_the_execution_reports_the_bound_window(windows, fake_cua, binding):
    fake_cua.script(snapshot=[(FRAME, 0), (FRAME, 0)], act=[({"success": True}, 0)])
    result = cua.execute("click", {"x": 1, "y": 1}, binding=binding)
    assert result.binding.window_handle == 987654
    assert result.as_dict()["binding"]["pid"] == 4242


def test_ok_requires_a_proven_verdict_not_merely_a_satisfied_one(windows, fake_cua, binding):
    """``ok`` is the conjunction of every predicate being evaluated and passing."""
    fake_cua.script(
        snapshot=[(FRAME, 0), (FRAME, 0)],
        act=[({"success": True}, 0)],
        verify=[
            (
                {
                    "success": True,
                    "results": [
                        {"status": "satisfied", "name": "window"},
                        {"status": "unknown", "name": "element"},
                    ],
                },
                0,
            )
        ],
    )
    with pytest.raises(CuaVerificationError):
        cua.execute(
            "click",
            {"x": 1, "y": 1},
            binding=binding,
            expectations=[{"window_exists": True}, {"element_exists": {"role": "button"}}],
        )


def test_every_module_keeps_the_no_injection_red_line():
    """The adapter drives external input only; it never injects into the host."""
    root = Path(cua.__file__).parent
    for name in ("cli.py", "surface.py", "guards.py", "actions.py", "__init__.py"):
        source = (root / name).read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        for forbidden in ("WriteProcessMemory", "VirtualAllocEx", "CreateRemoteThread"):
            assert forbidden not in code, f"{name} must not inject into the host process"
