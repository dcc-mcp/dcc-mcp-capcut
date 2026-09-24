"""Delivery rules a plan can declare: canvas aspect, reframing, encode preset.

These are the three things a canonical plan says about how it is *delivered*
rather than what it contains, and they live in their own module for one reason:
both links that act on them must give the same verdict. ``plan_to_actions``
lowers a plan to an ``export_video`` action, and batch delivery renders one plan
per item -- if each of them interpreted ``output.export`` in its own way, a
preset that batch refuses would still be dispatched as a distorted encode by
``apply_edit_plan``.

Nothing here imports :mod:`dcc_mcp_capcut.editplan`, which is what lets that
module import back from here without a cycle.
"""

from __future__ import annotations

import math
from typing import Any, Optional

EXPORT_FORMATS = ("mp4", "mov")
EXPORT_CODECS = ("h264", "h265", "prores")
EXPORT_PRESET_FIELDS = {"format", "codec", "bitrate_mbps", "fps", "audio", "width", "height"}

REFRAME_FITS = ("contain", "cover")

#: Rounding for every reported float, so a reframe report compares equal on any
#: platform instead of carrying a different last digit per libm.
_ROUND_DIGITS = 6


def _round(value: float) -> float:
    return round(float(value), _ROUND_DIGITS)


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


# ---------------------------------------------------------------------------
# Aspect ratio, reframe, export preset
# ---------------------------------------------------------------------------


def parse_aspect_ratio(value: Any, label: str = "aspect_ratio") -> tuple[int, int]:
    """Parse a ``W:H`` canvas aspect into a positive integer pair.

    Only the two-integer form is accepted: ``CANVAS_PRESETS`` is the vocabulary
    the whole adapter already speaks, and accepting a bare float would let a
    template declare an aspect no preset and no host setting can name.
    """
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a 'W:H' string, not {type(value).__name__}")
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"{label} must look like '16:9', not {value!r}")
    try:
        width, height = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"{label} must look like '16:9', not {value!r}") from None
    if width <= 0 or height <= 0:
        raise ValueError(f"{label} must carry positive integers, not {value!r}")
    return width, height


def check_canvas_aspect(plan: dict[str, Any]) -> None:
    """Reject a declared output aspect that contradicts the plan's canvas.

    Checked on every rendered item, not only on items that declare a reframe:
    the two values are the same fact stated twice, and a plan that states it
    two different ways would otherwise be delivered at whichever one the host
    happens to honour.
    """
    declared = (plan.get("output") or {}).get("aspect_ratio")
    if declared is None:
        return
    ratio_width, ratio_height = parse_aspect_ratio(declared, "output.aspect_ratio")
    target_width, target_height = int(plan["width"]), int(plan["height"])
    if abs(target_width / target_height - ratio_width / ratio_height) > 1e-6:
        raise ValueError(
            f"output.aspect_ratio {declared!r} disagrees with the canvas "
            f"{target_width}x{target_height}"
        )


