# dcc-mcp-capcut

Typed MCP adapter for CapCut Desktop. CapCut has no stable public Python API,
so this adapter uses a localhost, token-authenticated bridge and a bundled
CapCut-side panel. MCP calls remain typed and auditable; the panel is the only
component allowed to invoke CapCut host APIs.

## Host platforms

Host binding is dispatched through a platform provider rather than hard-coded
Windows paths:

| Platform | Discovery | Install plan | Doctor `capcut_executable` |
| --- | --- | --- | --- |
| Windows | `CapCut.exe` / `JianyingPro.exe` under `%LOCALAPPDATA%\<app>\Apps` and `%PROGRAMFILES%\<app>`, with the file version read from the `.exe`'s `VS_VERSIONINFO` resource | exact `winget install` command | `ok` / `fail` |
| macOS | `CapCut.app` / `JianyingPro.app` under `/Applications` and `~/Applications`, with the `Info.plist` bundle version | `brew install --cask capcut`, or the official download page where no cask exists | `ok` / `fail` |
| Linux | none | none; `status: unsupported` with the reason | `skip`, reported as `unsupported` |

Each provider also reports the host build it found -- the Windows `.exe`
version resource, the macOS `Info.plist` bundle version -- and grades it against
the machine-readable matrix in `src/dcc_mcp_capcut/hosts/versions.py`. A build
that was read but is unlisted is a `warn` naming the version, never a silent
pass; a build whose version could not be read is a separate `warn`, because
"could not read" and "read and untested" are different facts.

ByteDance publishes no official Linux client, so Linux reports an explicit
conclusion instead of an empty "not installed" that could be mistaken for a
broken install. macOS window binding needs **Accessibility permission** for the
controlling app (System Settings > Privacy & Security > Accessibility) — a
user-side grant the adapter reports but never requests or bypasses. No provider
installs anything: every plan still goes through the operator-owned
`ui_control__system_operation` grant.

## Capabilities

The bundled skills cover project lifecycle/settings, media import/relink and
proxies, timeline/clip editing, transitions, text and auto-captions, audio
mixing/fades, effects and color, AI helpers (background removal/stabilization),
video/thumbnail export, one-call assembly of a whole edit plan, batch production
from a template, and a complete `build_vlog_demo` recipe.

### Export receipt

`export_thumbnail` and `get_export_status` accept an opt-in `verify_output`
flag. Left off, a result proves only that the job was accepted — the contract
every caller has today. Set it and the host must probe the rendered artifact and
return `path`, `exists`, `size_bytes`, `duration_sec` (timed media only; a still
omits it) and `streams` under `verification.output`, or the call fails closed.
The asynchronous submits `export_video` and `build_vlog_demo` do not take the
flag: they return a job acknowledgement and the artifact does not exist yet, so
their receipt comes from `get_export_status`. Batch delivery reports one receipt
per rendered item and reuses the same field set. The normative table lives in
[the export and verification reference](src/dcc_mcp_capcut/skills/references/export-and-verification.md).

## Run locally

```powershell
uv sync --extra dev
uv run pytest
uv run python -c "from dcc_mcp_capcut import start_server; start_server()"
```

## Guided installation and environment setup

The `capcut-setup` skill is built in. Call `detect_installation` and then
`installation_plan` when CapCut is missing. `auto_setup_capcut` executes the
full install-and-bind flow after receiving an operator-owned
`ui_control__system_operation` grant: it installs `ByteDance.CapCut` when
needed, configures the shared runtime/bridge, and verifies the exact CapCut
process. **It does not inject the panel** — that step is operator-owned and
consent-gated, and no automatic loader ships with this package (see
`capcut_panel/LOADING.md`). The adapter never shells out, edits the registry,
or silently installs software.

Host-bound capabilities additionally need the bundled panel running **inside**
the CapCut process, because the panel is what drains the bridge queue — see
[`src/dcc_mcp_capcut/capcut_panel/LOADING.md`](src/dcc_mcp_capcut/capcut_panel/LOADING.md)
for what the panel is, what it requires, and how to confirm it is connected.
That guide also records the current limit: **this package ships the panel
payload but no automatic loader**, so injecting it is operator-owned,
consent-gated work. Until something polls the bridge, `panel_connected` stays
`false` and host actions stay queued until the request timeout elapses. Treat
`panel_connected` as a liveness signal for a poller, not as proof that
`window.CapCut` exists: a panel opened in a normal browser also reports `true`
while every host action fails immediately.

