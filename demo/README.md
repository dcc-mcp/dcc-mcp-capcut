# CapCut Vlog Demo

This demo is a short vertical travel montage using NASA/JPL public-domain
visuals and locally generated ambient audio. No copyrighted music is bundled.

```powershell
python demo/fetch_assets.py
python demo/validate_recipe.py demo/vlog_recipe.json
python demo/render_vlog.py
```

The rendered proof is written to `demo/output/free-travel-vlog.mp4` with a
SHA-256 receipt beside it. The caption tracks are also checked in as
`demo/galaxy_zh.srt` and `demo/galaxy_en.srt` for direct CapCut subtitle
import.

## One plan, three paths

Both scripts consume the canonical edit plan
(`dcc-mcp-capcut/edit-plan/v1`, see `docs/edit-plan.md`) instead of keeping
their own copy of the rules:

- `validate_recipe.py` compiles the recipe and reports the plan — this is the
  same verdict `export_otio` and `apply_edit_plan` apply.
- `render_vlog.py` builds the FFmpeg filter graph from the compiled plan and
  writes it next to the render as `demo/output/free-travel-vlog.plan.json`.

That plan file is the hand-off to the host: feed it to `apply_edit_plan` (or
`build_vlog_demo`) with `media_dir` set to **`demo/`** for a native CapCut
project. Call `apply_edit_plan` with `dry_run: true` first to see the compiled
plan and the exact action script without dispatching anything.

`demo/` is the delivery root, not `demo/assets/`: the plan's portable paths are
`assets/<media>` and `galaxy_zh.srt`, so `media_dir` has to be the directory
those paths are relative to. Pointing at `demo/assets/` would resolve them to
`demo/assets/assets/<media>`, which does not exist — and would fail before any
dispatch, naming the files it could not find.

Asset ids resolve to local paths through `local_path` in `assets.json`, which
is how the id-only `music` entry in the recipe finds its file. The subtitle is
the checked-in `demo/galaxy_zh.srt`, so it resolves without any extra step.

## Two languages, one plan

The recipe names a single subtitle file, so it compiles to a one-element
`subtitles` list. Multi-language delivery is the plural form — pass a plan
carrying both files and every link accepts it:

```json
{
  "subtitles": [
    {"file": "galaxy_zh.srt", "format": "srt", "language": "zh-CN"},
    {"file": "galaxy_en.srt", "format": "srt", "language": "en-US"}
  ]
}
```

`apply_edit_plan` emits one `import_subtitles` step per entry, so each language
lands on its own editable text track. `dry_run: true` lists both files under
`referenced` and checks that both exist under `media_dir` before anything is
dispatched.

The equivalent recipe form is `subtitle_files`, which takes paths or objects:

```json
{"subtitle_files": ["galaxy_zh.srt", {"file": "galaxy_en.srt", "language": "en-US"}]}
```

It is mutually exclusive with `subtitle_file`, for the same reason the two
canonical forms are: a document that expressed both would be a union the author
did not write.

The recipe's second clip starts at **4.5 s**, not 4.2 s: the two clips overlap
at 4.2 s, which the canonical contract rejects for a single picture track. That
overlap is exactly the divergence this contract removes — the old recipe
validator accepted it while `export_otio` rejected it, and the renderer had
always concatenated at 4.5 s.

Sources and license notes are recorded in `assets.json`. NASA/JPL attribution
should remain in the project description or end card when publishing.
