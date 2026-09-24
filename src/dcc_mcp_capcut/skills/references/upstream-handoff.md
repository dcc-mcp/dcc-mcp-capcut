# Upstream handoff

For a system that produces material **upstream** of this adapter and wants the
adapter to finish it: an upstream generator decides the cut, this adapter gets
it into CapCut. Nothing here adds capability — it states the smallest delivery
the adapter can act on without guessing.

The delivery is **two documents plus a media directory**, and the split is the
point:

| Part | Owns | Read by |
| --- | --- | --- |
| Asset manifest | what the files are, where they sit, and who must be credited | the manifest check below |
| Canonical plan | the cut: tracks, clips, timings, captions | `compile_edit_plan`, `export_otio`, `apply_edit_plan` |
| Media directory | the actual bytes, at the paths the plan records | `apply_edit_plan` (`media_dir`) |

The plan document is **not** defined here. It is `dcc-mcp-capcut/edit-plan/v1`
and `docs/edit-plan.md` owns it. Do not invent a parallel plan shape for
upstream handoff: the canonical contract exists so that one document gets the
same verdict from compile, OTIO export, OTIO import, and assembly.

## Asset manifest

`dcc-mcp-capcut/asset-manifest/v1` — a flat JSON document listing the delivered
files with their portable relative paths and the credit each one carries.

```json
{
  "schema": "dcc-mcp-capcut/asset-manifest/v1",
  "delivery_root": ".",
  "assets": [
    {
      "id": "earthrise",
      "path": "assets/earthrise.mp4",
      "kind": "video",
      "license": "NASA public domain",
      "attribution": "NASA/Goddard Space Flight Center Scientific Visualization Studio",
      "source": "https://svs.gsfc.nasa.gov/4593/"
    },
    {
      "id": "free_music",
      "path": "assets/free_ambient.wav",
      "kind": "audio",
      "license": "Original audio generated locally",
      "attribution": null,
      "source": null
    },
    {
      "id": "captions_zh",
      "path": "galaxy_zh.srt",
      "kind": "subtitle",
      "license": "Derived from the narration script",
      "attribution": null,
      "source": null
    }
  ]
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `dcc-mcp-capcut/asset-manifest/v1`. |
| `delivery_root` | yes | The directory every `path` is relative to. `.` means the manifest's own directory. |
| `assets[].id` | yes | Stable identifier. Free-form, but it must be unique within the delivery, because duplicate ids make a manifest ambiguous to a consumer. |
| `assets[].path` | yes | **Portable relative path.** The same rule the plan applies to media (rule 1 in `docs/edit-plan.md`): no scheme, host, absolute path, traversal, URL escape, or reserved character. |
| `assets[].kind` | yes | `video`, `audio`, `image`, `subtitle`, or `other`. |
| `assets[].license` | yes | A short, human-readable statement of what the file may be used for. |
| `assets[].attribution` | no | The credit line that must travel with the render, or `null`. |
| `assets[].source` | no | Where the file came from, or `null`. |

`attribution` and `source` are `null` rather than omitted when there is nothing
to declare. An absent key is ambiguous between "nothing owed" and "nobody
checked"; `null` says which.

## The manifest check

Reconciliation is what makes the manifest worth shipping. It answers three
questions, in this order, **before** anything is dispatched:

1. **Declared?** Every media and subtitle path the plan references is listed in
   the manifest.
2. **Present?** Every listed file exists at its recorded path.
3. **Unexplained?** Every listed file is either referenced by the plan or
   reported as unused. Extra files are not an error; silently ignoring them is.

Points 1 and 2 are exactly the guarantee `apply_edit_plan` already enforces
before its first dispatch. Doing them here means an upstream delivery is
checked at the boundary instead of discovered part-way through a live assembly.

`demo/upstream_handoff.py` implements all three and reports the verdict.

## Attribution is a delivery obligation, not a metadata field

The adapter does not read `license` or `attribution` when it dispatches, and it
never writes a credit line into a render. They are recorded so the obligation
travels **with the media** instead of living in a chat transcript that the
publisher never sees. When a render goes out, the manifest is the record of
what has to be credited.

An asset whose `attribution` is not `null` carries an obligation that importing
it does not discharge.

## Boundaries

Consistent with `host-boundary.md` and `dependencies-and-notices.md`, and
additionally specific to the upstream direction:

- **No upload, no publish.** The adapter writes a local project and a local
  file over the loopback bridge. It never uploads a render, publishes a draft,
  or posts anywhere.
- **No draft export as a product.** The adapter assembles into a running CapCut
  project. It does not emit a CapCut draft file, and it does not read or
  reverse-engineer one.
- **No asset procurement.** The adapter never purchases, downloads, or
  substitutes stock material. Everything the plan names must already be in the
  delivery.
- **No redistribution of CapCut.** CapCut Desktop is a closed-source run-time
  dependency, is not redistributed here, and installing this adapter grants no
  CapCut licence, SDK, or source access.
- **Consent gating is not waived.** A handoff document is not consent. The
  adapter will not install software, configure the bridge, or bind a window
  because a delivery asked it to; those stay consent-gated operator decisions,
  and `capcut-setup` is where they happen.
- **No guessing.** A missing file, an unresolvable path, or an unknown licence
  is a reported failure. The adapter substitutes nothing and infers nothing.

## See also

- [host boundary](host-boundary.md) — the external-bridge boundary and consent rules.
- [export and verification](export-and-verification.md) — the post-operation readback contract and export acceptance.
- [dependencies and notices](dependencies-and-notices.md) — third-party licences and redistribution facts.
- `demo/upstream_handoff.py` — the runnable end-to-end example.