Verify with `GET /health` on the bridge URL, and set
`DCC_MCP_CAPCUT_BRIDGE_TOKEN` to a per-user secret for production use.

## Vlog demo

`demo/assets.json` records NASA/JPL public-domain source pages and attribution
notes. Run `python demo/fetch_assets.py`, then `python demo/render_vlog.py` for
an offline 9:16 proof in `demo/output/free-travel-vlog.mp4`. The render is
driven by the canonical edit plan and writes it to
`demo/output/free-travel-vlog.plan.json`; feed that file to `apply_edit_plan`
with `media_dir` set to `demo/` for a native CapCut project. That directory is
the delivery root the plan's portable relative paths resolve against.

## Canonical edit plan

`dcc-mcp-capcut/edit-plan/v1` is the one plan document the adapter agrees on,
documented in [`docs/edit-plan.md`](docs/edit-plan.md). `compile_edit_plan`
normalises a plan or a vlog recipe into it, and three links consume it:

| Link | Tool | Host needed |
| --- | --- | --- |
| Compile/validate | `compile_edit_plan` | no |
| Portable export/import | `export_otio` / `import_otio` | no |
| Assemble into CapCut | `apply_edit_plan` | yes |

All three share one set of rules, so a plan that compiles is a plan every link
accepts — previously the vlog recipe and the OTIO exporter disagreed about
whether two clips on one track could overlap. The one exception is OTIO export,
which additionally requires `media_duration` on every clip because it will not
write an `available_range` it cannot prove.

Assembly is one call instead of a hand-orchestrated sequence: `apply_edit_plan`
takes a plan plus a media directory, validates it host-free, and lowers it to
an ordered action script. Use `dry_run: true` to inspect that script without
dispatching anything. See
[ADR 0002](docs/adr/0002-canonical-edit-plan-and-assembly.md) for the spike
behind it.

## Batch production from a template

One template plus N variable sets becomes N renders. The template is an ordinary
plan or recipe carrying `{{placeholder}}` fields, so every variant is validated
by the same rules as a hand-written plan. `render_batch_template` takes the two
and returns every compiled plan, reframe report and encode preset, host-free:

```json
{
  "template": {
    "schema": "capcut-vlog-recipe/v1",
    "project_name": "promo {{lang}} {{aspect}}",
    "aspect_ratio": "{{aspect}}",
    "output_path": "out/promo_{{lang}}_{{aspect}}.mp4",
    "media": [{"id": "a", "path": "clips/{{lang}}/a.mp4", "start": 0, "duration": "{{length}}"}],
    "reframe": {"fit": "contain", "source_aspect_ratio": "16:9"},
    "export": {"codec": "h264", "bitrate_mbps": 12}
  },
  "variables": [
    {"lang": "en", "aspect": "16:9", "length": 8},
    {"lang": "zh", "aspect": "9:16", "length": 8}
  ]
}
```

`run_batch` then assembles and exports each item in turn, writing a manifest
after every one and reporting a receipt per delivered item. Failures are
isolated to the item that earned them, and a batch is resumable from its
manifest with `resume: true`. Reframing is declared and reported, never applied
silently: `cover` requires a `safe_area`, and a crop that would eat it is an
error rather than a warning.

Rendering is sequential and needs the visible, bound CapCut window for the whole
run. See [docs/batch-and-templates.md](docs/batch-and-templates.md).

## Portable OpenTimelineIO export

Install `dcc-mcp-capcut[interchange]` to enable the `capcut-interchange`
skill's `export_otio` and `import_otio` tools, or use the host-independent CLI:

```powershell
python -m dcc_mcp_capcut.interchange --input edit.json --output timeline.otio
```

`export_otio` accepts either that explicit edit decision list or a canonical
`plan` document, which it lowers to the EDL below. The list has `name`, `fps`,
`width`, `height`, `duration_frames`, and `tracks`. Each track has `name`,
`kind` (`Video` or `Audio`), and ordered `clips`. Each clip specifies `name`,
relative `media` path, timeline `start`, optional `source_in` (default 0),
`duration`, and `media_duration`; all time values are integer frames at `fps`.
Optional `captions` contain `text`, `start`, and `duration` and become markers.
See [the interchange contract](docs/interchange.md) for a complete example.

