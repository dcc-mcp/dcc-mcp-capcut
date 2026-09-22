"""Portable, frame-accurate editorial interchange without a running CapCut host.

The input is an explicit edit decision list, never an inferred live timeline.
Only straight cuts, track gaps and caption markers are represented. Callers
must bake effects into media before exporting; unsupported fields are errors.

The field validators and the portable media rule are owned by
:mod:`dcc_mcp_capcut.editplan`, the canonical edit-plan contract, so the OTIO
export link and the assembly link cannot drift into two different verdicts for
the same plan.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dcc_mcp_capcut.editplan import relative_media as _relative_media
from dcc_mcp_capcut.editplan import require_fps
from dcc_mcp_capcut.editplan import require_integer as _integer
from dcc_mcp_capcut.editplan import require_object as _object
from dcc_mcp_capcut.editplan import require_text as _text


def export_otio(timeline: dict[str, Any]) -> dict[str, Any]:
    """Return OTIO JSON from a strict frame-based EDL; performs no disk or host IO."""
    try:
        import opentimelineio as otio
    except ImportError as exc:
        raise RuntimeError("Install dcc-mcp-capcut[interchange] for OTIO support") from exc

    _object(
        timeline,
        {"name", "fps", "width", "height", "duration_frames", "tracks", "captions"},
        {"name", "fps", "width", "height", "duration_frames", "tracks"},
        "timeline",
    )
    name = _text(timeline["name"], "name")
    fps = require_fps(timeline["fps"])
    duration = _integer(timeline["duration_frames"], "duration_frames", 1)
    width = _integer(timeline["width"], "width", 1)
    height = _integer(timeline["height"], "height", 1)
    tracks = timeline["tracks"]
    if not isinstance(tracks, list) or not tracks:
        raise ValueError("tracks must be a nonempty list")

    def time_range(start: int, length: int):
        return otio.opentime.TimeRange(
            otio.opentime.RationalTime(start, fps), otio.opentime.RationalTime(length, fps)
        )

    result = otio.schema.Timeline(name=name, global_start_time=otio.opentime.RationalTime(0, fps))
    result.metadata["dcc_mcp_capcut"] = {
        "width": width,
        "height": height,
        "fps": fps,
        "origin": "explicit_edit_decisions",
        "effects": "baked_into_referenced_media",
        "captions": "markers_only; use accompanying SRT for editable subtitles",
    }
    media_paths: set[str] = set()
    clip_count = 0
    for track_spec in tracks:
        _object(track_spec, {"name", "kind", "clips"}, {"name", "kind", "clips"}, "track")
        if track_spec["kind"] not in ("Video", "Audio"):
            raise ValueError("track kind must be Video or Audio")
        track = otio.schema.Track(
            name=_text(track_spec["name"], "track name"), kind=track_spec["kind"]
        )
        clips = track_spec["clips"]
        if not isinstance(clips, list):
            raise ValueError("clips must be a list")
        cursor = 0
        for spec in clips:
            _object(
                spec,
                {"name", "media", "start", "source_in", "duration", "media_duration"},
                {"name", "media", "start", "duration", "media_duration"},
                "clip",
            )
            start = _integer(spec["start"], "start")
            source_in = _integer(spec.get("source_in", 0), "source_in")
            length = _integer(spec["duration"], "duration", 1)
            available = _integer(spec["media_duration"], "media_duration", 1)
            if start < cursor:
                raise ValueError("clips must be ordered and non-overlapping within a track")
            if start + length > duration or source_in + length > available:
                raise ValueError("clip exceeds timeline or media duration")
            if start > cursor:
                track.append(otio.schema.Gap(source_range=time_range(0, start - cursor)))
            media = _relative_media(spec["media"])
            media_paths.add(media)
            track.append(
                otio.schema.Clip(
                    name=_text(spec["name"], "clip name"),
                    media_reference=otio.schema.ExternalReference(
                        target_url=media, available_range=time_range(0, available)
                    ),
                    source_range=time_range(source_in, length),
                )
            )
            cursor = start + length
            clip_count += 1
        if cursor < duration:
            track.append(otio.schema.Gap(source_range=time_range(0, duration - cursor)))
        result.tracks.append(track)

    captions = timeline.get("captions", [])
    if not isinstance(captions, list):
        raise ValueError("captions must be a list")
    for caption in captions:
        _object(caption, {"text", "start", "duration"}, {"text", "start", "duration"}, "caption")
        start = _integer(caption["start"], "caption start")
        length = _integer(caption["duration"], "caption duration", 1)
        if start + length > duration:
            raise ValueError("caption exceeds timeline duration")
        result.tracks.markers.append(
            otio.schema.Marker(
                name=_text(caption["text"], "caption text"),
                marked_range=time_range(start, length),
                metadata={"type": "subtitle"},
            )
        )

    return {
        "otio_json": otio.adapters.write_to_string(result, adapter_name="otio_json"),
        "duration_frames": duration,
        "fps": fps,
        "clip_count": clip_count,
        "media_paths": sorted(media_paths),
        "limitations": [
            "Source is supplied edit decisions, not a verified live CapCut timeline.",
            "Effects must be baked; captions are markers, not native text tracks.",
            "Resolve relative media paths from the timeline file directory.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = export_otio(json.loads(args.input.read_text(encoding="utf-8-sig")))
    # Exclusive creation preserves existing deliverables and user edits.
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(result["otio_json"])


if __name__ == "__main__":
    main()
