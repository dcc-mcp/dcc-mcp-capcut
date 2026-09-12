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
`demo/galaxy_zh.srt` for direct CapCut subtitle import. The same
`vlog_recipe.json` is the portable input for the CapCut bridge; when CapCut is
running, import the two clips, add the generated `free_ambient.wav`, apply the
caption timings, and export at 1080x1920.

Sources and license notes are recorded in `assets.json`. NASA/JPL attribution
should remain in the project description or end card when publishing.
