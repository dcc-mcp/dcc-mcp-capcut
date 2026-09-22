"""The external ASR executor seam.

Speech-to-text is the one part of the subtitle chain the adapter must **not**
own. Choosing an engine is a user decision: it depends on language, hardware,
licence and whatever the upstream pipeline already runs. So the adapter ships
no model, downloads no weights, and adds no heavy dependency. It defines a
contract and invokes whatever the user points it at.

That contract lives entirely in the environment:

``DCC_MCP_CAPCUT_ASR_EXECUTOR``
    Path to a user-supplied executable (a script, a binary, a wrapper around a
    service). Unset means "no ASR configured", which is reported as such --
    never as a silent empty transcript.

``DCC_MCP_CAPCUT_ASR_TIMEOUT``
    Seconds the executor may run. Optional; defaults to
    :data:`DEFAULT_TIMEOUT`.

Invocation (``shell=False`` throughout, so no argument is ever interpreted by
a shell)::

    <executor> <media> [--language <code>] --format <srt|json>

stdout carries the transcript, stderr carries diagnostics, and the exit status
decides the verdict:

* ``0`` and ``--format srt``  -- stdout is SRT text.
* ``0`` and ``--format json`` -- stdout is
  ``{"language": str|null, "segments": [{"start": float, "end": float, "text": str}]}``.
* non-zero                    -- :class:`AsrExecutionError`, with the last
  line of stderr attached.

The failure modes are distinct types rather than one error with a message,
because the caller's next action differs: an unconfigured executor is a setup
step, a timeout is a retry or a longer budget, and unparseable output is a bug
in the executor the user owns.

Trust boundary: this runs a binary the operator named. That is the point of
the seam, and it is why the executor path is read from the operator's own
environment rather than from anything a model or a plan document can supply --
a plan is data, and data must not name an executable.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .subtitles import Cue, SubtitleFormatError, parse_cues, render_srt

ASR_EXECUTOR_ENV = "DCC_MCP_CAPCUT_ASR_EXECUTOR"
ASR_TIMEOUT_ENV = "DCC_MCP_CAPCUT_ASR_TIMEOUT"

SRT = "srt"
JSON = "json"
OUTPUT_FORMATS = (SRT, JSON)
DEFAULT_OUTPUT_FORMAT = SRT

DEFAULT_TIMEOUT = 600.0
MIN_TIMEOUT = 1.0
MAX_TIMEOUT = 3600.0

#: Executor stderr can be enormous; the last line is enough to act on.
MAX_ERROR_CHARS = 800


class AsrError(RuntimeError):
    """Base class for every ASR seam failure."""


class AsrNotConfiguredError(AsrError):
    """No executor was configured."""


class AsrExecutorMissingError(AsrError):
    """An executor was configured but cannot be run."""


class AsrTimeoutError(AsrError):
    """The executor did not finish inside the budget."""


class AsrFormatError(AsrError):
    """The executor succeeded but its output could not be read as a transcript."""


class AsrExecutionError(AsrError):
    """The executor ran and failed, or could not be started."""


@dataclass(frozen=True)
class Segment:
    """One transcript segment: a span in seconds and the text spoken in it."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    """The normalised result of an executor run, in the adapter's own shape."""

    segments: tuple[Segment, ...]
    language: Optional[str] = None
    output_format: str = DEFAULT_OUTPUT_FORMAT
    executor: Optional[str] = None

    @property
    def cues(self) -> list[Cue]:
        return [
            Cue(index=number, start=segment.start, end=segment.end, text=segment.text)
            for number, segment in enumerate(self.segments, start=1)
        ]

    @property
    def srt(self) -> str:
        return render_srt(self.cues)

    @property
    def duration(self) -> float:
        return max((segment.end for segment in self.segments), default=0.0)


def configured_executor() -> Optional[str]:
    """Return the configured executor path, or ``None`` when unset or blank."""
    value = os.environ.get(ASR_EXECUTOR_ENV) or ""
    return value.strip() or None


def resolve_timeout(timeout: Optional[float] = None) -> float:
    """Resolve the run budget: explicit argument, then env, then the default."""
    if timeout is None:
        raw = (os.environ.get(ASR_TIMEOUT_ENV) or "").strip()
        timeout = float(raw) if raw else DEFAULT_TIMEOUT
    if isinstance(timeout, bool):
        raise ValueError("timeout must be a number of seconds")
    value = float(timeout)
    if not math.isfinite(value) or value < MIN_TIMEOUT or value > MAX_TIMEOUT:
        raise ValueError(f"timeout must be between {MIN_TIMEOUT} and {MAX_TIMEOUT} seconds")
    return value


def resolve_executor(executor: Optional[str] = None) -> Path:
    """Return the executor to run, or raise the failure that explains why not.

    The path must be a file. On POSIX it must also be executable: subprocess
    would raise ``PermissionError`` mid-flight, and naming the missing ``+x``
    bit up front is the difference between "chmod +x it" and a stack trace.
    """
    candidate = str(executor or configured_executor() or "").strip()
    if not candidate:
        raise AsrNotConfiguredError(
            f"no ASR executor configured: set {ASR_EXECUTOR_ENV} to your own transcribe "
            "script; the adapter ships no model and downloads no weights"
        )
    path = Path(candidate).expanduser()
    if not path.is_file():
        raise AsrExecutorMissingError(f"{ASR_EXECUTOR_ENV} does not point at a file: {path}")
    if os.name == "posix" and not os.access(path, os.X_OK):
        raise AsrExecutorMissingError(
            f"ASR executor is not executable: {path} (run: chmod +x {path})"
        )
    return path


