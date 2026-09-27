"""The one place the adapter shells out, and the only argv it may build.

``dcc-cua`` is the project-owned UI-control CLI. This module is deliberately the
*only* seam that reaches it, for the same reason the panel is the only component
allowed to call CapCut host APIs: a typed adapter that assembles command lines
at the call site is one format string away from a shell.

Two rules hold for every function here:

- **Fixed argv.** Each builder returns a list whose flags are literals. Operator
  data -- PIDs, coordinates, JSON payloads -- is only ever a *value*, never a
  flag, and never reaches a shell.
- **Fail closed with a code.** A driver failure arrives as a JSON envelope and
  is classified into the :mod:`~dcc_mcp_capcut.cua.errors` taxonomy, so the
  caller branches on a code rather than matching prose.

Driver messages are truncated before they are raised: an error surfaces *what*
failed, not an unbounded copy of host text the operator never asked to see.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

from .errors import CuaError, CuaUnavailable, classify

#: The CLI name resolved on PATH. Kept a module constant so tests can point the
#: whole module at a fake binary in one place.
DCC_CUA = "dcc-cua"

#: Generous enough for a cold start plus one window capture, short enough that a
#: hung driver is reported instead of stalling an agent turn.
DEFAULT_TIMEOUT = 45.0

#: Driver text is evidence, not content: cap it so an operator log stays a log.
MAX_MESSAGE = 400

#: Exit statuses that mean "the driver ran and answered", as opposed to a
#: transport-level failure. A non-zero status in this range still carries a
#: parseable JSON envelope on stdout.
_JSON_STATUSES = range(0, 256)


def _truncate(text: str) -> str:
    collapsed = " ".join(str(text or "").split())
    return collapsed if len(collapsed) <= MAX_MESSAGE else collapsed[: MAX_MESSAGE - 1] + "…"


def _positive_int(value: Any, field: str) -> str:
    """Validate one id before it becomes an argv value."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CuaError(f"{field} must be a positive integer, got {value!r}")
    return str(value)


