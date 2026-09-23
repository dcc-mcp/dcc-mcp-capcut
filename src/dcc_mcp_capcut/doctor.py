"""Read-only preflight diagnostics for the CapCut adapter.

``dcc-mcp-capcut-doctor`` collects the evidence the adapter needs before it
binds a CapCut window, so a failed start reports one diagnosable cause plus a
concrete remediation instead of a bare traceback.

Every check is read-only. Nothing is installed, written, registered or
mutated: the runtime handshake probe runs with a saved/restored environment,
and the port check only opens and immediately closes a loopback socket.

Severity contract:

``ok``
    The prerequisite is satisfied.
``warn``
    The adapter can start, but degraded, insecure or with an optional feature
    disabled.
``fail``
    The adapter cannot start in the current state.
``skip``
    The prerequisite does not apply to this platform.

Exit codes:

``0``
    No check failed; warnings and skips are tolerated.
``1``
    At least one check failed.
``2``
    Invalid command line (argparse).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import socket
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .__version__ import __version__
from .asr import ASR_EXECUTOR_ENV, AsrError, configured_executor, resolve_executor
from .bootstrap import CapCutBindingError, select_capcut_window
from .bridge import DEFAULT_BRIDGE_TOKEN
from .hosts import get_provider
from .installer import verify_installation

OK = "ok"
WARN = "warn"
FAIL = "fail"
SKIP = "skip"
STATUSES = (OK, WARN, FAIL, SKIP)

EXIT_OK = 0
EXIT_FAILED = 1

MIN_PYTHON = (3, 9)
MIN_CORE_VERSION = "0.19.90"
DEFAULT_BRIDGE_PORT = 47410
PANEL_DIR = Path(__file__).resolve().parent / "capcut_panel"
PANEL_FILES = ("HOST_API.md", "index.html", "panel.js")
QT_PROBE_ENV = (
    "DCC_CAPCUT_PROBE_ENDPOINT",
    "DCC_CAPCUT_PROBE_TOKEN",
    "DCC_CAPCUT_PROBE_EXE_SHA256",
)
QT_PROBE_PID_ENV = "DCC_MCP_CAPCUT_PID"
DCC_CUA_TIMEOUT = 15.0

_RUNTIME_MISSING = "DCC_MCP_RUNTIME_MISSING"


@dataclass(frozen=True)
class Check:
    """One diagnostic item: a verdict, its evidence, and an optional fix."""

    name: str
    status: str
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)
    hint: str | None = None


def _version_tuple(value: str) -> tuple[int, ...]:
    """Parse a dotted version into ints, ignoring non-numeric suffixes."""
    parts = []
    for chunk in str(value).strip().split("."):
        digits = ""
        for char in chunk:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _version_at_least(installed: str, minimum: str) -> bool:
    left, right = _version_tuple(installed), _version_tuple(minimum)
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return left >= right


def _distribution_version(distribution: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(distribution)
    except Exception:  # noqa: BLE001 - metadata is advisory, never fatal
        return None


def _python_version() -> str:
    return "{}.{}.{}".format(*sys.version_info[:3])


@contextlib.contextmanager
def _preserved_environ():
    """Run a block without letting it leak environment mutations."""
    original = dict(os.environ)
    try:
        yield
    finally:
        for key in set(os.environ) - set(original):
            os.environ.pop(key, None)
        for key, value in original.items():
            if os.environ.get(key) != value:
                os.environ[key] = value


def check_python() -> Check:
    current = _python_version()
    detail = {"version": current, "minimum": "{}.{}".format(*MIN_PYTHON)}
    if sys.version_info[:2] >= MIN_PYTHON:
        return Check("python", OK, f"CPython {current} satisfies the supported minimum", detail)
    return Check(
        "python",
        FAIL,
        f"CPython {current} is older than the supported minimum {detail['minimum']}",
        detail,
        hint=f"Install Python {detail['minimum']} or newer and reinstall dcc-mcp-capcut into it.",
    )


def check_core() -> Check:
    requirement = f"dcc-mcp-core>={MIN_CORE_VERSION},<1.0.0"
    try:
        import dcc_mcp_core
    except Exception as error:  # noqa: BLE001 - any import failure is the verdict
        return Check(
            "dcc_mcp_core",
            FAIL,
            f"dcc_mcp_core is not importable ({type(error).__name__}: {error})",
            {"importable": False, "minimum": MIN_CORE_VERSION},
            hint=f"pip install '{requirement}'",
        )
    installed = _distribution_version("dcc_mcp_core") or getattr(dcc_mcp_core, "__version__", None)
    if not installed:
        return Check(
            "dcc_mcp_core",
            WARN,
            "dcc_mcp_core is importable but its version metadata is unavailable",
            {"importable": True, "installed": None, "minimum": MIN_CORE_VERSION},
            hint=f"Reinstall the package so its metadata is recorded: pip install --force-reinstall '{requirement}'",
        )
    installed = str(installed)
    detail = {"importable": True, "installed": installed, "minimum": MIN_CORE_VERSION}
    if not _version_at_least(installed, MIN_CORE_VERSION):
        return Check(
            "dcc_mcp_core",
            FAIL,
            f"dcc_mcp_core {installed} is older than the declared install floor {MIN_CORE_VERSION}",
            detail,
            hint=f"pip install --upgrade '{requirement}'",
        )
    return Check(
        "dcc_mcp_core",
        OK,
        f"dcc_mcp_core {installed} satisfies the declared install floor",
        detail,
    )


def check_runtime() -> Check:
    """Probe the runtime/adapter manifest handshake without a traceback."""
    try:
        with _preserved_environ():
            from .shared_runtime import require_runtime

            result = require_runtime()
    except RuntimeError as error:
        message = str(error)
        code = message.split(":", 1)[0].strip()
        if code == _RUNTIME_MISSING:
            return Check(
                "runtime_handshake",
                WARN,
                "the verified dcc-mcp-runtime bundle is not installed",
                {"error_code": code, "handshake": None},
                hint=(
                    "Only the dcc-mcp-capcut-runtime entry point needs the bundle; "
                    "install it, or start the adapter with the plain dcc-mcp-capcut entry point."
                ),
            )
        return Check(
            "runtime_handshake",
            FAIL,
            message,
            {"error_code": code, "handshake": None},
            hint="Reinstall the verified dcc-mcp-runtime bundle and the matching CapCut adapter wheel.",
        )
    except Exception as error:  # noqa: BLE001 - deployment failures must not traceback
        return Check(
            "runtime_handshake",
            FAIL,
            f"the runtime handshake raised {type(error).__name__}: {error}",
            {"error_code": None, "handshake": None},
            hint="Reinstall the verified dcc-mcp-runtime bundle and the matching CapCut adapter wheel.",
        )
    handshake = getattr(result, "handshake", None)
    detail = {
        "error_code": None,
        "handshake": {
            name: getattr(handshake, name, None)
            for name in (
                "adapter_id",
                "adapter_version",
                "runtime_id",
                "runtime_version",
                "capabilities_fingerprint",
            )
        },
    }
    return Check(
        "runtime_handshake", OK, "runtime bundle handshake exposes all four metadata", detail
    )


def check_capcut_executable() -> Check:
    """Grade installation evidence through the platform provider.

    Windows keeps its original verdicts. macOS reports the discovered
    application bundle and its version instead of pretending the host does not
    exist, and Linux reports an explicit ``unsupported`` conclusion with the
    reason rather than an empty "not installed".
    """
    provider = get_provider()
    verdict = provider.check_executable()
    return Check(
        "capcut_executable",
        verdict["status"],
        verdict["summary"],
        verdict["detail"],
        verdict["hint"],
    )


def _dcc_cua_inventory(timeout: float = DCC_CUA_TIMEOUT) -> list[dict[str, Any]]:
    completed = subprocess.run(  # noqa: S603 - project-owned read-only inventory command
        ["dcc-cua", "list"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    inventory = json.loads(completed.stdout)
    if not isinstance(inventory, list):
        raise ValueError("dcc-cua inventory must be a list")
    return inventory


def check_dcc_cua() -> Check:
    """Probe the window inventory through the platform provider.

    Windows: a missing CLI is a failed prerequisite. macOS: window binding is a
    real path but still being validated, and it needs user-granted Accessibility
    permission, so an absent CLI degrades to a warning instead of a failure.
    Linux: no official client exists, so no inventory is attempted at all.
    """
    provider = get_provider()
    if provider.window_inventory == "unsupported":
        return Check(
            "dcc_cua",
            SKIP,
            f"CapCut window binding is unsupported on {provider.label}",
            {
                "installed": False,
                "platform": provider.name,
                "reason": provider.unsupported_reason,
            },
            hint=provider.window_binding_hint(inventory_unavailable=True),
        )
    try:
        inventory = _dcc_cua_inventory()
    except FileNotFoundError:
        if provider.window_inventory == "degraded":
            return Check(
                "dcc_cua",
                WARN,
                "dcc-cua is not installed or not on PATH; window binding is unverified",
                {"installed": False, "platform": provider.name},
                hint=provider.window_binding_hint(inventory_unavailable=True),
            )
        return Check(
            "dcc_cua",
            FAIL,
            "dcc-cua is not installed or not on PATH",
            {"installed": False},
            hint=provider.window_binding_hint(inventory_unavailable=True),
        )
    except subprocess.TimeoutExpired:
        return Check(
            "dcc_cua",
            FAIL,
            f"dcc-cua list timed out after {DCC_CUA_TIMEOUT:g}s",
            {"installed": True},
            hint="Close or restart a hung dcc-cua process, then re-run the doctor.",
        )
    except subprocess.CalledProcessError as error:
        return Check(
            "dcc_cua",
            FAIL,
            f"dcc-cua list exited with {error.returncode}",
            {"installed": True, "returncode": error.returncode},
            hint="Run 'dcc-cua list' manually and fix the reported error before starting the adapter.",
        )
    except (json.JSONDecodeError, ValueError) as error:
        return Check(
            "dcc_cua",
            FAIL,
            f"dcc-cua returned an invalid window inventory ({error})",
            {"installed": True},
            hint="Reinstall dcc-cua so 'dcc-cua list' emits a JSON array of windows.",
        )
    capcut_windows = [
        window
        for window in inventory
        if provider.flavor_by_app_name(window.get("app_name", "")) is not None
    ]
    try:
        binding = select_capcut_window(inventory)
    except CapCutBindingError as error:
        message = str(error)
        hint = (
            "Leave exactly one visible CapCut main window: close the other CapCut windows."
            if "multiple" in message
            else provider.window_binding_hint(inventory_unavailable=False)
        )
        return Check(
            "dcc_cua",
            FAIL,
            f"dcc-cua is available but cannot bind one window: {message}",
            {"installed": True, "capcut_windows": len(capcut_windows)},
            hint=hint,
        )
    return Check(
        "dcc_cua",
        OK,
        f"exactly one visible CapCut main window (pid={binding.pid}, hwnd={binding.window_handle})",
        {"installed": True, "capcut_windows": len(capcut_windows), "pid": binding.pid},
    )


def _bridge_port() -> int:
    try:
        port = int(os.environ.get("DCC_MCP_CAPCUT_BRIDGE_PORT", ""))
    except ValueError:
        return DEFAULT_BRIDGE_PORT
    return port if 1 <= port <= 65535 else DEFAULT_BRIDGE_PORT


def _port_is_free(port: int) -> bool:
    with contextlib.closing(socket.socket()) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def check_bridge_port() -> Check:
    port = _bridge_port()
    if _port_is_free(port):
        return Check("bridge_port", OK, f"127.0.0.1:{port} is free", {"port": port})
    detail: dict[str, Any] = {"port": port}
    try:
        detail["running_bridge"] = verify_installation()
    except Exception as error:  # noqa: BLE001 - the health probe is advisory evidence
        detail["running_bridge_error"] = f"{type(error).__name__}: {error}"
    return Check(
        "bridge_port",
        FAIL,
        f"127.0.0.1:{port} is already in use",
        detail,
        hint=(
            "Stop the running dcc-mcp-capcut instance, or set DCC_MCP_CAPCUT_BRIDGE_PORT "
            "to a free port and restart."
        ),
    )


def check_bridge_token() -> Check:
    token = os.environ.get("DCC_MCP_CAPCUT_BRIDGE_TOKEN", "")
    detail = {
        "configured": bool(token),
        "uses_default_token": token == DEFAULT_BRIDGE_TOKEN,
        "length": len(token),
    }
    if token and token != DEFAULT_BRIDGE_TOKEN:
        return Check("bridge_token", OK, "a per-user bridge token is configured", detail)
    if not token:
        return Check(
            "bridge_token",
            WARN,
            "DCC_MCP_CAPCUT_BRIDGE_TOKEN is unset; the adapter falls back to the shared default",
            detail,
            hint=f"Set DCC_MCP_CAPCUT_BRIDGE_TOKEN to a per-user secret (not '{DEFAULT_BRIDGE_TOKEN}').",
        )
    return Check(
        "bridge_token",
        WARN,
        f"DCC_MCP_CAPCUT_BRIDGE_TOKEN uses the insecure default '{DEFAULT_BRIDGE_TOKEN}'",
        detail,
        hint='Replace it with a per-user secret, e.g. python -c "import secrets;print(secrets.token_urlsafe(32))".',
    )


def check_panel_files() -> Check:
    missing = [name for name in PANEL_FILES if not (PANEL_DIR / name).is_file()]
    detail = {"panel_dir": str(PANEL_DIR), "expected": list(PANEL_FILES), "missing": missing}
    if missing:
        return Check(
            "panel_files",
            FAIL,
            f"the bundled panel payload is incomplete: missing {', '.join(missing)}",
            detail,
            hint="Reinstall the adapter wheel; the panel payload ships inside the package.",
        )
    return Check("panel_files", OK, "the bundled panel payload is complete", detail)


def check_qt_probe() -> Check:
    values = {name: os.environ.get(name, "") for name in QT_PROBE_ENV}
    pid = os.environ.get(QT_PROBE_PID_ENV, "")
    missing = sorted(name for name, value in values.items() if not value)
    problems = []
    if (
        values["DCC_CAPCUT_PROBE_ENDPOINT"]
        and not Path(values["DCC_CAPCUT_PROBE_ENDPOINT"]).is_file()
    ):
        problems.append("DCC_CAPCUT_PROBE_ENDPOINT does not point at a readable file")
    token = values["DCC_CAPCUT_PROBE_TOKEN"]
    if token and len(token.encode()) < 32:
        problems.append("DCC_CAPCUT_PROBE_TOKEN must be at least 32 bytes")
    digest = values["DCC_CAPCUT_PROBE_EXE_SHA256"]
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        problems.append("DCC_CAPCUT_PROBE_EXE_SHA256 must be 64 lowercase hex characters")
    if not pid.isdecimal():
        problems.append(f"{QT_PROBE_PID_ENV} must be the decimal PID of the bound CapCut host")
    detail = {
        "missing": missing,
        "problems": problems,
        "pid_configured": bool(pid),
        "required": [*QT_PROBE_ENV, QT_PROBE_PID_ENV],
    }
    if missing or problems:
        return Check(
            "qt_probe",
            WARN,
            "the optional native Qt probe is not usable; capcut-native skills stay unavailable",
            detail,
            hint=(
                f"Set {', '.join(QT_PROBE_ENV)} and {QT_PROBE_PID_ENV} "
                "to enable the optional Qt probe."
            ),
        )
    return Check("qt_probe", OK, "the optional native Qt probe is fully configured", detail)


def check_opentimelineio() -> Check:
    try:
        import opentimelineio as otio
    except Exception as error:  # noqa: BLE001 - optional extra, never fatal
        return Check(
            "opentimelineio",
            WARN,
            f"opentimelineio is not importable ({type(error).__name__}); OTIO export is unavailable",
            {"importable": False},
            hint="pip install 'dcc-mcp-capcut[interchange]' to enable the capcut-interchange skill.",
        )
    installed = str(getattr(otio, "__version__", "unknown"))
    return Check(
        "opentimelineio",
        OK,
        f"opentimelineio {installed} is importable",
        {"importable": True, "installed": installed},
    )


def check_asr_executor() -> Check:
    """Report whether the external ASR seam has anything to call.

    Transcription is optional, so a missing executor is a ``warn``, never a
    ``fail``: the adapter starts and every other capability works, and only
    ``capcut-asr`` is unavailable. The message still names the variable and
    says plainly that the adapter ships no model, because "no ASR configured"
    is a state a user has to be able to recognise and act on -- silently
    returning an empty transcript would be far worse.
    """
    configured = configured_executor()
    if configured is None:
        return Check(
            "asr_executor",
            WARN,
            f"no ASR executor configured ({ASR_EXECUTOR_ENV} is unset); "
            "transcription is unavailable",
            {"configured": False, "env": ASR_EXECUTOR_ENV, "usable": False},
            hint=(
                f"Set {ASR_EXECUTOR_ENV} to your own transcribe script if you need "
                "captions from audio. The adapter ships no ASR model and downloads "
                "no weights, so the choice of engine is yours; see docs/asr-executor.md."
            ),
        )
    try:
        executor = resolve_executor()
    except AsrError as error:
        return Check(
            "asr_executor",
            WARN,
            str(error),
            {"configured": True, "path": configured, "usable": False},
            hint=f"Point {ASR_EXECUTOR_ENV} at a runnable transcribe script; see docs/asr-executor.md.",
        )
    return Check(
        "asr_executor",
        OK,
        f"ASR executor configured: {executor}",
        {"configured": True, "path": str(executor), "usable": True},
    )


CHECKS: tuple[tuple[str, Callable[[], Check]], ...] = (
    ("python", check_python),
    ("dcc_mcp_core", check_core),
    ("runtime_handshake", check_runtime),
    ("capcut_executable", check_capcut_executable),
    ("dcc_cua", check_dcc_cua),
    ("bridge_port", check_bridge_port),
    ("bridge_token", check_bridge_token),
    ("panel_files", check_panel_files),
    ("qt_probe", check_qt_probe),
    ("opentimelineio", check_opentimelineio),
    ("asr_executor", check_asr_executor),
)


def run_checks() -> list[Check]:
    """Run every check; a broken check becomes a failed check, never a traceback."""
    results: list[Check] = []
    for name, check in CHECKS:
        try:
            results.append(check())
        except Exception as error:  # noqa: BLE001 - diagnostics must never crash the doctor
            results.append(
                Check(
                    name,
                    FAIL,
                    f"the diagnostic itself failed: {type(error).__name__}: {error}",
                    {"error_type": type(error).__name__},
                    hint="Report this as a bug with the doctor --json output attached.",
                )
            )
    return results


@dataclass(frozen=True)
class Report:
    """The full preflight report: ordered checks plus the exit-code contract."""

    checks: tuple[Check, ...]
    python_version: str = field(default_factory=_python_version)
    platform: str = field(default_factory=lambda: os.name)
    # Which platform provider produced the host checks, so a report from a
    # machine the operator did not expect is self-describing.
    host_provider: str = field(default_factory=lambda: get_provider().name)

    @property
    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        return counts

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.status == FAIL)

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def exit_code(self) -> int:
        return EXIT_OK if self.ok else EXIT_FAILED

    def to_json(self) -> dict[str, Any]:
        return {
            "tool": "dcc-mcp-capcut-doctor",
            "version": __version__,
            "python": self.python_version,
            "platform": self.platform,
            "host_provider": self.host_provider,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "counts": self.counts,
            "checks": [asdict(check) for check in self.checks],
        }


def run_doctor() -> Report:
    return Report(checks=tuple(run_checks()))


def render_report(report: Report, *, fix_hints: bool = False) -> str:
    width = max((len(check.name) for check in report.checks), default=0)
    lines = [
        f"dcc-mcp-capcut doctor {__version__} - CPython {report.python_version} on {report.platform}"
    ]
    for check in report.checks:
        lines.append(f"[{check.status:>4}]  {check.name:<{width}}  {check.summary}")
        if fix_hints and check.status != OK and check.hint:
            lines.append(f"{'':<{width + 10}}fix: {check.hint}")
    counts = report.counts
    lines.append("")
    lines.append(
        f"{counts[OK]} passed, {counts[WARN]} warned, {counts[FAIL]} failed, {counts[SKIP]} skipped"
    )
    if not fix_hints:
        lines.append(
            "Re-run with --fix-hints for remediation steps, or --json for a machine-readable report."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dcc-mcp-capcut-doctor",
        description="Read-only preflight diagnostics for the CapCut adapter.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="emit a machine-readable JSON report",
    )
    parser.add_argument(
        "--fix-hints",
        dest="fix_hints",
        action="store_true",
        help="print remediation suggestions; never changes any state",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_doctor()
    if args.as_json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(render_report(report, fix_hints=args.fix_hints))
    return report.exit_code


__all__ = [
    "CHECKS",
    "Check",
    "Report",
    "check_asr_executor",
    "main",
    "render_report",
    "run_checks",
    "run_doctor",
]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
