"""The external ASR executor seam.

Every test here runs a **fake executor**, not a model: a throwaway script that
obeys the documented contract. The adapter's job is the seam -- discovery,
argv, timeout, output validation, failure classification -- and a fake that
speaks the contract is what actually exercises it. Nothing in this file
downloads, imports or runs a speech engine.

The three paths the contract has to get right are success, timeout and
malformed output, plus the "nothing configured" case that must never look like
an empty transcript.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from dcc_mcp_capcut import asr

SRT_OUTPUT = textwrap.dedent(
    """\
    1
    00:00:00,500 --> 00:00:02,000
    first line

    2
    00:00:02,500 --> 00:00:04,000
    second line
    """
)

JSON_SEGMENTS = {
    "language": "en-US",
    "segments": [
        {"start": 0.5, "end": 2.0, "text": "first line"},
        {"start": 2.5, "end": 4.0, "text": "second line"},
    ],
}


@pytest.fixture
def media(tmp_path):
    target = tmp_path / "clip.wav"
    target.write_bytes(b"RIFF")
    return target


@pytest.fixture
def write_executor(tmp_path):
    """Materialise a fake executor and return it as a runnable file.

    The contract accepts *any* executable, so the test double has to be one
    on every platform CI runs. On POSIX that is a script with a shebang for
    the current interpreter; on Windows a bare ``.py`` is not executable, so
    the same body is launched through a ``.cmd`` wrapper -- which is also how
    a real Windows user would point the variable at a Python script.
    """

    def _make(body: str, name: str = "fake_asr") -> Path:
        source = tmp_path / f"{name}_body.py"
        source.write_text(textwrap.dedent(body), encoding="utf-8")

        if os.name == "posix":
            # Shebang plus the body in one executable file; the separate copy
            # is not used here, but keeping it means both platforms read the
            # same source text.
            path = tmp_path / name
            path.write_text(f"#!{sys.executable}\n{textwrap.dedent(body)}", encoding="utf-8")
            path.chmod(0o755)
            return path

        path = tmp_path / f"{name}.cmd"
        path.write_text(f'@"{sys.executable}" "{source}" %*\n', encoding="utf-8")
        return path

    return _make


def configure(monkeypatch, executor=None):
    if executor is None:
        monkeypatch.delenv(asr.ASR_EXECUTOR_ENV, raising=False)
    else:
        monkeypatch.setenv(asr.ASR_EXECUTOR_ENV, str(executor))
    monkeypatch.delenv(asr.ASR_TIMEOUT_ENV, raising=False)


# ---------------------------------------------------------------------------
# Discovery: what "not configured" means
# ---------------------------------------------------------------------------


def test_unset_executor_is_reported_as_unconfigured(monkeypatch):
    configure(monkeypatch)
    assert asr.configured_executor() is None
    with pytest.raises(asr.AsrNotConfiguredError, match="no ASR executor configured"):
        asr.resolve_executor()


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_a_blank_executor_value_counts_as_unset(monkeypatch, value):
    monkeypatch.setenv(asr.ASR_EXECUTOR_ENV, value)
    assert asr.configured_executor() is None
    with pytest.raises(asr.AsrNotConfiguredError):
        asr.resolve_executor()


def test_the_unconfigured_error_names_the_variable(monkeypatch):
    """The message has to be actionable on its own."""
    configure(monkeypatch)
    with pytest.raises(asr.AsrNotConfiguredError) as caught:
        asr.resolve_executor()
    assert asr.ASR_EXECUTOR_ENV in str(caught.value)
    assert "no model" in str(caught.value)


def test_a_configured_path_that_is_not_a_file_is_missing(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path / "nope.py")
    with pytest.raises(asr.AsrExecutorMissingError, match="does not point at a file"):
        asr.resolve_executor()


def test_a_directory_is_not_an_executor(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    with pytest.raises(asr.AsrExecutorMissingError):
        asr.resolve_executor()


@pytest.mark.skipif(os.name != "posix", reason="the executable bit is a POSIX rule")
def test_a_non_executable_file_is_reported_as_missing(monkeypatch, write_executor):
    path = write_executor("print('')")
    path.chmod(0o644)
    configure(monkeypatch, path)
    with pytest.raises(asr.AsrExecutorMissingError, match="not executable"):
        asr.resolve_executor()


def test_an_explicit_executor_argument_overrides_the_environment(
    monkeypatch, write_executor, tmp_path
):
    """A call may name its own executor; the env var is only the default."""
    good = write_executor("print('')")
    configure(monkeypatch, tmp_path / "not-used.py")
    assert asr.resolve_executor(str(good)) == good


# ---------------------------------------------------------------------------
# The argv contract
# ---------------------------------------------------------------------------


def test_the_command_is_an_argv_list_and_never_a_shell_string(write_executor, media):
    executor = write_executor("print('')")
    command = asr.build_command(executor, media)
    assert command[0] == str(executor)
    assert command[1] == str(media)
    assert command[-2:] == ["--format", "srt"]
    assert all(isinstance(part, str) for part in command)


def test_language_and_format_are_forwarded(write_executor, media):
    command = asr.build_command(write_executor(""), media, language="zh-CN", output_format="json")
    assert command[2:4] == ["--language", "zh-CN"]
    assert command[4:6] == ["--format", "json"]


def test_language_is_omitted_when_not_supplied(write_executor, media):
    assert "--language" not in asr.build_command(write_executor(""), media)


def test_an_unknown_output_format_is_rejected(write_executor, media):
    with pytest.raises(ValueError, match="output_format must be one of"):
        asr.build_command(write_executor(""), media, output_format="vtt")


# ---------------------------------------------------------------------------
# Timeout resolution
# ---------------------------------------------------------------------------


def test_the_default_timeout_applies_without_configuration(monkeypatch):
    monkeypatch.delenv(asr.ASR_TIMEOUT_ENV, raising=False)
    assert asr.resolve_timeout() == asr.DEFAULT_TIMEOUT


def test_the_environment_supplies_the_timeout(monkeypatch):
    monkeypatch.setenv(asr.ASR_TIMEOUT_ENV, "42.5")
    assert asr.resolve_timeout() == 42.5


def test_an_explicit_timeout_beats_the_environment(monkeypatch):
    monkeypatch.setenv(asr.ASR_TIMEOUT_ENV, "999")
    assert asr.resolve_timeout(5) == 5


@pytest.mark.parametrize("value", ["0", "-1", "0.5", "99999", "abc"])
def test_a_timeout_outside_the_allowed_window_is_rejected(monkeypatch, value):
    monkeypatch.setenv(asr.ASR_TIMEOUT_ENV, value)
    with pytest.raises((ValueError, TypeError)):
        asr.resolve_timeout()


def test_a_blank_timeout_environment_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv(asr.ASR_TIMEOUT_ENV, "   ")
    assert asr.resolve_timeout() == asr.DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


def test_an_srt_executor_produces_normalised_segments(monkeypatch, write_executor, media):
    executor = write_executor(
        f"""
        import sys
        sys.stdout.write({SRT_OUTPUT!r})
        """
    )
    configure(monkeypatch, executor)

    transcript = asr.transcribe(str(media))

    assert [segment.text for segment in transcript.segments] == ["first line", "second line"]
    assert [segment.start for segment in transcript.segments] == [0.5, 2.5]
    assert transcript.output_format == "srt"
    assert transcript.executor == str(executor)
    assert transcript.duration == 4.0


def test_a_json_executor_produces_the_same_normalised_shape(monkeypatch, write_executor, media):
    """Both output formats collapse into one shape, so callers never branch."""
    payload = json.dumps(JSON_SEGMENTS)
    executor = write_executor(
        f"""
        import sys
        sys.stdout.write({payload!r})
        """
    )
    configure(monkeypatch, executor)

    transcript = asr.transcribe(str(media), output_format="json", language="en-US")

    assert transcript.language == "en-US"
    assert [segment.text for segment in transcript.segments] == ["first line", "second line"]
    assert transcript.output_format == "json"
    # The normalised result renders back to the same SRT the other format emits.
    assert transcript.srt.splitlines()[1].startswith("00:00:00,500 --> 00:00:02,000")


def test_transcript_cues_are_numbered_from_one(monkeypatch, write_executor, media):
    executor = write_executor(f"import sys; sys.stdout.write({SRT_OUTPUT!r})")
    configure(monkeypatch, executor)
    assert [cue.index for cue in asr.transcribe(str(media)).cues] == [1, 2]


def test_a_missing_media_file_is_reported_before_the_executor_is_resolved(
    monkeypatch, write_executor, tmp_path
):
    """A path typo must not masquerade as an executor failure."""
    configure(monkeypatch, write_executor("print('')"))
    with pytest.raises(asr.AsrExecutionError, match="media file not found"):
        asr.transcribe(str(tmp_path / "absent.wav"))


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


def test_an_executor_that_overruns_its_budget_raises_a_timeout(monkeypatch, write_executor, media):
    # 5 s against a 1 s budget: comfortably over the limit, and short enough
    # that a platform where killing the wrapper leaves the child running does
    # not turn the suite into a minute-long wait.
    executor = write_executor(
        """
        import time
        time.sleep(3)
        """
    )
    configure(monkeypatch, executor)

    with pytest.raises(asr.AsrTimeoutError) as caught:
        asr.transcribe(str(media), timeout=1.0)

    message = str(caught.value)
    assert "did not finish within 1s" in message
    assert str(executor) in message
    assert isinstance(caught.value, asr.AsrError)


def test_a_timeout_is_not_reported_as_a_format_error(monkeypatch, write_executor, media):
    executor = write_executor("import time; time.sleep(3)")
    configure(monkeypatch, executor)
    with pytest.raises(asr.AsrTimeoutError):
        asr.transcribe(str(media), timeout=1.0)


# ---------------------------------------------------------------------------
# Failure: non-zero exit
# ---------------------------------------------------------------------------


def test_a_failing_executor_surfaces_its_own_stderr(monkeypatch, write_executor, media):
    executor = write_executor(
        """
        import sys
        sys.stderr.write("noise\\nmodel weights missing\\n")
        sys.exit(3)
        """
    )
    configure(monkeypatch, executor)

    with pytest.raises(asr.AsrExecutionError) as caught:
        asr.transcribe(str(media))

    message = str(caught.value)
    assert "exited 3" in message
    # The last line is the actionable one; earlier noise is dropped.
    assert "model weights missing" in message
    assert "noise" not in message


def test_an_executor_that_writes_no_stderr_still_names_its_exit_code(
    monkeypatch, write_executor, media
):
    executor = write_executor("import sys; sys.exit(1)")
    configure(monkeypatch, executor)
    with pytest.raises(asr.AsrExecutionError, match="exited 1"):
        asr.transcribe(str(media))


# ---------------------------------------------------------------------------
# Failure: malformed output
# ---------------------------------------------------------------------------


def test_empty_stdout_is_a_format_error_not_an_empty_transcript(monkeypatch, write_executor, media):
    """The whole point of failing closed: silence is not a transcript."""
    executor = write_executor("pass")
    configure(monkeypatch, executor)
    with pytest.raises(asr.AsrFormatError, match="not valid SRT"):
        asr.transcribe(str(media))


def test_non_srt_prose_is_a_format_error(monkeypatch, write_executor, media):
    executor = write_executor("print('I refuse to transcribe')")
    configure(monkeypatch, executor)
    with pytest.raises(asr.AsrFormatError, match="not valid SRT"):
        asr.transcribe(str(media))


def test_unparseable_json_is_a_format_error(monkeypatch, write_executor, media):
    executor = write_executor("print('{not json')")
    configure(monkeypatch, executor)
    with pytest.raises(asr.AsrFormatError, match="not valid JSON"):
        asr.transcribe(str(media), output_format="json")


@pytest.mark.parametrize(
    "payload",
    [
        "[]",  # not an object
        "{}",  # no segments
        '{"segments": {}}',  # segments is not a list
        '{"segments": []}',  # no segments at all
        '{"segments": [1]}',  # segment not an object
        '{"segments": [{"start": 0, "end": 1}]}',  # text missing
        '{"segments": [{"start": "x", "end": 1, "text": "a"}]}',  # start not a number
        '{"segments": [{"start": 5, "end": 1, "text": "a"}]}',  # ends before it starts
        '{"segments": [{"start": -1, "end": 1, "text": "a"}]}',  # negative time
        '{"segments": [{"start": 0, "end": 1, "text": 7}]}',  # text not a string
    ],
)
def test_json_shapes_that_cannot_be_a_transcript_are_rejected(
    monkeypatch, write_executor, media, payload
):
    executor = write_executor(f"print({payload!r})")
    configure(monkeypatch, executor)
    with pytest.raises(asr.AsrFormatError):
        asr.transcribe(str(media), output_format="json")


def test_a_non_string_language_is_rejected(monkeypatch, write_executor, media):
    payload = '{"language": 7, "segments": [{"start": 0, "end": 1, "text": "a"}]}'
    executor = write_executor(f"print({payload!r})")
    configure(monkeypatch, executor)
    with pytest.raises(asr.AsrFormatError, match="language must be a string"):
        asr.transcribe(str(media), output_format="json")


def test_a_format_error_is_not_a_configuration_error(monkeypatch, write_executor, media):
    """Distinct failure classes exist so the caller's next action differs."""
    configure(monkeypatch, write_executor("print('garbage')"))
    with pytest.raises(asr.AsrFormatError):
        asr.transcribe(str(media))
    # A path the operator set but that cannot be run is a different class again:
    # "configure it" and "fix it" are different instructions.
    with pytest.raises(asr.AsrExecutorMissingError):
        asr.resolve_executor(str(media.parent / "absent"))


