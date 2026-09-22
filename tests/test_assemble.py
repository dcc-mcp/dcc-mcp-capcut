"""The assembly direction: one plan plus a media directory becomes a project.

The host is not reachable from CI, so these tests pin the part that *is*
provable offline: the plan is validated and lowered host-free, ``dry_run`` never
touches the bridge, a host that implements the batch action gets one call, a
host that rejects it as unsupported gets the composed walk, and a part-way
failure is reported with the steps it already applied instead of a bare
"something went wrong".

``@skill_entry`` never raises -- it converts every exception into a failure
envelope -- so failures are asserted through the envelope, exactly as a caller
would see them.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from dcc_mcp_capcut.editplan import PLAN_SCHEMA, compile_plan

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "src" / "dcc_mcp_capcut" / "skills" / "capcut-assemble" / "scripts"

MEDIA_INDEX = {
    "earthrise": "assets/earthrise.mp4",
    "oahu_flyover": "assets/oahu_flyover.mp4",
    "free_music": "assets/free_ambient.wav",
}

TIMELINE = {"tracks": 2, "duration": 12.5}


def load_skill():
    spec = importlib.util.spec_from_file_location("apply_edit_plan", SCRIPT / "apply_edit_plan.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def skill(monkeypatch):
    """The skill script with ``call_bridge`` routed at a recording fake."""
    module = load_skill()
    calls: list[tuple[str, dict]] = []
    behaviour: dict[str, object] = {}

    def fake_call_bridge(action, params, **_kwargs):
        calls.append((action, params))
        handler = behaviour.get("handle")
        if handler is None:
            raise AssertionError("no host behaviour configured")
        return handler(action, params)

    monkeypatch.setattr(module, "call_bridge", fake_call_bridge)
    module.calls = calls
    module.respond = lambda handler: behaviour.__setitem__("handle", handler)
    return module


@pytest.fixture
def media_dir(tmp_path):
    """A delivery root holding every file the shipped recipe references.

    That includes the subtitle file: the plan hands it to the host as a path,
    so it is a referenced file exactly like the media is. Demo
    ``fetch_assets.py`` stages it for the same reason.
    """
    (tmp_path / "assets").mkdir()
    for name in ("earthrise.mp4", "oahu_flyover.mp4", "free_ambient.wav"):
        (tmp_path / "assets" / name).write_bytes(b"\x00")
    (tmp_path / "galaxy_zh.srt").write_bytes(b"\x00")
    return tmp_path


@pytest.fixture
def recipe():
    return json.loads((ROOT / "demo" / "vlog_recipe.json").read_text(encoding="utf-8"))


def ok(result):
    """The skill's own context block from a successful envelope."""
    assert result["success"] is True, result
    return result["context"]


def failed(result):
    """Assert the envelope is a failure and return its searchable text."""
    assert result["success"] is False, result
    return result["message"] + result.get("context", {}).get("traceback", "")


def host_result(**extra):
    return {"verification": {"ok": True, "timeline": TIMELINE}, **extra}


def batch_host(skill):
    """A host that implements the batch action: one call, one receipt."""

    def handle(action, params):
        assert action == "apply_edit_plan", f"unexpected action {action}"
        return host_result(timeline_id="tl-1")

    skill.respond(handle)


def composed_host(skill):
    """A host that only supports the existing single-shot actions."""

    def handle(action, params):
        if action == "apply_edit_plan":
            raise RuntimeError("Unsupported action: apply_edit_plan")
        if action == "import_media":
            return host_result(media_id=f"m-{len(skill.calls) - 1}")
        if action == "create_timeline":
            return host_result(timeline_id="tl-2")
        if action == "add_clip":
            return host_result(clip_id=f"clip-{len(skill.calls)}")
        if action == "import_subtitles":
            return host_result(caption_ids=["cap-1", "cap-2"])
        return host_result()

    skill.respond(handle)


# ---------------------------------------------------------------------------
# Host-free validation
# ---------------------------------------------------------------------------


def test_dry_run_never_reaches_the_bridge(skill, recipe, media_dir):
    skill.respond(lambda action, params: (_ for _ in ()).throw(AssertionError("bridge called")))

    context = ok(
        skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir), dry_run=True)
    )

    assert skill.calls == []
    assert context["dispatched"] is False
    assert context["strategy"] == "none"
    assert context["schema"] == PLAN_SCHEMA
    assert context["plan"]["duration_frames"] == 375
    assert [step["action"] for step in context["script"]["actions"]][:5] == [
        "import_media",
        "import_media",
        "import_media",
        "create_timeline",
        "add_clip",
    ]


