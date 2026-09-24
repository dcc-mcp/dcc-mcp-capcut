# Upstream handoff example

The worked example for `references/upstream-handoff.md`: what a system that
generates material **upstream** of this adapter delivers, and what the adapter
does with it.

```text
upstream-delivery/
├── asset-manifest.json     what the files are, and who must be credited
├── edit-plan.json          the cut: dcc-mcp-capcut/edit-plan/v1
├── assets/                 the media, at the portable paths the plan records
└── captions/               subtitle files, same rule
```

This directory is the default delivery root, so no arguments are needed:

```powershell
python demo/upstream_handoff.py                    # stages 1-5, host-free
python demo/upstream_handoff.py --json             # machine-readable verdict
python demo/upstream_handoff.py --dispatch         # stage 6, needs a host
python demo/upstream_handoff.py --media-dir PATH   # a real delivery
```

## Stages

| Stage | Host | What it proves |
| --- | --- | --- |
| 1 load | no | the delivery carries both handoff documents |
| 2 reconcile | no | declared, present, explained — before any dispatch |
| 3 compile | no | the plan is a valid canonical plan |
| 4 OTIO round trip | no | the plan survives portable interchange |
| 5 dry run | no | the exact action script, without touching the host |
| 6 dispatch (`--dispatch`) | **yes** | the plan lands in a CapCut project |

Stage 6 needs a bound CapCut window — run `capcut-setup` first.

## Placeholder media

The checked-in delivery ships the two handoff documents and a real subtitle
file, but **no media bytes**. The contract under test is that every referenced
path resolves inside the delivery root and that the plan compiles — not that
pixels decode. Absent media are materialised as zero-byte placeholders so the
example runs offline; they are gitignored, and `--no-materialize` reports them
as missing instead, which is what you want when validating a real delivery:

```powershell
python demo/upstream_handoff.py --no-materialize
```

For a renderable run, fetch real footage into `demo/upstream-delivery/assets/`
— the plan's paths are relative to the delivery root, so `demo/assets/` is the
wrong directory (it is also gitignored). Then dispatch:

```powershell
python demo/upstream_handoff.py --no-materialize   # prove every file is real
python demo/upstream_handoff.py --dispatch         # stage 6, needs a bound host
```

`--dispatch` refuses to run while placeholders exist, so a run that materialised
placeholder media cannot mutate a real project with empty files.

## Platform differences

Stages 1-5 are identical everywhere — pure computation over two JSON documents
and a directory listing, with no platform-specific path handling beyond
`pathlib`.

Stage 6 differs, and the difference is entirely in host binding, not in this
example:

| | Windows | macOS |
| --- | --- | --- |
| Host binding | `DCC_MCP_CAPCUT_PID` and `DCC_MCP_CAPCUT_WINDOW_HANDLE` from the `dcc-cua` window inventory | same, **plus Accessibility permission** for the controlling app (System Settings > Privacy & Security > Accessibility) |
| Install route | `winget install --id ByteDance.CapCut --exact` | `brew install --cask capcut`, or the official download page |
| Inventory CLI | `dcc-cua` on `PATH` | `dcc-cua` support still being validated; the doctor warns instead of failing when it is absent |
| Linux | unsupported — no official client, so there is no host to bind | |

The Accessibility grant is a user-side decision: the adapter reports the
requirement and never requests, grants, or bypasses it. See
`references/host-platforms.md` for the full matrix.

## Attribution

`attribution` in the manifest is a delivery obligation, not something the
adapter acts on — it never writes a credit line into a render. Before
publishing anything built from this example, carry the credit lines named in
`asset-manifest.json` through to the published work.
