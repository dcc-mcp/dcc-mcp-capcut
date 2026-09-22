"""Validate the portable Vlog recipe through the canonical edit plan.

This used to keep its own copy of the rules, which is how the same media ended
up with two different verdicts: the shipped recipe once placed two video clips
at ``0/4.5`` and ``4.2/8.0``, and this validator accepted the 0.3 s overlap that
``export_otio`` rejected. The recipe is now compiled into
``dcc-mcp-capcut/edit-plan/v1`` and validated by the one contract every link --
offline render, OTIO export, CapCut assembly -- shares.

Requires the installed package (``pip install .``); there is no second rule set
to fall back to, because a fallback is exactly the bug this removes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from dcc_mcp_capcut.editplan import compile_plan, plan_to_actions
except ImportError as exc:  # pragma: no cover - environment problem, not a recipe problem
    raise SystemExit(
        "dcc_mcp_capcut is not importable; install the package "
        "(python -m pip install .) so the recipe is validated by the adapter's "
        f"canonical edit plan rather than a local copy of the rules: {exc}"
    ) from exc

ROOT = Path(__file__).resolve().parent


def media_index() -> dict[str, str]:
    """Map asset ids to their local relative paths, as recorded in assets.json."""
    assets = json.loads((ROOT / "assets.json").read_text(encoding="utf-8"))
    return {asset["id"]: asset["local_path"] for asset in assets["assets"]}


def validate(path: str) -> dict:
    recipe = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = compile_plan(recipe, media_index=media_index())
    script = plan_to_actions(plan)
    return {
        "schema": plan["schema"],
        "project_name": plan["name"],
        "aspect_ratio": f"{plan['width']}:{plan['height']}",
        "duration": round(plan["duration_frames"] / plan["fps"], 3),
        "duration_frames": plan["duration_frames"],
        "fps": plan["fps"],
        "clip_count": sum(len(track["clips"]) for track in plan["tracks"]),
        "caption_count": len(plan["captions"]),
        "has_music": any(track["kind"] == "Audio" for track in plan["tracks"]),
        "action_count": len(script["actions"]),
    }


if __name__ == "__main__":
    print(json.dumps(validate(sys.argv[1] if len(sys.argv) > 1 else "vlog_recipe.json"), indent=2))