def test_dry_run_still_enforces_the_shared_verdict(skill, recipe, media_dir):
    overlapping = json.loads(json.dumps(recipe))
    overlapping["media"][1]["start"] = 4.2

    assert "overlap" in failed(
        skill.main(recipe=overlapping, media_index=MEDIA_INDEX, dry_run=True)
    )
    assert skill.calls == []


def test_missing_media_blocks_dispatch_before_any_mutation(skill, recipe, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "earthrise.mp4").write_bytes(b"\x00")

    assert "does not contain every referenced file" in failed(
        skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(tmp_path))
    )
    assert skill.calls == []


def test_a_missing_subtitle_file_fails_before_any_dispatch(skill, recipe, media_dir):
    """The subtitle is a referenced file too.

    A plan that names one resolves it against ``media_dir`` and hands the path
    to the host, so it has to be checked with the media. Otherwise the run fails
    at ``import_subtitles`` -- after the imports, the timeline and every clip
    have already mutated the host.
    """
    (Path(media_dir) / "galaxy_zh.srt").unlink()

    assert "does not contain every referenced file" in failed(
        skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir))
    )
    assert "galaxy_zh.srt" in failed(
        skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir))
    )
    assert skill.calls == []


def test_dry_run_reports_every_referenced_file(skill, recipe, media_dir):
    context = ok(
        skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir), dry_run=True)
    )

    assert context["script"]["referenced"] == [
        "assets/earthrise.mp4",
        "assets/oahu_flyover.mp4",
        "assets/free_ambient.wav",
        "galaxy_zh.srt",
    ]


def test_media_dir_is_required_unless_dry_run(skill, recipe):
    assert "media_dir is required" in failed(skill.main(recipe=recipe, media_index=MEDIA_INDEX))


def test_plan_and_recipe_are_mutually_exclusive(skill, recipe):
    plan = compile_plan(recipe, media_index=MEDIA_INDEX)

    assert "exactly one of 'plan' or 'recipe'" in failed(
        skill.main(plan=plan, recipe=recipe, dry_run=True)
    )
    assert "either 'plan'" in failed(skill.main(dry_run=True))


def test_unknown_strategy_is_rejected(skill, recipe, media_dir):
    assert "strategy must be one of" in failed(
        skill.main(
            recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir), strategy="whatever"
        )
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_a_host_echoing_the_payload_does_not_break_the_result(skill, recipe, media_dir):
    """The host receipt must not be spread straight into the tool result.

    A host is free to echo back the ``plan`` or ``script`` it received. Those are
    also keys in the adapter's own summary, so spreading the receipt would raise
    ``TypeError: got multiple values for keyword argument`` and return a failure
    envelope for an assembly that actually succeeded. Latent today: ``auto`` only
    reaches this branch once a host implements the batch action.
    """

    def handle(action, params):
        assert action == "apply_edit_plan"
        return host_result(
            timeline_id="tl-7",
            plan=params["plan"],
            script=params["script"],
            echoed="anything",
        )

    skill.respond(handle)

    context = ok(skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir)))

    assert context["strategy"] == "host"
    assert context["timeline_id"] == "tl-7"
    assert context["verification"]["ok"] is True
    # The adapter's own keys survive, and the full receipt is still reachable.
    assert context["plan"]["duration_frames"] == 375
    assert context["host_result"]["echoed"] == "anything"


def test_marker_alone_does_not_trigger_a_fallback(skill, recipe, media_dir):
    """Only a rejection naming *this* action means "not implemented".

    A bare marker is a real failure: falling back would replay the whole plan as
    a composed script over a timeline the batch action may already have partly
    assembled, and the composed walk does not roll back.
    """
    for message in (
        "unsupported action parameter: media_dir",
        "unknown action field: media_dir",
        "Unsupported action: add_clip",
        "CapCut host API is unavailable",
    ):
        skill.calls.clear()

        def handle(action, params, message=message):
            raise RuntimeError(message)

        skill.respond(handle)
        assert message in failed(
            skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir))
        ), message
        # Never retried as a composed script: only the batch probe was attempted.
        assert [action for action, _ in skill.calls] == ["apply_edit_plan"], message


