"""The canonical edit-plan contract for dcc-mcp-capcut.

One document, one verdict. ``docs/interchange.md`` (frame-based EDL/OTIO) and
``demo/vlog_recipe.json`` (``capcut-vlog-recipe/v1``, seconds-based) used to be
two independent plan formats with two independent rule sets -- the same media
that ``validate_recipe.py`` accepted was rejected by ``export_otio``. This
module is the single owner of the rules both of them now consume:

* ``compile_plan`` normalises either format into one canonical plan
  (``dcc-mcp-capcut/edit-plan/v1``), validating media paths, per-track overlap
  and bounds exactly once.
* ``plan_to_edl`` renders that plan into the strict frame EDL that
  :func:`dcc_mcp_capcut.interchange.export_otio` already accepts, so the OTIO
  export link and the assembly link cannot drift apart.
* ``plan_to_actions`` renders the same plan into an ordered CapCut bridge
  action script, which is the import/assembly direction.
* ``plan_from_otio`` converts OTIO back into a canonical plan, closing the
  round trip.

The module is host-free and deterministic: it performs no host dispatch, no
network IO, and no media decoding. Media *existence* is only checked when the
caller supplies a ``media_dir``.

Units: every ``start``, ``duration``, ``source_in`` and ``media_duration`` in a
canonical plan is an **integer frame** at the plan's ``fps``. Presentation
values that no portable timeline can carry (``volume``, ``fade_in``,
``fade_out``, text ``style``) stay advisory: the assembly path consumes them,
OTIO export cannot represent them, and ``plan_to_edl`` strips them rather than
encoding a guess.
"""

from __future__ import annotations

import math
import posixpath
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

PLAN_SCHEMA = "dcc-mcp-capcut/edit-plan/v1"
VLOG_RECIPE_SCHEMA = "capcut-vlog-recipe/v1"

DEFAULT_FPS = 30.0
DEFAULT_ASPECT_RATIO = "9:16"

#: Canvas presets shared by the vlog recipe profile. Anything else must be
#: supplied explicitly as ``width``/``height`` on the plan.
CANVAS_PRESETS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}

SUBTITLE_FORMATS = ("srt", "lrc", "ass")

MEDIA_PLACEHOLDER = "$media:"
TIMELINE_PLACEHOLDER = "$timeline"
CLIP_PLACEHOLDER = "$clip:"

# A host that does not implement a batch action rejects it with one of these
# markers; see capcut_panel/HOST_API.md. Anything else is a real failure and is
# never silently retried as a composed script.
UNSUPPORTED_ACTION_MARKERS = (
    "unsupported action",
    "unsupported_action",
    "unknown action",
    "unknown_action",
)


def relative_media(value: Any) -> str:
    """Return a portable relative media path or raise.

    This is the one media rule in the adapter: relative, no scheme, no host,
    no traversal, no URL escapes, no reserved characters. Both the OTIO export
    link and the assembly link validate against it, which is what keeps their
    verdicts identical.
    """
    text = require_text(value, "media")
    parts = urlsplit(text)
    if (
        parts.scheme
        or parts.netloc
        or parts.query
        or parts.fragment
        or text.startswith("/")
        or "\\" in text
        or any(p in ("", ".", "..") or any(c in '<>:"|?*' for c in p) for p in text.split("/"))
        or "%" in text
        or any(ord(c) < 32 for c in text)
    ):
        raise ValueError("media must be a portable relative path without traversal or URL escapes")
    return text


