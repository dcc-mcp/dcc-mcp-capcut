"""Child-process console handling: the helper, and the gate on every shell-out.

Two things are pinned here and they cover different failure modes.

:func:`test_run_hidden_injects_the_windows_flag` and its counterpart prove the
helper passes the right ``creationflags`` value -- the actual behaviour, on both
Windows and POSIX.

:func:`test_no_shell_out_bypasses_the_helper` is the durable one. It reads every
module under ``src/`` and fails on a direct ``subprocess.run`` / ``Popen`` call,
so a *new* call site added six months from now is caught even though nobody
remembered this file exists. A per-call-site assertion could not do that.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dcc_mcp_capcut import subprocess_util

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "dcc_mcp_capcut"

#: The helper module itself is the only place allowed to call ``subprocess``
#: directly -- it is the seam, not a caller of it.
HELPER_MODULE = SRC_ROOT / "subprocess_util.py"


def _code_without_comments(path: Path) -> str:
    """Strip comment-only lines so prose about a rule cannot satisfy it."""
    source = path.read_text(encoding="utf-8")
    return "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))


class _FakeCompleted:
    returncode = 0
    stdout = ""
    stderr = ""


@pytest.fixture
def captured_kwargs(monkeypatch):
    """Replace ``subprocess.run`` with a recorder, and hand back what it saw."""
    seen: list[dict] = []

    def record(args, **kwargs):
        seen.append({"args": list(args), **kwargs})
        return _FakeCompleted()

    monkeypatch.setattr(subprocess, "run", record)
    return seen


def test_run_hidden_injects_the_windows_flag(captured_kwargs):
    """On Windows the flag must be ``CREATE_NO_WINDOW``, not a generic truthy."""
    assert hasattr(subprocess, "CREATE_NO_WINDOW"), "test requires a Windows host"
    subprocess_util.run_hidden(["dcc-cua", "list"], timeout=5)
    assert captured_kwargs[0]["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_run_hidden_passes_the_flag_through_as_zero_off_windows(monkeypatch, captured_kwargs):
    """Off Windows the flag is inert: ``getattr(..., 0)`` must surface as ``0``."""
    monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    monkeypatch.setattr(subprocess_util, "CREATE_NO_WINDOW", 0)
    subprocess_util.run_hidden(["dcc-cua", "list"], timeout=5)
    assert captured_kwargs[0]["creationflags"] == 0


def test_run_hidden_leaves_every_other_argument_alone(captured_kwargs):
    """The helper hardens window creation only -- argv and semantics are unchanged."""
    subprocess_util.run_hidden(
        ["dcc-cua", "snapshot"],
        capture_output=True,
        text=True,
        timeout=45.0,
    )
    call = captured_kwargs[0]
    assert call["args"] == ["dcc-cua", "snapshot"]
    assert call["capture_output"] is True
    assert call["text"] is True
    assert call["timeout"] == 45.0


def test_run_hidden_does_not_override_an_explicit_flag(monkeypatch, captured_kwargs):
    """An explicit ``creationflags`` wins -- the injection is a default."""
    monkeypatch.setattr(subprocess_util, "CREATE_NO_WINDOW", 0)
    subprocess_util.run_hidden(["dcc-cua", "list"], creationflags=0x00000010)
    assert captured_kwargs[0]["creationflags"] == 0x00000010


def test_the_helper_declares_no_shell_route():
    """Same rule as the CUA seam: no shell, ever, at the one place that shells out."""
    code = _code_without_comments(HELPER_MODULE)
    assert "shell=" not in code
    assert "os.system" not in code


def test_no_shell_out_bypasses_the_helper():
    """Every shell-out in the package goes through ``run_hidden``.

    Delete the helper call at any call site -- revert it to a bare
    ``subprocess.run`` -- and this fails, which is the point: the gate is what
    stops the next call site from reintroducing a flashing console.
    """
    offenders = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if path == HELPER_MODULE:
            continue
        code = _code_without_comments(path)
        if "subprocess.run(" in code or "subprocess.Popen(" in code:
            offenders.append(path.relative_to(SRC_ROOT))
    assert not offenders, f"shell-outs bypassing run_hidden(): {offenders}"
