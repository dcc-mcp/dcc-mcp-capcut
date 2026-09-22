"""Offline subtitle parsing, alignment and rendering.

These cover the part of the subtitle chain that must not depend on a host:
what a file means, how it maps onto the timeline, and what gets handed to
CapCut. Everything here is host-free on purpose -- a host that ignored an
``align`` directive would be indistinguishable from one that implemented it,
so the verdict is settled before dispatch.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from dcc_mcp_capcut.editplan import cues_to_captions
from dcc_mcp_capcut.subtitles import (
    SEQUENCE,
    TIMECODE,
    SubtitleFormatError,
    align_cues,
    parse_cues,
    parse_lrc,
    parse_srt,
    prepare_import_params,
    render_srt,
)

SRT = textwrap.dedent(
    """\
    1
    00:00:00,600 --> 00:00:02,300
    抬头看，银河系就在我们身边

    2
    00:00:02,400 --> 00:00:04,300
    this light may have travelled for millennia

    3
    00:00:05,000 --> 00:00:07,800
    third
    """
)


def write(tmp_path, name, text):
    target = tmp_path / name
    target.write_text(text, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# SRT parsing
# ---------------------------------------------------------------------------


def test_srt_parses_spans_and_text():
    cues = parse_srt(SRT)
    assert [cue.index for cue in cues] == [1, 2, 3]
    assert [cue.start for cue in cues] == [0.6, 2.4, 5.0]
    assert [cue.end for cue in cues] == [2.3, 4.3, 7.8]
    assert cues[0].text == "抬头看，银河系就在我们身边"


def test_srt_without_the_index_line_parses():
    """The numeric index is optional in the format and in practice."""
    cues = parse_srt("00:00:01,000 --> 00:00:02,000\nhello\n")
    assert [(cue.start, cue.end, cue.text) for cue in cues] == [(1.0, 2.0, "hello")]


def test_srt_accepts_a_dot_as_the_millisecond_separator():
    cues = parse_srt("1\n00:00:01.500 --> 00:00:02.250\na\n")
    assert (cues[0].start, cues[0].end) == (1.5, 2.25)


def test_srt_tolerates_crlf_and_a_bom():
    cues = parse_srt("\ufeff1\r\n00:00:01,000 --> 00:00:02,000\r\nhello\r\n")
    assert cues[0].text == "hello"


def test_srt_pads_a_short_millisecond_field():
    """,6 means 600 ms -- it is three digits padded, not a scaling factor."""
    cues = parse_srt("00:00:01,6 --> 00:00:02,0\na\n")
    assert cues[0].start == 1.6
    assert cues[0].end == 2.0


def test_multi_line_cue_text_is_preserved():
    cues = parse_srt("1\n00:00:01,000 --> 00:00:02,000\nline one\nline two\n")
    assert cues[0].text == "line one\nline two"


def test_srt_ignores_trailing_coordinate_metadata():
    cues = parse_srt("1\n00:00:01,000 --> 00:00:02,000 X1:0 X2:100 Y1:0 Y2:10\na\n")
    assert cues[0].end == 2.0


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "no timing here",
        "1\nnot-a-time --> 00:00:02,000\ntext\n",
        "1\n00:00:01,000 --> 00:00:02,000\n",  # timing but no text
        "1\n00:00:05,000 --> 00:00:02,000\nbackwards\n",  # ends before it starts
        "1\n",  # index, nothing else
    ],
)
def test_srt_that_cannot_yield_a_cue_is_rejected(bad):
    with pytest.raises(SubtitleFormatError):
        parse_srt(bad)


def test_srt_errors_name_the_offending_block():
    with pytest.raises(SubtitleFormatError, match="block 2"):
        parse_srt("1\n00:00:01,000 --> 00:00:02,000\nok\n\n2\nbroken\ntext\n")


def test_a_non_string_input_is_rejected():
    with pytest.raises(SubtitleFormatError):
        parse_srt(None)


# ---------------------------------------------------------------------------
# LRC parsing
# ---------------------------------------------------------------------------


def test_lrc_derives_end_times_from_the_next_stamp():
    cues = parse_lrc("[00:01.00]first\n[00:03.50]second\n[00:06.00]third\n")
    assert [cue.start for cue in cues] == [1.0, 3.5, 6.0]
    assert [cue.end for cue in cues] == [3.5, 6.0, 9.0]  # last uses the default


def test_lrc_repeats_the_text_for_each_stamp_on_a_line():
    cues = parse_lrc("[00:01.00][00:05.00]chorus\n")
    assert [cue.start for cue in cues] == [1.0, 5.0]
    assert [cue.text for cue in cues] == ["chorus", "chorus"]


def test_lrc_ignores_metadata_headers():
    cues = parse_lrc("[ti:Title]\n[ar:Artist]\n[00:02.00]line\n")
    assert len(cues) == 1 and cues[0].start == 2.0


def test_lrc_without_timestamps_is_rejected():
    with pytest.raises(SubtitleFormatError, match="no cues found"):
        parse_lrc("just some text\n")


# ---------------------------------------------------------------------------
# Format dispatch
# ---------------------------------------------------------------------------


def test_parse_cues_dispatches_on_format():
    assert len(parse_cues(SRT, "srt")) == 3
    assert len(parse_cues("[00:01.00]a\n", "lrc")) == 1


def test_ass_is_explicitly_not_parsed_offline():
    """Better a clear refusal than a silent loss of style and positioning."""
    with pytest.raises(SubtitleFormatError, match="offline subtitle parsing supports"):
        parse_cues("[Script Info]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,text", "ass")


def test_an_unknown_format_is_rejected():
    with pytest.raises(SubtitleFormatError):
        parse_cues(SRT, "vtt")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_render_srt_round_trips_through_the_parser():
    cues = parse_srt(SRT)
    assert parse_srt(render_srt(cues)) == cues


def test_render_srt_renumbers_from_one():
    """The source numbering is not authoritative; the renderer's is."""
    shifted = [cue for cue in parse_srt(SRT)[1:]]
    assert [cue.index for cue in parse_srt(render_srt(shifted))] == [1, 2]