# ---------------------------------------------------------------------------
# The documented contract, verified end to end through a real subprocess
# ---------------------------------------------------------------------------


def test_the_executor_receives_the_documented_arguments(monkeypatch, write_executor, media):
    """argv[1] is the media, and --language / --format arrive as documented."""
    spy = write_executor(
        """
        import json, sys
        sys.stdout.write(json.dumps({
            "language": "en",
            "segments": [{"start": 0.0, "end": 1.0, "text": " ".join(sys.argv[1:])}],
        }))
        """
    )
    configure(monkeypatch, spy)

    transcript = asr.transcribe(str(media), language="en-US", output_format="json")

    received = transcript.segments[0].text
    assert received.startswith(str(media))
    assert "--language en-US" in received
    assert "--format json" in received


def test_stderr_does_not_pollute_a_successful_transcript(monkeypatch, write_executor, media):
    executor = write_executor(
        f"""
        import sys
        sys.stderr.write("warning: using cpu\\n")
        sys.stdout.write({SRT_OUTPUT!r})
        """
    )
    configure(monkeypatch, executor)
    assert len(asr.transcribe(str(media)).segments) == 2


def test_the_contract_survives_the_python_the_tests_run_on(write_executor, media):
    """The fake executor runs on sys.executable, so this is not version-bound."""
    executor = write_executor(
        f"""
        import sys
        assert sys.executable, "the fake executor needs the current interpreter"
        sys.stdout.write({SRT_OUTPUT!r})
        """
    )
    assert asr.transcribe(str(media), executor=str(executor)).segments[0].text == "first line"
    assert Path(sys.executable).is_file()


