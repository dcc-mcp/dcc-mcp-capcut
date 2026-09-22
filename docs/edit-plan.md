# Canonical edit plan

`dcc-mcp-capcut/edit-plan/v1` is the one plan document the adapter agrees on.
It is the contract behind three links that share it:

| Link | Tool | Host | What it does |
| --- | --- | --- | --- |
| Compile | `compile_edit_plan` (`capcut-interchange`) | no | Normalises a plan or a vlog recipe into the canonical form. |
| Export | `export_otio` (`capcut-interchange`) | no | Lowers the plan to portable OTIO JSON. |
| Import | `import_otio` (`capcut-interchange`) | no | Reads OTIO back into a canonical plan. |
| Assemble | `apply_edit_plan` (`capcut-assemble`) | yes | Plays the plan into a CapCut project. |

All four validate against the same rules in
`src/dcc_mcp_capcut/editplan.py`, so **a plan that compiles is a plan every
link accepts**. That is the property this contract exists for: before it, the
vlog recipe and the OTIO EDL applied different rules to the same media, and the
shipped demo recipe had a 0.3 s overlap that one link accepted and the other
rejected.

Background and the spike that settled the assembly direction:
[ADR 0002](adr/0002-canonical-edit-plan-and-assembly.md).

## The document

```json
{
  "schema": "dcc-mcp-capcut/edit-plan/v1",
  "name": "银河系：我们身处其中",
  "fps": 30,
  "width": 1080,
  "height": 1920,
  "duration_frames": 375,
  "tracks": [
    {
      "name": "Picture",
      "kind": "Video",
      "clips": [
        {
          "name": "earthrise",
          "media": "assets/earthrise.mp4",
          "start": 0,
          "source_in": 0,
          "duration": 135,
          "media_duration": 135
        },
        {
          "name": "oahu_flyover",
          "media": "assets/oahu_flyover.mp4",
          "start": 135,
          "source_in": 0,
          "duration": 240,
          "media_duration": 240
        }
      ]
    },
    {
      "name": "Music",
      "kind": "Audio",
      "clips": [
        {
          "name": "free_music",
          "media": "assets/free_ambient.wav",
          "start": 0,
          "source_in": 0,
          "duration": 375,
          "media_duration": null,
          "audio": {"volume": 0.22, "fade_in": 0.8, "fade_out": 1.2}
        }
      ]
    }
  ],
  "captions": [
    {"text": "抬头看，银河系就在我们身边", "start": 18, "duration": 51,
     "style": {"font": "Microsoft YaHei", "size": 48, "weight": 700, "color": "#FFFFFF"}}
  ],
  "subtitle": {"file": "galaxy_zh.srt", "format": "srt"},
  "output": {"path": "./output/free-travel-vlog.mp4", "aspect_ratio": "9:16"}
}
```

### Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | no | `dcc-mcp-capcut/edit-plan/v1`. Must match the document shape. |
| `name` | yes | Project/timeline name. |
| `fps` | yes | Finite, positive. Fractional rates are preserved. |
| `width` / `height` | yes | Canvas, in pixels. Advisory for editors, authoritative for assembly. |
| `duration_frames` | no | Defaults to the end of the last clip or caption. |
| `tracks` | yes | Non-empty. Ordered bottom to top, as in OTIO. |
| `captions` | no | Inline captions; ignored by assembly when `subtitle` is present. |
| `subtitle` | no | An SRT/LRC/ASS file to import as an editable text track. |
| `output` | no | Delivery path and aspect ratio. |

Track: `name`, `kind` (`Video` or `Audio`), `clips`.

Clip: `name`, `media`, `start`, `duration`, optional `source_in` (default 0),
`media_duration`, and optional advisory `audio`.

Caption: `text`, `start`, `duration`, optional advisory `style`.

## Units

Every `start`, `duration`, `source_in` and `media_duration` is an **integer
frame** at the plan's `fps`. This is the canonical form, and it is what makes
the frame-accurate OTIO link and the seconds-based CapCut tool schemas a
conversion rather than a second opinion.

Advisory presentation values — `audio.volume`, `audio.fade_in`,
`audio.fade_out`, caption `style`, `subtitle`, `output` — are in the host's own
units (seconds and relative level), because that is what the CapCut action
schemas take.