def require_object(value: Any, allowed: set[str], required: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if value.keys() - allowed:
        raise ValueError(f"{label} has unsupported fields: {sorted(value.keys() - allowed)}")
    if required - value.keys():
        raise ValueError(f"{label} requires: {sorted(required - value.keys())}")
    return value


def require_integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def require_fps(value: Any, label: str = "fps") -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{label} must be finite and positive")
    return float(value)


def to_frames(seconds: Any, fps: float) -> int:
    """Convert seconds to frames with round-half-up.

    A canonical plan is frame-based, so converting a seconds-based recipe is
    inherently a rounding step. Half-up is chosen over banker's rounding so a
    value sitting exactly on a half frame always moves the same way.
    """
    value = float(seconds)
    if isinstance(seconds, bool) or not math.isfinite(value) or value < 0:
        raise ValueError("time values must be finite numbers >= 0")
    return int(math.floor(value * fps + 0.5))


def to_seconds(frames: int, fps: float) -> float:
    """Convert frames back to seconds for host tools that take seconds."""
    return round(frames / fps, 6)


def _normalize_relative_path(value: Any, label: str) -> str:
    """Normalise a recipe-supplied path, then apply the canonical media rule.

    Recipes are hand-written and routinely carry a ``./`` prefix. That is
    tolerated here, once, and only on the way in: the canonical plan always
    stores the clean relative form. Traversal, absolute and URL forms survive
    normalisation and are still rejected by :func:`relative_media`.
    """
    text = require_text(value, label)
    candidate = posixpath.normpath(text.replace("\\", "/"))
    if candidate == ".." or candidate.startswith("../"):
        raise ValueError(f"{label} must stay inside the delivery directory: {text!r}")
    return relative_media(candidate)


def _optional_number(value: Any, label: str, minimum: float = 0.0) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if value < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return float(value)


# ---------------------------------------------------------------------------
# Canonical plan
# ---------------------------------------------------------------------------

_PLAN_FIELDS = {
    "schema",
    "name",
    "fps",
    "width",
    "height",
    "duration_frames",
    "tracks",
    "captions",
    "subtitle",
    "output",
}
_TRACK_FIELDS = {"name", "kind", "clips"}
_CLIP_FIELDS = {"name", "media", "start", "source_in", "duration", "media_duration", "audio"}
_AUDIO_FIELDS = {"volume", "fade_in", "fade_out"}
_CAPTION_FIELDS = {"text", "start", "duration", "style"}
_SUBTITLE_FIELDS = {"file", "format", "offset", "language", "style"}
_OUTPUT_FIELDS = {"path", "aspect_ratio"}


def _validate_clip(spec: Any, track_name: str, index: int) -> dict:
    label = f"track '{track_name}' clip {index}"
    require_object(spec, _CLIP_FIELDS, {"name", "media", "start", "duration"}, label)
    clip = {
        "name": require_text(spec["name"], f"{label} name"),
        "media": relative_media(spec["media"]),
        "start": require_integer(spec["start"], f"{label} start"),
        "source_in": require_integer(spec.get("source_in", 0), f"{label} source_in"),
        "duration": require_integer(spec["duration"], f"{label} duration", 1),
    }
    media_duration = spec.get("media_duration")
    if media_duration is not None:
        media_duration = require_integer(media_duration, f"{label} media_duration", 1)
    clip["media_duration"] = media_duration
    audio = spec.get("audio")
    if audio is not None:
        require_object(audio, _AUDIO_FIELDS, set(), f"{label} audio")
        clip["audio"] = {
            key: value
            for key, value in (
                ("volume", _optional_number(audio.get("volume"), f"{label} audio volume")),
                ("fade_in", _optional_number(audio.get("fade_in"), f"{label} audio fade_in")),
                ("fade_out", _optional_number(audio.get("fade_out"), f"{label} audio fade_out")),
            )
            if value is not None
        }
    return clip


def normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate a canonical plan and fill its defaults.

    Raises :class:`ValueError` for the same conditions the OTIO exporter and
    the assembly path reject: per-track overlap, out-of-bounds clips and
    captions, and non-portable media paths.
    """
    require_object(plan, _PLAN_FIELDS, {"name", "fps", "width", "height", "tracks"}, "plan")
    schema = plan.get("schema", PLAN_SCHEMA)
    if schema != PLAN_SCHEMA:
        raise ValueError(f"unsupported plan schema: {schema!r} (expected {PLAN_SCHEMA!r})")

    fps = require_fps(plan["fps"])
    normalized: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "name": require_text(plan["name"], "name"),
        "fps": fps,
        "width": require_integer(plan["width"], "width", 1),
        "height": require_integer(plan["height"], "height", 1),
    }
    tracks_spec = plan["tracks"]
    if not isinstance(tracks_spec, list) or not tracks_spec:
        raise ValueError("tracks must be a nonempty list")

    tracks: list[dict[str, Any]] = []
    for track_spec in tracks_spec:
        require_object(track_spec, _TRACK_FIELDS, _TRACK_FIELDS, "track")
        name = require_text(track_spec["name"], "track name")
        kind = track_spec["kind"]
        if kind not in ("Video", "Audio"):
            raise ValueError("track kind must be Video or Audio")
        clips_spec = track_spec["clips"]
        if not isinstance(clips_spec, list):
            raise ValueError("clips must be a list")
        clips = [_validate_clip(spec, name, i) for i, spec in enumerate(clips_spec)]
        cursor = 0
        for clip in clips:
            if clip["start"] < cursor:
                raise ValueError(
                    f"track '{name}': clips overlap at frame {clip['start']} "
                    f"(previous clip ends at {cursor}); ordered and non-overlapping "
                    "within a track, overlays belong on a separate track"
                )
            if clip["media_duration"] is not None and (
                clip["source_in"] + clip["duration"] > clip["media_duration"]
            ):
                raise ValueError(f"track '{name}': clip '{clip['name']}' exceeds media duration")
            cursor = clip["start"] + clip["duration"]
        tracks.append({"name": name, "kind": kind, "clips": clips})

    ends = [clip["start"] + clip["duration"] for track in tracks for clip in track["clips"]]

    captions_spec = plan.get("captions", [])
    if not isinstance(captions_spec, list):
        raise ValueError("captions must be a list")
    captions: list[dict[str, Any]] = []
    for index, spec in enumerate(captions_spec):
        require_object(spec, _CAPTION_FIELDS, {"text", "start", "duration"}, f"caption {index}")
        caption = {
            "text": require_text(spec["text"], f"caption {index} text"),
            "start": require_integer(spec["start"], f"caption {index} start"),
            "duration": require_integer(spec["duration"], f"caption {index} duration", 1),
        }
        if spec.get("style") is not None:
            if not isinstance(spec["style"], dict):
                raise ValueError(f"caption {index} style must be an object")
            caption["style"] = spec["style"]
        captions.append(caption)
        ends.append(caption["start"] + caption["duration"])

    if not ends:
        raise ValueError("plan must place at least one clip or caption")
    declared = plan.get("duration_frames")
    duration = (
        require_integer(declared, "duration_frames", 1) if declared is not None else max(ends)
    )
    # No separate "content is longer than duration_frames" check: the per-clip
    # and per-caption checks below already name the offending item, so every
    # link reports the same message for the same mistake.
    for track in tracks:
        for clip in track["clips"]:
            if clip["start"] + clip["duration"] > duration:
                raise ValueError(
                    f"track '{track['name']}': clip '{clip['name']}' exceeds timeline duration"
                )
    for caption in captions:
        if caption["start"] + caption["duration"] > duration:
            raise ValueError("caption exceeds timeline duration")
    normalized["duration_frames"] = duration
    normalized["tracks"] = tracks
    normalized["captions"] = captions

    subtitle = plan.get("subtitle")
    if subtitle is not None:
        require_object(subtitle, _SUBTITLE_FIELDS, {"file"}, "subtitle")
        fmt = subtitle.get("format")
        if fmt is not None and fmt not in SUBTITLE_FORMATS:
            raise ValueError(f"subtitle format must be one of {list(SUBTITLE_FORMATS)}")
        normalized["subtitle"] = {
            "file": require_text(subtitle["file"], "subtitle file"),
            **{
                key: value
                for key, value in (
                    ("format", fmt),
                    ("offset", _optional_number(subtitle.get("offset"), "subtitle offset")),
                    ("language", subtitle.get("language")),
                    ("style", subtitle.get("style")),
                )
                if value is not None
            },
        }
        if "language" in normalized["subtitle"]:
            require_text(normalized["subtitle"]["language"], "subtitle language")
        if "style" in normalized["subtitle"] and not isinstance(
            normalized["subtitle"]["style"], dict
        ):
            raise ValueError("subtitle style must be an object")

    output = plan.get("output")
    if output is not None:
        require_object(output, _OUTPUT_FIELDS, set(), "output")
        normalized["output"] = {
            key: value
            for key, value in (
                ("path", output.get("path")),
                ("aspect_ratio", output.get("aspect_ratio")),
            )
            if value is not None
        }
        if "path" in normalized["output"]:
            require_text(normalized["output"]["path"], "output path")
        if "aspect_ratio" in normalized["output"]:
            require_text(normalized["output"]["aspect_ratio"], "output aspect_ratio")
        if not normalized["output"]:
            raise ValueError("output requires at least one of: path, aspect_ratio")

    return normalized


# ---------------------------------------------------------------------------
# vlog recipe profile
# ---------------------------------------------------------------------------

_RECIPE_FIELDS = {
    "schema",
    "project_name",
    "aspect_ratio",
    "media",
    "music",
    "subtitle_file",
    "captions",
    "output_path",
}
_RECIPE_MEDIA_FIELDS = {"id", "path", "start", "duration", "track_type", "source_in"}
_RECIPE_MUSIC_FIELDS = {"media_id", "path", "start", "duration", "volume", "fade_in", "fade_out"}
_RECIPE_CAPTION_FIELDS = {"text", "start", "duration", "style"}


def _recipe_media_path(item: dict, index: int, media_index: dict[str, str] | None) -> str:
    label = f"recipe media {index}"
    path = item.get("path")
    if path is None:
        # The music bed carries its asset id as 'media_id', recipe clips as
        # 'id'; both resolve through the same caller-supplied index.
        item_id = item.get("id") or item.get("media_id")
        if not item_id or not media_index or item_id not in media_index:
            raise ValueError(
                f"{label} needs 'path', or 'id' with a media_index entry for {item_id!r}"
            )
        path = media_index[item_id]
    return _normalize_relative_path(path, f"{label} path")


def compile_recipe(
    recipe: dict[str, Any],
    *,
    fps: float = DEFAULT_FPS,
    media_index: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Compile a ``capcut-vlog-recipe/v1`` document into a canonical plan.

    Seconds become frames at ``fps``. ``media_index`` maps recipe asset ids to
    portable relative paths, which is how an id-only entry such as the music bed
    resolves without hard-coding a filename.
    """
    require_object(recipe, _RECIPE_FIELDS, {"media"}, "recipe")
    schema = recipe.get("schema", VLOG_RECIPE_SCHEMA)
    if schema != VLOG_RECIPE_SCHEMA:
        raise ValueError(f"unsupported recipe schema: {schema!r} (expected {VLOG_RECIPE_SCHEMA!r})")
    fps = require_fps(fps)

    media_spec = recipe["media"]
    if not isinstance(media_spec, list) or not media_spec:
        raise ValueError("recipe.media must be a nonempty list")

    aspect_ratio = recipe.get("aspect_ratio", DEFAULT_ASPECT_RATIO)
    if not isinstance(aspect_ratio, str) or aspect_ratio not in CANVAS_PRESETS:
        raise ValueError(f"recipe aspect_ratio must be one of {sorted(CANVAS_PRESETS)}")
    width, height = CANVAS_PRESETS[aspect_ratio]

    video_clips: list[dict[str, Any]] = []
    audio_clips: list[dict[str, Any]] = []
    for index, item in enumerate(media_spec):
        require_object(item, _RECIPE_MEDIA_FIELDS, {"start", "duration"}, f"recipe media {index}")
        track_type = item.get("track_type", "video")
        if track_type not in ("video", "audio"):
            raise ValueError(f"recipe media {index} track_type must be video or audio")
        start = to_frames(item["start"], fps)
        duration = to_frames(item["duration"], fps)
        if duration < 1:
            raise ValueError(
                f"recipe media {index} duration is shorter than one frame at {fps} fps"
            )
        clip = {
            "name": item.get("id") or f"clip{index}",
            "media": _recipe_media_path(item, index, media_index),
            "start": start,
            "source_in": to_frames(item.get("source_in", 0), fps),
            "duration": duration,
            "media_duration": None,
        }
        (video_clips if track_type == "video" else audio_clips).append(clip)

    tracks: list[dict[str, Any]] = []
    if video_clips:
        tracks.append({"name": "Picture", "kind": "Video", "clips": video_clips})

    music = recipe.get("music")
    if music is not None:
        require_object(music, _RECIPE_MUSIC_FIELDS, set(), "recipe music")
        audio_clips.append(
            {
                "name": music.get("media_id") or "music",
                "media": _recipe_media_path(music, 0, media_index),
                "start": to_frames(music.get("start", 0), fps),
                "source_in": 0,
                "duration": (
                    to_frames(music["duration"], fps) if music.get("duration") is not None else None
                ),
                "media_duration": None,
                "audio": {
                    key: value
                    for key, value in (
                        ("volume", _optional_number(music.get("volume"), "music volume")),
                        ("fade_in", _optional_number(music.get("fade_in"), "music fade_in")),
                        ("fade_out", _optional_number(music.get("fade_out"), "music fade_out")),
                    )
                    if value is not None
                },
            }
        )

    captions = []
    for index, item in enumerate(recipe.get("captions", [])):
        require_object(
            item, _RECIPE_CAPTION_FIELDS, {"text", "start", "duration"}, f"recipe caption {index}"
        )
        caption = {
            "text": require_text(item["text"], f"recipe caption {index} text"),
            "start": to_frames(item["start"], fps),
            "duration": max(1, to_frames(item["duration"], fps)),
        }
        if item.get("style") is not None:
            if not isinstance(item["style"], dict):
                raise ValueError(f"recipe caption {index} style must be an object")
            caption["style"] = item["style"]
        captions.append(caption)

    # The cut length comes from the picture and captions alone: a music bed
    # without an explicit duration spans that cut instead of defining it, which
    # is what the offline renderer already assumed.
    ends = [clip["start"] + clip["duration"] for clip in video_clips] + [
        caption["start"] + caption["duration"] for caption in captions
    ]
    if not ends:
        raise ValueError("recipe must place at least one video clip or caption")
    content_end = max(ends)
    for clip in audio_clips:
        if clip["duration"] is None:
            clip["duration"] = max(1, content_end - clip["start"])

    if audio_clips:
        tracks.append({"name": "Music", "kind": "Audio", "clips": audio_clips})

    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "name": recipe.get("project_name") or "CapCut vlog",
        "fps": fps,
        "width": width,
        "height": height,
        "tracks": tracks,
        "captions": captions,
    }

    subtitle_file = recipe.get("subtitle_file")
    if subtitle_file is not None:
        plan["subtitle"] = {"file": _normalize_relative_path(subtitle_file, "subtitle_file")}
    output_path = recipe.get("output_path")
    if output_path is not None or recipe.get("aspect_ratio") is not None:
        plan["output"] = {"aspect_ratio": aspect_ratio}
        if output_path is not None:
            plan["output"]["path"] = require_text(output_path, "output_path")

    return normalize_plan(plan)


