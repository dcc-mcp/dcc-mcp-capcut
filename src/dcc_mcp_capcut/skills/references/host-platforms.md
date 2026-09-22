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

Windows discovery and planning are unchanged by this refactor. Only the
packaging moved: the same candidate roots, the same flavour order (CapCut
before JianyingPro), and the same doctor verdicts.

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