# ---------------------------------------------------------------------------
# Regressions: a transcript must not be re-parsed from its own rendering
# ---------------------------------------------------------------------------


def test_an_empty_text_segment_still_transcribes(monkeypatch, write_executor, media):
    """An empty segment renders an SRT block with no text line; re-parsing that
    block rejects it, so a successful transcription must not round-trip."""
    payload = '{"segments": [{"start": 0.0, "end": 1.0, "text": ""}]}'
    executor = write_executor(f"print({payload!r})")
    configure(monkeypatch, executor)

    transcript = asr.transcribe(str(media), output_format="json")

    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == ""
    # transcript.cues is the normalised source; transcript.srt is the rendering.
    assert transcript.cues[0].text == ""


def test_transcribe_reports_captions_for_an_empty_text_segment(monkeypatch, write_executor, media):
    """The skill derives captions from the transcript, never from its own SRT."""
    import importlib.util

    payload = '{"segments": [{"start": 0.0, "end": 1.0, "text": ""}]}'
    executor = write_executor(f"print({payload!r})")
    monkeypatch.setenv(asr.ASR_EXECUTOR_ENV, str(executor))

    spec = importlib.util.spec_from_file_location(
        "transcribe_skill",
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_capcut"
        / "skills"
        / "capcut-asr"
        / "scripts"
        / "transcribe.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.main(media=str(media), output_format="json", fps=30)

    assert result["success"] is True
    assert result["context"]["captions"] == [{"text": "", "start": 0, "duration": 30}]


def test_a_segment_text_with_a_blank_line_survives_transcription(
    monkeypatch, write_executor, media
):
    """A blank line would split one cue into two blocks on re-parse."""
    payload = '{"segments": [{"start": 0.0, "end": 1.0, "text": "one\\n\\ntwo"}]}'
    executor = write_executor(f"print({payload!r})")
    configure(monkeypatch, executor)

    transcript = asr.transcribe(str(media), output_format="json")

    assert len(transcript.segments) == 1
    assert transcript.cues[0].text == "one\n\ntwo"
