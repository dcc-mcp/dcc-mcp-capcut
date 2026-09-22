# External ASR executor contract

`dcc-mcp-capcut` ships **no speech-to-text model** and downloads no weights.
Which ASR to run is your decision: it depends on language, hardware, licence and
whatever your upstream pipeline already uses. The adapter defines the seam and
calls whatever you point it at.

This document is the whole contract. An executor that follows it works with
`capcut-asr`'s `transcribe` today, and one that does not fails with a message
that names the problem.

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `DCC_MCP_CAPCUT_ASR_EXECUTOR` | yes, to transcribe | Path to **your** executable: a script, a binary, or a wrapper around a service. |
| `DCC_MCP_CAPCUT_ASR_TIMEOUT` | no | Seconds the executor may run. `1`–`3600`, default `600`. |

Unset means "not configured". `dcc-mcp-capcut-doctor` reports that as a `warn`
on the `asr_executor` check -- the adapter still starts, and only transcription
is unavailable. It is never reported as an empty transcript.

## Invocation

```text
<executor> <media> [--language <code>] --format <srt|json>
```

| Part | Notes |
| --- | --- |
| `<media>` | Absolute path to the media file, as `argv[1]`. |
| `--language <code>` | Present only when the caller supplied one, e.g. `zh-CN`. A hint, not a constraint -- ignore it if your engine detects language itself. |
| `--format <srt\|json>` | Always present. Which of the two output shapes to write. |

The adapter invokes this as an **argv list with `shell=False`**. Nothing you
receive is interpreted by a shell, so paths with spaces arrive intact and there
is no injection surface. stdin is closed.

## Output

Write the transcript to **stdout**, diagnostics to **stderr**, and exit `0`.

### `--format srt`

Standard SRT text on stdout:

```text
1
00:00:00,500 --> 00:00:02,000
first line

2
00:00:02,500 --> 00:00:04,000
second line
```

Both `,` and `.` are accepted as the millisecond separator, and the optional
numeric index line may be omitted.

### `--format json`

```json
{
  "language": "en-US",
  "segments": [
    {"start": 0.5, "end": 2.0, "text": "first line"},
    {"start": 2.5, "end": 4.0, "text": "second line"}
  ]
}
```

* `segments` is required and must be a non-empty list.
* `start` and `end` are float seconds, finite and `>= 0`, with `end >= start`.
* `text` is a string.
* `language` is optional; when present it overrides the hint.

Both shapes are normalised into the same result, so a caller never has to branch
on the format it asked for.

## Failure

Exit non-zero. The last non-empty line of your stderr is attached to the error,
because that is the line worth reading:

```text
ASR executor exited 3: model weights missing
```

## Errors you may see

| Message | Cause | Fix |
| --- | --- | --- |
| `no ASR executor configured: set DCC_MCP_CAPCUT_ASR_EXECUTOR ...` | The variable is unset or blank. | Set it. |
| `DCC_MCP_CAPCUT_ASR_EXECUTOR does not point at a file: ...` | Set, but the path is wrong or is a directory. | Fix the path. The adapter does not search `PATH`. |
| `ASR executor is not executable: ...` | POSIX file without the `+x` bit. | `chmod +x` it, or wrap it. |
| `ASR executor did not finish within Ns: ...` | Overran the budget. | Raise the timeout, or use a faster engine. |
| `ASR executor produced output that is not valid SRT: ...` | Exited `0` but stdout is not the requested format. | Honour `--format`. |
| `ASR executor JSON output requires a 'segments' list` | JSON shape is missing or wrong. | See the JSON section above. |
| `ASR executor exited N: ...` | Your script failed. | Read your own last stderr line. |
| `media file not found: ...` | The input path does not exist. | Fix it; this is checked before the executor runs. |

## Worked examples

### Python script (POSIX)

```python
#!/usr/bin/env python3
"""Emit a fixed transcript; swap the body for your engine."""

import sys

media = sys.argv[1]
fmt = sys.argv[sys.argv.index("--format") + 1]
language = None
if "--language" in sys.argv:
    language = sys.argv[sys.argv.index("--language") + 1]

segments = [{"start": 0.5, "end": 2.0, "text": "first line"}]

if fmt == "json":
    import json

    json.dump({"language": language, "segments": segments}, sys.stdout)
else:
    sys.stdout.write("1\n00:00:00,500 --> 00:00:02,000\nfirst line\n")

sys.stderr.write(f"transcribed {media} via the example executor\n")
```

```bash
chmod +x transcribe.py
export DCC_MCP_CAPCUT_ASR_EXECUTOR=/path/to/transcribe.py
```

### Windows

A bare `.py` is not executable on Windows, so point the variable at a `.cmd`
wrapper -- this is the same shape the project's own tests use:

```bat
@echo off
"C:\Python312\python.exe" "C:\path\to\transcribe.py" %*
```

```powershell
$env:DCC_MCP_CAPCUT_ASR_EXECUTOR = "C:\path\to\transcribe.cmd"
```

### Wrapping a service

Anything executable qualifies, including a wrapper that calls a hosted API:

```bash
#!/usr/bin/env bash
set -euo pipefail
media="$1"
curl -sS -F "file=@${media}" https://your-asr.example/v1/transcribe
```

## Trust boundary

The adapter runs a binary the operator named. That is the point of the seam --
and it is why the executor path is read **only** from the operator's own
environment or an explicit call argument. A plan document is data, and data
never names an executable.

## Verifying

```bash
dcc-mcp-capcut-doctor --fix-hints   # reports the asr_executor check
```

An `ok` on `asr_executor` means the path exists and, on POSIX, is executable. It
does not run your engine -- invoke `transcribe` for that.