def _non_negative_int(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CuaError(f"{field} must be a non-negative integer, got {value!r}")
    return str(value)


# --- argv builders ---------------------------------------------------------
#
# Every builder takes already-validated values and returns a list. No builder
# accepts a free-form flag list, and none of them uses shell=True.


def list_args() -> list[str]:
    """``dcc-cua list`` -- the read-only window inventory."""
    return [DCC_CUA, "list"]


def snapshot_args(*, pid: int, window_handle: int, output: str | None = None) -> list[str]:
    """``dcc-cua snapshot`` against one exact window, pixels only.

    ``--pixels-only`` is not an optimisation here, it is the correct route: the
    driver documents that ``no_accessibility_provider`` is permanent for a window
    class, and CapCut's whole UI is a single opaque QML canvas. Asking for the
    accessibility tree on every capture would pay for a projection that cannot
    exist. It also pins the capture to the exact window -- the driver never
    widens it to a whole-desktop screenshot, so a pixel receipt is always
    evidence about the bound window alone.
    """
    args = [
        DCC_CUA,
        "snapshot",
        "--pid",
        _positive_int(pid, "pid"),
        "--window-id",
        _positive_int(window_handle, "window_handle"),
        "--pixels-only",
    ]
    if output is not None:
        args += ["--output", str(output)]
    return args


def act_args(
    *,
    pid: int,
    window_handle: int,
    action_json: str,
    observation_width: int | None = None,
    observation_height: int | None = None,
    output: str | None = None,
) -> list[str]:
    """``dcc-cua act`` -- deliver one action to one exact window.

    The observation size is what makes coordinate input meaningful: the driver
    maps ``x``/``y`` from the *last* screenshot's coordinate space, so an act
    without the matching width/height is a guess against a stale frame. Callers
    pass the size of the snapshot they just took.
    """
    args = [
        DCC_CUA,
        "act",
        "--pid",
        _positive_int(pid, "pid"),
        "--window-id",
        _positive_int(window_handle, "window_handle"),
        "--action-json",
        str(action_json),
    ]
    if observation_width is not None:
        args += ["--observation-width", _positive_int(observation_width, "observation_width")]
    if observation_height is not None:
        args += ["--observation-height", _positive_int(observation_height, "observation_height")]
    if output is not None:
        args += ["--output", str(output)]
    return args


def verify_args(
    *,
    pid: int,
    window_handle: int,
    expect_json: str,
    timeout_ms: int | None = None,
    stable_samples: int | None = None,
) -> list[str]:
    """``dcc-cua verify`` -- evaluate bounded predicates against one window."""
    args = [
        DCC_CUA,
        "verify",
        "--pid",
        _positive_int(pid, "pid"),
        "--window-id",
        _positive_int(window_handle, "window_handle"),
        "--expect-json",
        str(expect_json),
    ]
    if timeout_ms is not None:
        args += ["--timeout-ms", _positive_int(timeout_ms, "timeout_ms")]
    if stable_samples is not None:
        args += ["--stable-samples", _positive_int(stable_samples, "stable_samples")]
    return args


# --- runner ----------------------------------------------------------------


def _decode_envelope(payload: Any) -> dict[str, Any]:
    """Normalise one driver response into a dict, or explain why it is not one.

    A bare array is a legitimate answer, not a malformed one: ``dcc-cua list``
    emits the window inventory as a JSON array with no envelope around it. It is
    wrapped here so every caller downstream sees the same shape.
    """
    if isinstance(payload, list):
        return {"success": True, "windows": payload}
    if not isinstance(payload, dict):
        raise CuaError("dcc-cua returned a response that is not a JSON object")
    error = payload.get("error")
    if payload.get("success") is False:
        if isinstance(error, dict):
            raise classify(str(error.get("code") or ""), _truncate(error.get("message")))
        raise CuaError(_truncate(error or "dcc-cua reported a failure without a code"))
    return payload


def run_json(args: Sequence[str], *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Run one fixed argv and return the driver's JSON object.

    Raises :class:`CuaUnavailable` when the CLI is absent -- which is a
    different fact from "the CLI ran and refused", and gets a different
    remediation -- and maps every other transport failure onto the taxonomy.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - project-owned CLI, fixed argv, no shell
            list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise CuaUnavailable(
            "dcc-cua is not installed or not on PATH; the pixel execution route is unavailable"
        ) from error
    except subprocess.TimeoutExpired as error:
        command = " ".join(args[:2])
        raise CuaError(f"dcc-cua {command} timed out after {timeout:g}s") from error
    except OSError as error:
        raise CuaError(f"dcc-cua could not be started: {error.strerror or error}") from error

    stdout = (completed.stdout or "").strip()
    if not stdout:
        # A non-zero exit with no payload is a crash, not a verdict: say so with
        # the status attached rather than pretending an empty result was a
        # successful no-op.
        raise CuaError(
            f"dcc-cua exited with {completed.returncode} and produced no JSON"
            if completed.returncode not in (0,)
            else "dcc-cua produced no output"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise CuaError(
            f"dcc-cua returned invalid JSON ({error.msg} at line {error.lineno})"
        ) from error

    if completed.returncode != 0:
        has_verdict = isinstance(payload, dict) and bool(
            payload.get("error") or payload.get("success") is not None
        )
        if not has_verdict:
            # A non-zero exit carrying no verdict is a crash. Reporting it as an
            # empty success would let a failed driver call read as a no-op.
            raise CuaError(f"dcc-cua exited with {completed.returncode} and produced no JSON")
        # Non-zero exit with a real envelope: classify it so the driver's own
        # error code reaches the caller.
        payload = {**payload, "success": False}
    return _decode_envelope(payload)


__all__ = [
    "DCC_CUA",
    "DEFAULT_TIMEOUT",
    "MAX_MESSAGE",
    "act_args",
    "list_args",
    "run_json",
    "snapshot_args",
    "verify_args",
]

# Keep the status range referenced for readers: every exit status is inspected,
# but only through ``completed.returncode``, never through a shell.
assert _JSON_STATUSES is not None
