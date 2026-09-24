"""Canonical export receipt: opt-in proof that a rendered artifact exists.

The export contract every caller gets by default is deliberately weak. An
export submit result is accepted on ``job_id`` **or** ``output_path`` alone, and
``get_export_status`` reports a terminal state without describing the artifact
it produced, so a host can satisfy today's contract with a file that is
missing, empty, or the wrong dimensions.

This module defines the stronger receipt, and it is **opt-in**: a caller asks
for it with ``verify_output: true``, and only then does the adapter hold the
host to it and fail closed. A caller that never asks keeps exactly the contract
it has today, so tightening the receipt cannot break an existing MCP client.
The adapter never synthesises a receipt and never probes anything itself:
duration and stream facts come from a probe the **host** runs (``ffprobe`` or
an equivalent), and this module only proves the receipt is complete and
internally consistent.

Only calls that can actually know the artifact honour the flag. An asynchronous
submit cannot: ``export_video`` and ``build_vlog_demo`` return a job
acknowledgement, so the receipt for a rendered video comes from
``get_export_status`` once the job reaches a terminal state.

The field set here is final, not a starting point. Batch delivery (one template
plus N variable sets) reports one of these per rendered item, so the shape is
meant to be reused verbatim rather than re-designed per caller.
"""

from __future__ import annotations

import math
import os
from typing import Any

# Bumped whenever the meaning of a field changes. A receipt without this key is
# a v1 receipt; there is no other version yet.
RECEIPT_VERSION = "1"

# The opt-in request flag. A caller sets it on an export tool call; the adapter
# reads it from the request params, before dispatch, and never infers it.
VERIFY_OUTPUT_PARAM = "verify_output"

# Where the host puts the receipt, inside ``verification``. Timed readback
# already lives under ``verification.timeline``; this is the same idea.
RECEIPT_KEY = "output"

# Actions that honour the opt-in flag. Deliberately excludes the asynchronous
# submits: ``export_video`` and ``build_vlog_demo`` only acknowledge a job, so
# demanding a receipt from them would cost the caller the ``job_id`` it needs
# to poll -- the artifact does not exist yet at submit time.
EXPORT_RECEIPT_ACTIONS = frozenset({"export_thumbnail", "get_export_status"})

STREAM_KINDS = ("video", "audio", "image", "subtitle", "data")

# Streams that give the artifact a duration, and streams that give it a
# picture. An export deliverable must have a picture; only the timed kinds
# force ``duration_sec`` to be present.
_TIMED_STREAM_KINDS = frozenset({"video", "audio"})
_PICTURE_STREAM_KINDS = frozenset({"video", "image"})

# Per-action stream expectations: (a stream of one of these kinds is required,
# streams of these kinds are rejected). An action absent from this table falls
# back to the generic rule below: any picture will do.
#
# ``get_export_status`` is deliberately absent. It only holds a ``job_id`` and
# cannot know whether the job renders a video or a still, so holding it to
# either kind would reject honest hosts.
_ACTION_STREAM_RULE: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # A thumbnail renders a still: an image stream, and nothing timed.
    "export_thumbnail": (frozenset({"image"}), _TIMED_STREAM_KINDS),
    # Video renders carry a video stream. These two no longer take the flag
    # themselves -- they submit asynchronously and the artifact does not exist
    # yet -- but batch delivery validates one receipt per rendered item against
    # the same action name, so the rule stays and is the one to rely on.
    "export_video": (frozenset({"video"}), frozenset()),
    "build_vlog_demo": (frozenset({"video"}), frozenset()),
}
_FALLBACK_STREAM_RULE = (_PICTURE_STREAM_KINDS, frozenset())

# Numeric stream fields the host must report for a given stream kind. Audio
# leaves channels and sample rate optional because a probe may legitimately
# report them as unknown.
_REQUIRED_STREAM_INTS = {"video": ("width", "height"), "image": ("width", "height")}
_OPTIONAL_POSITIVE_INTS = ("channels", "sample_rate_hz")
_OPTIONAL_NON_NEGATIVE_INTS = ("bit_rate",)
_OPTIONAL_POSITIVE_NUMBERS = ("fps", "duration_sec")


