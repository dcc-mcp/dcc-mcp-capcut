"""Offline subtitle cue handling: parsing, alignment and rendering.

The adapter owns three subtitle concerns that must not depend on the CapCut
host, because a host that silently ignores a directive is indistinguishable
from a host that implemented it:

* **Parsing** an SRT or LRC file into :class:`Cue` objects, so timing can be
  inspected and rewritten before anything reaches the timeline.
* **Alignment** -- choosing how a file's timecodes map onto the timeline.
  ``timecode`` honours the file's own clock; ``sequence`` discards it and packs
  cues back to back. Both are resolved here, in the adapter, so the verdict is
  the same whichever host build performs the import.
* **Rendering** cues back to SRT, which is what an aligned import hands to the
  host and what the external ASR executor contract speaks.

ASS is deliberately not parsed: its timing is event-based (per-line style and
positioning blocks) and reducing it to start/end/text offline would discard
more than it preserves. Files in that format are handed to the host untouched,
and asking for offline alignment on one raises rather than guessing.

This module performs no host dispatch and no network IO. It reads and writes
files it is explicitly told to.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

TIMECODE = "timecode"
SEQUENCE = "sequence"
ALIGNMENTS = (TIMECODE, SEQUENCE)

#: Formats the adapter can parse offline. ``ass`` is accepted by the host but
#: deliberately absent here -- see the module docstring.
PARSE_FORMATS = ("srt", "lrc")

#: A sequence-aligned cue keeps its own duration where that is meaningful, but
#: a source file with a zero-length cue or a 40-second block would otherwise
#: produce an unusable track, so the duration is clamped into this window.
MIN_SEQUENCE_DURATION = 0.2
MAX_SEQUENCE_DURATION = 5.0

#: An LRC file carries no end times; the last cue has nothing to run up to.
LRC_DEFAULT_DURATION = 3.0

#: Suffix inserted before the extension when an aligned file is written next to
#: its source and the caller did not name an output path.
ALIGNED_SUFFIX = ".aligned.srt"

#: Keys the adapter consumes itself. They are never forwarded to the host: an
#: unknown parameter reaching a host that validates strictly would be a hard
#: failure, and one reaching a permissive host would be silently ignored --
#: which is exactly how "the alignment did not happen" becomes invisible.
ADAPTER_SIDE_KEYS = ("align", "output_path")

_SRT_TIMING = re.compile(
    r"^\s*(\d{1,3}):([0-5]?\d):([0-5]?\d)[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,3}):([0-5]?\d):([0-5]?\d)[,.](\d{1,3})\s*(.*)$"
)
_LRC_TIMESTAMP = re.compile(r"\[(\d{1,3}):([0-5]?\d(?:[.,]\d{1,3})?)\]")


class SubtitleFormatError(ValueError):
    """A subtitle file could not be parsed into cues offline."""


@dataclass(frozen=True)
class Cue:
    """One subtitle cue: a span on the timeline and the text shown over it."""

    index: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def _finite_seconds(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SubtitleFormatError(f"{label} must be a finite number, got {value!r}")
    if value < 0:
        raise SubtitleFormatError(f"{label} must be >= 0, got {value!r}")
    return float(value)


def _clock_to_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    """Convert SRT ``HH:MM:SS,mmm`` parts to seconds.

    The millisecond field is padded rather than scaled: SRT writes three
    digits, and a file that writes ``,6`` means 600 ms, not 6 ms.
    """
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, "0")) / 1000.0


def _format_clock(seconds: float) -> str:
    total_ms = int(round(max(0.0, float(seconds)) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_srt(text: str) -> list[Cue]:
    """Parse SRT text into cues.

    Blocks are separated by blank lines and may open with a numeric index.
    CRLF and a UTF-8 BOM are tolerated because both are routine in files that
    arrive from an editor or a transcription service. Anything else that keeps
    a block from yielding a span and a text raises :class:`SubtitleFormatError`
    naming the block, so a caller can point at the line that needs fixing.
    """
    if not isinstance(text, str):
        raise SubtitleFormatError("SRT input must be a string")
    body = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        raise SubtitleFormatError("SRT input is empty; no cues found")

    cues: list[Cue] = []
    for number, block in enumerate(re.split(r"\n\s*\n", body), start=1):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        cursor = 1 if lines[0].strip().isdigit() else 0
        if cursor >= len(lines):
            raise SubtitleFormatError(f"SRT block {number} carries an index but no timing line")
        match = _SRT_TIMING.match(lines[cursor])
        if not match:
            raise SubtitleFormatError(
                f"SRT block {number} has no 'start --> end' timing line: {lines[cursor]!r}"
            )
        start = _clock_to_seconds(*match.group(1, 2, 3, 4))
        end = _clock_to_seconds(*match.group(5, 6, 7, 8))
        content = "\n".join(lines[cursor + 1 :]).strip()
        if not content:
            raise SubtitleFormatError(f"SRT block {number} has no text")
        if end < start:
            raise SubtitleFormatError(
                f"SRT block {number} ends before it starts ({end}s < {start}s)"
            )
        cues.append(Cue(index=len(cues) + 1, start=start, end=end, text=content))

    if not cues:
        raise SubtitleFormatError("SRT input is empty; no cues found")
    return cues


def parse_lrc(text: str) -> list[Cue]:
    """Parse LRC text into cues.

    LRC stamps the *start* of a line only, so a cue runs until the next stamp.
    The final cue has nothing to run up to and gets
    :data:`LRC_DEFAULT_DURATION`. A line carrying several stamps -- a repeated
    chorus -- becomes one cue per stamp, all with the same text.
    """
    if not isinstance(text, str):
        raise SubtitleFormatError("LRC input must be a string")
    body = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")

    stamps: list[tuple[float, str]] = []
    for line in body.split("\n"):
        matches = list(_LRC_TIMESTAMP.finditer(line))
        if not matches:
            continue
        content = line[matches[-1].end() :].strip()
        for match in matches:
            minutes = int(match.group(1))
            seconds = float(match.group(2).replace(",", "."))
            stamps.append((minutes * 60 + seconds, content))

    if not stamps:
        raise SubtitleFormatError("LRC input carries no [mm:ss.xx] timestamps; no cues found")
    stamps.sort(key=lambda item: item[0])

    cues: list[Cue] = []
    for position, (start, content) in enumerate(stamps):
        end = (
            stamps[position + 1][0] if position + 1 < len(stamps) else start + LRC_DEFAULT_DURATION
        )
        if end < start:
            end = start
        cues.append(Cue(index=position + 1, start=start, end=end, text=content))
    return cues


def parse_cues(text: str, fmt: str = "srt") -> list[Cue]:
    """Parse subtitle text of ``fmt`` (``srt`` or ``lrc``) into cues."""
    if fmt == "srt":
        return parse_srt(text)
    if fmt == "lrc":
        return parse_lrc(text)
    raise SubtitleFormatError(
        f"offline subtitle parsing supports {list(PARSE_FORMATS)}, not {fmt!r}; "
        "hand the file to the host without 'align' to keep its own timecodes"
    )


def render_srt(cues: Sequence[Cue]) -> str:
    """Render cues as SRT text, renumbering from 1."""
    blocks = [
        f"{number}\n{_format_clock(cue.start)} --> {_format_clock(cue.end)}\n{cue.text}\n"
        for number, cue in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


def align_cues(
    cues: Sequence[Cue],
    strategy: str = TIMECODE,
    *,
    offset: float = 0.0,
    min_duration: float = MIN_SEQUENCE_DURATION,
    max_duration: float = MAX_SEQUENCE_DURATION,
) -> list[Cue]:
    """Place cues on the timeline under ``strategy``.

    ``timecode``
        Honour the file's clock and shift the whole track by ``offset``. This
        is the default and what a plain import has always done.

    ``sequence``
        Discard the absolute timecodes and lay the cues back to back in file
        order, starting at ``offset``. Each cue keeps its own duration, clamped
        into ``[min_duration, max_duration]``, so gaps collapse and a
        zero-length cue still gets a readable span. Use this when the source
        timecodes are for a different cut than the one being assembled.
    """
    if strategy not in ALIGNMENTS:
        raise ValueError(f"align must be one of {list(ALIGNMENTS)}, not {strategy!r}")
    shift = _finite_seconds(offset, "offset")
    if min_duration < 0 or max_duration <= 0 or min_duration > max_duration:
        raise ValueError(
            f"sequence durations must satisfy 0 <= min <= max, got {min_duration}..{max_duration}"
        )

    if strategy == TIMECODE:
        return [
            Cue(index=number, start=cue.start + shift, end=cue.end + shift, text=cue.text)
            for number, cue in enumerate(cues, start=1)
        ]

    aligned: list[Cue] = []
    # The cursor accumulates, and a rendered timecode only has millisecond
    # resolution, so raw float sums would drift a long subtitle file off the
    # millisecond grid and render a start like 00:00:01,699 from 1.7. Snapping
    # to whole milliseconds each step keeps every cue exactly where it reads.
    cursor = round(shift, 3)
    for number, cue in enumerate(cues, start=1):
        duration = round(min(max(cue.duration, min_duration), max_duration), 3)
        aligned.append(
            Cue(index=number, start=cursor, end=round(cursor + duration, 3), text=cue.text)
        )
        cursor = round(cursor + duration, 3)
    return aligned


def _aligned_output_path(source: Path, output_path: Optional[str]) -> Path:
    if output_path:
        return Path(str(output_path)).expanduser()
    return source.with_name(f"{source.stem}{ALIGNED_SUFFIX}")


def prepare_import_params(params: dict[str, Any]) -> dict[str, Any]:
    """Resolve an import request into the params the host will actually receive.

    ``align`` and ``output_path`` are adapter-side directives, so they are
    stripped before dispatch in every case: the host never sees them.

    Under ``timecode`` (the default) nothing is read or written -- the file
    goes to the host exactly as it does today. Under ``sequence`` the source is
    parsed, re-timed, rendered back to SRT and written out, and the rewritten
    file is what gets imported. Doing it here rather than delegating to the
    host is what makes the strategy mean the same thing on every host build,
    and what lets a plan be validated offline before dispatch.
    """
    if not isinstance(params, dict):
        raise ValueError("import params must be an object")
    strategy = params.get("align") or TIMECODE
    if strategy not in ALIGNMENTS:
        raise ValueError(f"align must be one of {list(ALIGNMENTS)}, not {strategy!r}")

    dispatched = {key: value for key, value in params.items() if key not in ADAPTER_SIDE_KEYS}

    if strategy == TIMECODE:
        return dispatched

    source = Path(str(params.get("path") or "")).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"subtitle file not found: {source}")
    fmt = str(params.get("format") or "srt").lower()
    cues = parse_cues(source.read_text(encoding="utf-8", errors="replace"), fmt)
    aligned = align_cues(cues, SEQUENCE, offset=float(params.get("offset") or 0.0))

    target = _aligned_output_path(source, params.get("output_path"))
    if target.parent and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_srt(aligned), encoding="utf-8")

    dispatched["path"] = str(target)
    # The rewritten file already carries the offset and is SRT by construction;
    # leaving the caller's values in place would apply the shift twice, or ask
    # the host to read the wrong parser.
    dispatched["format"] = "srt"
    dispatched["offset"] = 0.0
    return dispatched


__all__ = [
    "ADAPTER_SIDE_KEYS",
    "ALIGNMENTS",
    "Cue",
    "SEQUENCE",
    "SubtitleFormatError",
    "TIMECODE",
    "align_cues",
    "parse_cues",
    "parse_lrc",
    "parse_srt",
    "prepare_import_params",
    "render_srt",
]
