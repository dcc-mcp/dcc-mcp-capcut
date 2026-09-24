"""Batch production: one template plus N variable sets becomes N renders.

The adapter's tools cover editing *actions*. What they do not cover is the
work an editor actually repeats: the same cut delivered as 16:9, 9:16 and 1:1,
the same subtitles in three languages, the same promo rendered every morning.
That is
this module, and it is deliberately split the way the rest of the adapter is
split:

* **Everything here is host-free.** Rendering a template, computing a reframe,
  building a batch manifest and recording an item's outcome are pure document
  operations: no bridge, no network, no media decoding, no clock. They are
  therefore provable in CI, and a caller can inspect all N variants -- every
  plan, every output path, every crop -- before a single host mutation.
* **Dispatch lives in the skill script** (``capcut-batch/scripts/run_batch.py``),
  which owns the polling, the sleeping and the failure isolation policy. This
  module only owns the state machine that policy writes into.

Two rules shape the whole design.

**A variable set that fails never takes the batch with it.** A batch is built by
rendering every variable set up front; one that does not compile -- an undeclared
variable, a plan that overlaps, a reframe that would crop the declared safe area
-- is recorded as ``failed`` with the reason and the rest still build. That is
the same guarantee the run gives at dispatch time, and it starts one step
earlier, because a batch that dies on item 7 of 40 after twenty minutes of
rendering is the failure mode this exists to prevent.

**Nothing is cropped silently.** The one genuinely surprising thing a
template-driven batch can do to your picture is reframe it. ``contain`` is the
default, and it never crops: it fits the authored frame inside the delivery
canvas and reports the bars it produced. ``cover`` fills the canvas and does
crop, so it requires an explicit ``safe_area``, and a crop that would eat that
safe area is an error rather than a warning. Either way the item carries the
arithmetic it applied.

Units and vocabulary follow :mod:`dcc_mcp_capcut.editplan`: a template is a
canonical plan (or a vlog recipe) carrying ``{{placeholder}}`` strings, and the
rendered result is a canonical plan, so a batch item is validated by exactly the
rules every other link applies.
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Optional

from .editplan import DEFAULT_FPS, compile_plan

BATCH_SCHEMA = "dcc-mcp-capcut/batch/v1"

#: A placeholder: ``{{ name }}``, optionally padded, inside a string. A field
#: whose whole value is one placeholder takes the variable's own type, which is
#: how a template declares a duration or a canvas size rather than only text.
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.\-]*)\s*\}\}")

REFRAME_FITS = ("contain", "cover")

EXPORT_FORMATS = ("mp4", "mov")
EXPORT_CODECS = ("h264", "h265", "prores")
EXPORT_PRESET_FIELDS = {"format", "codec", "bitrate_mbps", "fps", "audio", "width", "height"}

#: Item lifecycle. A batch is a list of these, not a loop: the manifest is the
#: thing that survives a crash, so the state has to be a field on the item.
ITEM_STATES = ("pending", "running", "done", "failed", "skipped")

#: ``get_export_status`` vocabulary. The host owns the state machine; these are
#: the terminal values batch reads, and only ``done`` counts as a render.
TERMINAL_EXPORT_STATES = ("done", "failed", "cancelled", "error")
SUCCESS_EXPORT_STATE = "done"

#: Rounding for every reported float, so a reframe report compares equal on any
#: platform instead of carrying a different last digit per libm.
_ROUND_DIGITS = 6


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _round(value: float) -> float:
    return round(float(value), _ROUND_DIGITS)


# ---------------------------------------------------------------------------
# Variable substitution
# ---------------------------------------------------------------------------


def _variable(name: str, variables: dict[str, Any], where: str) -> Any:
    if name not in variables:
        declared = ", ".join(sorted(variables)) or "none"
        raise ValueError(f"{where} uses undeclared variable {name!r}; declared: {declared}")
    return variables[name]


def _interpolated(value: Any, where: str) -> str:
    """Render one variable into text for use inside a longer string.

    Only the types with an unambiguous text form. A bool interpolated into a
    path would silently become ``True`` or ``False`` depending on the Python
    version's casing, and ``None`` would become the four characters ``None`` --
    neither is ever what the template author meant, so both are errors rather
    than a silently wrong filename.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(
            f"{where}: only strings and numbers can be interpolated into text, "
            f"got {type(value).__name__}"
        )
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{where}: cannot interpolate a non-finite number")
        return repr(value)
    raise ValueError(
        f"{where}: only strings and numbers can be interpolated into text, "
        f"got {type(value).__name__}"
    )


