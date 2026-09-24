# Host platform providers

Every Windows assumption the adapter used to hard-code — where the editor is
installed, how a running instance appears in a window inventory, what a
reviewable install plan looks like, and what the doctor reports when the host is
absent — now lives behind one `HostProvider` per platform. Callers
(`installer`, `bootstrap` window selection, and the doctor) dispatch through
`dcc_mcp_capcut.hosts.get_provider()` instead of branching on `os.name`.

The point is honest coverage: macOS users get a real diagnostic path instead of
`Windows-only; skipped`, and Linux users get an explicit conclusion instead of
an empty "not installed" they could mistake for a broken install.

## Support matrix

| Platform | `provider` | `supported` | Discovery | Install plan | Window inventory |
| --- | --- | --- | --- | --- | --- |
| Windows | `windows` | yes | `CapCut.exe` / `JianyingPro.exe` under `%LOCALAPPDATA%\<app>\Apps`, `%PROGRAMFILES%\<app>`, `%PROGRAMFILES(X86)%\<app>` | exact `winget install --id … --exact` command | `dcc-cua list`; a missing CLI is a failed prerequisite |
| macOS | `macos` | yes | `CapCut.app` / `JianyingPro.app` under `/Applications` and `~/Applications`; `Contents/Info.plist` supplies `CFBundleShortVersionString` and `CFBundleIdentifier` | `brew install --cask capcut` where a cask exists, otherwise the official download page | `dcc-cua list`; a missing CLI degrades to `warn` |
| Linux | `linux` | no | none | none; `status: unsupported` plus the reason | not attempted |

Windows verdicts and candidate-root ordering are unchanged by this refactor:
the same roots in the same order, the same flavour order (CapCut before
JianyingPro), the same plan shape and the same doctor output. One edge case did
move: the roots are now filtered *before* the install layout is appended, so a
machine with `LOCALAPPDATA` / `PROGRAMFILES` unset no longer yields relative
candidates such as `CapCut\Apps\CapCut.exe`. Those could never match a real
install and could match a directory in the current working directory.

## macOS specifics

- A bundle is installed even when its `Info.plist` cannot be read; the version
  then reports as `null` rather than failing discovery.
- 剪映专业版 has no Homebrew cask, so the plan offers only its official
  download page. No command is invented for a package that does not exist.
- Window binding on macOS needs **Accessibility permission** for the
  controlling app (System Settings > Privacy & Security > Accessibility). That
  is a user-side grant: the adapter reports the requirement in doctor hints and
  never requests, grants, or bypasses it.
- macOS window inventory names are bundle names (`CapCut`, `剪映专业版`), not
  Windows executable names (`CapCut.exe`). Flavour matching is per provider, so
  a Windows-shaped name is never treated as macOS evidence.

## Linux specifics

ByteDance publishes no official CapCut or 剪映 professional client for Linux.
The provider therefore reports:

- `detect_installation()` → `installed: false`, `unsupported: true`, and a
  `reason` string.
- `installation_plan()` → `status: "unsupported"`, `installer: null`, and
  `supported_platforms: ["Windows", "macOS"]`.
- doctor `capcut_executable` → `skip`, with `unsupported` and the reason in its
  detail, because the prerequisite does not apply to this platform.

## Verified host versions

`dcc_mcp_capcut.hosts.versions` is the machine-readable source of truth for
which host builds the adapter has actually been tested against. It replaces the
prose acceptance note in `native/qt-probe/README.md`, so `detect_installation()`
and the doctor can answer "is this build verified?" instead of reporting an
install as simply "found".

The table is keyed `platform x edition x version`: `SUPPORTED_HOST_VERSIONS`
holds one `HostVersion` per shipped build, with the Qt runtime it vendors and
the notes recording how acceptance was reached. `version_support(platform,
edition, version)` grades a discovered build and returns `status`, `listed`,
`known_versions`, `verified_builds`, `match` and `hint`.

| `status` | Meaning | Doctor severity |
| --- | --- | --- |
| `verified` | listed and acceptance-tested end to end | `ok` |
| `known` | listed as shipped, not acceptance-tested here | `ok` (with a hint) |
| `unknown` | discovered, but absent from the matrix | `warn` + hint |
| `undetermined` | discovered, but the version could not be read | `warn` + hint |
| `unsupported` | the platform ships no host at all | `skip` |

An unlisted build is a **warning, never a failure**: the adapter binds and
starts on it, and it is not honest to call that a broken install. The hint names
the build, the verified builds, and how to get the version added to the matrix.
Only two states skip — a platform with no host, and a platform where nothing is
installed yet, because there is then no build to grade.

Currently verified: Windows CapCut `9.4.0.4015` (Qt `6.2.2`). No macOS or
剪映专业版 build has been acceptance-tested yet, so those rows are empty rather
than assumed.

## Consent is unchanged

No provider installs anything. Every plan — WinGet, Homebrew cask, or official
download page — is evidence an operator approves through the same
`ui_control__system_operation` grant, and `verify_installation` is still the
only thing allowed to claim readiness.

## Testing a provider without the platform

`hosts.set_platform(name)` forces every caller onto one provider, and returns to
auto-detection with `set_platform(None)`. It exists for tests and diagnostics;
production code must leave it alone. Do not fake `os.name` instead:
`pathlib.Path` picks its flavour from `os.name` when it is constructed, so
faking it breaks unrelated path handling.