def test_host_batch_action_is_one_round_trip(skill, recipe, media_dir):
    batch_host(skill)

    context = ok(skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir)))

    assert [action for action, _ in skill.calls] == ["apply_edit_plan"]
    assert context["strategy"] == "host"
    assert context["dispatched"] is True
    assert context["timeline_id"] == "tl-1"
    assert context["verification"]["timeline"] == TIMELINE
    # The host receives the whole plan plus the script it can execute directly.
    body = skill.calls[0][1]
    assert body["plan"]["schema"] == PLAN_SCHEMA
    assert body["media_dir"] == str(media_dir)
    assert body["script"]["actions"][0]["action"] == "import_media"


def test_unsupported_batch_action_falls_back_to_the_composed_walk(skill, recipe, media_dir):
    composed_host(skill)

    context = ok(skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir)))

    assert [action for action, _ in skill.calls] == [
        "apply_edit_plan",
        "import_media",
        "import_media",
        "import_media",
        "create_timeline",
        "add_clip",
        "add_clip",
        "add_clip",
        "set_audio_volume",
        "add_audio_fade",
        "import_subtitles",
        "save_project",
    ]
    assert context["strategy"] == "composed"
    assert context["fallback_reason"] == "Unsupported action: apply_edit_plan"
    assert context["timeline_id"] == "tl-2"
    assert context["verification"]["ok"] is True
    # Every mutating step returns the readback; the last one is kept.
    assert context["verification"]["readback_from"] == "save_project"


def test_composed_walk_binds_host_ids_into_later_steps(skill, recipe, media_dir):
    composed_host(skill)

    ok(skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir)))
    imports = [(action, params) for action, params in skill.calls if action == "import_media"]

    # One file per import step, at the paths the plan records.
    assert [params["paths"][0] for _, params in imports] == [
        str(Path(media_dir) / "assets" / "earthrise.mp4"),
        str(Path(media_dir) / "assets" / "oahu_flyover.mp4"),
        str(Path(media_dir) / "assets" / "free_ambient.wav"),
    ]
    add_clips = [params for action, params in skill.calls if action == "add_clip"]
    # Each import's returned media_id is bound to the clip that uses it.
    assert [params["media_id"] for params in add_clips] == ["m-1", "m-2", "m-3"]
    assert {params["timeline_id"] for params in add_clips} == {"tl-2"}
    # Audio presentation targets the clip the music bed was placed as.
    by_action = {action: params for action, params in skill.calls}
    assert by_action["set_audio_volume"]["clip_id"].startswith("clip-")
    assert by_action["add_audio_fade"]["clip_id"] == by_action["set_audio_volume"]["clip_id"]
    assert by_action["import_subtitles"]["path"] == str(Path(media_dir) / "galaxy_zh.srt")


def test_composed_strategy_skips_the_batch_probe(skill, recipe, media_dir):
    composed_host(skill)

    context = ok(
        skill.main(
            recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir), strategy="composed"
        )
    )

    assert "apply_edit_plan" not in [action for action, _ in skill.calls]
    assert context["strategy"] == "composed"
    assert context["fallback_reason"] is None


def test_host_strategy_refuses_to_fall_back(skill, recipe, media_dir):
    composed_host(skill)

    assert "Unsupported action: apply_edit_plan" in failed(
        skill.main(
            recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir), strategy="host"
        )
    )
    assert [action for action, _ in skill.calls] == ["apply_edit_plan"]


def test_a_real_host_failure_is_never_retried_as_a_composed_walk(skill, recipe, media_dir):
    def handle(action, params):
        raise RuntimeError("CapCut host API is unavailable")

    skill.respond(handle)

    assert "CapCut host API is unavailable" in failed(
        skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir))
    )
    assert [action for action, _ in skill.calls] == ["apply_edit_plan"]


def test_a_batch_action_without_proof_is_not_accepted(skill, recipe, media_dir):
    """A bare acknowledgement is an error, per the fail-closed contract."""
    skill.respond(lambda action, params: {"verification": {"ok": False}})

    assert "verified post-operation readback" in failed(
        skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir))
    )


