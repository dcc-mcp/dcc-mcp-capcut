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
| `dcc-mcp-core` | `>=0.19.13,<1.0.0`; doctor floor `0.19.13` | MIT | No — resolved from PyPI at install time |
| `opentimelineio` | `>=0.16,<1` (optional extra `interchange`) | Apache-2.0 | No — optional extra, resolved from PyPI |

Neither dependency is vendored or modified here. Their licenses apply to the
packages you install, and only to those packages.

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
