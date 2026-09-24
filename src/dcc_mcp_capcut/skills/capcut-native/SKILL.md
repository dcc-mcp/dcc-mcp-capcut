---
name: capcut-native
description: Inspect a connected native Qt probe without claiming desktop editing support.
license: MIT
compatibility: "Optional matching Qt 6 probe; Windows, macOS, Linux protocol"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.4.0", layer: domain, stage: scene, tags: "capcut, native, qt, diagnostics", tools: tools.yaml}  # x-release-please-version
---

The operator must configure the optional probe endpoint, token, executable hash,
and exact host PID. These tools never launch, inject, install, or modify the host.
Inspecting Qt metadata does not prove access to CapCut projects or editor commands.
Object IDs are local to each response, not handles for later invocation.

## When to use

- Diagnosing how a CapCut release composes its Qt UI, before deciding whether a
  host integration is feasible.
- Confirming that a Qt probe build actually loaded in a specific host process.

Do **not** use this skill to edit. It exposes no editing, TTS, export, property
value read, or invocation capability.

## Prerequisites

All four variables below must be set; the probe is otherwise unavailable and
`capcut-native` stays unusable by design. The probe binary itself is a separate
build requirement, not a variable — see the paragraph after the table.

| Variable | Requirement |
| --- | --- |
| `DCC_CAPCUT_PROBE_ENDPOINT` | Path to the endpoint JSON written by the host at launch |
| `DCC_CAPCUT_PROBE_TOKEN` | Random secret of at least 32 bytes |
| `DCC_CAPCUT_PROBE_EXE_SHA256` | 64 lowercase hex characters of the intended executable |
| `DCC_MCP_CAPCUT_PID` | Decimal PID of the bound CapCut host |

You also need a probe binary built against the **matching** Qt SDK (CI pins Qt
`6.2.2`, Qt6 `Core`/`Gui`/`Network`) and loaded by the host — either through the
generic plugin loader or `qttestability`, launched with
`-testability --dcc-capcut-probe-config <absolute-json-path>`. Loading requires a
new host process; the probe does not attach to a running one. The endpoint file
carries port, PID, version, and executable hash — never the token. Keep it
private and delete stale files after the host exits.

See `native/qt-probe/README.md` for the full build, load, and distribution
procedure.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `describe_qt_host` | no | yes | Probe identity and read-only capabilities. |
| `inspect_qt_objects` | no | yes | Bounded Qt object and method metadata; `max_nodes` 1..5000 (default 500), `max_depth` 0..20 (default 8). |

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `Qt probe is not configured; no native capabilities established` | `DCC_CAPCUT_PROBE_ENDPOINT` or a >=32-byte token is missing. | Configure the probe environment, or use the panel-backed skills instead. The doctor reports this as `warn`, not `fail`: the adapter still starts. |
| `Qt probe requires an explicit host PID and executable SHA-256` | The hash is not 64 lowercase hex, or the PID is missing/non-decimal. | Supply both for the bound host. |
| `Qt probe endpoint file is missing; start the host to write it` | `DCC_CAPCUT_PROBE_ENDPOINT` points at a path the host has not written, or the last host deleted it on exit. | Start the host with the probe configured so it writes a fresh endpoint file; the probe does not attach to a running process. Re-check the path for typos. |
| `Qt probe endpoint could not be read` | The endpoint file exists but the process cannot open it (permissions, or a directory at that path). | Fix the path and its permissions, then restart the host. |
| `Invalid Qt probe endpoint` | The endpoint file is present but is not a JSON object (truncated, empty, or not JSON at all). | Restart the host to rewrite the endpoint; do not hand-edit it. |
| `Qt probe endpoint does not match the bound host` | The endpoint describes a different PID or executable hash, or the protocol is not 1. | Restart the host to write a fresh endpoint file; delete stale endpoints. |
| `Qt probe response does not match the bound host` | The response's PID, hash, `backend`, or `verification_scope` is wrong. | Confirm the probe build and the bound host match. |
| `Qt probe rejected the metadata request` | Bad authorization or an unsupported operation. | Check the shared token and the `max_nodes` / `max_depth` bounds. |
| `Qt probe endpoint exceeds size limit` | The endpoint file is over 4 KiB. | Regenerate it; a legitimate endpoint is a few hundred bytes. |
| Host never loads the plugin | The vendor Qt build may lack `QGenericPlugin::staticMetaObject`, or the app rejects third-party libraries. | Use the `qttestability` loader. There is no injection fallback. |

## Acceptance

- `describe_qt_host` returned probe identity with `backend: "qt-probe"` and
  `verification_scope: "qt_metadata"`.
- `inspect_qt_objects` returned metadata bounded by the requested `max_nodes`
  and `max_depth`, with the response repeating the bound host's PID and
  executable hash.
- Object counts are reported as **metadata**, never as editing capability.
- Before publishing any probe bundle, record its SHA-256, architecture, compiler
  ABI, Qt version, probe protocol, and exact host-build acceptance evidence.

## Boundaries

- Metadata only. This skill does not establish access to CapCut projects, editor
  commands, TTS, export, property values, or arbitrary invocation.
- Object IDs are snapshot-local indices, not handles for later use.
- Matching Qt version strings are necessary but are **not** proof of vendor ABI
  compatibility.
- The probe reads this user's environment for its token; it is not a security
  boundary against another process that can already do so.
- CapCut host acceptance is a separate test from the CI fixture. Fixture success
  on macOS or Linux does not imply a CapCut release for that platform exists.
- This change supplies source and build tests, **not** a production native
  release. No Qt binary ships in the wheel; distributing a probe bundle carries
  the license obligations of the Qt SDK you built against.

## References

- [dependencies and notices](../references/dependencies-and-notices.md)
- [host boundary](../references/host-boundary.md)
- [troubleshooting](../references/troubleshooting.md)