The exporter preserves gaps, source trims, separate tracks and fractional
frame rates. It rejects overlaps, out-of-range edits, absolute/traversing media
paths and unknown fields. The CLI refuses to overwrite an existing file.

This is export from supplied edit decisions, not a readback of a live CapCut
project. Bake unsupported effects into media and include SRT for editable
subtitles. Ship all referenced media with the OTIO file, and resolve relative
paths from its directory. Other applications may require an OTIO importer.

`import_otio` reads OTIO JSON or an `.otio` file back into a canonical plan.
Timings, trims, gaps, track structure and caption markers survive; advisory
presentation fields (audio volume/fades, caption style) have no OTIO
representation and are reported as dropped rather than reconstructed.

## Preflight diagnostics

`dcc-mcp-capcut-doctor` is a read-only preflight entry point. It collects the
evidence the adapter needs before it binds a window, so a failed start reports
one diagnosable cause plus a remediation instead of a traceback:

```powershell
dcc-mcp-capcut-doctor             # human-readable summary
dcc-mcp-capcut-doctor --fix-hints # add remediation steps
dcc-mcp-capcut-doctor --json      # machine-readable report
```

It checks the Python version, `dcc_mcp_core` against the CI-verified floor, the
runtime bundle handshake, the CapCut executable, `dcc-cua` availability and
window uniqueness, the bridge port and token, the bundled panel payload, the
optional Qt probe configuration, and `opentimelineio`. The executable and
window checks run through the platform provider, so macOS gets real host
verdicts and Linux gets an explicit `unsupported` reason. The report names the
provider in `host_provider`.

Every check is `ok`, `warn` (the adapter still starts, but degraded or with an
optional feature disabled), `fail` (the adapter cannot start in this state), or
`skip` (not applicable to this platform). The exit code is `0` when nothing
failed and `1` when at least one check failed. The doctor never installs,
writes, or mutates anything.

## Release gates

Release Please cuts the release: it opens a release PR against `main`, and
merging it creates the tag, the GitHub release, and the artifacts. Two gates
stand between a drifted tree and a published artifact.

**One version per release.** The wheel and sdist take their version from
`pyproject.toml` while the panel archive takes the one `release.yml` derives
from the tag, so a tree that lagged behind its own tag used to publish a single
release mixing `dcc_mcp_capcut-0.1.0-*.whl` with
`dcc-mcp-capcut-0.2.0-panel.zip`. `tools/check_release_version.py` reads the
version back out of `pyproject.toml`, `src/dcc_mcp_capcut/__version__.py`, the
wheel, the sdist and the panel archive, and fails unless every one of them
declares the version the release tag names:

```bash
python tools/check_release_version.py                      # do the sources agree?
python tools/check_release_version.py --print-version      # the in-tree version
python tools/check_release_version.py --expect 0.3.0 --dist dist
```

It runs on every PR that builds artifacts, and twice in `release.yml` — once
against the tree before anything is built, and once against `dist/` before
anything is uploaded. A file it cannot read a version from is a failure, not a
skip.

**A green release PR.** A PR opened with the default `GITHUB_TOKEN` creates its
`pull_request` runs in an approval-required state, so they sit at
`action_required` with zero jobs and never turn green on their own. `release-please.yml` therefore prefers `secrets.RELEASE_PLEASE_TOKEN` — a
PAT makes the release PR an ordinary PR whose checks run on their own — and
falls back to `GITHUB_TOKEN` until that secret exists. With the fallback in
place, approve the release PR's runs by hand on the Actions page before
merging; the version gate in `release.yml` runs regardless, because it is
triggered by the push to `main`.

## Runtime boundary

The adapter is an external-bridge (`instance_type=gui`) service. It does not
invent a CapCut API, use raw script execution, or silently fall back to generic
computer automation. For UI verification use the project-owned `dcc-cua` /
`ui-control` route with an exact CapCut PID and HWND.

`dcc-mcp-runtime` is distributed as a separately verified runtime bundle, not
as a PyPI dependency. The `dcc-mcp-capcut-runtime` entry point refuses to start
when that runtime is missing, its CapCut manifest is stale, or required
handshake metadata is absent.
