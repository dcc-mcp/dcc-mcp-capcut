# CapCut Vlog Demo

This demo is a short vertical travel montage using NASA/JPL public-domain
visuals and locally generated ambient audio. No copyrighted music is bundled.

```powershell
python demo/fetch_assets.py
python demo/validate_recipe.py demo/vlog_recipe.json
python demo/render_vlog.py
```

The rendered proof is written to `demo/output/free-travel-vlog.mp4` with a
SHA-256 receipt beside it. The Chinese caption track is also available as
`demo/galaxy_zh.srt` for direct CapCut subtitle import.

## One plan, three paths

Both scripts consume the canonical edit plan
(`dcc-mcp-capcut/edit-plan/v1`, see `docs/edit-plan.md`) instead of keeping
their own copy of the rules:

- `validate_recipe.py` compiles the recipe and reports the plan — this is the
  same verdict `export_otio` and `apply_edit_plan` apply.
- `render_vlog.py` builds the FFmpeg filter graph from the compiled plan and
  writes it next to the render as `demo/output/free-travel-vlog.plan.json`.

That plan file is the hand-off to the host: feed it to `apply_edit_plan` (or
`build_vlog_demo`) with `media_dir` pointing at `demo/assets` for a native
CapCut project. Call `apply_edit_plan` with `dry_run: true` first to see the
compiled plan and the exact action script without dispatching anything.

Asset ids resolve to local paths through `local_path` in `assets.json`, which
is how the id-only `music` entry in the recipe finds its file.

The recipe's second clip starts at **4.5 s**, not 4.2 s: the two clips overlap
at 4.2 s, which the canonical contract rejects for a single picture track. That
overlap is exactly the divergence this contract removes — the old recipe
validator accepted it while `export_otio` rejected it, and the renderer had
always concatenated at 4.5 s.

Sources and license notes are recorded in `assets.json`. NASA/JPL attribution
should remain in the project description or end card when publishing.
