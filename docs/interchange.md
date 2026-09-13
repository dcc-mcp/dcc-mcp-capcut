# Portable editorial interchange

`export_otio` accepts an explicit edit decision list. It uses the official
OpenTimelineIO library, requires the `interchange` extra, and never invokes a
CapCut host API. The typed tool returns `otio_json`, `duration_frames`, `fps`,
`clip_count`, `media_paths`, and explicit `limitations`; saving and packaging
the returned JSON is the caller's responsibility.

```json
{
  "name": "Earth short",
  "fps": 30,
  "width": 1080,
  "height": 1920,
  "duration_frames": 180,
  "tracks": [
    {
      "name": "Picture",
      "kind": "Video",
      "clips": [
        {
          "name": "Opening",
          "media": "media/opening.mp4",
          "start": 0,
          "source_in": 0,
          "duration": 180,
          "media_duration": 180
        }
      ]
    },
    {
      "name": "Narration",
      "kind": "Audio",
      "clips": [
        {
          "name": "Voice",
          "media": "media/voice.wav",
          "start": 15,
          "duration": 150,
          "media_duration": 150
        }
      ]
    }
  ],
  "captions": [{"text": "Our home", "start": 30, "duration": 90}]
}
```

Frame values refer to the declared timeline fps, including media in/out
values. Source frame rates must be conformed before producing the edit list.
The example's audio track receives a 15-frame leading and trailing gap.
Separate tracks may overlap; clips within a track may not. Tracks are ordered
bottom to top as in OTIO. Source trims and duration bounds are validated.

Only straight cuts, gaps, external media and markers are supported. Unknown
fields (including speed changes and effects) fail explicitly. Render graphic
effects per shot before interchange and retain their source project for later
changes. Captions are timeline markers, not native subtitle clips: provide SRT
alongside the edit. Canvas metadata is advisory; configure the target editor's
sequence to the specified dimensions and fps.

Media paths are relative to the delivered OTIO file directory. The exporter
does not check file existence or decode media; validate those separately when
building a delivery bundle. The CLI creates its output exclusively and will
not overwrite an existing file. It does not create parent directories.

Import availability differs by editor and installed adapters. A successful
official-library round trip verifies OTIO structure, not native application
acceptance or reconstruction of proprietary CapCut effects.
