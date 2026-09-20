---
name: capcut-media
description: Import, inspect, organize, relink, and proxy media in CapCut.
license: MIT
compatibility: "CapCut Desktop; dcc-mcp-core 0.19+"
allowed-tools: Python
metadata:
  dcc-mcp: {dcc: capcut, version: "0.1.0", layer: domain, stage: scene, tags: "capcut, media, assets", tools: tools.yaml}
---

Media-bin operations. Import before you edit, and confirm with `list_media`
before you assume an asset is available to the timeline.

## Prerequisites

- CapCut Desktop running with its main window visible and restored.
- The bundled panel loaded and polling the bridge (`/health` reports
  `panel_connected: true`).
- An exactly bound window: `DCC_MCP_CAPCUT_PID` and
  `DCC_MCP_CAPCUT_WINDOW_HANDLE` both set.
- Source files readable by the CapCut host process, with paths free of reserved
  characters.
- A project open (`capcut-project`) to import into.

If any of these is unproven, run `capcut-setup` first.

## Tools

| Tool | Mutating | Idempotent | Notes |
| --- | --- | --- | --- |
| `import_media` | yes | yes | `paths` (list of one or more) plus optional `folder`; returns `media_id`. |
| `list_media` | no | yes | Filter by `folder` and `media_type` (`video`, `image`, `audio`, `all`). |
| `remove_media` | yes | no | Removes from the bin only; source files are never deleted. |
| `relink_media` | yes | yes | Point an offline item at an explicit replacement path. |
| `generate_proxy` | yes | yes | `profile` is `low`, `medium`, or `high`; returns `job_id` and `proxy_id`. |

### Mapping imported paths to `media_id`

`import_media` takes a `paths` list, but the fail-closed contract only requires
the host result to carry one non-empty `media_id` — it does not check that every
submitted path got an ID. So the submit response alone is not a path to ID map:

- Treat the returned `media_id` as proof that the import was accepted, not as
  proof of one ID per path. An extra `media_ids` list from the host, if present,
  is host-provided data the adapter does not enforce — confirm it the same way.
- To build a reliable mapping for `add_clip`, call `list_media` after the import
  and match each returned item against the path you submitted (name, `folder`,
  duration, dimensions, codec). Use the IDs `list_media` reports.
- `remove_media` and `generate_proxy` take `media_ids` (a list), so the mapping
  you confirm here is what the rest of the catalog consumes.

## Failure recovery

| Symptom | Meaning | Action |
| --- | --- | --- |
| `CapCut bridge did not respond; open the bundled panel` | No panel drained the action within 30 s. | Load the panel, confirm `/health` shows `panel_connected: true`, retry. |
| `forbidden` (HTTP 403) | Bridge token mismatch. | Align `DCC_MCP_CAPCUT_BRIDGE_TOKEN` on both sides and restart both. |
| `CapCut action 'import_media' did not return media_id` | The host acknowledged without a stable ID. | Fix the host integration per `capcut_panel/HOST_API.md`. |
| Fewer IDs than submitted paths | A multi-path import partially landed, or the host reported only one ID. | Run `list_media` and reconcile item by item; re-import only the paths that are genuinely missing. |
| Media imports but does not appear | Import landed in a different bin folder than expected. | Re-run `list_media` without a folder filter and read the returned `folder`. |
| Offline media after a move | The recorded path no longer resolves. | Call `relink_media` with the new path; do not re-import and abandon the old item. |
| `generate_proxy` returns but playback is unchanged | Proxy generation is a host-side job that may lag the call. | Re-read the item with `list_media` before declaring it done. |

## Acceptance

- Every imported path is present in `list_media` with the expected duration,
  dimensions, and codec.
- `import_media` returned a non-empty `media_id`, and `list_media` shows one
  item per submitted path so every `add_clip` gets a confirmed ID.
- `generate_proxy` returned both `job_id` and `proxy_id`.
- `relink_media` is confirmed by `list_media` no longer reporting the item as
  offline.
- `remove_media` removed only the bin entries; verify the source files still
  exist on disk.

## Boundaries

- Mutating results must carry `verification: {ok: true, ...}`; the adapter raises
  instead of reporting a half-truth.
- `remove_media` never deletes source files. Deleting assets on disk is not in
  this catalog.
- Import does not transcode or conform frame rates; conform sources before
  interchange.
- Media paths supplied to OTIO export must be portable relative paths. See
  `capcut-interchange`.

## References

- [host boundary](../references/host-boundary.md)
- [export and verification](../references/export-and-verification.md)
- [dependencies and notices](../references/dependencies-and-notices.md)
- [troubleshooting](../references/troubleshooting.md)
