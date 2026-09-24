"""The export receipt is opt-in, so the tests pin both halves of that promise.

One half: a caller that never asks for the receipt keeps the contract it had
before it existed -- and the asynchronous submits, which cannot possibly carry
one, are not asked. The other: a caller that does ask is held to a receipt that
describes *this* artifact, with the picture *this* action produces.

Several cases here are regression tests for review findings, not for code that
was written wrong on purpose: a receipt that passed while describing a
different file, while describing a still where a video was due, or while
carrying ``NaN`` were all real holes.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

from dcc_mcp_capcut.contracts import validate_host_result
from dcc_mcp_capcut.export_receipt import (
    EXPORT_RECEIPT_ACTIONS,
    _normalize_path,
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


def test_only_actions_that_can_know_the_artifact_accept_the_flag():
    # The asynchronous submits acknowledge a job; the file does not exist when
    # they return. Asking them for a receipt would only cost the caller the
    # job_id it needs to poll.
    assert EXPORT_RECEIPT_ACTIONS == {"export_thumbnail", "get_export_status"}
    for action in ("export_video", "build_vlog_demo"):
        assert action not in EXPORT_RECEIPT_ACTIONS


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


@pytest.mark.parametrize("action", ["export_video", "build_vlog_demo"])
def test_an_async_submit_ignores_the_flag_rather_than_demanding_a_receipt(action):
    # Regression: these two only acknowledge a job, so requiring a receipt
    # raised before the caller ever saw the job_id.
    result = {"job_id": "job-1", "verification": {"ok": True}}

    assert validate_host_result(action, result, params={"verify_output": True}) is result


# --- opting in holds the host to the receipt --------------------------------


def test_a_video_receipt_is_accepted_on_a_status_poll():
    result = video_result()

    assert (
        validate_host_result("get_export_status", result, params={"verify_output": True}) is result
    )


def test_a_still_receipt_is_accepted_on_a_thumbnail():
    result = still_result()

    assert (
        validate_host_result("export_thumbnail", result, params={"verify_output": True}) is result
    )


def test_a_status_poll_accepts_whichever_picture_the_job_produced():
    # get_export_status only holds a job_id and cannot know in advance whether
    # the job renders a video or a still, so it must not be held to either.
    assert (
        validate_host_result("get_export_status", still_result(), params={"verify_output": True})
        is not None
    )


def test_a_missing_receipt_fails_closed():
    result = {"job_id": "job-1", "verification": {"ok": True}}

    with pytest.raises(RuntimeError, match="export receipt must be an object"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_read_only_status_poll_gets_its_own_error_wording():
    # "post-operation readback" points the wrong way for a poll, so the
    # read-only action reports the missing ok flag in its own terms.
    result = {"state": "done", "verification": {"output": copy.deepcopy(VIDEO_RECEIPT)}}

    with pytest.raises(RuntimeError, match="cannot report an export receipt without"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_mutating_receipt_call_keeps_the_mutation_wording():
    result = {"output_path": "C:/out/frame.png", "verification": {"ok": False}}

    with pytest.raises(RuntimeError, match="lacks verified post-operation readback"):
        validate_host_result("export_thumbnail", result, params={"verify_output": True})


def test_a_receipt_for_a_file_that_is_not_on_disk_is_rejected():
    result = video_result()
    result["verification"]["output"]["exists"] = False

    with pytest.raises(RuntimeError, match="does not prove the artifact exists"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_an_empty_file_is_rejected():
    result = video_result()
    result["verification"]["output"]["size_bytes"] = 0

    with pytest.raises(RuntimeError, match="size_bytes as an integer >= 1"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_missing_duration_is_rejected_for_timed_media():
    result = video_result()
    del result["verification"]["output"]["duration_sec"]

    with pytest.raises(RuntimeError, match="must carry duration_sec as a finite number"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_still_carrying_a_duration_is_rejected():
    result = still_result()
    result["verification"]["output"]["duration_sec"] = 42.5

    with pytest.raises(RuntimeError, match="reports duration_sec for a still"):
        validate_host_result("export_thumbnail", result, params={"verify_output": True})


def test_no_stream_info_is_rejected():
    result = video_result()
    result["verification"]["output"]["streams"] = []

    with pytest.raises(RuntimeError, match="lacks stream info"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_an_audio_only_artifact_is_not_a_video_export():
    result = video_result()
    result["verification"]["output"]["streams"] = [
        {"kind": "audio", "codec": "aac", "channels": 2},
    ]

    with pytest.raises(RuntimeError, match="has no image or video stream"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


# --- the picture has to match the action ------------------------------------


def test_a_thumbnail_cannot_satisfy_the_receipt_with_a_video_stream():
    # Regression: video and image were treated as interchangeable, so a still
    # receipt passed for export_thumbnail and a video receipt passed too.
    result = video_result(output_path="C:/out/vlog.mp4")

    with pytest.raises(RuntimeError, match="has no image stream; export_thumbnail"):
        validate_host_result("export_thumbnail", result, params={"verify_output": True})


def test_a_thumbnail_rejects_a_timed_stream_alongside_the_image():
    receipt = copy.deepcopy(STILL_RECEIPT)
    receipt["streams"].append({"kind": "video", "codec": "h264", "width": 1920, "height": 1080})
    receipt["duration_sec"] = 12.0
    result = still_result()
    result["verification"]["output"] = receipt

    with pytest.raises(RuntimeError, match="reports a video stream; export_thumbnail"):
        validate_host_result("export_thumbnail", result, params={"verify_output": True})


@pytest.mark.parametrize("action", ["export_video", "build_vlog_demo"])
def test_a_still_receipt_does_not_satisfy_a_video_render(action):
    # export_video no longer takes the flag itself -- it submits
    # asynchronously -- but batch delivery validates one receipt per rendered
    # item against these action names, so the rule is asserted directly.
    with pytest.raises(RuntimeError, match=f"has no video stream; {action}"):
        validate_export_receipt(action, copy.deepcopy(STILL_RECEIPT))

    assert validate_export_receipt(action, copy.deepcopy(VIDEO_RECEIPT)) is not None


# --- the receipt has to describe this artifact ------------------------------


def test_a_receipt_describing_another_file_is_rejected():
    result = video_result()
    result["output_path"] = "C:/out/NEW.mp4"

    with pytest.raises(RuntimeError, match="but get_export_status was asked to produce"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_path_binding_is_not_rejected_over_spelling():
    # Separator style, drive-letter case and a relative path are folded away
    # before comparison, so an honest host is not failed over form.
    result = video_result()
    result["output_path"] = "c:\\out\\.\\vlog.mp4"

    assert (
        validate_host_result("get_export_status", result, params={"verify_output": True}) is result
    )


# --- path folding must not depend on the platform running the test ----------

# Windows-style spellings a CapCut host really emits. All of them must fold to
# the same value everywhere, including under posixpath on the Linux runners.
WINDOWS_SPELLINGS = [
    "C:/out/vlog.mp4",
    "c:/out/vlog.mp4",
    "C:\\out\\vlog.mp4",
    "c:\\out\\vlog.mp4",
    "C:/out/./vlog.mp4",
    "c:\\out\\.\\vlog.mp4",
    "C:/out/sub/../vlog.mp4",
    "C:/OUT/vlog.mp4",
]


@pytest.mark.parametrize("spelling", WINDOWS_SPELLINGS)
def test_path_folding_is_platform_independent(spelling):
    # Regression: os.path.normcase+abspath is ntpath on Windows and posixpath
    # on Linux, where a backslash is an ordinary character and "." does not
    # fold -- so this passed locally and failed on 4 CI lanes. Pinned against
    # the literal expected value so it cannot drift with the platform.
    assert _normalize_path(spelling) == "c:/out/vlog.mp4"


@pytest.mark.parametrize("spelling", WINDOWS_SPELLINGS)
def test_paths_that_differ_only_in_spelling_compare_equal(spelling):
    assert _normalize_path(spelling) == _normalize_path("C:/out/vlog.mp4")


def test_paths_that_name_different_files_stay_unequal():
    # The fold must not be so loose that a wrong artifact slips through.
    left = _normalize_path("C:/out/vlog.mp4")
    for other in ("C:/out/vlog-2.mp4", "C:/other/vlog.mp4", "C:/out/vlog.mov"):
        assert left != _normalize_path(other)


def test_relative_paths_fold_without_a_cwd_prefix():
    # abspath would resolve these against the adapter's cwd, which is not the
    # host's, so normpath folds them instead.
    assert _normalize_path("./out/vlog.mp4") == _normalize_path("out/vlog.mp4")
    assert _normalize_path("out\\vlog.mp4") == _normalize_path("out/vlog.mp4")


def test_path_binding_is_skipped_when_the_result_carries_no_output_path():
    result = {"state": "done", "verification": {"ok": True, "output": copy.deepcopy(VIDEO_RECEIPT)}}

    assert (
        validate_host_result("get_export_status", result, params={"verify_output": True}) is result
    )


@pytest.mark.parametrize("bad", [42, "", "   ", ["C:/out/vlog.mp4"], {"path": "C:/out/vlog.mp4"}])
def test_a_present_but_unusable_output_path_is_rejected(bad):
    # Regression: a non-string output_path used to skip the bind entirely, so a
    # broken host silently turned the check off. Absent is skippable; present
    # and unusable is not.
    result = video_result(output_path=bad)

    with pytest.raises(RuntimeError, match="cannot be bound"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_running_job_cannot_yield_a_receipt():
    # Regression: the docs told callers to poll with verify_output, which turns
    # the very first poll into an error and hides progress. Failing closed here
    # is correct -- there is no artifact yet -- so the guidance is to poll
    # unflagged until terminal and then ask once.
    running = {"state": "running", "progress": 0.42}

    assert validate_host_result("get_export_status", running) is running
    with pytest.raises(RuntimeError, match="cannot report an export receipt without"):
        validate_host_result("get_export_status", running, params={"verify_output": True})


def test_an_absent_output_path_skips_the_bind():
    # get_export_status usually has none, and guessing one is worse than
    # not checking.
    result = {"state": "done", "verification": {"ok": True, "output": copy.deepcopy(VIDEO_RECEIPT)}}

    assert (
        validate_host_result("get_export_status", result, params={"verify_output": True}) is result
    )
    assert (
        validate_host_result(
            "get_export_status", video_result(output_path=None), params={"verify_output": True}
        )
        is not None
    )


# --- non-finite numbers are not values --------------------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_duration_is_rejected(value):
    result = video_result()
    result["verification"]["output"]["duration_sec"] = value

    with pytest.raises(RuntimeError, match="must carry duration_sec as a finite number"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_non_finite_stream_fps_is_rejected():
    result = video_result()
    result["verification"]["output"]["streams"][0]["fps"] = float("nan")

    with pytest.raises(RuntimeError, match="must carry fps as a finite number"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_json_nan_literals_do_not_slip_through():
    # json.loads accepts NaN/Infinity by default, so a host forwarding an
    # ffprobe field reported as N/A really can produce this.
    assert math.isnan(json.loads('{"duration_sec": NaN}')["duration_sec"])
    result = video_result()
    result["verification"]["output"] = json.loads(json.dumps(VIDEO_RECEIPT).replace("42.5", "NaN"))

    with pytest.raises(RuntimeError, match="must carry duration_sec as a finite number"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


# --- remaining field rules --------------------------------------------------


def test_a_video_stream_without_dimensions_is_rejected():
    result = video_result()
    del result["verification"]["output"]["streams"][0]["width"]

    with pytest.raises(RuntimeError, match=r"streams\[0\] must carry width"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_an_unknown_stream_kind_is_rejected():
    result = video_result()
    result["verification"]["output"]["streams"][0]["kind"] = "hologram"

    with pytest.raises(RuntimeError, match="unsupported kind 'hologram'"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_stream_without_a_codec_is_rejected():
    result = video_result()
    result["verification"]["output"]["streams"][0]["codec"] = "   "

    with pytest.raises(RuntimeError, match=r"streams\[0\] must carry codec"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_boolean_is_not_a_size():
    # ``isinstance(True, int)`` is true in Python, so a bare truth check would
    # accept ``size_bytes: true`` as a size of 1 byte.
    result = video_result()
    result["verification"]["output"]["size_bytes"] = True

    with pytest.raises(RuntimeError, match="size_bytes as an integer >= 1"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_a_half_written_probe_block_is_rejected():
    result = video_result()
    result["verification"]["output"]["probe"] = {"tool": "  "}

    with pytest.raises(RuntimeError, match="probe must carry tool"):
        validate_host_result("get_export_status", result, params={"verify_output": True})


def test_an_absent_probe_block_is_fine():
    result = video_result()
    del result["verification"]["output"]["probe"]

    assert (
        validate_host_result("get_export_status", result, params={"verify_output": True}) is result
    )


def test_validate_export_receipt_returns_the_host_object_unchanged():
    receipt = copy.deepcopy(VIDEO_RECEIPT)

    assert validate_export_receipt("get_export_status", receipt) is receipt


# --- the flag survives the trip through a real skill script ------------------


def load_export_script(name: str):
    """Import a packaged skill script the way the MCP server loads it."""
    spec = importlib.util.spec_from_file_location(f"export_script_{name}", _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("script", ["export_thumbnail", "get_export_status"])
@pytest.mark.parametrize("verify_output", [True, False])
def test_a_receipt_script_forwards_verify_output_to_the_bridge(script, verify_output, monkeypatch):
    captured = {}

    def fake_call(action, params):
        captured.update(action=action, params=params)
        return {
            "job_id": "job-1",
            "output_path": "C:/out/frame.png",
            "verification": {"ok": True, "output": copy.deepcopy(STILL_RECEIPT)},
        }

    monkeypatch.setattr(_COMMON, "call_bridge", fake_call)

    module = load_export_script(script)
    result = module.main(output_path="C:/out/frame.png", verify_output=verify_output)

    assert captured["action"] == script
    assert captured["params"]["verify_output"] is verify_output
    assert result["success"] is True


@pytest.mark.parametrize("script", ["export_thumbnail", "get_export_status"])
def test_a_receipt_script_fails_closed_on_a_bare_acknowledgement(script, monkeypatch):
    monkeypatch.setattr(
        _COMMON,
        "call_bridge",
        lambda action, params: {"job_id": "job-1", "verification": {"ok": True}},
    )

    module = load_export_script(script)
    result = module.main(output_path="C:/out/frame.png", verify_output=True)

    assert result["success"] is False
    assert "export receipt" in result["message"]


@pytest.mark.parametrize("script", ["export_video", "build_vlog_demo"])
def test_an_async_submit_script_still_returns_the_job_id(script, monkeypatch):
    # Regression: with the flag wired to these two, the caller lost the job_id
    # to an unreceiptable submit.
    monkeypatch.setattr(
        _COMMON,
        "call_bridge",
        lambda action, params: {"job_id": "job-1", "verification": {"ok": True}},
    )

    module = load_export_script(script)
    result = module.main(output_path="C:/out/vlog.mp4", verify_output=True)

    assert result["success"] is True
    assert result["context"]["job_id"] == "job-1"