def test_render_srt_formats_the_clock_with_three_digits():
    text = render_srt(parse_srt("00:00:01,500 --> 00:01:02,005\na\n"))
    assert "00:00:01,500 --> 00:01:02,005" in text


def test_render_srt_clamps_a_negative_start_to_zero():
    from dcc_mcp_capcut.subtitles import Cue

    assert "00:00:00,000" in render_srt([Cue(1, -5.0, 1.0, "a")])


def test_rendering_an_empty_list_is_empty():
    assert render_srt([]) == ""


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


def test_timecode_is_the_default_and_preserves_the_source_clock():
    cues = parse_srt(SRT)
    assert align_cues(cues) == cues


def test_timecode_shifts_the_whole_track_by_the_offset():
    aligned = align_cues(parse_srt(SRT), TIMECODE, offset=1.5)
    assert [cue.start for cue in aligned] == [2.1, 3.9, 6.5]
    assert [cue.text for cue in aligned] == [cue.text for cue in parse_srt(SRT)]


def test_sequence_discards_absolute_timecodes_and_packs_cues():
    aligned = align_cues(parse_srt(SRT), SEQUENCE)
    assert [cue.start for cue in aligned] == [0.0, 1.7, 3.6]
    # Each cue keeps its own duration; the 0.1 s gap in the source collapses.
    assert [round(cue.end - cue.start, 3) for cue in aligned] == [1.7, 1.9, 2.8]


def test_sequence_starts_at_the_offset():
    aligned = align_cues(parse_srt(SRT), SEQUENCE, offset=10.0)
    assert aligned[0].start == 10.0
    assert aligned[1].start == 11.7


def test_sequence_clamps_an_overlong_cue():
    long_cue = parse_srt("00:00:00,000 --> 00:00:40,000\nblocks the screen\n")
    aligned = align_cues(long_cue, SEQUENCE, max_duration=5.0)
    assert aligned[0].end - aligned[0].start == 5.0


def test_sequence_gives_a_zero_length_cue_a_readable_span():
    empty = parse_srt("00:00:03,000 --> 00:00:03,000\nnothing\n")
    aligned = align_cues(empty, SEQUENCE, min_duration=0.2)
    assert aligned[0].end - aligned[0].start == 0.2


def test_sequence_keeps_the_cue_order_and_text():
    aligned = align_cues(parse_srt(SRT), SEQUENCE)
    assert [cue.index for cue in aligned] == [1, 2, 3]
    assert aligned[0].text == "抬头看，银河系就在我们身边"


def test_an_unknown_alignment_strategy_is_rejected():
    with pytest.raises(ValueError, match="align must be one of"):
        align_cues(parse_srt(SRT), "by-vibes")


@pytest.mark.parametrize(
    "kwargs", [{"min_duration": -1}, {"max_duration": 0}, {"min_duration": 9, "max_duration": 1}]
)
def test_a_nonsense_duration_window_is_rejected(kwargs):
    with pytest.raises(ValueError, match="sequence durations"):
        align_cues(parse_srt(SRT), SEQUENCE, **kwargs)


def test_aligning_an_empty_list_is_empty():
    assert align_cues([], SEQUENCE) == []


# ---------------------------------------------------------------------------
# Cues to canonical plan captions
# ---------------------------------------------------------------------------


def test_cues_become_frame_based_plan_captions():
    captions = cues_to_captions(parse_srt(SRT), 30)
    assert captions[0] == {"text": "抬头看，银河系就在我们身边", "start": 18, "duration": 51}
    assert captions[1]["start"] == 72


def test_a_sub_frame_cue_still_gets_one_frame():
    tiny = parse_srt("00:00:00,000 --> 00:00:00,010\nblink\n")
    assert cues_to_captions(tiny, 30)[0]["duration"] == 1