def _is_number(value: Any) -> bool:
    """True for a real, finite number -- bools and nan/inf do not count.

    ``nan`` and ``inf`` are the practical hole here: ``json.loads`` accepts
    ``NaN`` and ``Infinity`` literals by default, so a host forwarding an
    ``ffprobe`` field it reported as ``N/A`` can otherwise walk a non-value
    straight through every range check.
    """
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _require_text(source: dict[str, Any], key: str, where: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{where} must carry {key} as a non-empty string")
    return value


def _require_int(source: dict[str, Any], key: str, where: str, minimum: int) -> int:
    value = source.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise RuntimeError(f"{where} must carry {key} as an integer >= {minimum}")
    return value


def _require_number(source: dict[str, Any], key: str, where: str) -> float:
    value = source.get(key)
    if not _is_number(value) or value <= 0:
        raise RuntimeError(f"{where} must carry {key} as a finite number > 0")
    return float(value)


def _normalize_path(value: str) -> str:
    """Fold path spelling so an honest host is not rejected over style.

    The host and the adapter do not agree on separators or drive-letter case,
    and a relative path resolves against each side's own working directory, so
    both sides go through the same fold before they are compared.
    """
    return os.path.normcase(os.path.abspath(value))


def receipt_requested(params: Any) -> bool:
    """True only when the caller explicitly asked for the export receipt.

    Anything other than a literal boolean ``true`` leaves the flag off, so a
    caller that passes ``"true"`` or ``1`` keeps today's contract rather than
    being silently held to a stricter one it did not opt into.
    """
    return isinstance(params, dict) and params.get(VERIFY_OUTPUT_PARAM) is True


def _validate_stream(stream: Any, index: int, where: str) -> str:
    label = f"{where} streams[{index}]"
    if not isinstance(stream, dict):
        raise RuntimeError(f"{label} must be an object")
    kind = stream.get("kind")
    if kind not in STREAM_KINDS:
        expected = ", ".join(STREAM_KINDS)
        raise RuntimeError(f"{label} has unsupported kind {kind!r}; expected one of {expected}")
    _require_text(stream, "codec", label)
    for key in _REQUIRED_STREAM_INTS.get(kind, ()):
        _require_int(stream, key, label, 1)
    for key in _OPTIONAL_POSITIVE_INTS:
        if stream.get(key) is not None:
            _require_int(stream, key, label, 1)
    for key in _OPTIONAL_NON_NEGATIVE_INTS:
        if stream.get(key) is not None:
            _require_int(stream, key, label, 0)
    for key in _OPTIONAL_POSITIVE_NUMBERS:
        if stream.get(key) is not None:
            _require_number(stream, key, label)
    return kind


def _validate_stream_kinds(kinds: set[str], action: str, where: str) -> None:
    """Require the picture this action actually produces, and nothing else."""
    required, forbidden = _ACTION_STREAM_RULE.get(action, _FALLBACK_STREAM_RULE)
    if not kinds & required:
        expected = " or ".join(sorted(required))
        raise RuntimeError(f"{where} has no {expected} stream; {action} must report one")
    surprise = kinds & forbidden
    if surprise:
        found = ", ".join(sorted(surprise))
        raise RuntimeError(f"{where} reports a {found} stream; {action} renders a still")


def _validate_duration(receipt: dict[str, Any], where: str, timed: bool) -> None:
    """Duration is mandatory for timed media and wrong for a still."""
    value = receipt.get("duration_sec")
    if timed:
        if not _is_number(value) or value <= 0:
            raise RuntimeError(
                f"{where} must carry duration_sec as a finite number > 0 for timed media"
            )
    elif value is not None:
        raise RuntimeError(f"{where} reports duration_sec for a still; omit it or set it to null")


def _validate_expected_path(path: str, expected_path: Any, action: str, where: str) -> None:
    """Tie the receipt to the artifact this call was asked to produce.

    Without this the receipt only proves *some* file exists: a host could hand
    back a stale probe from an earlier render, or the previous item in a batch,
    and every field check would pass. The comparison is skipped when the result
    carries no ``output_path`` to compare against -- ``get_export_status``
    usually does not, and guessing one would be worse than not checking.
    """
    if not isinstance(expected_path, str) or not expected_path.strip():
        return
    if _normalize_path(path) != _normalize_path(expected_path):
        raise RuntimeError(
            f"{where} describes {path!r}, but {action} was asked to produce {expected_path!r}"
        )


def _validate_probe(receipt: dict[str, Any], where: str) -> None:
    """The probe block is optional, but a half-written one is an error."""
    probe = receipt.get("probe")
    if probe is None:
        return
    if not isinstance(probe, dict):
        raise RuntimeError(f"{where} probe must be an object")
    if "tool" in probe:
        _require_text(probe, "tool", f"{where} probe")


def validate_export_receipt(
    action: str, receipt: Any, *, expected_path: Any = None
) -> dict[str, Any]:
    """Validate a host-supplied export receipt; raise when it is not a proof.

    ``expected_path`` is the ``output_path`` from the same result, when it has
    one, and the receipt's own ``path`` must describe that same artifact.

    Returns the receipt unchanged so callers can keep the host's own object
    rather than a normalised copy that could drift from it.
    """
    where = f"CapCut action '{action}' export receipt"
    if not isinstance(receipt, dict):
        raise RuntimeError(f"{where} must be an object under verification.{RECEIPT_KEY}")

    path = _require_text(receipt, "path", where)
    _validate_expected_path(path, expected_path, action, where)
    # A receipt for a file that is not on disk is not a receipt. The host owns
    # the check; the adapter refuses to take it on trust.
    if receipt.get("exists") is not True:
        raise RuntimeError(f"{where} does not prove the artifact exists on disk")
    _require_int(receipt, "size_bytes", where, 1)

    streams = receipt.get("streams")
    if not isinstance(streams, list) or not streams:
        raise RuntimeError(f"{where} lacks stream info: streams must be a non-empty list")
    kinds = {_validate_stream(stream, index, where) for index, stream in enumerate(streams)}
    _validate_stream_kinds(kinds, action, where)

    _validate_duration(receipt, where, bool(kinds & _TIMED_STREAM_KINDS))
    for key in ("width", "height"):
        if receipt.get(key) is not None:
            _require_int(receipt, key, where, 1)
    _validate_probe(receipt, where)
    return receipt
