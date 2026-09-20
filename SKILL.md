---
name: dcc-mcp-capcut
description: Router index for the CapCut Desktop adapter skills; the authoritative skill content ships inside the Python package.
license: MIT
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, layer: index, stage: setup, tags: "capcut, index, router"}
---

# Router only — this file is not a skill body

This file is an **index**. It exists so a repository reader or an agent that
lands at the checkout root can find the real content. It is not the authoritative
description of any CapCut capability.

- **Authoritative content lives inside the package**, in
  `src/dcc_mcp_capcut/skills/capcut-*/SKILL.md`. Those 11 files ship in the
  wheel, which is what an agent actually consumes.
- **This file is not in the lint loop.** CI validates
  `src/dcc_mcp_capcut/skills/capcut-*` with `dcc-mcp-cli lint --warnings-as-errors`
  and nothing else. Do not add capability documentation here: it would become an
  unmaintained second source of truth that no check reads.
- CapCut Desktop has no stable public Python API. Every capability below that
  drives the host runs through a typed, token-authenticated loopback bridge and
  the bundled CapCut-side panel, and therefore needs `capcut-setup` first. Two
  skills are exempt: `capcut-interchange` runs host-free from supplied edit
  decisions, and `capcut-native` talks to the optional Qt probe endpoint instead
  of the bridge and panel (it still needs the bound host PID). Do not run
  `capcut-setup`, and do not reject a call, for those two.
  See `src/dcc_mcp_capcut/skills/references/host-boundary.md`.

## Skill index

| Skill | Scope |
| --- | --- |
| `capcut-setup` | Detect CapCut, consent-gated install-and-bind, bridge config, readiness proof. Start here. |
| `capcut-project` | Project lifecycle, canvas, and project settings. |
| `capcut-media` | Import, list, relink, proxy, and bin removal of media. |
| `capcut-timeline` | Timeline creation and clip/transition editing. |
| `capcut-text` | Text overlays, subtitle import, auto-captions. |
| `capcut-audio` | Audio placement, level, and fades. |
| `capcut-effects` | Effects and color adjustment. |
| `capcut-ai` | Optional host-side background removal and stabilization. |
| `capcut-export` | Render, monitor, cancel, thumbnail, and the vlog recipe. |
| `capcut-interchange` | Portable OpenTimelineIO export from supplied edit decisions. No host required. |
| `capcut-native` | Optional read-only Qt metadata probe. Diagnostics only. |

## Shared references

Shipped inside the package at `src/dcc_mcp_capcut/skills/references/`, next to
the `capcut-*` skill directories and deliberately outside the lint glob:

- `host-boundary.md` — the external-bridge boundary, consent rules, bridge contract.
- `dependencies-and-notices.md` — third-party licenses and the "having this skill grants no rights" statement.
- `export-and-verification.md` — the post-operation readback contract and export acceptance.
- `troubleshooting.md` — symptom to cause to remediation, starting with `dcc-mcp-capcut-doctor`.

## Before using any skill

```powershell
dcc-mcp-capcut-doctor --fix-hints
```

Exit code `0` means nothing failed. See `README.md` for installation and the
runtime boundary.