def test_captions_round_half_up_like_every_other_plan_conversion():
    # 0.05 s at 30 fps is 1.5 frames; the plan's rule rounds it up, so cue
    # conversion cannot use a second, different rounding.
    assert cues_to_captions(parse_srt("00:00:00,000 --> 00:00:00,050\na\n"), 30)[0]["duration"] == 2


def test_a_non_positive_fps_is_rejected():
    with pytest.raises(ValueError, match="finite and positive"):
        cues_to_captions(parse_srt(SRT), 0)


# ---------------------------------------------------------------------------
# prepare_import_params: what actually reaches the host
# ---------------------------------------------------------------------------


def test_timecode_alignment_is_a_pass_through(tmp_path):
    """The default must stay byte-identical to the previous behaviour."""
    source = write(tmp_path, "a.srt", SRT)
    params = prepare_import_params(
        {"path": str(source), "timeline_id": "t1", "offset": 1.0, "language": "zh-CN"}
    )
    assert params == {
        "path": str(source),
        "timeline_id": "t1",
        "offset": 1.0,
        "language": "zh-CN",
    }


def test_align_timecode_writes_nothing(tmp_path):
    source = write(tmp_path, "a.srt", SRT)
    prepare_import_params({"path": str(source), "align": "timecode"})
    assert sorted(path.name for path in tmp_path.iterdir()) == ["a.srt"]


def test_adapter_side_keys_never_reach_the_host(tmp_path):
    """A host that validates strictly would reject them; one that does not
    would silently ignore them. Either way, forwarding is wrong."""
    source = write(tmp_path, "a.srt", SRT)
    params = prepare_import_params(
        {"path": str(source), "align": "timecode", "output_path": str(tmp_path / "out.srt")}
    )
    assert "align" not in params
    assert "output_path" not in params


def test_sequence_alignment_writes_a_re_timed_srt_and_imports_that(tmp_path):
    source = write(tmp_path, "a.srt", SRT)
    target = tmp_path / "aligned" / "out.srt"

    params = prepare_import_params(
        {"path": str(source), "align": "sequence", "output_path": str(target)}
    )

    assert target.is_file()
    assert params["path"] == str(target)
    assert params["format"] == "srt"
    # The shift is already in the file; leaving the caller's offset in place
    # would apply it twice.
    assert params["offset"] == 0.0
    assert [cue.start for cue in parse_srt(target.read_text(encoding="utf-8"))] == [0.0, 1.7, 3.6]


def test_sequence_defaults_the_output_next_to_the_source(tmp_path):
    source = write(tmp_path, "a.srt", SRT)
    params = prepare_import_params({"path": str(source), "align": "sequence"})
    assert params["path"] == str(tmp_path / "a.aligned.srt")
    assert Path(params["path"]).is_file()


def test_sequence_honours_the_offset_as_its_starting_point(tmp_path):
    source = write(tmp_path, "a.srt", SRT)
    params = prepare_import_params({"path": str(source), "align": "sequence", "offset": 10.0})
    assert parse_srt(Path(params["path"]).read_text(encoding="utf-8"))[0].start == 10.0


def test_sequence_preserves_the_other_params(tmp_path):
    source = write(tmp_path, "a.srt", SRT)
    params = prepare_import_params(
        {
            "path": str(source),
            "timeline_id": "t1",
            "language": "zh-CN",
            "style": {"size": 48},
            "align": "sequence",
        }
    )
    assert params["timeline_id"] == "t1"
    assert params["language"] == "zh-CN"
    assert params["style"] == {"size": 48}


def test_sequence_creates_a_missing_output_directory(tmp_path):
    source = write(tmp_path, "a.srt", SRT)
    target = tmp_path / "nested" / "deeper" / "out.srt"
    prepare_import_params({"path": str(source), "align": "sequence", "output_path": str(target)})
    assert target.is_file()


def test_sequence_on_a_missing_file_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="subtitle file not found"):
        prepare_import_params({"path": str(tmp_path / "absent.srt"), "align": "sequence"})


def test_sequence_on_an_ass_file_refuses_rather_than_guessing(tmp_path):
    source = write(tmp_path, "a.ass", "[Script Info]\nDialogue: 0,0:00:01.00,0:00:02.00\n")
    with pytest.raises(SubtitleFormatError, match="offline subtitle parsing supports"):
        prepare_import_params({"path": str(source), "format": "ass", "align": "sequence"})


def test_sequence_rejects_an_unknown_strategy(tmp_path):
    source = write(tmp_path, "a.srt", SRT)
    with pytest.raises(ValueError, match="align must be one of"):
        prepare_import_params({"path": str(source), "align": "by-vibes"})


def test_prepare_requires_an_object():
    with pytest.raises(ValueError, match="import params must be an object"):
        prepare_import_params("not an object")