def compile_plan(
    document: dict[str, Any],
    *,
    fps: float = DEFAULT_FPS,
    media_index: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Normalise either accepted plan format into a canonical plan.

    The shape is discriminated, not guessed from a version string: a document
    with ``tracks`` is a canonical plan, a document with ``media`` is a vlog
    recipe. A declared ``schema`` has to agree with the shape.
    """
    if not isinstance(document, dict):
        raise ValueError("plan must be an object")
    has_tracks = "tracks" in document
    has_media = "media" in document
    if has_tracks == has_media:
        raise ValueError(
            "plan must carry either 'tracks' (canonical plan) or 'media' (vlog recipe)"
        )
    if has_tracks:
        return normalize_plan(document)
    return compile_recipe(document, fps=fps, media_index=media_index)


# ---------------------------------------------------------------------------
# Consumers: OTIO export, OTIO import, CapCut assembly
# ---------------------------------------------------------------------------


def plan_to_edl(plan: dict[str, Any]) -> dict[str, Any]:
    """Render a canonical plan as the strict frame EDL ``export_otio`` accepts.

    Advisory presentation fields are stripped here rather than passed through:
    OTIO cannot represent volume, fades or text styling, and guessing an
    encoding would be worse than not carrying them. Timings, trims, gaps,
    tracks and caption markers all survive.
    """
    normalized = normalize_plan(plan)
    tracks = []
    for track in normalized["tracks"]:
        clips = []
        for clip in track["clips"]:
            if clip["media_duration"] is None:
                raise ValueError(
                    f"clip '{clip['name']}' on track '{track['name']}' has no media_duration; "
                    "probe the media (or supply it) before exporting OTIO, because the "
                    "exporter refuses to claim bounds it cannot prove"
                )
            clips.append(
                {
                    "name": clip["name"],
                    "media": clip["media"],
                    "start": clip["start"],
                    "source_in": clip["source_in"],
                    "duration": clip["duration"],
                    "media_duration": clip["media_duration"],
                }
            )
        tracks.append({"name": track["name"], "kind": track["kind"], "clips": clips})
    return {
        "name": normalized["name"],
        "fps": normalized["fps"],
        "width": normalized["width"],
        "height": normalized["height"],
        "duration_frames": normalized["duration_frames"],
        "tracks": tracks,
        "captions": [
            {"text": caption["text"], "start": caption["start"], "duration": caption["duration"]}
            for caption in normalized["captions"]
        ],
    }


def plan_to_actions(
    plan: dict[str, Any],
    *,
    media_dir: Optional[str] = None,
    export: bool = False,
) -> dict[str, Any]:
    """Render a canonical plan as an ordered CapCut bridge action script.

    The script is deterministic and host-free: it is the same document whether
    it is returned by a dry run or handed to the bridge. ``media_dir`` resolves
    the plan's portable relative paths and is required before dispatch -- every
    referenced file must exist, otherwise the call fails before a single host
    mutation happens.

    Placeholders tie the steps together: ``$media:mN`` (imported media id),
    ``$timeline`` (created timeline id) and ``$clip:cN`` (placed clip id) are
    substituted from the receipts as the script is executed.
    """
    normalized = normalize_plan(plan)
    fps = normalized["fps"]

    order: list[tuple[int, int, dict]] = []
    for track_index, track in enumerate(normalized["tracks"]):
        for clip_index, clip in enumerate(track["clips"]):
            order.append((track_index, clip_index, clip))
    order.sort(key=lambda item: (item[0], item[2]["start"]))

    media_keys: dict[str, str] = {}
    media_order: list[str] = []
    for _, _, clip in order:
        if clip["media"] not in media_keys:
            key = f"m{len(media_order)}"
            media_keys[clip["media"]] = key
            media_order.append(clip["media"])

    resolved = media_order
    if media_dir is not None:
        base = Path(media_dir).resolve()
        missing = [path for path in media_order if not (base / path).is_file()]
        if missing:
            raise ValueError(
                "media_dir does not contain every referenced file: "
                + ", ".join(sorted(missing))
                + f" (looked under {base})"
            )
        resolved = [str(base / path) for path in media_order]

    # One import per file, not one import for the whole list. The fail-closed
    # contract only guarantees import_media returns a single 'media_id', so a
    # multi-path call cannot be mapped back to the individual clips -- see
    # capcut-media on why the plural field is not enforced. One path per call is
    # unambiguous, and the whole plan is still one tool call to the caller.
    actions: list[dict[str, Any]] = [
        {
            "action": "import_media",
            "params": {"paths": [path]},
            "media_ref": media_keys[media_order[index]],
        }
        for index, path in enumerate(resolved)
    ]
    actions.append(
        {
            "action": "create_timeline",
            "params": {
                "name": normalized["name"],
                "width": normalized["width"],
                "height": normalized["height"],
                "fps": fps,
            },
        }
    )

    video_tracks_seen = 0
    track_types: dict[int, str] = {}
    for track_index, track in enumerate(normalized["tracks"]):
        if track["kind"] == "Audio":
            track_types[track_index] = "audio"
        else:
            # The first picture track is the base track; further picture tracks
            # in CapCut are overlay tracks stacked above it.
            track_types[track_index] = "video" if video_tracks_seen == 0 else "overlay"
            video_tracks_seen += 1

    for clip_index, (track_index, _, clip) in enumerate(order):
        params: dict[str, Any] = {
            "media_id": f"{MEDIA_PLACEHOLDER}{media_keys[clip['media']]}",
            "timeline_id": TIMELINE_PLACEHOLDER,
            "track_type": track_types[track_index],
            "start": to_seconds(clip["start"], fps),
            "source_in": to_seconds(clip["source_in"], fps),
            "source_out": to_seconds(clip["source_in"] + clip["duration"], fps),
        }
        action: dict[str, Any] = {"action": "add_clip", "params": params}
        if clip.get("audio"):
            action["clip_ref"] = f"c{clip_index}"
        actions.append(action)
        audio = clip.get("audio") or {}
        if audio.get("volume") is not None:
            actions.append(
                {
                    "action": "set_audio_volume",
                    "params": {
                        "clip_id": f"{CLIP_PLACEHOLDER}c{clip_index}",
                        "volume": audio["volume"],
                    },
                }
            )
        if audio.get("fade_in") is not None or audio.get("fade_out") is not None:
            params = {"clip_id": f"{CLIP_PLACEHOLDER}c{clip_index}"}
            if audio.get("fade_in") is not None:
                params["fade_in"] = audio["fade_in"]
            if audio.get("fade_out") is not None:
                params["fade_out"] = audio["fade_out"]
            actions.append({"action": "add_audio_fade", "params": params})

    subtitle = normalized.get("subtitle")
    if subtitle is not None:
        subtitle_path = subtitle["file"]
        if media_dir is not None:
            subtitle_path = str(Path(media_dir).resolve() / subtitle["file"])
        params = {"timeline_id": TIMELINE_PLACEHOLDER, "path": subtitle_path}
        if subtitle.get("format") is not None:
            params["format"] = subtitle["format"]
        if subtitle.get("offset"):
            params["offset"] = subtitle["offset"]
        if subtitle.get("language") is not None:
            params["language"] = subtitle["language"]
        if subtitle.get("style") is not None:
            params["style"] = subtitle["style"]
        actions.append({"action": "import_subtitles", "params": params})
    else:
        for caption in normalized["captions"]:
            params = {
                "timeline_id": TIMELINE_PLACEHOLDER,
                "text": caption["text"],
                "start": to_seconds(caption["start"], fps),
                "duration": to_seconds(caption["duration"], fps),
            }
            if caption.get("style") is not None:
                params["style"] = caption["style"]
            actions.append({"action": "add_text", "params": params})

    if export:
        output = normalized.get("output") or {}
        if not output.get("path"):
            raise ValueError("export=True requires output.path on the plan")
        actions.append(
            {
                "action": "export_video",
                "params": {
                    "timeline_id": TIMELINE_PLACEHOLDER,
                    "output_path": output["path"],
                    "width": normalized["width"],
                    "height": normalized["height"],
                    "fps": fps,
                },
            }
        )

    actions.append({"action": "save_project", "params": {}})
    return {
        "media": {media_keys[path]: path for path in media_order},
        "actions": actions,
    }


def is_unsupported_action(error: BaseException) -> bool:
    """Report whether a host rejection means "this action is not implemented"."""
    message = str(error).lower()
    return any(marker in message for marker in UNSUPPORTED_ACTION_MARKERS)


def substitute_placeholders(params: dict[str, Any], ids: dict[str, str]) -> dict[str, Any]:
    """Replace ``$media:``/``$timeline``/``$clip:`` placeholders with host ids."""
    resolved: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str) and value.startswith(("$media:", "$timeline", "$clip:")):
            if value not in ids:
                raise RuntimeError(f"assembly step refers to unresolved id {value!r}")
            resolved[key] = ids[value]
        else:
            resolved[key] = value
    return resolved


def plan_from_otio(
    source: str,
    *,
    fps: Optional[float] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> dict[str, Any]:
    """Read OTIO JSON (or an ``.otio`` file path) into a canonical plan.

    This is the import direction of the interchange link. Canvas values are
    read from the ``dcc_mcp_capcut`` metadata block written by
    :func:`dcc_mcp_capcut.interchange.export_otio`; when a foreign OTIO file
    carries no such block, the caller must supply ``fps``/``width``/``height``
    because there is nothing to read them from and guessing would fabricate
    evidence.
    """
    try:
        import opentimelineio as otio
    except ImportError as exc:  # pragma: no cover - exercised through the extra
        raise RuntimeError("Install dcc-mcp-capcut[interchange] for OTIO support") from exc

    if isinstance(source, Path):
        source = str(source)
    looks_like_json = source.lstrip().startswith("{")
    if looks_like_json:
        timeline = otio.adapters.read_from_string(source, "otio_json")
    else:
        timeline = otio.adapters.read_from_file(source)

    metadata = dict(timeline.metadata.get("dcc_mcp_capcut") or {})
    rate = float(timeline.duration().rate)
    resolved_fps = require_fps(fps if fps is not None else metadata.get("fps", rate), "fps")
    resolved_width = width if width is not None else metadata.get("width")
    resolved_height = height if height is not None else metadata.get("height")
    if resolved_width is None or resolved_height is None:
        raise ValueError(
            "this OTIO file carries no dcc_mcp_capcut canvas metadata; supply width and height"
        )

    def frames_of(value: Any) -> int:
        return int(round(float(value.rescaled_to(resolved_fps).value)))

    tracks: list[dict[str, Any]] = []
    for track in timeline.tracks:
        clips = []
        for child in track.find_clips():
            reference = child.media_reference
            if not hasattr(reference, "target_url"):
                raise ValueError(
                    f"clip '{child.name}' has no external media reference; "
                    "only straight cuts of external media are supported"
                )
            source_range = child.source_range
            available = reference.available_range
            clips.append(
                {
                    "name": child.name,
                    "media": relative_media(reference.target_url),
                    "start": frames_of(child.range_in_parent().start_time),
                    "source_in": frames_of(source_range.start_time),
                    "duration": frames_of(source_range.duration),
                    "media_duration": (
                        frames_of(available.duration) if available is not None else None
                    ),
                }
            )
        if clips:
            tracks.append({"name": track.name, "kind": track.kind, "clips": clips})

    captions = [
        {
            "text": marker.name,
            "start": frames_of(marker.marked_range.start_time),
            "duration": frames_of(marker.marked_range.duration),
        }
        for marker in timeline.tracks.markers
    ]
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "name": timeline.name,
        "fps": resolved_fps,
        "width": int(resolved_width),
        "height": int(resolved_height),
        "tracks": tracks,
        "captions": captions,
    }
    return normalize_plan(plan)
