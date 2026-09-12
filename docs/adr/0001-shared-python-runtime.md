# ADR 0001: Shared Python runtime for DCC adapters

- Status: Proposed
- Date: 2026-09-12

## Context

Multiple adapters need Python for MCP transport, typed skills, media tooling,
and lifecycle management. Requiring a system Python makes installation and
reproducibility fragile. At the same time, DCC-embedded Python interpreters
(Maya, Blender, Houdini, 3ds Max) have vendor-specific ABIs and must not be
replaced by a bundled interpreter inside the host process.

## Decision

Build a shared, out-of-process `dcc-mcp-runtime` per OS/architecture/Python
minor using PyOxidizer. Package `dcc-mcp-core`, the gateway/CLI client, bridge
protocol, observability, and common media helpers once. Ship each adapter as a
thin wheel/skill bundle loaded from `lib/site-packages` next to the runtime.

The runtime exposes a versioned typed adapter ABI and capability handshake:

```text
runtime_id, platform, arch, python_minor, core_version, adapter_id,
adapter_version, capabilities_fingerprint, artifact_sha256
```

Host-specific plugins remain separate. They communicate with the runtime over
the existing typed HTTP/JSON-RPC or stdio bridge and own their DCC API calls.
No bundled runtime is injected into a DCC process, and no adapter may expose
arbitrary Python execution as a public tool.

## PyOxidizer layout

Use the same pattern already proven by the OBS/Unity sidecars:

```text
dcc-mcp-runtime.exe
lib/                  # filesystem-relative Python resources
lib/site-packages/    # signed adapter wheels
runtime-manifest.json # ABI, hashes, platform, SBOM, signature
```

`resources_location = "filesystem-relative:lib"` and a module search path of
`$ORIGIN/lib/site-packages` keep the base executable immutable while allowing
adapter bundles to update independently. Release artifacts are signed and
verified before activation; upgrades are side-by-side and selected by a
manifest, with rollback to the previous verified bundle.

## Consequences

### Benefits

- One tested Python/Core baseline across CapCut, OBS, Unity, and future adapters.
- No user-managed Python installation for standalone sidecars.
- Smaller adapter packages and faster security updates to shared transport.
- Clear process boundary for DCC vendor ABI and license isolation.

### Costs and limits

- Build matrix expands to Windows/macOS/Linux and each supported architecture.
- Native dependencies (FFmpeg, Qt, vendor SDKs) still require per-adapter or
  per-host packaging and cannot be assumed portable.
- PyOxidizer build/debugging is more complex than a normal wheel or `uv` env.
- An adapter still needs a host plugin/bridge; the shared runtime cannot create
  missing DCC APIs.

## Alternatives considered

1. **System Python + uv** — best developer experience, but not a reliable
   end-user installation contract.
2. **One embedded interpreter injected into every DCC** — rejected because
   vendor Python ABIs, licensing, and host thread ownership differ.
3. **One monolithic executable containing every adapter** — rejected because
   it couples release cadence, increases attack surface, and makes capability
   ownership unclear.

## Rollout

1. Extract a runtime repository with a locked Core version and reproducible
   PyOxidizer build.
2. Migrate CapCut and OBS sidecars first; keep source/`uv` development paths.
3. Add manifest/hash/signature verification and a fresh-install smoke test.
4. Migrate additional external-bridge adapters, then evaluate embedded-host
   adapters individually rather than forcing them onto the runtime.
