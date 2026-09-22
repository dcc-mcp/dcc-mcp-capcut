# Dependencies and notices

Verified against the pins in `pyproject.toml`, the installed distribution
metadata, `.github/workflows/qt-probe.yml`, and `demo/assets.json`. Re-verify
every row when a pin, an SDK, or a demo asset changes; do not copy license text
from an older release.

## This package

| Item | License | Notes |
| --- | --- | --- |
| `dcc-mcp-capcut` (this adapter, including bundled skills) | MIT | See the repository `LICENSE`. |

## Python dependencies

| Dependency | Pin | License | Distributed in this wheel? |
| --- | --- | --- | --- |
| `dcc-mcp-core` | `>=0.19.90,<1.0.0`; doctor floor `0.19.90`; CI-verified `0.19.90` and `0.20.21` (see below) | MIT | No — resolved from PyPI at install time |
| `opentimelineio` | `>=0.16,<1` (optional extra `interchange`) | Apache-2.0 | No — optional extra, resolved from PyPI |

Neither dependency is vendored or modified here. Their licenses apply to the
packages you install, and only to those packages.

### `dcc-mcp-core` floor

The declared install floor is `0.19.90`. It was raised from `0.19.13` after
measurement, and the reason is recorded here so the number is never moved back
without new evidence:

| Version | `DccServerOptions.from_env` has `instance_type` | Measured on this adapter |
| --- | --- | --- |
| `0.19.13` | n/a | **Not on PyPI.** No such release exists, so the old floor could not be installed as written. |
| `0.19.45` | **No** | **2 failed / 199 passed** — `TypeError: DccServerOptions.from_env() got an unexpected keyword argument 'instance_type'` at `src/dcc_mcp_capcut/server.py:38` |
| `0.19.90` | **Yes** (introduced here) | **201 passed** — the declared floor, and the lowest usable 0.19.x |
| `0.20.21` | Yes | **201 passed** — the version the `skill-contract` lint job pins |

There is no 0.19.x release between `0.19.45` and `0.19.90` on PyPI, so `0.19.90`
is the exact boundary: `instance_type` is what the adapter needs and `0.19.90`
is the first version that has it. `0.19.90` still declares
`requires_python>=3.7` and ships `cp37` wheels, so the Python 3.7 line is
unaffected.

Supporting `0.19.45` by omitting `instance_type` was considered and rejected:
the attribute does not exist there, so the adapter would silently drop the GUI
instance declaration that core writes into `instance_metadata` for discovery.
That would remove the guard rather than satisfy it.

The `core-floor` CI job pins one version at a time and reports `USABLE`,
`NOT USABLE`, `NOT RESOLVABLE`, or `NOT INSTALLABLE` in its job summary. Both
supported floors (`0.19.90`, `0.20.21`) are blocking; the `0.19.13` entry is
report-only and documents the phantom floor it replaced. Do not close a gap by
relaxing that job or by deleting a lane.

Skill `compatibility` declares `dcc-mcp-core 0.20.21+`, the combination the
`skill-contract` lint job pins; the install floor is the lower bound, not the
recommended version.

## Native and external run-time dependencies (not bundled)

| Dependency | Used by | License | Notes |
| --- | --- | --- | --- |
| FFmpeg / ffprobe | `demo/render_vlog.py`; operator-side validation of exported renders (`ffprobe` in `capcut-export` acceptance) | LGPL or GPL depending on the build | External binaries resolved from `PATH`; never shipped with this wheel. Export verification is an operator-side validation dependency: the adapter only calls `ffprobe` through documented acceptance steps, it does not vendor or redistribute it. Run `ffmpeg -version` to read the exact license and configuration of the build you use. |
| Qt SDK (Qt6 `Core`, `Gui`, `Network`) | build/test of the optional native probe in `native/qt-probe` | LGPLv3 / GPLv2+ / commercial, depending on the SDK you build with | CI pins Qt `6.2.2`. No Qt binary ships in this wheel. A published probe bundle inherits the obligations of the SDK it was built against — confirm your SDK's license before distributing one. |
| CapCut Desktop | the whole adapter | Proprietary, closed source | A run-time dependency. Not distributed, not modified, not reverse engineered. Installed with the operator-confirmed `winget install --id ByteDance.CapCut --exact` plan. |
| `dcc-mcp-runtime` | the `dcc-mcp-capcut-runtime` entry point | Distributed as a separately verified bundle | Not a PyPI dependency; the runtime entry point refuses to start without it. |

## Demo media

`demo/assets.json` is the authoritative record for every demo asset. In summary:

- NASA/JPL stills and video used by the vlog recipe are released as public-domain
  US Government work. Public-domain status is asserted **per asset** on its
  source page — verify the specific asset before publishing anything outside
  this repository.
- Retain source and credit metadata with any derivative, and verify third-party
  marks (logos, insignia, recognizable branding) before publishing.
- The demo background music is generated locally by `demo/render_vlog.py` from
  FFmpeg sine sources. It carries no third-party rights; the rendering FFmpeg
  build's own license still applies to the encoded output.

## Boundary statement

Having this skill installed grants no additional rights:

- It does not grant access to the `dcc-mcp-core` repository, its issue tracker,
  or any internal system; only the published package is consumed.
- It does not grant a CapCut license, a CapCut SDK, or permission to
  redistribute CapCut.
- It does not grant consent to install software, mutate the host, or bind a
  window that was not explicitly selected. Every install/configure action still
  requires an operator-owned grant.
- It does not turn Qt metadata inspection into editing capability. See
  `capcut-native/SKILL.md`.

## See also

- `host-boundary.md` — the external-bridge boundary and the bridge contract.
- `export-and-verification.md` — verification and export acceptance.
- `troubleshooting.md` — symptom to cause to remediation.