def _substitute_text(text: str, variables: dict[str, Any], where: str) -> Any:
    if "{{" not in text:
        return text

    whole = PLACEHOLDER.fullmatch(text)
    if whole is not None:
        # A field that is exactly one placeholder keeps the variable's own type,
        # so a template can declare a duration, an fps or a canvas as a number
        # instead of stringifying it and hoping the compile accepts the text.
        value = _variable(whole.group(1), variables, where)
        if isinstance(value, (dict, list)) or value is None:
            raise ValueError(
                f"{where} is a whole-value placeholder, so its variable must be a "
                f"scalar, not {type(value).__name__}: a variable that injects "
                "structure would let a variable set rewrite the template's shape"
            )
        return value

    parts = list(PLACEHOLDER.finditer(text))
    covered = {match.start() for match in parts}
    for index, char in enumerate(text):
        # An unmatched "{{" is a typo, and leaving it in place turns a
        # mistyped variable into a literal path that silently renders the wrong
        # file. Fail here, naming the field.
        if char == "{" and text.startswith("{{", index) and index not in covered:
            raise ValueError(f"{where} has a malformed placeholder: {text!r}")

    def replace(match: re.Match) -> str:
        return _interpolated(_variable(match.group(1), variables, where), where)

    return PLACEHOLDER.sub(replace, text)


def substitute_variables(document: Any, variables: dict[str, Any], where: str = "template") -> Any:
    """Replace every ``{{placeholder}}`` in a document, recursively.

    Substitution runs **before** the plan is compiled, so the values a variable
    supplies are validated by the same media-path, overlap and bounds rules as
    a hand-written plan -- a variable cannot smuggle in a traversal path or an
    overlapping clip by arriving late.
    """
    if isinstance(document, dict):
        return {
            key: substitute_variables(value, variables, f"{where}.{key}")
            for key, value in document.items()
        }
    if isinstance(document, list):
        return [
            substitute_variables(value, variables, f"{where}[{index}]")
            for index, value in enumerate(document)
        ]
    if isinstance(document, str):
        return _substitute_text(document, variables, where)
    return document


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


def resolve_export(plan: dict[str, Any]) -> dict[str, Any]:
    """Resolve a plan's declared encode preset against its canvas.

    The canvas is the default for every unsetting, so a plan with no ``export``
    block asks the host for exactly the canvas it framed. A preset that declares
    an output size of another aspect is rejected: changing the aspect at encode
    time is a reframe, and doing it here would bypass the safe-area check
    entirely.
    """
    output = plan.get("output") or {}
    preset = output.get("export")
    if preset is None:
        preset = {}
    _require_object(preset, "output.export")
    if preset.keys() - EXPORT_PRESET_FIELDS:
        raise ValueError(
            f"output.export has unsupported fields: {sorted(preset.keys() - EXPORT_PRESET_FIELDS)}"
        )

    resolved: dict[str, Any] = {
        "width": int(plan["width"]),
        "height": int(plan["height"]),
        "fps": float(plan["fps"]),
    }
    width = preset.get("width")
    height = preset.get("height")
    if width is not None or height is not None:
        if width is None or height is None:
            raise ValueError("output.export width and height must be declared together")
        for key, value in (("width", width), ("height", height)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"output.export {key} must be an integer >= 1")
        canvas_ratio = int(plan["width"]) / int(plan["height"])
        if abs(width / height - canvas_ratio) > 1e-6:
            raise ValueError(
                f"output.export size {width}x{height} does not match the canvas "
                f"{plan['width']}x{plan['height']}; reframing is declared under "
                "output.reframe, not at encode time"
            )
        resolved["width"] = width
        resolved["height"] = height

    if preset.get("fps") is not None:
        fps = preset["fps"]
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps):
            raise ValueError("output.export fps must be a finite number")
        if fps <= 0:
            raise ValueError("output.export fps must be > 0")
        resolved["fps"] = float(fps)

    fmt = preset.get("format")
    if fmt is not None:
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"output.export format must be one of {list(EXPORT_FORMATS)}")
        resolved["format"] = fmt
    codec = preset.get("codec")
    if codec is not None:
        if codec not in EXPORT_CODECS:
            raise ValueError(f"output.export codec must be one of {list(EXPORT_CODECS)}")
        resolved["codec"] = codec
    bitrate = preset.get("bitrate_mbps")
    if bitrate is not None:
        if (
            isinstance(bitrate, bool)
            or not isinstance(bitrate, (int, float))
            or not math.isfinite(bitrate)
            or bitrate <= 0
        ):
            raise ValueError("output.export bitrate_mbps must be a finite number > 0")
        resolved["bitrate_mbps"] = float(bitrate)
    audio = preset.get("audio")
    if audio is not None:
        if not isinstance(audio, bool):
            raise ValueError("output.export audio must be a boolean")
        resolved["audio"] = audio
    return resolved


