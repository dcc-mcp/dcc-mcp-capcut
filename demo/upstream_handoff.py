"""End-to-end example of the upstream handoff format.

An upstream generator -- a storyboard tool, a script-to-video pipeline, a
template renderer -- produces the cut and the material. This script is the
contract check for that handoff: it reconciles the asset manifest against the
edit plan, compiles the plan, proves the plan is portable through OTIO, and
lowers it to the exact CapCut action script **without touching the host**.

Everything through stage 5 is host-free and runs on any platform. Stage 6 is
the only part that needs a bound CapCut window, and it is opt-in.

    python demo/upstream_handoff.py                     # stages 1-5, host-free
    python demo/upstream_handoff.py --json              # machine-readable verdict
    python demo/upstream_handoff.py --dispatch          # stage 6, needs a bound host
    python demo/upstream_handoff.py --media-dir PATH    # a real delivery directory

The bundled delivery under ``demo/upstream-delivery/`` is the worked example.
It ships the two handoff documents and a real subtitle file, but no media
bytes: the contract under test is that every referenced path resolves inside
the delivery root and that the plan compiles, not that pixels decode. Absent
media are materialised as zero-byte placeholders so the example runs offline;
``--no-materialize`` turns that off and reports them as missing instead, which
is what you want when validating a real delivery.

Requires the installed package (``python -m pip install '.[interchange]'``);
there is no local copy of the rules, because a second rule set is exactly the
divergence the canonical edit plan exists to remove.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from dcc_mcp_capcut.editplan import (
        compile_plan,
        plan_from_otio,
        plan_to_actions,
        plan_to_edl,
        relative_media,
    )
    from dcc_mcp_capcut.editplan import resolve_referenced_files as _resolve_referenced_files
    from dcc_mcp_capcut.interchange import export_otio
except ImportError as exc:  # pragma: no cover - environment problem, not a contract problem
    raise SystemExit(
        "dcc_mcp_capcut is not importable; install the package "
        "(python -m pip install '.[interchange]') so the handoff is checked by the "
        f"adapter's canonical edit plan rather than a local copy of the rules: {exc}"
    ) from exc

ROOT = Path(__file__).resolve().parent
DEFAULT_DELIVERY = ROOT / "upstream-delivery"

MANIFEST_SCHEMA = "dcc-mcp-capcut/asset-manifest/v1"
PLAN_SCHEMA = "dcc-mcp-capcut/edit-plan/v1"


class HandoffError(RuntimeError):
    """The delivery does not satisfy the handoff contract."""


def load_delivery(media_dir: Path) -> tuple[dict, dict]:
    """Read the two handoff documents from the delivery root."""
    manifest_path = media_dir / "asset-manifest.json"
    plan_path = media_dir / "edit-plan.json"
    for path in (manifest_path, plan_path):
        if not path.is_file():
            raise HandoffError(f"{path.name} is missing from the delivery root {media_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    schema = manifest.get("schema")
    if schema != MANIFEST_SCHEMA:
        raise HandoffError(
            f"asset-manifest.json declares schema {schema!r}; expected {MANIFEST_SCHEMA!r}"
        )
    return manifest, plan


def declared_paths(manifest: dict) -> list[str]:
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise HandoffError("asset-manifest.json carries no assets")
    seen: set[str] = set()
    paths: list[str] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise HandoffError(f"assets[{index}] is not an object")
        for field in ("id", "path", "kind", "license"):
            if not asset.get(field):
                raise HandoffError(f"assets[{index}] is missing required field {field!r}")

        # Portability is enforced here, on every declared path, and not only on
        # the subset the plan happens to reference. The manifest is the input a
        # downstream copy of this example would feed straight to the filesystem
        # -- materialize() writes to these paths -- so an unvalidated absolute
        # or traversing path would write outside the delivery root before
        # reconcile() ever got a chance to reject the delivery.
        try:
            path = relative_media(asset["path"])
        except ValueError as exc:
            raise HandoffError(
                f"assets[{index}] declares a non-portable path {asset['path']!r}: {exc}"
            ) from exc

        if path in seen:
            raise HandoffError(f"assets[{index}] repeats the path {path!r}")
        seen.add(path)
        paths.append(path)
    return paths


def referenced_paths(plan: dict) -> list[str]:
    """Every path the plan will hand to the host on dispatch."""
    referenced: list[str] = []
    for track in plan.get("tracks", []):
        for clip in track.get("clips", []):
            if clip.get("media") and clip["media"] not in referenced:
                referenced.append(clip["media"])
    for subtitle in plan.get("subtitles", []):
        if subtitle.get("file") and subtitle["file"] not in referenced:
            referenced.append(subtitle["file"])
    return referenced


def materialize(manifest: dict, media_dir: Path) -> list[str]:
    """Create a zero-byte placeholder for any declared asset that is not present.

    The bundled delivery ships the two handoff documents and a real SRT, but no
    media bytes: the contract under test is that paths resolve and the plan
    compiles, not that pixels decode. Placeholders make the example runnable
    with no network and no footage. Real deliveries skip this entirely.
    """
    created: list[str] = []
    for asset in manifest["assets"]:
        target = media_dir / asset["path"]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")
            created.append(asset["path"])
    return created


def reconcile(manifest: dict, plan: dict, media_dir: Path) -> dict:
    """Check declared, present, and explained before anything touches the host.

    The three checks are ordered so the failure names the real problem: a path
    the plan uses but the manifest never declared is a different mistake from a
    declared file that was never delivered, and both differ from a delivered
    file nothing references.
    """
    declared = declared_paths(manifest)
    referenced = referenced_paths(plan)

    undeclared = [path for path in referenced if path not in declared]
    if undeclared:
        raise HandoffError(
            "the plan references paths the manifest does not declare: " + ", ".join(undeclared)
        )

    resolved = _resolve_referenced_files(media_dir.resolve(), referenced)
    missing = [path for path in referenced if not resolved[path].is_file()]
    if missing:
        raise HandoffError(
            f"the delivery root {media_dir} does not contain every referenced file: "
            + ", ".join(missing)
        )

    unused = [path for path in declared if path not in referenced]
    return {
        "declared": len(declared),
        "referenced": len(referenced),
        "unused": unused,
        "attribution": [
            {"path": asset["path"], "attribution": asset.get("attribution")}
            for asset in manifest["assets"]
            if asset.get("attribution")
        ],
    }


def portable_round_trip(plan: dict) -> dict:
    """Export to OTIO and read it back, proving the plan survives interchange.

    OTIO cannot carry the advisory presentation fields, so the round trip is
    expected to return the portable core -- timings, trims, gaps and track
    structure -- and to drop volume, fades, styling, subtitle files and the
    output path. Reporting what was dropped is the point: a silent drop would
    be the bug.
    """
    exported = export_otio(plan_to_edl(plan))
    otio_json = exported["otio_json"]
    restored = plan_from_otio(otio_json)

    # What the round trip did not carry back, derived from the two documents
    # rather than assumed: advisory presentation is the documented OTIO limit.
    dropped = [key for key in ("output", "subtitles") if plan.get(key) and not restored.get(key)]
    if any("audio" in clip for track in plan["tracks"] for clip in track["clips"]) and not any(
        "audio" in clip for track in restored["tracks"] for clip in track["clips"]
    ):
        dropped.append("clip audio presentation")

    return {
        "otio_bytes": len(otio_json),
        "restored_clips": sum(len(track["clips"]) for track in restored["tracks"]),
        "restored_duration_frames": restored["duration_frames"],
        "matches_duration": restored["duration_frames"] == plan["duration_frames"],
        "dropped_by_otio": dropped,
    }


def run(
    media_dir: Path,
    *,
    dispatch: bool = False,
    export: bool = False,
    materialize_placeholders: bool = True,
) -> dict:
    manifest, plan = load_delivery(media_dir)
    verdict: dict[str, Any] = {
        "stage": "reconcile",
        "media_dir": str(media_dir),
        "manifest_schema": manifest["schema"],
    }

    # Validate every declared path before writing any of them. materialize()
    # creates files at those paths, so validating afterwards would let a
    # traversing or absolute path write outside the delivery root on its way to
    # being rejected. declared_paths() is the check that makes that impossible.
    declared_paths(manifest)

    if materialize_placeholders:
        verdict["placeholders_created"] = materialize(manifest, media_dir)

    verdict["reconciliation"] = reconcile(manifest, plan, media_dir)
    verdict["stage"] = "compile"

    compiled = compile_plan(plan)
    if compiled["schema"] != PLAN_SCHEMA:
        raise HandoffError(f"the plan compiled to {compiled['schema']!r}, not {PLAN_SCHEMA!r}")
    verdict["plan"] = {
        "name": compiled["name"],
        "fps": compiled["fps"],
        "canvas": f"{compiled['width']}x{compiled['height']}",
        "duration_frames": compiled["duration_frames"],
        "clip_count": sum(len(track["clips"]) for track in compiled["tracks"]),
        "caption_count": len(compiled["captions"]),
        "subtitle_count": len(compiled["subtitles"]),
    }
    verdict["stage"] = "otio"

    verdict["interchange"] = portable_round_trip(compiled)
    verdict["stage"] = "dry-run"

    script = plan_to_actions(compiled, media_dir=str(media_dir), export=export)
    verdict["action_script"] = {
        "step_count": len(script["actions"]),
        "actions": [step["action"] for step in script["actions"]],
        "dispatched": False,
    }
    verdict["stage"] = "host-free complete"

    if dispatch:
        verdict["stage"] = "dispatch"
        from dcc_mcp_capcut.bridge import call_bridge

        result = call_bridge("apply_edit_plan", {"plan": compiled, "strategy": "auto"})
        verdict["dispatch"] = result
        verdict["stage"] = "complete"
    else:
        verdict["next"] = (
            "stage 6 (--dispatch) needs a bound CapCut host: run capcut-setup first, "
            "or see references/upstream-handoff.md for the macOS differences."
        )

    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--media-dir",
        type=Path,
        default=DEFAULT_DELIVERY,
        help="Delivery root holding asset-manifest.json and edit-plan.json.",
    )
    parser.add_argument(
        "--dispatch",
        action="store_true",
        help="Run stage 6: dispatch the plan to a bound CapCut host.",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Append an export_video step to the action script.",
    )
    parser.add_argument(
        "--no-materialize",
        action="store_true",
        help="Do not create placeholder files for declared-but-absent assets; "
        "report them as missing instead. Use this to validate a real delivery.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the verdict as JSON.")
    args = parser.parse_args(argv)

    media_dir: Path = args.media_dir
    if not media_dir.is_dir():
        print(f"delivery root not found: {media_dir}", file=sys.stderr)
        return 2

    try:
        verdict = run(
            media_dir,
            dispatch=args.dispatch,
            export=args.export,
            materialize_placeholders=not args.no_materialize,
        )
    except (HandoffError, ValueError) as exc:
        print(f"HANDOFF REJECTED: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(verdict, indent=2, ensure_ascii=False))
        return 0

    plan = verdict["plan"]
    recon = verdict["reconciliation"]
    inter = verdict["interchange"]
    script = verdict["action_script"]
    print(f"delivery root      : {verdict['media_dir']}")
    print(f"manifest schema    : {verdict['manifest_schema']}")
    print(f"declared / referenced assets : {recon['declared']} / {recon['referenced']}")
    if recon["unused"]:
        print(f"  unused (declared but not referenced): {', '.join(recon['unused'])}")
    for entry in recon["attribution"]:
        print(f"  attribution owed : {entry['path']} -- {entry['attribution']}")
    print(f"plan               : {plan['name']} ({plan['canvas']} @ {plan['fps']} fps)")
    print(
        f"                     {plan['clip_count']} clips, "
        f"{plan['caption_count']} captions, "
        f"{plan['subtitle_count']} subtitle files, "
        f"{plan['duration_frames']} frames"
    )
    print(
        f"otio round trip    : {inter['otio_bytes']} bytes, "
        f"{inter['restored_clips']} clips restored, "
        f"duration preserved: {inter['matches_duration']}"
    )
    if inter["dropped_by_otio"]:
        print(
            f"  dropped by otio  : {', '.join(inter['dropped_by_otio'])} "
            "(expected -- keep the plan document as the authoritative copy)"
        )
    print(f"action script      : {script['step_count']} steps, dispatched: {script['dispatched']}")
    print(f"  {' -> '.join(script['actions'])}")
    print(f"stage              : {verdict['stage']}")
    if "next" in verdict:
        print(f"next               : {verdict['next']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
