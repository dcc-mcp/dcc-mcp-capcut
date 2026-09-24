"""The export receipt is opt-in, so the tests pin both halves of that promise.

One half: a caller that never asks for the receipt keeps the contract it had
before it existed. The other: a caller that does ask is held to it, including
on `get_export_status`, which is read-only and otherwise exempt from every
contract rule.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
from pathlib import Path

import pytest

from dcc_mcp_capcut.contracts import validate_host_result
from dcc_mcp_capcut.export_receipt import (
    EXPORT_RECEIPT_ACTIONS,
    receipt_requested,
    validate_export_receipt,
)

_COMMON = importlib.import_module("dcc_mcp_capcut.skills._shared.scripts.common")
_SCRIPTS = Path(__file__).parents[1] / "src/dcc_mcp_capcut/skills/capcut-export/scripts"

VIDEO_RECEIPT = {
    "path": "C:/out/vlog.mp4",
    "exists": True,
    "size_bytes": 18345921,
    "duration_sec": 42.5,
    "width": 1080,
    "height": 1920,
    "streams": [
        {"kind": "video", "codec": "h264", "width": 1080, "height": 1920, "fps": 30.0},
        {"kind": "audio", "codec": "aac", "channels": 2, "sample_rate_hz": 48000},
    ],
    "probe": {"tool": "ffprobe", "version": "6.0"},
}

STILL_RECEIPT = {
    "path": "C:/out/frame.png",
    "exists": True,
    "size_bytes": 204813,
    "streams": [{"kind": "image", "codec": "png", "width": 1920, "height": 1080}],
}


def video_result(**overrides):
    result = {
        "job_id": "job-1",
        "output_path": "C:/out/vlog.mp4",
        "verification": {"ok": True, "output": copy.deepcopy(VIDEO_RECEIPT)},
    }
    result.update(overrides)
    return result


def still_result(**overrides):
    result = {
        "job_id": "job-2",
        "output_path": "C:/out/frame.png",
        "verification": {"ok": True, "output": copy.deepcopy(STILL_RECEIPT)},
    }
    result.update(overrides)
    return result


# --- the opt-in flag itself -------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        None,
        {},
        {"output_path": "C:/out/vlog.mp4"},
        {"verify_output": False},
        {"verify_output": "true"},
        {"verify_output": 1},
    ],
)
def test_only_an_explicit_boolean_true_opts_in(params):
    assert receipt_requested(params) is False


def test_an_explicit_boolean_true_opts_in():
    assert receipt_requested({"verify_output": True}) is True


def test_receipt_actions_cover_every_export_producing_tool():
    assert EXPORT_RECEIPT_ACTIONS == {
        "export_video",
        "export_thumbnail",
        "get_export_status",
        "build_vlog_demo",
    }


# --- the receipt is never required by default -------------------------------


def test_export_video_without_the_flag_keeps_todays_contract():
    result = {"job_id": "job-1", "verification": {"ok": True}}

    assert validate_host_result("export_video", result) is result


def test_export_video_tolerates_a_loose_output_block_when_not_asked_for():
    # A host that already returns some output object must not start failing
    # just because a stricter receipt now exists.
    result = {"output_path": "C:/out/vlog.mp4", "verification": {"ok": True, "output": "nope"}}

    assert validate_host_result("export_video", result) is result


def test_get_export_status_without_the_flag_is_untouched():
    result = {"state": "done"}

    assert validate_host_result("get_export_status", result) is result


def test_a_non_export_action_ignores_the_flag():
    result = {"media_id": "m-1", "verification": {"ok": True}}

    assert validate_host_result("import_media", result, params={"verify_output": True}) is result


# --- opting in holds the host to the receipt --------------------------------


@pytest.mark.parametrize("action", sorted(EXPORT_RECEIPT_ACTIONS))
def test_a_complete_video_receipt_is_accepted(action):
    result = video_result()

    assert validate_host_result(action, result, params={"verify_output": True}) is result


def test_a_still_receipt_is_accepted():
    result = still_result()

    assert (
        validate_host_result("export_thumbnail", result, params={"verify_output": True}) is result
    )


def test_a_read_only_status_call_is_held_to_the_receipt_when_asked():
    result = {"state": "done", "verification": {"ok": True, "output": copy.deepcopy(VIDEO_RECEIPT)}}

    assert (
        validate_host_result("get_export_status", result, params={"verify_output": True}) is result
    )


def test_a_missing_receipt_fails_closed():
    result = {"job_id": "job-1", "verification": {"ok": True}}

    with pytest.raises(RuntimeError, match="export receipt must be an object"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_an_unverified_result_cannot_carry_a_receipt():
    result = {"job_id": "job-1", "verification": {"ok": False, "output": VIDEO_RECEIPT}}

    with pytest.raises(RuntimeError, match="lacks verified post-operation readback"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_a_receipt_for_a_file_that_is_not_on_disk_is_rejected():
    result = video_result()
    result["verification"]["output"]["exists"] = False

    with pytest.raises(RuntimeError, match="does not prove the artifact exists"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_an_empty_file_is_rejected():
    result = video_result()
    result["verification"]["output"]["size_bytes"] = 0

    with pytest.raises(RuntimeError, match="size_bytes as an integer >= 1"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_a_missing_duration_is_rejected_for_timed_media():
    result = video_result()
    del result["verification"]["output"]["duration_sec"]

    with pytest.raises(RuntimeError, match="must carry duration_sec as a number > 0"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_a_still_carrying_a_duration_is_rejected():
    result = still_result()
    result["verification"]["output"]["duration_sec"] = 42.5

    with pytest.raises(RuntimeError, match="reports duration_sec for a still"):
        validate_host_result("export_thumbnail", result, params={"verify_output": True})


def test_no_stream_info_is_rejected():
    result = video_result()
    result["verification"]["output"]["streams"] = []

    with pytest.raises(RuntimeError, match="lacks stream info"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_an_audio_only_artifact_is_not_a_video_export():
    result = video_result()
    result["verification"]["output"]["streams"] = [
        {"kind": "audio", "codec": "aac", "channels": 2},
    ]

    with pytest.raises(RuntimeError, match="no video or image stream"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_a_video_stream_without_dimensions_is_rejected():
    result = video_result()
    del result["verification"]["output"]["streams"][0]["width"]

    with pytest.raises(RuntimeError, match="streams\\[0\\] must carry width"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_an_unknown_stream_kind_is_rejected():
    result = video_result()
    result["verification"]["output"]["streams"][0]["kind"] = "hologram"

    with pytest.raises(RuntimeError, match="unsupported kind 'hologram'"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_a_stream_without_a_codec_is_rejected():
    result = video_result()
    result["verification"]["output"]["streams"][0]["codec"] = "   "

    with pytest.raises(RuntimeError, match="streams\\[0\\] must carry codec"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_a_boolean_is_not_a_size():
    # ``isinstance(True, int)`` is true in Python, so a bare truth check would
    # accept ``size_bytes: true`` as a size of 1 byte.
    result = video_result()
    result["verification"]["output"]["size_bytes"] = True

    with pytest.raises(RuntimeError, match="size_bytes as an integer >= 1"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_a_half_written_probe_block_is_rejected():
    result = video_result()
    result["verification"]["output"]["probe"] = {"tool": "  "}

    with pytest.raises(RuntimeError, match="probe must carry tool"):
        validate_host_result("export_video", result, params={"verify_output": True})


def test_an_absent_probe_block_is_fine():
    result = video_result()
    del result["verification"]["output"]["probe"]

    assert validate_host_result("export_video", result, params={"verify_output": True}) is result


def test_validate_export_receipt_returns_the_host_object_unchanged():
    receipt = copy.deepcopy(VIDEO_RECEIPT)

    assert validate_export_receipt("export_video", receipt) is receipt


# --- the flag survives the trip through a real skill script ------------------


def load_export_script(name: str):
    """Import a packaged skill script the way the MCP server loads it."""
    spec = importlib.util.spec_from_file_location(f"export_script_{name}", _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "script", ["export_video", "export_thumbnail", "get_export_status", "build_vlog_demo"]
)
@pytest.mark.parametrize("verify_output", [True, False])
def test_the_skill_script_forwards_verify_output_to_the_bridge(script, verify_output, monkeypatch):
    captured = {}

    def fake_call(action, params):
        captured.update(action=action, params=params)
        return {
            "job_id": "job-1",
            "verification": {"ok": True, "output": copy.deepcopy(VIDEO_RECEIPT)},
        }

    monkeypatch.setattr(_COMMON, "call_bridge", fake_call)

    module = load_export_script(script)
    result = module.main(output_path="C:/out/vlog.mp4", verify_output=verify_output)

    assert captured["action"] == script
    assert captured["params"]["verify_output"] is verify_output
    assert result["success"] is True


@pytest.mark.parametrize(
    "script", ["export_video", "export_thumbnail", "get_export_status", "build_vlog_demo"]
)
def test_an_opted_in_export_script_fails_closed_on_a_bare_acknowledgement(script, monkeypatch):
    monkeypatch.setattr(
        _COMMON,
        "call_bridge",
        lambda action, params: {"job_id": "job-1", "verification": {"ok": True}},
    )

    module = load_export_script(script)
    result = module.main(output_path="C:/out/vlog.mp4", verify_output=True)

    assert result["success"] is False
    assert "export receipt" in result["message"]
