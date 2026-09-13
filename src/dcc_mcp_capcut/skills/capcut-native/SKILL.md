---
name: capcut-native
description: Inspect a connected native Qt probe without claiming desktop editing support.
license: MIT
compatibility: "Optional matching Qt 6 probe; Windows, macOS, Linux protocol"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: scene, tags: "capcut, native, qt, diagnostics", tools: tools.yaml}
---

The operator must configure the optional probe endpoint, token, executable hash,
and exact host PID. These tools never launch, inject, install, or modify the host.
Inspecting Qt metadata does not prove access to CapCut projects or editor commands.
Object IDs are local to each response, not handles for later invocation.