def test_partial_failure_names_the_step_and_what_was_applied(skill, recipe, media_dir):
    def handle(action, params):
        if action == "apply_edit_plan":
            raise RuntimeError("Unsupported action: apply_edit_plan")
        if action == "add_clip":
            raise RuntimeError("host rejected the clip")
        if action == "import_media":
            return host_result(media_id=f"m-{len(skill.calls) - 1}")
        if action == "create_timeline":
            return host_result(timeline_id="tl-3")
        return host_result()

    skill.respond(handle)

    message = failed(skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir)))

    assert "stopped at step 4 (add_clip)" in message
    assert "['import_media', 'import_media', 'import_media', 'create_timeline']" in message
    assert "not rolled back" in message


def test_an_import_step_without_a_media_id_fails_closed(skill, recipe, media_dir):
    """The fail-closed contract is what makes the id mapping trustworthy."""

    def handle(action, params):
        if action == "apply_edit_plan":
            raise RuntimeError("Unsupported action: apply_edit_plan")
        if action == "import_media":
            return host_result()  # acknowledged, but no stable id
        return host_result(timeline_id="tl-4", clip_id="c")

    skill.respond(handle)

    assert "did not return media_id" in failed(
        skill.main(recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir))
    )


def test_a_walk_that_proves_nothing_is_a_failure(skill):
    """The composed walk's final guard.

    Steps such as ``add_clip`` are already readback-gated by the fail-closed
    contract, so the guard is the backstop for a script whose steps are not
    gated: it refuses to report success when nothing proved the timeline.
    """
    script = {
        "media": {"m0": "media/a.mp4"},
        "actions": [
            {"action": "import_media", "params": {"paths": ["media/a.mp4"]}, "media_ref": "m0"},
            {"action": "create_timeline", "params": {"name": "no proof"}},
            {"action": "save_project", "params": {}},
        ],
    }

    def handle(action, params):
        if action == "import_media":
            return {"verification": {"ok": True}, "media_id": "m-x"}
        return {"verification": {"ok": True}, "timeline_id": "tl-6"}

    skill.respond(handle)

    with pytest.raises(RuntimeError, match="no step returned a timeline readback"):
        skill._run_composed(script)


# ---------------------------------------------------------------------------
# Subtitle alignment through the composed walk
# ---------------------------------------------------------------------------


def test_the_composed_walk_resolves_sequence_alignment_before_dispatch(skill, media_dir):
    """`align` is an adapter directive, so it never reaches the host -- the walk
    re-times the file itself and imports the rewritten one."""
    subtitle = (
        "1\n00:00:00,600 --> 00:00:02,300\nfirst\n\n2\n00:00:03,000 --> 00:00:05,000\nsecond\n"
    )
    (media_dir / "galaxy_zh.srt").write_text(subtitle, encoding="utf-8")
    recipe = json.loads((ROOT / "demo" / "vlog_recipe.json").read_text(encoding="utf-8"))
    recipe.pop("captions", None)
    recipe["subtitle_file"] = "./galaxy_zh.srt"
    recipe["subtitle_files"] = [
        {"file": "galaxy_zh.srt", "align": "sequence", "output_path": "out/galaxy.aligned.srt"}
    ]
    recipe.pop("subtitle_file")
    composed_host(skill)

    context = ok(
        skill.main(
            recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir), strategy="composed"
        )
    )

    assert context["strategy"] == "composed"
    imports = [params for action, params in skill.calls if action == "import_subtitles"]
    assert len(imports) == 1
    # The host got the rewritten file, and no adapter-side directives.
    assert imports[0]["path"] == str(media_dir / "out" / "galaxy.aligned.srt")
    assert "align" not in imports[0]
    assert "output_path" not in imports[0]
    rewritten = (media_dir / "out" / "galaxy.aligned.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,700" in rewritten


def test_the_composed_walk_leaves_a_timecode_subtitle_untouched(skill, recipe, media_dir):
    """The default path must stay exactly what it was before `align` existed."""
    composed_host(skill)

    ok(
        skill.main(
            recipe=recipe, media_index=MEDIA_INDEX, media_dir=str(media_dir), strategy="composed"
        )
    )

    imports = [params for action, params in skill.calls if action == "import_subtitles"]
    assert imports[0]["path"] == str(media_dir / "galaxy_zh.srt")
    # Nothing was written next to the delivery root's files.
    assert sorted(path.name for path in media_dir.iterdir()) == ["assets", "galaxy_zh.srt"]