Seconds-based recipes are converted with round-half-up at `fps`.

## Rules

These are the rules, and every link applies them.

1. **Media paths are portable relative paths.** No scheme, host, absolute
   path, traversal, URL escape or reserved character. The rule lives once, in
   `editplan.relative_media`, and `interchange.py` imports it.
2. **Clips within a track are ordered and non-overlapping.** Overlays belong
   on a separate track; separate tracks may overlap. Rejected with the track
   name and the frame the overlap starts at.
3. **Nothing exceeds the timeline.** `start + duration <= duration_frames`.
4. **Source trims cannot exceed the media.** When `media_duration` is
   supplied, `source_in + duration <= media_duration`. When it is absent, the
   bound is unproven: assembly proceeds, and OTIO export refuses rather than
   claim a bound it cannot prove.
5. **Captions stay inside the timeline.**
6. **`media_duration` is required for OTIO export**, and only for it, because
   the exporter writes an `available_range`.

## Advisory fields and what happens to them

OTIO cannot represent volume, fades, text styling, a subtitle file or an
output path. `plan_to_edl` **strips** them instead of encoding a guess, so an
OTIO round trip returns the portable core: timings, trims, gaps, track
structure and caption markers survive; presentation does not. This is a
declared limit, not something to reconstruct on import — keep the plan
document as the authoritative copy.

| Field | Assembly | OTIO export |
| --- | --- | --- |
| `audio.volume` | `set_audio_volume` | dropped |
| `audio.fade_in` / `fade_out` | `add_audio_fade` | dropped |
| caption `style` | `add_text(style=...)` | dropped |
| `subtitle` | `import_subtitles` | dropped |
| `output` | `export_video` (with `export: true`) | dropped |

## The vlog recipe profile

`capcut-vlog-recipe/v1` is a seconds-based profile over the same contract, not
a parallel format. `compile_plan` discriminates by shape — a document with
`tracks` is a plan, a document with `media` is a recipe — and a declared
`schema` must agree with that shape.

```json
{
  "project_name": "银河系：我们身处其中",
  "aspect_ratio": "9:16",
  "media": [
    {"id": "earthrise", "path": "./assets/earthrise.mp4", "start": 0, "duration": 4.5, "track_type": "video"}
  ],
  "music": {"media_id": "free_music", "start": 0, "volume": 0.22, "fade_in": 0.8, "fade_out": 1.2},
  "subtitle_file": "./galaxy_zh.srt",
  "captions": [{"text": "抬头看，银河系就在我们身边", "start": 0.6, "duration": 1.7, "style": {"size": 48}}],
  "output_path": "./output/free-travel-vlog.mp4"
}
```

Recipe-only conveniences, resolved during compilation:

- `aspect_ratio` maps to a canvas: `9:16` → 1080x1920, `16:9` → 1920x1080,
  `1:1` → 1080x1080.
- A leading `./` is tolerated in recipe paths and normalised away. The
  canonical plan always stores the clean relative form.
- An id-only entry such as `music.media_id` resolves through `media_index`
  (in the demo, built from `demo/assets.json`).
- A music bed without an explicit `duration` spans the cut. The cut length
  comes from the picture and captions alone, so the bed never defines it.

## Assembly

`apply_edit_plan` lowers the plan to an ordered action script. The script is
deterministic and host-free; `dry_run` returns it without dispatching anything.

```text
import_media   × one per referenced file
create_timeline
add_clip       × one per clip, ordered by track then start
set_audio_volume / add_audio_fade   (only for clips carrying advisory audio)
import_subtitles  — or —  add_text × one per caption
export_video   (only with export: true)
save_project
```

Picture tracks map to `track_type`: the first is `video`, subsequent ones are
`overlay`. Audio tracks map to `audio`.

Placeholders tie the steps together and are substituted from the receipts as
the script runs: `$media:mN` (imported media id), `$timeline` (created
timeline id), `$clip:cN` (placed clip id). Media is imported **one file per
call** because the fail-closed contract guarantees a single `media_id` per
`import_media` call, so a multi-path import could not be mapped back to
individual clips.

`media_dir` resolves the plan's portable relative paths, and every referenced
file must exist before the first dispatch. See
`capcut-assemble/SKILL.md` for the dispatch strategies and failure modes.