# ---------------------------------------------------------------------------
# Rendering one item
# ---------------------------------------------------------------------------


def render_template(
    document: dict[str, Any],
    variables: dict[str, Any],
    *,
    fps: float = DEFAULT_FPS,
    media_index: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Render one variable set into a canonical plan plus its delivery report.

    The returned ``plan`` is a compiled canonical plan, so it is the same
    document ``apply_edit_plan`` assembles and ``export_otio`` lowers. Alongside
    it come the two things a single export never had to say out loud: the
    reframe arithmetic, and the encode preset the item will be rendered with.
    """
    _require_object(document, "template")
    _require_object(variables, "variables")
    rendered = substitute_variables(document, variables)
    if not isinstance(rendered, dict):
        raise ValueError("template must render to an object")
    plan = compile_plan(rendered, fps=fps, media_index=media_index)
    check_canvas_aspect(plan)
    return {
        "name": plan["name"],
        "plan": plan,
        "reframe": resolve_reframe(plan),
        "export": resolve_export(plan),
        "output_path": (plan.get("output") or {}).get("path"),
    }


# ---------------------------------------------------------------------------
# Batch manifest
# ---------------------------------------------------------------------------


def _item(index: int, variables: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "name": None,
        "state": "pending",
        "variables": variables,
        "plan": None,
        "reframe": None,
        "export": None,
        "output_path": None,
        "timeline_id": None,
        "job_id": None,
        "receipt": None,
        "error": None,
        "attempts": 0,
    }


def build_batch(
    document: dict[str, Any],
    variables: list[dict[str, Any]],
    *,
    fps: float = DEFAULT_FPS,
    media_index: Optional[dict[str, str]] = None,
    media_dir: Optional[str] = None,
    require_output: bool = True,
) -> dict[str, Any]:
    """Render every variable set into a batch manifest.

    Rendering happens for the whole batch up front, and **a variable set that
    fails to render does not abort the build**: it becomes a ``failed`` item
    carrying the reason. That is the first half of failure isolation, and it is
    the cheap half -- discovering on item 31 that item 31 never compiled, before
    thirty renders have been spent, is the whole point.

    ``require_output`` is on for a batch that will be run and off for one that
    is only being inspected: a plan with no ``output.path`` is a perfectly good
    plan to look at and an impossible one to deliver.
    """
    _require_object(document, "template")
    if not isinstance(variables, list) or not variables:
        raise ValueError("variables must be a nonempty list of objects")
    for index, entry in enumerate(variables):
        _require_object(entry, f"variables[{index}]")

    items: list[dict[str, Any]] = []
    for index, entry in enumerate(variables):
        item = _item(index, entry)
        try:
            rendered = render_template(document, entry, fps=fps, media_index=media_index)
        except (ValueError, RuntimeError) as error:
            # Deliberately not TypeError/AttributeError: a bug in this module
            # must surface as a crash, not as forty items that "failed".
            item["state"] = "failed"
            item["error"] = str(error)
            items.append(item)
            continue
        item["name"] = rendered["name"]
        item["plan"] = rendered["plan"]
        item["reframe"] = rendered["reframe"]
        item["export"] = rendered["export"]
        item["output_path"] = rendered["output_path"]
        if require_output and not item["output_path"]:
            item["state"] = "failed"
            item["error"] = (
                "the rendered plan carries no output.path; a batch item needs a "
                "destination to render to"
            )
        items.append(item)

    return {
        "schema": BATCH_SCHEMA,
        "template": document,
        "options": {
            "fps": fps,
            "media_index": media_index,
            "media_dir": media_dir,
        },
        "items": items,
    }


def _check_manifest(manifest: Any, where: str) -> dict[str, Any]:
    _require_object(manifest, where)
    schema = manifest.get("schema")
    if schema != BATCH_SCHEMA:
        raise ValueError(f"{where} has unsupported schema {schema!r} (expected {BATCH_SCHEMA!r})")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"{where} must carry a nonempty 'items' list")
    for index, item in enumerate(items):
        _require_object(item, f"{where} items[{index}]")
        if item.get("state") not in ITEM_STATES:
            raise ValueError(
                f"{where} items[{index}] has unknown state {item.get('state')!r}; "
                f"expected one of {list(ITEM_STATES)}"
            )
    return manifest


def load_batch(path: str) -> dict[str, Any]:
    """Read a batch manifest back from disk.

    A half-written or hand-edited manifest is rejected rather than repaired:
    resuming from a state the adapter cannot fully read is how a batch silently
    re-renders finished items or loses the failures it already recorded.
    """
    source = os.fspath(path)
    try:
        document = json.loads(open(source, encoding="utf-8").read())
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read batch manifest {source}: {error}") from None
    return _check_manifest(document, f"batch manifest {source}")


def save_batch(path: str, manifest: dict[str, Any]) -> None:
    """Write a batch manifest atomically.

    The manifest is the resume record, so it is rewritten after every item.
    Writing it in place means a crash between ``truncate`` and ``write`` leaves
    a file that is not JSON, and the batch -- every item already rendered, every
    failure already paid for -- becomes unresumable. Replace instead.
    """
    _check_manifest(manifest, "batch manifest")
    target = os.fspath(path)
    temporary = f"{target}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, target)


# ---------------------------------------------------------------------------
# Item state transitions
# ---------------------------------------------------------------------------


def _index(manifest: dict[str, Any], index: int) -> dict[str, Any]:
    items = manifest["items"]
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(items):
        raise ValueError(f"batch has no item {index!r}")
    return items[index]


def begin_item(manifest: dict[str, Any], index: int) -> dict[str, Any]:
    """Mark an item as running and count the attempt."""
    item = _index(manifest, index)
    item["state"] = "running"
    item["attempts"] = int(item.get("attempts") or 0) + 1
    item["error"] = None
    return item


def complete_item(
    manifest: dict[str, Any],
    index: int,
    *,
    timeline_id: Optional[str] = None,
    job_id: Optional[str] = None,
    receipt: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Mark an item as delivered, carrying the proof that it was."""
    item = _index(manifest, index)
    item["state"] = "done"
    item["error"] = None
    if timeline_id is not None:
        item["timeline_id"] = timeline_id
    if job_id is not None:
        item["job_id"] = job_id
    if receipt is not None:
        item["receipt"] = receipt
    return item


def fail_item(manifest: dict[str, Any], index: int, error: Any) -> dict[str, Any]:
    """Record why an item failed, and leave the rest of the batch alone."""
    item = _index(manifest, index)
    item["state"] = "failed"
    item["error"] = str(error) or error.__class__.__name__
    return item


def skip_item(manifest: dict[str, Any], index: int, reason: str) -> dict[str, Any]:
    """Mark an item as never attempted, after an earlier item stopped the batch."""
    item = _index(manifest, index)
    if item["state"] != "pending":
        return item
    item["state"] = "skipped"
    item["error"] = reason
    return item


def select_items(manifest: dict[str, Any], *, retry_failed: bool = False) -> list[int]:
    """The indices still worth attempting, in order.

    ``retry_failed`` is what resume turns on: a failed item is the one thing a
    second run exists to fix, and it costs nothing to attempt again because a
    render is idempotent per output path. A ``done`` item is never re-attempted.
    """
    wanted = {"pending"} if not retry_failed else {"pending", "failed"}
    return [item["index"] for item in manifest["items"] if item["state"] in wanted]


def item_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts = {state: 0 for state in ITEM_STATES}
    for item in manifest["items"]:
        counts[item["state"]] += 1
    return counts


def summarize(manifest: dict[str, Any]) -> dict[str, Any]:
    """A compact report: the whole point of a batch is the per-item verdict.

    Failed items keep their error so the operator can tell "one bad variable
    set" from "the host died on item 12" without opening the manifest, and
    ``done`` items keep their receipt rather than a bare ``true`` -- a batch is
    accepted one artifact at a time, and the receipt is that acceptance.
    """
    counts = item_counts(manifest)
    return {
        "schema": manifest["schema"],
        "total": len(manifest["items"]),
        "counts": counts,
        "complete": counts["failed"] == 0 and counts["skipped"] == 0 and counts["pending"] == 0,
        "items": [
            {
                "index": item["index"],
                "name": item["name"],
                "state": item["state"],
                "output_path": item["output_path"],
                "attempts": item["attempts"],
                "error": item["error"],
                "receipt": item["receipt"],
                "cropped": bool((item.get("reframe") or {}).get("cropped")),
            }
            for item in manifest["items"]
        ],
    }
