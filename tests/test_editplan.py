"""The canonical edit plan is one contract with one verdict.

Before this module existed, ``demo/vlog_recipe.json`` and ``docs/interchange.md``
were two plan formats with two rule sets: the shipped recipe placed two video
clips at ``0/4.5`` and ``4.2/8.0``, a 0.3 s overlap that ``validate_recipe.py``
accepted and ``export_otio`` rejected. These tests pin the property that fixes
it -- the same document gets the same verdict on every link -- and cover the
import/assembly direction the contract exists to serve.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from dcc_mcp_capcut.editplan import (
    PLAN_SCHEMA,
    VLOG_RECIPE_SCHEMA,
    compile_plan,
    compile_recipe,
    is_unsupported_action,
    normalize_plan,
    plan_from_otio,
    plan_to_actions,
    plan_to_edl,
    relative_media,
)
from dcc_mcp_capcut.interchange import export_otio

ROOT = Path(__file__).parents[1]

MEDIA_INDEX = {
    "earthrise": "assets/earthrise.mp4",
    "oahu_flyover": "assets/oahu_flyover.mp4",
    "free_music": "assets/free_ambient.wav",
}


def load_shipped_recipe() -> dict:
    return json.loads((ROOT / "demo" / "vlog_recipe.json").read_text(encoding="utf-8"))


def portable_core(plan: dict) -> dict:
    """The plan minus the advisory fields no portable format can carry."""
    core = copy.deepcopy(plan)
    for track in core["tracks"]:
        for clip in track["clips"]:
            clip.pop("audio", None)
    for caption in core["captions"]:
        caption.pop("style", None)
    return core


def proven(plan: dict) -> dict:
    """Fill ``media_duration`` so the OTIO link can prove every source bound."""
    plan = copy.deepcopy(plan)
    for track in plan["tracks"]:
        for clip in track["clips"]:
            clip["media_duration"] = clip["source_in"] + clip["duration"]
    return plan


@pytest.fixture
def recipe() -> dict:
    return load_shipped_recipe()


@pytest.fixture
def plan() -> dict:
    """A small canonical plan with two picture clips, music and two captions."""
    return {
        "schema": PLAN_SCHEMA,
        "name": "地球 / Earth",
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "duration_frames": 300,
        "tracks": [
            {
                "name": "Picture",
                "kind": "Video",
                "clips": [
                    {
                        "name": "opening",
                        "media": "media/opening.mp4",
                        "start": 0,
                        "source_in": 0,
                        "duration": 120,
                        "media_duration": 200,
                    },
                    {
                        "name": "second",
                        "media": "media/second.mp4",
                        "start": 150,
                        "source_in": 10,
                        "duration": 150,
                        "media_duration": 400,
                    },
                ],
            },
            {
                "name": "Music",
                "kind": "Audio",
                "clips": [
                    {
                        "name": "bed",
                        "media": "media/bed.wav",
                        "start": 0,
                        "source_in": 0,
                        "duration": 300,
                        "media_duration": 300,
                        "audio": {"volume": 0.22, "fade_in": 0.8, "fade_out": 1.2},
                    }
                ],
            },
        ],
        "captions": [
            {"text": "共同的家", "start": 20, "duration": 60},
            {"text": "我们的位置", "start": 160, "duration": 90, "style": {"size": 48}},
        ],
    }


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------


def test_shipped_recipe_compiles_to_the_canonical_schema(recipe):
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)

    assert plan["schema"] == PLAN_SCHEMA
    assert plan["name"] == recipe["project_name"]
    assert plan["fps"] == 30
    # 9:16 from the recipe's aspect ratio.
    assert (plan["width"], plan["height"]) == (1080, 1920)
    # 4.5 s + 8.0 s at 30 fps.
    assert plan["duration_frames"] == 375
    assert [track["name"] for track in plan["tracks"]] == ["Picture", "Music"]
    assert [track["kind"] for track in plan["tracks"]] == ["Video", "Audio"]
    assert [clip["start"] for clip in plan["tracks"][0]["clips"]] == [0, 135]
    assert [clip["duration"] for clip in plan["tracks"][0]["clips"]] == [135, 240]


def test_recipe_paths_are_normalized_to_the_portable_form(recipe):
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)
    media = {clip["media"] for track in plan["tracks"] for clip in track["clips"]}
    # The recipe writes './assets/earthrise.mp4'; the plan stores the clean
    # relative path the OTIO link accepts.
    assert media == {
        "assets/earthrise.mp4",
        "assets/oahu_flyover.mp4",
        "assets/free_ambient.wav",
    }


def test_music_bed_spans_the_cut_and_keeps_its_advisory_mix(recipe):
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)
    music = plan["tracks"][1]["clips"][0]

    assert music["media"] == "assets/free_ambient.wav"
    assert music["start"] == 0
    assert music["duration"] == plan["duration_frames"]
    assert music["audio"] == {"volume": 0.22, "fade_in": 0.8, "fade_out": 1.2}


def test_recipe_captions_and_subtitle_survive_compilation(recipe):
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)

    assert [caption["start"] for caption in plan["captions"]] == [18, 72, 150, 225, 306]
    assert plan["captions"][0]["style"]["size"] == 48
    assert plan["subtitle"] == {"file": "galaxy_zh.srt"}
    assert plan["output"] == {"path": "./output/free-travel-vlog.mp4", "aspect_ratio": "9:16"}


def test_plan_shape_and_recipe_shape_are_discriminated(recipe, plan):
    assert compile_plan(plan)["schema"] == PLAN_SCHEMA

    with pytest.raises(ValueError, match="either 'tracks' .* or 'media'"):
        compile_plan({"name": "neither"})
    with pytest.raises(ValueError, match="either 'tracks' .* or 'media'"):
        compile_plan({**plan, "media": []})


def test_declared_schema_must_match_the_document_shape(recipe, plan):
    with pytest.raises(ValueError, match="unsupported recipe schema"):
        compile_recipe({**recipe, "schema": PLAN_SCHEMA})
    with pytest.raises(ValueError, match="unsupported plan schema"):
        normalize_plan({**plan, "schema": VLOG_RECIPE_SCHEMA})


def test_id_only_entries_need_a_media_index(recipe):
    with pytest.raises(ValueError, match="media_index"):
        compile_plan(recipe)


# ---------------------------------------------------------------------------
# One verdict on every link
# ---------------------------------------------------------------------------


def test_the_shipped_recipe_no_longer_overlaps(recipe):
    """The 0.3 s overlap that split the two rule sets is gone from the demo."""
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)
    picture = plan["tracks"][0]["clips"]
    ends = [clip["start"] + clip["duration"] for clip in picture]

    assert ends[0] <= picture[1]["start"]


def test_overlap_is_rejected_identically_on_the_offline_links(plan):
    overlapping = copy.deepcopy(plan)
    overlapping["tracks"][0]["clips"][1]["start"] = 100

    with pytest.raises(ValueError, match="overlap"):
        normalize_plan(overlapping)
    with pytest.raises(ValueError, match="overlap"):
        plan_to_edl(overlapping)
    with pytest.raises(ValueError, match="overlap"):
        plan_to_actions(overlapping)


def test_the_recipe_overlap_both_formats_used_to_disagree_on(recipe):
    """0/4.5 against 4.2/8.0: accepted by the old validator, rejected now."""
    overlapping = load_shipped_recipe()
    overlapping["media"][1]["start"] = 4.2

    with pytest.raises(ValueError, match="overlap at frame 126"):
        compile_plan(overlapping, media_index=MEDIA_INDEX)


def test_bounds_verdict_is_identical_on_every_link(plan):
    out_of_bounds = copy.deepcopy(plan)
    out_of_bounds["tracks"][0]["clips"][1]["duration"] = 200

    with pytest.raises(ValueError, match="exceeds timeline duration"):
        normalize_plan(out_of_bounds)
    with pytest.raises(ValueError, match="exceeds timeline duration"):
        plan_to_edl(out_of_bounds)
    with pytest.raises(ValueError, match="exceeds timeline duration"):
        plan_to_actions(out_of_bounds)


def test_source_trim_bounds_are_checked(plan):
    over_trimmed = copy.deepcopy(plan)
    over_trimmed["tracks"][0]["clips"][1]["source_in"] = 380

    with pytest.raises(ValueError, match="exceeds media duration"):
        normalize_plan(over_trimmed)
    with pytest.raises(ValueError, match="exceeds media duration"):
        plan_to_edl(over_trimmed)


def test_caption_bounds_are_checked(plan):
    extended = copy.deepcopy(plan)
    extended["captions"][1]["duration"] = 200

    with pytest.raises(ValueError, match="caption exceeds timeline duration"):
        normalize_plan(extended)


def test_audio_level_is_bounded_like_the_host_tool_schema(recipe):
    """set_audio_volume caps volume at 4; catch an out-of-range level at compile time."""
    loud = json.loads(json.dumps(recipe))
    loud["music"]["volume"] = 8

    with pytest.raises(ValueError, match="music volume must be <= 4.0"):
        compile_plan(loud, media_index=MEDIA_INDEX)

    recipe["music"]["volume"] = 4.0
    assert (
        compile_plan(recipe, media_index=MEDIA_INDEX)["tracks"][1]["clips"][0]["audio"]["volume"]
        == 4.0
    )


def test_media_path_rule_is_shared_with_the_otio_exporter(plan):
    """Traversal, absolute and URL forms fail on both links, not just one."""
    for bad in ("../a.mp4", "/a.mp4", "https://host/a.mp4", "media/%2e%2e/a.mp4"):
        broken = copy.deepcopy(plan)
        broken["tracks"][0]["clips"][0]["media"] = bad
        with pytest.raises(ValueError, match="media must be a portable relative path"):
            normalize_plan(broken)
        with pytest.raises(ValueError, match="media must be a portable relative path"):
            export_otio(plan_to_edl(broken))

    assert relative_media("media/shot 01.mp4") == "media/shot 01.mp4"


def test_a_plan_that_compiles_exports_without_a_second_verdict(plan):
    """The export link cannot reject what the contract already accepted."""
    receipt = export_otio(plan_to_edl(plan))

    assert receipt["duration_frames"] == 300
    assert receipt["clip_count"] == 3
    assert receipt["media_paths"] == ["media/bed.wav", "media/opening.mp4", "media/second.mp4"]


def test_plan_to_edl_strips_advisory_fields_instead_of_guessing(plan):
    edl = plan_to_edl(plan)

    assert "audio" not in edl["tracks"][1]["clips"][0]
    assert "style" not in edl["captions"][1]
    # The portable core is untouched.
    assert edl["tracks"][0]["clips"][1]["source_in"] == 10


def test_plan_to_edl_refuses_to_claim_bounds_it_cannot_prove(recipe):
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)

    with pytest.raises(ValueError, match="no media_duration"):
        plan_to_edl(plan)

    assert plan_to_edl(proven(plan))["tracks"][0]["clips"][0]["media_duration"] == 135


# ---------------------------------------------------------------------------
# Assembly direction
# ---------------------------------------------------------------------------


def test_plan_to_actions_is_deterministic_and_ordered(plan):
    script = plan_to_actions(plan)

    assert script["media"] == {
        "m0": "media/opening.mp4",
        "m1": "media/second.mp4",
        "m2": "media/bed.wav",
    }
    # Captions go out as add_text steps, so there is no subtitle file here.
    assert script["referenced"] == ["media/opening.mp4", "media/second.mp4", "media/bed.wav"]
    # One import per file: the host contract only guarantees a single
    # media_id per call, so a multi-path import could not be mapped back.
    assert [step["action"] for step in script["actions"]] == [
        "import_media",
        "import_media",
        "import_media",
        "create_timeline",
        "add_clip",
        "add_clip",
        "add_clip",
        "set_audio_volume",
        "add_audio_fade",
        "add_text",
        "add_text",
        "save_project",
    ]
    assert script == plan_to_actions(plan)


def test_action_params_carry_frames_as_seconds_and_resolvable_ids(plan):
    steps = plan_to_actions(plan)["actions"]
    second = [step for step in steps if step["action"] == "add_clip"][1]

    assert second["params"] == {
        "media_id": "$media:m1",
        "timeline_id": "$timeline",
        "track_type": "video",
        "start": 5.0,
        "source_in": 0.333333,
        "source_out": 5.333333,
    }
    # 10 frames in, 150 frames long, at 30 fps.
    assert second["params"]["source_out"] - second["params"]["source_in"] == pytest.approx(5.0)


def test_second_picture_track_becomes_an_overlay(plan):
    overlay_plan = copy.deepcopy(plan)
    overlay_plan["tracks"].insert(
        1,
        {
            "name": "Overlay",
            "kind": "Video",
            "clips": [
                {
                    "name": "title",
                    "media": "media/title.png",
                    "start": 0,
                    "duration": 60,
                    "media_duration": 60,
                }
            ],
        },
    )
    steps = plan_to_actions(overlay_plan)["actions"]
    add_clips = [step for step in steps if step["action"] == "add_clip"]

    # Steps are ordered by track, so the base picture track is filled first and
    # the overlay track's clip follows it.
    assert [step["params"]["track_type"] for step in add_clips] == [
        "video",
        "video",
        "overlay",
        "audio",
    ]


def test_subtitle_file_replaces_per_caption_text_steps(recipe):
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)
    steps = plan_to_actions(plan)["actions"]
    import_subtitles = [step for step in steps if step["action"] == "import_subtitles"]

    assert len(import_subtitles) == 1
    assert import_subtitles[0]["params"]["path"] == "galaxy_zh.srt"
    assert not [step for step in steps if step["action"] == "add_text"]

    captions_only = copy.deepcopy(plan)
    del captions_only["subtitle"]
    assert (
        len([s for s in plan_to_actions(captions_only)["actions"] if s["action"] == "add_text"])
        == 5
    )


def test_media_dir_is_checked_before_any_dispatch(plan, tmp_path):
    (tmp_path / "media").mkdir()
    for name in ("opening.mp4", "second.mp4", "bed.wav"):
        (tmp_path / "media" / name).write_bytes(b"")

    script = plan_to_actions(plan, media_dir=str(tmp_path))
    assert [step["action"] for step in script["actions"]][0] == "import_media"
    imports = [step for step in script["actions"] if step["action"] == "import_media"]
    assert [step["params"]["paths"][0] for step in imports] == [
        str(tmp_path / "media" / "opening.mp4"),
        str(tmp_path / "media" / "second.mp4"),
        str(tmp_path / "media" / "bed.wav"),
    ]
    assert [step["media_ref"] for step in imports] == ["m0", "m1", "m2"]
    assert [
        step["params"]["paths"][0]
        for step in plan_to_actions(plan)["actions"]
        if step["action"] == "import_media"
    ] == ["media/opening.mp4", "media/second.mp4", "media/bed.wav"]

    (tmp_path / "media" / "bed.wav").unlink()
    with pytest.raises(ValueError, match="does not contain every referenced file:"):
        plan_to_actions(plan, media_dir=str(tmp_path))


def test_a_missing_subtitle_file_is_checked_with_the_media(recipe, tmp_path):
    """The subtitle is handed to the host as a path, so it is a referenced file.

    Checking it alongside the media is what keeps "every referenced file must
    exist" true before the first dispatch, rather than failing at
    ``import_subtitles`` once the timeline is already populated.
    """
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)
    (tmp_path / "assets").mkdir()
    for name in ("earthrise.mp4", "oahu_flyover.mp4", "free_ambient.wav"):
        (tmp_path / "assets" / name).write_bytes(b"")

    with pytest.raises(ValueError, match="does not contain every referenced file:") as caught:
        plan_to_actions(plan, media_dir=str(tmp_path))
    assert "galaxy_zh.srt" in str(caught.value)

    (tmp_path / "galaxy_zh.srt").write_bytes(b"")
    steps = plan_to_actions(plan, media_dir=str(tmp_path))["actions"]
    assert [step for step in steps if step["action"] == "import_subtitles"][0]["params"][
        "path"
    ] == str(tmp_path / "galaxy_zh.srt")


def test_subtitle_file_must_be_a_portable_relative_path(plan):
    """The existence check is not a substitute for the path rule.

    ``plan_to_actions`` resolves the subtitle with ``Path(media_dir) / file`` and
    pathlib keeps an absolute path as-is, so an absolute value would escape the
    delivery root entirely -- and the recipe entry point already rejects that
    same value. One field, one verdict: the recipe side goes through
    ``relative_media``, so this side has to as well.
    """
    for bad in (
        "C:/Windows/win.ini",
        "/etc/hostname",
        "../secrets.srt",
        "https://host/subs.srt",
        "subs/%2e%2e/secrets.srt",
    ):
        broken = copy.deepcopy(plan)
        broken["subtitle"] = {"file": bad}
        with pytest.raises(ValueError, match="media must be a portable relative path"):
            normalize_plan(broken)

    broken = copy.deepcopy(plan)
    broken["subtitle"] = {"file": "galaxy_zh.srt"}
    assert normalize_plan(broken)["subtitle"]["file"] == "galaxy_zh.srt"


def test_subtitle_cannot_escape_the_delivery_root(plan, tmp_path):
    """End to end: an absolute subtitle can no longer reach the host."""
    (tmp_path / "media").mkdir()
    for name in ("opening.mp4", "second.mp4", "bed.wav"):
        (tmp_path / "media" / name).write_bytes(b"")
    (tmp_path / "galaxy_zh.srt").write_bytes(b"")

    with_subtitles = copy.deepcopy(plan)
    with_subtitles["subtitle"] = {"file": "galaxy_zh.srt"}
    steps = plan_to_actions(with_subtitles, media_dir=str(tmp_path))["actions"]
    assert [step for step in steps if step["action"] == "import_subtitles"][0]["params"][
        "path"
    ] == str(tmp_path / "galaxy_zh.srt")

    escaped = copy.deepcopy(plan)
    escaped["subtitle"] = {"file": "C:/Windows/win.ini"}
    with pytest.raises(ValueError, match="media must be a portable relative path"):
        plan_to_actions(escaped, media_dir=str(tmp_path))


def test_the_real_demo_directory_matches_the_documented_layout():
    """Guard the repo layout the README and ADR instruct, without downloading.

    The delivery root is ``demo/`` because the plan's portable paths are
    ``assets/<media>`` and ``galaxy_zh.srt``. This asserts those pieces exist in
    the repo as checked in, so a layout change cannot silently break the hand-off.
    """
    demo = ROOT / "demo"
    assert (demo / "galaxy_zh.srt").is_file(), "the subtitle the recipe references is gone"
    assert (demo / "vlog_recipe.json").is_file()
    assert (demo / "assets.json").is_file()

    catalog = json.loads((demo / "assets.json").read_text(encoding="utf-8"))
    for asset in catalog["assets"]:
        assert asset["local_path"].startswith("assets/"), (
            f"{asset['id']} escaped the delivery root; media_dir=demo would no longer "
            f"resolve it: {asset['local_path']}"
        )


def test_referenced_lists_every_file_a_dispatch_needs(recipe):
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)

    assert plan_to_actions(plan)["referenced"] == [
        "assets/earthrise.mp4",
        "assets/oahu_flyover.mp4",
        "assets/free_ambient.wav",
        "galaxy_zh.srt",
    ]


def test_export_step_requires_an_output_path(plan):
    with pytest.raises(ValueError, match="export=True requires output.path"):
        plan_to_actions(plan, export=True)

    with_output = copy.deepcopy(plan)
    with_output["output"] = {"path": "out/vlog.mp4"}
    steps = plan_to_actions(with_output, export=True)["actions"]

    assert [step["action"] for step in steps][-2:] == ["export_video", "save_project"]
    assert steps[-2]["params"]["output_path"] == "out/vlog.mp4"


def test_only_a_rejection_naming_this_action_means_fall_back():
    """Both the marker and the action name are required.

    A marker alone would turn an unrelated host error into a fallback that
    replays the plan as a composed script over a timeline the batch action may
    have already partly assembled.
    """
    assert is_unsupported_action(RuntimeError("Unsupported action: apply_edit_plan"))
    assert is_unsupported_action(RuntimeError('{"unsupported_action": "apply_edit_plan"}'))

    # Marker present, but not about this action -- or not a marker at all.
    assert not is_unsupported_action(RuntimeError("unsupported action parameter: media_dir"))
    assert not is_unsupported_action(RuntimeError("unknown action field: media_dir"))
    assert not is_unsupported_action(RuntimeError("Unsupported action: add_clip"))
    assert not is_unsupported_action(RuntimeError("CapCut host API is unavailable"))
    assert not is_unsupported_action(RuntimeError("verification.ok was not true"))

    # The check is scoped to the action being dispatched.
    assert is_unsupported_action(RuntimeError("Unsupported action: add_clip"), "add_clip")
    assert not is_unsupported_action(
        RuntimeError("Unsupported action: add_clip"), "apply_edit_plan"
    )


# ---------------------------------------------------------------------------
# OTIO import: closing the round trip
# ---------------------------------------------------------------------------


def test_otio_round_trip_preserves_the_portable_core(plan):
    receipt = export_otio(plan_to_edl(plan))
    restored = plan_from_otio(receipt["otio_json"])

    assert restored["name"] == plan["name"]
    assert restored["fps"] == plan["fps"]
    assert (restored["width"], restored["height"]) == (plan["width"], plan["height"])
    assert restored["duration_frames"] == plan["duration_frames"]
    assert restored["tracks"] == portable_core(plan)["tracks"]


def test_otio_round_trip_reports_advisory_loss_explicitly(plan):
    """Volume, fades and text style have no OTIO home; they are dropped, not faked."""
    restored = plan_from_otio(export_otio(plan_to_edl(plan))["otio_json"])

    assert "audio" not in restored["tracks"][1]["clips"][0]
    assert "style" not in restored["captions"][1]
    assert [caption["text"] for caption in restored["captions"]] == [
        caption["text"] for caption in plan["captions"]
    ]


def test_otio_import_reads_an_otio_file(plan, tmp_path):
    otio_path = tmp_path / "timeline.otio"
    otio_path.write_text(export_otio(plan_to_edl(plan))["otio_json"], encoding="utf-8")

    assert plan_from_otio(str(otio_path))["tracks"] == portable_core(plan)["tracks"]


def test_foreign_otio_needs_explicit_canvas(plan):
    receipt = export_otio(plan_to_edl(plan))
    payload = json.loads(receipt["otio_json"])
    payload["metadata"]["dcc_mcp_capcut"] = {}
    foreign = json.dumps(payload)

    with pytest.raises(ValueError, match="no dcc_mcp_capcut canvas metadata"):
        plan_from_otio(foreign)

    restored = plan_from_otio(foreign, width=1080, height=1920, fps=30)
    assert (restored["width"], restored["height"]) == (1080, 1920)


def test_otio_import_needs_the_interchange_extra(plan, monkeypatch):
    receipt = export_otio(plan_to_edl(plan))
    monkeypatch.setitem(sys.modules, "opentimelineio", None)

    with pytest.raises(RuntimeError, match=r"\[interchange\]"):
        plan_from_otio(receipt["otio_json"])


# ---------------------------------------------------------------------------
# The demo consumes the same contract
# ---------------------------------------------------------------------------


def test_the_demo_resolves_against_demo_as_the_delivery_root(tmp_path):
    """The documented hand-off must actually resolve.

    The plan's portable paths are ``assets/<media>`` and ``galaxy_zh.srt``, so the
    delivery root is ``demo/`` -- not ``demo/assets/``, which would look for
    ``demo/assets/assets/...``. This guards the exact instruction the README and
    ADR give for the live acceptance run.
    """
    plan = compile_plan(load_shipped_recipe(), media_index=MEDIA_INDEX)
    root = tmp_path / "demo"
    (root / "assets").mkdir(parents=True)
    for name in ("earthrise.mp4", "oahu_flyover.mp4", "free_ambient.wav"):
        (root / "assets" / name).write_bytes(b"")
    (root / "galaxy_zh.srt").write_bytes(b"")

    steps = plan_to_actions(plan, media_dir=str(root))["actions"]
    assert [step for step in steps if step["action"] == "import_subtitles"][0]["params"][
        "path"
    ] == str(root / "galaxy_zh.srt")

    with pytest.raises(ValueError, match="does not contain every referenced file"):
        plan_to_actions(plan, media_dir=str(root / "assets"))


def test_shipped_demo_assets_declare_their_local_paths():
    assets = json.loads((ROOT / "demo" / "assets.json").read_text(encoding="utf-8"))
    index = {asset["id"]: asset["local_path"] for asset in assets["assets"]}

    assert index == MEDIA_INDEX


def load_demo_module(name: str):
    path = ROOT / "demo" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"demo_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_validator_reports_the_canonical_plan():
    """``demo-contract`` in CI runs this, so it must not need any extra."""
    validate_recipe = load_demo_module("validate_recipe")

    summary = validate_recipe.validate(str(ROOT / "demo" / "vlog_recipe.json"))

    assert summary["schema"] == PLAN_SCHEMA
    assert summary["duration"] == 12.5
    assert summary["clip_count"] == 3
    assert summary["caption_count"] == 5
    assert summary["action_count"] > 1


def test_demo_validator_rejects_the_overlap_the_old_one_accepted(capsys):
    validate_recipe = load_demo_module("validate_recipe")
    overlapping = load_shipped_recipe()
    overlapping["media"][1]["start"] = 4.2
    path = ROOT / "demo" / "overlapping.tmp.json"
    path.write_text(json.dumps(overlapping, ensure_ascii=False), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="overlap"):
            validate_recipe.validate(str(path))
    finally:
        path.unlink()


def test_offline_renderer_builds_its_filter_from_the_plan(recipe):
    render_vlog = load_demo_module("render_vlog")
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)

    video_filter = render_vlog.build_filter(plan, font_option="")

    # One chain per picture clip, and every caption drawn inside the clip that
    # covers it, at clip-local times.
    assert video_filter.count("[0:v]trim") == 1
    assert video_filter.count("[1:v]trim") == 1
    assert video_filter.count("drawtext=") == 5
    assert "enable='between(t,0.6,2.3)'" in video_filter
    # 5.0 s absolute on a clip that starts at 4.5 s is 0.5 s local.
    assert "enable='between(t,0.5,2.8)'" in video_filter
    assert video_filter.endswith("[v0][v1]concat=n=2:v=1:a=0[v]")
    assert video_filter == render_vlog.build_filter(plan, font_option="")


def test_offline_renderer_music_mix_comes_from_the_plan(recipe):
    render_vlog = load_demo_module("render_vlog")
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)
    music = plan["tracks"][1]["clips"][0]

    assert render_vlog.duration_seconds(plan) == 12.5
    assert music["audio"]["volume"] == 0.22
