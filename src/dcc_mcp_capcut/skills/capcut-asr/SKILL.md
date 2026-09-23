---
name: capcut-asr
description: Transcribe audio or video through an external ASR executor you supply, and hand the result to the subtitle chain.
license: MIT
compatibility: "CapCut Desktop; any platform; dcc-mcp-core 0.20.21+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.2.0", layer: domain, stage: scene, tags: "capcut, asr, transcription, subtitles", tools: tools.yaml}  # x-release-please-version
---

This skill is a **seam**, not an engine. Which speech-to-text to use is your
decision -- it depends on language, hardware, licence and whatever your upstream
pipeline already runs -- so the adapter ships no model, downloads no weights and
pulls in no heavy dependency. You point `DCC_MCP_CAPCUT_ASR_EXECUTOR` at your
own transcribe script; the adapter validates the request, runs it, and
normalises the result into segments, SRT and canonical plan captions.

Nothing here touches CapCut. The skill is host-free and works on every platform,
which is the point: transcription happens *before* assembly, and the result is
just another file the plan or `capcut-text` can consume.

## Prerequisites

- `DCC_MCP_CAPCUT_ASR_EXECUTOR` set to an executable file you control. On macOS
  and Linux it must also carry the executable bit.
- That script must honour the contract in
  [docs/asr-executor.md](../../../docs/asr-executor.md):

  ```text
  <executor> <media> [--language <code>] --format <srt|json>
  ```

  stdout carries the transcript, stderr carries diagnostics, exit `0` means
  success.
- Run `dcc-mcp-capcut-doctor --fix-hints` to confirm the executor is discovered
  and runnable. When unset, the doctor reports `asr_executor` as a `warn` --
  the adapter still starts, and only this skill is unavailable.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `transcribe` | no (unless `output_path`) | yes | `media` plus optional `language`, `output_format`, `timeout`, `output_path`, `fps`, `executor`. |

Supply `fps` to also get `captions` back as canonical plan captions in integer
frames, ready to drop into a `dcc-mcp-capcut/edit-plan/v1` document. Supply
`output_path` to write the SRT so `capcut-text`'s `import_subtitles` can import
it directly.

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `no ASR executor configured: set DCC_MCP_CAPCUT_ASR_EXECUTOR ...` | The seam has nothing to call. | Set the variable to your transcribe script. The adapter will not pick one for you. |
| `DCC_MCP_CAPCUT_ASR_EXECUTOR does not point at a file: ...` | The variable is set but the path is wrong. | Fix the path. Resolve it yourself first; the adapter does not search `PATH`. |
| `ASR executor is not executable: ...` | POSIX file without the `+x` bit. | `chmod +x` it, or wrap it: `sh /path/to/script`. |
| `ASR executor did not finish within Ns: ...` | The run exceeded the budget. | Raise `timeout` or `DCC_MCP_CAPCUT_ASR_TIMEOUT` (max 3600 s), or use a faster engine. |
| `ASR executor produced output that is not valid SRT: ...` | It exited `0` but the stdout is not the format it was asked for. | Check the script honours `--format`; the adapter refuses to guess. |
| `ASR executor JSON output requires a 'segments' list` | JSON shape is missing or wrong. | Emit `{"segments": [{"start": 0.0, "end": 1.2, "text": "..."}]}`. |
| `ASR executor exited N: ...` | The script failed. The last stderr line is included. | Read that line; the executor is yours to debug. |
| `media file not found: ...` | The path being transcribed does not exist. | Fix the path. This is checked before the executor is resolved. |

## Acceptance

- `transcribe` returned a non-empty `segments` list with finite, non-negative
  `start`/`end` values where `end >= start`.
- `srt` is present and parses back to the same number of cues.
- When `fps` was supplied, `captions` is present and every `duration` is at
  least 1 frame.
- When `output_path` was supplied, that file exists and holds the SRT.
- Re-running with the same inputs produces the same output.

## Boundaries

- **No model is bundled and none is downloaded.** The adapter defines the
  contract and runs what you name. It will not choose an engine for you or
  install one behind your back.
- The executor is invoked as an argv list with `shell=False`. Nothing it
  receives is interpreted by a shell, and no plan document may name one: an
  executor path comes from the operator's environment or an explicit call
  argument, never from data.
- Transcription quality is the executor's. `segments` are returned as reported
  and are **not** a verified transcript -- do not publish them unreviewed.
- The timeout is a wall-clock budget for the whole run. A script that streams
  partial results is still one call here.
- This skill never mutates a CapCut project. Feeding the result into a timeline
  is `capcut-text` or `capcut-assemble`.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [dependencies and notices](../references/dependencies-and-notices.md)
- [troubleshooting](../references/troubleshooting.md)
