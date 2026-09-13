---
name: capcut-interchange
description: Export explicit frame-based edit decisions to portable OpenTimelineIO JSON.
license: MIT
compatibility: "dcc-mcp-capcut[interchange]; no CapCut host dispatch required"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: delivery, tags: "capcut, otio, interchange", tools: tools.yaml}
---

Use `export_otio` with explicit edit decisions. All times are integer frames
at the declared fps. Clips must be sorted and non-overlapping per track;
overlays belong on separate tracks. Media paths are relative to the exported
timeline directory. Include the referenced media alongside the OTIO file.

The tool returns JSON and does not write files or mutate the host. It never
claims to have read a live CapCut project. Effects must be baked into supplied
media. Captions become timeline markers; supply SRT for editable subtitles.
Unsupported fields fail rather than silently dropping effects or retiming.
