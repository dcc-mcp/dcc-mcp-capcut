import copy
import json

import opentimelineio as otio
import pytest

from dcc_mcp_capcut.interchange import export_otio, main


@pytest.fixture
def edit():
    return {
        "name": "地球 / Earth",
        "fps": 30,
        "width": 1080,
        "height": 1920,
        "duration_frames": 90,
        "tracks": [
            {
                "name": "Picture",
                "kind": "Video",
                "clips": [
                    {
                        "name": "shot",
                        "media": "media/地球 shot.mp4",
                        "start": 12,
                        "source_in": 5,
                        "duration": 45,
                        "media_duration": 60,
                    }
                ],
            },
            {
                "name": "Voice",
                "kind": "Audio",
                "clips": [
                    {
                        "name": "narration",
                        "media": "media/voice.wav",
                        "start": 0,
                        "duration": 90,
                        "media_duration": 90,
                    }
                ],
            },
        ],
        "captions": [{"text": "共同的家", "start": 20, "duration": 30}],
    }


def test_official_otio_readback_preserves_offsets_sources_audio_and_markers(edit):
    original = copy.deepcopy(edit)
    receipt = export_otio(edit)
    timeline = otio.adapters.read_from_string(receipt["otio_json"], "otio_json")
    assert edit == original
    assert timeline.name == "地球 / Earth"
    assert timeline.duration().value == 90
    picture, audio = timeline.tracks
    assert picture[0].duration().value == 12
    assert picture[1].range_in_parent().start_time.value == 12
    assert picture[1].source_range.start_time.value == 5
    assert picture[1].source_range.duration.value == 45
    assert picture[2].duration().value == 33
    assert picture[1].media_reference.target_url == "media/地球 shot.mp4"
    assert audio.kind == "Audio"
    assert timeline.tracks.markers[0].marked_range.start_time.value == 20
    assert timeline.tracks.markers[0].name == "共同的家"
    assert receipt["clip_count"] == 2
    assert timeline.metadata["dcc_mcp_capcut"]["width"] == 1080
    assert export_otio(edit) == receipt


def test_fractional_frame_rate_is_not_rounded(edit):
    edit["fps"] = 30000 / 1001
    timeline = otio.adapters.read_from_string(export_otio(edit)["otio_json"], "otio_json")
    assert timeline.duration().rate == edit["fps"]
    assert timeline.duration().to_seconds() == pytest.approx(3.003)


@pytest.mark.parametrize("fps", [0, -1, True, "30", float("nan"), float("inf")])
def test_invalid_frame_rates(edit, fps):
    edit["fps"] = fps
    with pytest.raises(ValueError, match="fps"):
        export_otio(edit)


@pytest.mark.parametrize(
    "field,value",
    [
        ("start", -1),
        ("duration", 0),
        ("source_in", True),
        ("duration", 1.5),
        ("source_in", 16),
        ("start", 46),
    ],
)
def test_invalid_ranges(edit, field, value):
    edit["tracks"][0]["clips"][0][field] = value
    with pytest.raises(ValueError):
        export_otio(edit)


@pytest.mark.parametrize(
    "path",
    [
        "../a.mp4",
        "/a.mp4",
        "C:/a.mp4",
        "https://a/a.mp4",
        "a\\b.mp4",
        "media//a.mp4",
        "media/./a.mp4",
        "media/a.mp4?x",
        "media/a.mp4#x",
        "media/%2e%2e/a.mp4",
        "media/\na.mp4",
    ],
)
def test_reject_nonportable_or_ambiguous_media_paths(edit, path):
    edit["tracks"][0]["clips"][0]["media"] = path
    with pytest.raises(ValueError, match="media"):
        export_otio(edit)


def test_overlap_and_unknown_effects_are_not_silently_lost(edit):
    clip = edit["tracks"][0]["clips"][0]
    edit["tracks"][0]["clips"].append(copy.deepcopy(clip))
    with pytest.raises(ValueError, match="non-overlapping"):
        export_otio(edit)
    edit["tracks"][0]["clips"].pop()
    clip["speed"] = 2
    with pytest.raises(ValueError, match="unsupported fields"):
        export_otio(edit)


def test_caption_bounds(edit):
    edit["captions"][0]["start"] = 61
    with pytest.raises(ValueError, match="caption exceeds"):
        export_otio(edit)


def test_cli_preserves_existing_output(edit, tmp_path, monkeypatch):
    source = tmp_path / "edit.json"
    output = tmp_path / "timeline.otio"
    source.write_text(json.dumps(edit), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv", ["interchange", "--input", str(source), "--output", str(output)]
    )
    main()
    assert otio.adapters.read_from_file(str(output)).duration().value == 90
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        main()
    assert output.read_bytes() == original
