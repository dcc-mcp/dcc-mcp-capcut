"""Validate and summarize the portable Vlog recipe without requiring CapCut."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def validate(path: str) -> dict:
    recipe = json.loads(Path(path).read_text(encoding="utf-8"))
    media = recipe.get("media", [])
    if not media:
        raise ValueError("recipe.media must contain at least one clip")
    starts = [float(item["start"]) for item in media]
    durations = [float(item["duration"]) for item in media]
    if any(start < 0 or duration <= 0 for start, duration in zip(starts, durations)):
        raise ValueError("media start must be >= 0 and duration must be > 0")
    end = max(start + duration for start, duration in zip(starts, durations))
    captions = recipe.get("captions", [])
    if any(float(c["start"]) + float(c["duration"]) > end + 1e-6 for c in captions):
        raise ValueError("caption extends past the final video clip")
    return {
        "project_name": recipe.get("project_name"),
        "aspect_ratio": recipe.get("aspect_ratio"),
        "duration": round(end, 3),
        "clip_count": len(media),
        "caption_count": len(captions),
        "has_music": bool(recipe.get("music")),
    }


if __name__ == "__main__":
    print(json.dumps(validate(sys.argv[1] if len(sys.argv) > 1 else "vlog_recipe.json"), indent=2))
