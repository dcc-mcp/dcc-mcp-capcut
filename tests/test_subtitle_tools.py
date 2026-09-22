"""The subtitle tools: alignment in `import_subtitles`, and the batch import.

The host is not reachable from CI, so ``call_bridge`` is routed at a recording
fake. What these tests prove is the part the adapter owns: which file reaches
the host, what params it carries, and what a part-way failure reports.

``@skill_entry`` never raises -- it converts every exception into a failure
envelope -- so failures are asserted through the envelope, exactly as a caller
would see them.
"""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
TEXT_SCRIPTS = ROOT / "src" / "dcc_mcp_capcut" / "skills" / "capcut-text" / "scripts"

TIMELINE = {"tracks": 2, "duration": 12.5}

SRT_ZH = textwrap.dedent(
    """\
    1
    00:00:00,600 --> 00:00:02,300
    抬头看

    2
    00:00:03,000 --> 00:00:05,000
    银河系
    """
)

SRT_EN = textwrap.dedent(
    """\
    1
    00:00:00,600 --> 00:00:02,300
    look up

    2
    00:00:03,000 --> 00:00:05,000
    the galaxy
    """
)


def load_skill(name: str):
    spec = importlib.util.spec_from_file_location(name, TEXT_SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ok_result(caption_ids, timeline=TIMELINE):
    return {
        "caption_ids": list(caption_ids),
        "timeline_id": "timeline-1",
        "verification": {"ok": True, "timeline": timeline},
    }


@pytest.fixture
def bridge(monkeypatch):
    """Load a skill script with ``call_bridge`` routed at a recording fake."""
    loaded: dict[str, object] = {}

    def _install(name: str):
        module = load_skill(name)
        calls: list[tuple[str, dict]] = []
        behaviour: dict[str, object] = {}

        def fake_call_bridge(action, params, **_kwargs):
            calls.append((action, params))
            handler = behaviour.get("handle")
            if handler is None:
                raise AssertionError("no host behaviour configured")
            return handler(action, params)

        monkeypatch.setattr(module, "call_bridge", fake_call_bridge)
        loaded["calls"] = calls
        loaded["module"] = module
        loaded["respond"] = lambda handler: behaviour.__setitem__("handle", handler)
        return loaded

    return _install


# ---------------------------------------------------------------------------
# import_subtitles
# ---------------------------------------------------------------------------


def test_timecode_import_hands_the_source_file_straight_to_the_host(bridge, tmp_path):
    """The default path must stay exactly what it was before `align` existed."""
    source = tmp_path / "a.srt"
    source.write_text(SRT_ZH, encoding="utf-8")
    skill = bridge("import_subtitles")
    counter = {"n": 0}

    def handler(action, params):
        counter["n"] += 1
        return ok_result([f"cap{counter['n']}"])

    skill["respond"](handler)

    result = skill["module"].main(path=str(source), timeline_id="t1", language="zh-CN", offset=1.5)

    assert result["success"] is True
    action, params = skill["calls"][0]
    assert action == "import_subtitles"
    assert params["path"] == str(source)
    assert params["timeline_id"] == "t1"
    assert params["language"] == "zh-CN"
    assert params["offset"] == 1.5
    assert source.read_text(encoding="utf-8") == SRT_ZH  # untouched


def test_adapter_side_directives_never_reach_the_host(bridge, tmp_path):
    source = tmp_path / "a.srt"
    source.write_text(SRT_ZH, encoding="utf-8")
    skill = bridge("import_subtitles")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    skill["module"].main(
        path=str(source), align="timecode", output_path=str(tmp_path / "aligned.srt")
    )

    _, params = skill["calls"][0]
    assert "align" not in params
    assert "output_path" not in params


def test_sequence_alignment_imports_the_re_timed_file(bridge, tmp_path):
    source = tmp_path / "a.srt"
    source.write_text(SRT_ZH, encoding="utf-8")
    target = tmp_path / "a.aligned.srt"
    skill = bridge("import_subtitles")
    skill["respond"](lambda action, params: ok_result(["cap1", "cap2"]))

    result = skill["module"].main(path=str(source), align="sequence")

    _, params = skill["calls"][0]
    assert params["path"] == str(target)
    assert target.is_file()
    # The host is told nothing about alignment: it just gets an SRT file.
    assert "align" not in params
    assert result["context"]["align"] == "sequence"
    assert result["context"]["imported_path"] == str(target)


def test_sequence_alignment_actually_re_times_the_cues(bridge, tmp_path):
    from dcc_mcp_capcut.subtitles import parse_srt

    source = tmp_path / "a.srt"
    source.write_text(SRT_ZH, encoding="utf-8")
    skill = bridge("import_subtitles")
    skill["respond"](lambda action, params: ok_result(["cap1", "cap2"]))

    skill["module"].main(path=str(source), align="sequence")

    _, params = skill["calls"][0]
    cues = parse_srt(Path(params["path"]).read_text(encoding="utf-8"))
    assert [cue.start for cue in cues] == [0.0, 1.7]


def test_an_explicit_output_path_is_used_and_reported(bridge, tmp_path):
    source = tmp_path / "a.srt"
    source.write_text(SRT_ZH, encoding="utf-8")
    target = tmp_path / "out" / "en.srt"
    skill = bridge("import_subtitles")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    result = skill["module"].main(path=str(source), align="sequence", output_path=str(target))

    assert skill["calls"][0][1]["path"] == str(target)
    assert result["context"]["output_path"] == str(target)


def test_a_host_that_acknowledges_without_caption_ids_is_rejected(bridge, tmp_path):
    """Fail-closed still applies: an import that produced nothing is a failure."""
    source = tmp_path / "a.srt"
    source.write_text(SRT_ZH, encoding="utf-8")
    skill = bridge("import_subtitles")
    skill["respond"](lambda action, params: {"verification": {"ok": True, "timeline": TIMELINE}})

    result = skill["module"].main(path=str(source))

    assert result["success"] is False
    assert "caption_ids" in result["message"]


def test_sequence_on_a_missing_file_fails_before_dispatch(bridge, tmp_path):
    skill = bridge("import_subtitles")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    result = skill["module"].main(path=str(tmp_path / "absent.srt"), align="sequence")

    assert result["success"] is False
    assert not skill["calls"], "nothing may be dispatched without a file to import"


def test_omitted_optionals_are_not_sent_as_nulls(bridge, tmp_path):
    source = tmp_path / "a.srt"
    source.write_text(SRT_ZH, encoding="utf-8")
    skill = bridge("import_subtitles")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    skill["module"].main(path=str(source))

    _, params = skill["calls"][0]
    assert "timeline_id" not in params
    assert "language" not in params
    assert "style" not in params


# ---------------------------------------------------------------------------
# import_subtitles_batch
# ---------------------------------------------------------------------------


def test_batch_imports_every_file_as_its_own_track(bridge, tmp_path):
    """The multi-language case: one call, one text track per language."""
    zh = tmp_path / "zh.srt"
    en = tmp_path / "en.srt"
    zh.write_text(SRT_ZH, encoding="utf-8")
    en.write_text(SRT_EN, encoding="utf-8")
    skill = bridge("import_subtitles_batch")
    counter = {"n": 0}

    def handler(action, params):
        counter["n"] += 1
        return ok_result([f"zh{counter['n']}", f"en{counter['n']}"])

    skill["respond"](handler)

    result = skill["module"].main(
        items=[
            {"path": str(zh), "language": "zh-CN"},
            {"path": str(en), "language": "en-US"},
        ],
        timeline_id="t1",
    )

    assert result["success"] is True
    assert [action for action, _ in skill["calls"]] == ["import_subtitles", "import_subtitles"]
    assert [params["path"] for _, params in skill["calls"]] == [str(zh), str(en)]
    assert [params["language"] for _, params in skill["calls"]] == ["zh-CN", "en-US"]
    assert all(params["timeline_id"] == "t1" for _, params in skill["calls"])

    context = result["context"]
    assert len(context["imported"]) == 2
    assert context["caption_count"] == 4
    assert [entry["language"] for entry in context["imported"]] == ["zh-CN", "en-US"]


def test_batch_reports_per_file_caption_ids(bridge, tmp_path):
    zh = tmp_path / "zh.srt"
    en = tmp_path / "en.srt"
    zh.write_text(SRT_ZH, encoding="utf-8")
    en.write_text(SRT_EN, encoding="utf-8")
    skill = bridge("import_subtitles_batch")
    responses = {"zh.srt": ["z1", "z2"], "en.srt": ["e1", "e2", "e3"]}

    def handler(action, params):
        name = Path(params["path"]).name
        return ok_result(responses[name])

    skill["respond"](handler)
    result = skill["module"].main(items=[{"path": str(zh)}, {"path": str(en)}])

    imported = result["context"]["imported"]
    assert [entry["caption_count"] for entry in imported] == [2, 3]
    assert result["context"]["caption_count"] == 5


def test_batch_stops_at_the_first_failure_and_reports_what_landed(bridge, tmp_path):
    zh = tmp_path / "zh.srt"
    en = tmp_path / "en.srt"
    zh.write_text(SRT_ZH, encoding="utf-8")
    en.write_text(SRT_EN, encoding="utf-8")
    skill = bridge("import_subtitles_batch")

    def handler(action, params):
        if Path(params["path"]).name == "en.srt":
            raise RuntimeError("CapCut bridge did not respond; open the bundled panel")
        return ok_result(["z1"])

    skill["respond"](handler)

    result = skill["module"].main(items=[{"path": str(zh)}, {"path": str(en)}])

    assert result["success"] is False
    message = result["message"]
    assert "stopped at item 1" in message
    assert "Items already imported" in message
    assert "zh.srt" in message
    assert "not rolled back" in message


def test_batch_validates_its_items_before_any_dispatch(bridge, tmp_path):
    good = tmp_path / "good.srt"
    good.write_text(SRT_ZH, encoding="utf-8")
    skill = bridge("import_subtitles_batch")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    result = skill["module"].main(items=[{"path": str(good)}, {"language": "en-US"}])

    assert result["success"] is False
    assert "items[1] requires a non-empty 'path'" in result["message"]
    assert not skill["calls"], "a malformed item must fail before the host is touched"


@pytest.mark.parametrize("items", [[], "not-a-list", None])
def test_batch_requires_a_non_empty_list(bridge, items):
    skill = bridge("import_subtitles_batch")
    skill["respond"](lambda action, params: ok_result(["cap1"]))
    result = skill["module"].main(items=items)
    assert result["success"] is False
    assert "non-empty list" in result["message"]


def test_batch_rejects_unknown_item_fields(bridge, tmp_path):
    source = tmp_path / "a.srt"
    source.write_text(SRT_ZH, encoding="utf-8")
    skill = bridge("import_subtitles_batch")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    result = skill["module"].main(items=[{"path": str(source), "timeline_id": "other"}])

    assert result["success"] is False
    assert "unsupported fields" in result["message"]


def test_batch_resolves_sequence_alignment_per_item(bridge, tmp_path):
    zh = tmp_path / "zh.srt"
    en = tmp_path / "en.srt"
    zh.write_text(SRT_ZH, encoding="utf-8")
    en.write_text(SRT_EN, encoding="utf-8")
    skill = bridge("import_subtitles_batch")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    result = skill["module"].main(
        items=[
            {"path": str(zh), "language": "zh-CN", "align": "sequence"},
            {"path": str(en), "language": "en-US", "align": "sequence"},
        ]
    )

    assert result["success"] is True
    assert [Path(params["path"]).name for _, params in skill["calls"]] == [
        "zh.aligned.srt",
        "en.aligned.srt",
    ]
    assert [entry["align"] for entry in result["context"]["imported"]] == ["sequence", "sequence"]


def test_batch_carries_the_last_timeline_readback(bridge, tmp_path):
    zh = tmp_path / "zh.srt"
    en = tmp_path / "en.srt"
    zh.write_text(SRT_ZH, encoding="utf-8")
    en.write_text(SRT_EN, encoding="utf-8")
    skill = bridge("import_subtitles_batch")
    skill["respond"](lambda action, params: ok_result(["cap1"], timeline={"tracks": 3}))

    result = skill["module"].main(items=[{"path": str(zh)}, {"path": str(en)}])

    verification = result["context"]["verification"]
    assert verification["ok"] is True
    assert verification["timeline"] == {"tracks": 3}
    assert verification["steps"] == 2


# ---------------------------------------------------------------------------
# Regressions: alignment must be resolved before any dispatch
# ---------------------------------------------------------------------------


def test_batch_resolves_alignment_for_every_item_before_dispatch(bridge, tmp_path):
    """A file that cannot be re-timed must fail before item 0 lands on the timeline.

    Resolving alignment lazily meant item 1 raising FileNotFoundError after item
    0 was already imported, with no "Items already imported" to show for it.
    """
    first = tmp_path / "first.srt"
    first.write_text(SRT_ZH, encoding="utf-8")
    skill = bridge("import_subtitles_batch")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    result = skill["module"].main(
        items=[
            {"path": str(first), "align": "sequence"},
            {"path": str(tmp_path / "absent.srt"), "align": "sequence"},
        ]
    )

    assert result["success"] is False
    assert not skill["calls"], "nothing may be imported when a later item cannot be resolved"


def test_batch_rejects_an_unalignable_format_before_any_dispatch(bridge, tmp_path):
    first = tmp_path / "first.srt"
    first.write_text(SRT_ZH, encoding="utf-8")
    ass = tmp_path / "second.ass"
    ass.write_text("[Script Info]\nDialogue: 0,0:00:01.00,0:00:02.00\n", encoding="utf-8")
    skill = bridge("import_subtitles_batch")
    skill["respond"](lambda action, params: ok_result(["cap1"]))

    result = skill["module"].main(
        items=[
            {"path": str(first), "align": "sequence"},
            {"path": str(ass), "format": "ass", "align": "sequence"},
        ]
    )

    assert result["success"] is False
    assert "offline subtitle parsing supports" in result["message"]
    assert not skill["calls"]


def test_batch_reports_progress_when_a_dispatch_itself_fails(bridge, tmp_path):
    """The failure path that *is* inside the loop still names what landed."""
    first = tmp_path / "first.srt"
    second = tmp_path / "second.srt"
    first.write_text(SRT_ZH, encoding="utf-8")
    second.write_text(SRT_EN, encoding="utf-8")
    skill = bridge("import_subtitles_batch")

    def handler(action, params):
        # Alignment rewrites the paths, so match on the stem, not the filename.
        if Path(params["path"]).stem.startswith("second"):
            raise RuntimeError("CapCut bridge did not respond; open the bundled panel")
        return ok_result(["cap1"])

    skill["respond"](handler)
    result = skill["module"].main(
        items=[
            {"path": str(first), "align": "sequence"},
            {"path": str(second), "align": "sequence"},
        ]
    )

    assert result["success"] is False
    assert "stopped at item 1" in result["message"]
    assert "Items already imported" in result["message"]