def build_command(
    executor: Path,
    media: Path,
    *,
    language: Optional[str] = None,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
) -> list[str]:
    """Build the executor argv. Always a list -- never a shell string."""
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"output_format must be one of {list(OUTPUT_FORMATS)}")
    command = [str(executor), str(media)]
    if language:
        command += ["--language", str(language)]
    command += ["--format", output_format]
    return command


def _error_detail(stderr: Optional[str]) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    detail = lines[-1] if lines else "the executor wrote nothing to stderr"
    if len(detail) > MAX_ERROR_CHARS:
        detail = detail[:MAX_ERROR_CHARS] + " ..."
    return detail


def run_executor(
    executor: Path,
    media: Path,
    *,
    language: Optional[str] = None,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
) -> str:
    """Run the executor and return its stdout, or raise the matching failure."""
    command = build_command(executor, media, language=language, output_format=output_format)
    seconds = resolve_timeout(timeout)
    try:
        completed = subprocess.run(  # noqa: S603 - operator-named argv, never a shell
            command,
            capture_output=True,
            timeout=seconds,
            check=False,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as error:
        raise AsrTimeoutError(
            f"ASR executor did not finish within {seconds:g}s: {' '.join(command)}"
        ) from error
    except OSError as error:
        raise AsrExecutionError(
            f"ASR executor could not be started: {type(error).__name__}: {error}"
        ) from error

    if completed.returncode != 0:
        raise AsrExecutionError(
            f"ASR executor exited {completed.returncode}: {_error_detail(completed.stderr)}"
        )
    return completed.stdout or ""


def _finite_seconds(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AsrFormatError(f"{label} must be a finite number, got {value!r}")
    if value < 0:
        raise AsrFormatError(f"{label} must be >= 0, got {value!r}")
    return float(value)


def parse_transcript(
    stdout: str,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    *,
    language: Optional[str] = None,
) -> Transcript:
    """Turn executor stdout into a :class:`Transcript`.

    Both output shapes are validated into the same normalised result, so a
    caller never has to branch on the format it asked for -- and an executor
    that ignores ``--format`` and emits the wrong shape is caught here instead
    of surfacing as a timeline that silently has no captions.
    """
    if output_format == SRT:
        try:
            cues = parse_cues(stdout or "", SRT)
        except SubtitleFormatError as error:
            # ``from None``: the parser's traceback points into this adapter,
            # while the actual fault is in the executor's output. Suppressing
            # the chain keeps the user aimed at the thing they can fix.
            raise AsrFormatError(
                f"ASR executor produced output that is not valid SRT: {error}"
            ) from None
        return Transcript(
            segments=tuple(Segment(cue.start, cue.end, cue.text) for cue in cues),
            language=language,
            output_format=SRT,
        )

    if output_format != JSON:
        raise ValueError(f"output_format must be one of {list(OUTPUT_FORMATS)}")

    try:
        payload = json.loads(stdout or "")
    except ValueError as error:
        raise AsrFormatError(
            f"ASR executor produced output that is not valid JSON: {error}"
        ) from None
    if not isinstance(payload, dict):
        raise AsrFormatError("ASR executor JSON output must be an object")
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        raise AsrFormatError("ASR executor JSON output requires a 'segments' list")
    if not raw_segments:
        raise AsrFormatError("ASR executor returned no segments")

    segments: list[Segment] = []
    for index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            raise AsrFormatError(f"segment {index} must be an object")
        start = _finite_seconds(item.get("start"), f"segment {index} start")
        end = _finite_seconds(item.get("end"), f"segment {index} end")
        if end < start:
            raise AsrFormatError(f"segment {index} ends before it starts ({end}s < {start}s)")
        text = item.get("text")
        if not isinstance(text, str):
            raise AsrFormatError(f"segment {index} text must be a string")
        segments.append(Segment(start, end, text))

    declared = payload.get("language", language)
    if declared is not None and not isinstance(declared, str):
        raise AsrFormatError("language must be a string")
    return Transcript(segments=tuple(segments), language=declared, output_format=JSON)


def transcribe(
    media: str,
    *,
    language: Optional[str] = None,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    timeout: Optional[float] = None,
    executor: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Transcript:
    """Transcribe ``media`` through the external ASR executor.

    The media file is checked before the executor is resolved, so a typo in a
    path is reported as a missing file rather than as an executor failure the
    user would go and debug in the wrong place.
    """
    if output_format not in OUTPUT_FORMATS:
        raise ValueError(f"output_format must be one of {list(OUTPUT_FORMATS)}")
    path = Path(str(media)).expanduser()
    if not path.is_file():
        raise AsrExecutionError(f"media file not found: {path}")

    resolved = resolve_executor(executor)
    stdout = run_executor(
        resolved,
        path,
        language=language,
        output_format=output_format,
        timeout=timeout,
        cwd=cwd,
    )
    transcript = parse_transcript(stdout, output_format, language=language)
    return Transcript(
        segments=transcript.segments,
        language=transcript.language,
        output_format=output_format,
        executor=str(resolved),
    )


__all__ = [
    "ASR_EXECUTOR_ENV",
    "ASR_TIMEOUT_ENV",
    "AsrError",
    "AsrExecutionError",
    "AsrExecutorMissingError",
    "AsrFormatError",
    "AsrNotConfiguredError",
    "AsrTimeoutError",
    "DEFAULT_TIMEOUT",
    "JSON",
    "OUTPUT_FORMATS",
    "SRT",
    "Segment",
    "Transcript",
    "build_command",
    "configured_executor",
    "parse_transcript",
    "resolve_executor",
    "resolve_timeout",
    "run_executor",
    "transcribe",
]