def resolve_reframe(plan: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Compute how a rendered plan's delivery canvas reframes its source.

    Returns ``None`` when the plan declares no reframe, so "no reframing was
    asked for" stays distinguishable from "reframing was a no-op".

    The source aspect defaults to the delivery aspect: a template that does not
    say what it was framed for is declaring that no reframing is needed, and the
    arithmetic below then reports an exact 1:1 fit rather than inventing a
    source. Declaring one is what makes the report mean something.

    A ``cover`` fit permanently discards picture, so it is the one case that
    requires the author to say how much of the frame is protected. Without a
    ``safe_area`` there is nothing to check the crop against, and "we cropped
    44% off the sides and hoped" is exactly the silent crop this module exists to
    prevent -- so the omission is an error, not a default.
    """
    output = plan.get("output") or {}
    policy = output.get("reframe")
    if policy is None:
        return None
    _require_object(policy, "output.reframe")

    allowed = {"fit", "safe_area", "source_aspect_ratio"}
    if policy.keys() - allowed:
        raise ValueError(
            f"output.reframe has unsupported fields: {sorted(policy.keys() - allowed)}"
        )

    fit = policy.get("fit", "contain")
    if fit not in REFRAME_FITS:
        raise ValueError(f"output.reframe fit must be one of {list(REFRAME_FITS)}, not {fit!r}")

    safe_area = policy.get("safe_area")
    if fit == "cover" and safe_area is None:
        raise ValueError(
            "output.reframe fit='cover' requires safe_area: the adapter will not "
            "crop without knowing what fraction of the source frame must survive. "
            "Declare safe_area, or use fit='contain' to fit the whole frame and "
            "take bars instead."
        )
    if fit != "cover" and safe_area is not None:
        raise ValueError(
            f"output.reframe safe_area is only meaningful with fit='cover'; fit={fit!r} never crops"
        )
    if safe_area is not None:
        if isinstance(safe_area, bool) or not isinstance(safe_area, (int, float)):
            raise ValueError("output.reframe safe_area must be a number in (0, 1]")
        if not 0 < float(safe_area) <= 1:
            raise ValueError(f"output.reframe safe_area must be in (0, 1], not {safe_area!r}")
        safe_area = float(safe_area)

    check_canvas_aspect(plan)
    target_width = int(plan["width"])
    target_height = int(plan["height"])

    source = policy.get("source_aspect_ratio")
    if source is None:
        source_width, source_height = target_width, target_height
        source_label = f"{target_width}:{target_height}"
    else:
        source_width, source_height = parse_aspect_ratio(
            source, "output.reframe source_aspect_ratio"
        )
        source_label = str(source)

    # Work in source units: the source frame is (source_width, source_height)
    # and the delivery canvas is a pixel box. Uniform scale only -- the
    # alternative, non-uniform stretch, is a distortion no editor asks for and
    # no host action here can express.
    scale = (
        min(target_width / source_width, target_height / source_height)
        if fit == "contain"
        else max(target_width / source_width, target_height / source_height)
    )
    visible_width = min(1.0, (target_width / scale) / source_width)
    visible_height = min(1.0, (target_height / scale) / source_height)
    cropped = visible_width < 1.0 or visible_height < 1.0

    report: dict[str, Any] = {
        "fit": fit,
        "source_aspect_ratio": source_label,
        "source": {"width": source_width, "height": source_height},
        "target": {"width": target_width, "height": target_height},
        "scale": _round(scale),
        "cropped": cropped,
        "visible_source_fraction": {
            "width": _round(visible_width),
            "height": _round(visible_height),
        },
        # Bars are contain's cost: the canvas area the picture does not cover.
        # Zero on the axis that defines the fit, so the pair reads as
        # "letterbox" or "pillarbox" without further interpretation.
        "bars": {
            "horizontal": _round(max(0.0, target_width - source_width * scale)),
            "vertical": _round(max(0.0, target_height - source_height * scale)),
        },
    }

    if safe_area is not None:
        preserved = visible_width >= safe_area and visible_height >= safe_area
        report["safe_area"] = _round(safe_area)
        report["safe_area_preserved"] = preserved
        if not preserved:
            raise ValueError(
                f"output.reframe fit='cover' would crop into the declared safe area: "
                f"only {visible_width:.1%} x {visible_height:.1%} of the source "
                f"frame survives, safe_area requires {safe_area:.1%} of both. "
                "Lower safe_area, or use fit='contain'."
            )
    return report


def validate_export_preset(preset: Any, canvas: tuple[int, int]) -> None:
    """Reject a declared encode preset that cannot be delivered as written.

    ``canvas`` is the plan's own width/height pair, and the size check is the
    important one: a preset naming an output size of another aspect is asking
    for a reframe at encode time, which would bypass the safe-area check that
    :func:`resolve_reframe` performs. It is a reframe, so it belongs there.

    Split out from :func:`resolve_export` so the plan compiler can hold a
    document to this verdict once, at compile time, rather than only when some
    later link happens to ask for the encode settings.
    """
    _require_object(preset, "output.export")
    if preset.keys() - EXPORT_PRESET_FIELDS:
        raise ValueError(
            f"output.export has unsupported fields: {sorted(preset.keys() - EXPORT_PRESET_FIELDS)}"
        )

    width = preset.get("width")
    height = preset.get("height")
    if width is not None or height is not None:
        if width is None or height is None:
            raise ValueError("output.export width and height must be declared together")
        for key, value in (("width", width), ("height", height)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"output.export {key} must be an integer >= 1")
        canvas_width, canvas_height = canvas
        if abs(width / height - canvas_width / canvas_height) > 1e-6:
            raise ValueError(
                f"output.export size {width}x{height} does not match the canvas "
                f"{canvas_width}x{canvas_height}; reframing is declared under "
                "output.reframe, not at encode time"
            )

    fps = preset.get("fps")
    if fps is not None:
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps):
            raise ValueError("output.export fps must be a finite number")
        if fps <= 0:
            raise ValueError("output.export fps must be > 0")
    fmt = preset.get("format")
    if fmt is not None and fmt not in EXPORT_FORMATS:
        raise ValueError(f"output.export format must be one of {list(EXPORT_FORMATS)}")
    codec = preset.get("codec")
    if codec is not None and codec not in EXPORT_CODECS:
        raise ValueError(f"output.export codec must be one of {list(EXPORT_CODECS)}")
    bitrate = preset.get("bitrate_mbps")
    if bitrate is not None and (
        isinstance(bitrate, bool)
        or not isinstance(bitrate, (int, float))
        or not math.isfinite(bitrate)
        or bitrate <= 0
    ):
        raise ValueError("output.export bitrate_mbps must be a finite number > 0")
    audio = preset.get("audio")
    if audio is not None and not isinstance(audio, bool):
        raise ValueError("output.export audio must be a boolean")


def resolve_export(plan: dict[str, Any]) -> dict[str, Any]:
    """Resolve a plan's declared encode preset against its canvas.

    The canvas is the default for every unset setting, so a plan with no
    ``export`` block asks the host for exactly the canvas it framed.
    """
    output = plan.get("output") or {}
    preset = output.get("export") or {}
    validate_export_preset(preset, (int(plan["width"]), int(plan["height"])))

    resolved: dict[str, Any] = {
        "width": int(plan["width"]),
        "height": int(plan["height"]),
        "fps": float(plan["fps"]),
    }
    if preset.get("width") is not None:
        resolved["width"] = preset["width"]
        resolved["height"] = preset["height"]
    if preset.get("fps") is not None:
        resolved["fps"] = float(preset["fps"])
    for key in ("format", "codec", "bitrate_mbps", "audio"):
        if preset.get(key) is not None:
            resolved[key] = float(preset[key]) if key == "bitrate_mbps" else preset[key]
    return resolved
