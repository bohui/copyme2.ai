# Reusable art, scene illustrations only

The host supplies `build/asset-catalog.json`. Reuse its versioned stock pack:
animated avatar, CSS memory markers, original music loop and interaction chime.
Use native HTML/CSS and system fonts for interface and dialogue. Represent other
people with existing generic markers or CSS silhouettes and source-supported
names. The childhood avatar is imagined, not a real-person likeness. Select an
appropriate existing pack before using this policy for another age or art style.

The only newly generated artwork is **scene-background illustration**. Match
`stock.scene_style` and illustrate source-supported places, objects and weather.
Keep uncertain details schematic. Backgrounds contain no characters, portraits,
text, logos or interface. Reuse one location across its memories; do not request
one image per event. Combine compatible locations into a row-major atlas to
reduce generation calls. The art handoff reports the requested call count,
without promising a price or speedup that has not been measured.

For the art stage, return `design/ART_DIRECTION.md` and
`design/SCENE_ART_PLAN.json`. The JSON shape is:

```json
{
  "style": "gouache-childhood-v1",
  "illustrations": [
    {
      "id": "places",
      "kind": "scene-background",
      "columns": 2,
      "rows": 1,
      "scenes": ["home", "school"],
      "prompt": "A precise two-column, one-row atlas of two distinct side-on storybook backgrounds: home on the left and school on the right. Describe only the approved source-supported settings here. Match the supplied stock scene style. Clear horizontal walking ground, no people, text, borders or gutters."
    }
  ]
}
```

Use unique slug IDs. Name every atlas cell once, in row-major order. Expand the
example to the actual designed locations and a complete image-generation prompt;
include the style description in that prompt. The host validates the plan,
restores matching cached PNGs, and generates only missing entries using the
available image-generation skill. Inspect generated pixels for grid boundaries,
source fidelity and compatibility with the stock avatar before recording them.
Record the original PNG; cache registration does not establish QA or approve art.

For production, use only catalog entries with `status: ready`. The host stages
stock files under `assets/stock/<pack-id>/` and illustrations under
`assets/scenes/`. Use the supplied URLs and actual atlas/cell dimensions. Keep
media files external and local. Load stock `stock.css` before `game.css`; use the
catalog's avatar markup and update `data-moving` and `data-facing` from existing
movement state. Maintain its foot baseline and scale a wrapper if needed.
Scene changes must display the correct atlas cell. Preserve gameplay, source
text, keyboard/touch controls, focus and reduced-motion support.

Music starts off. Enable playback only from a user action, with a persistent mute
control available during dialogue. Use the existing theme and cue; voices remain
absent. Shared characters, UI, portraits, music and sound are not generation
requests. A different asset policy requires an explicit user request.

Before delivery, exercise the real game with local assets under the preview CSP:
desktop and touch replay, scene changes, avatar idle/walk/facing and reduced
motion, opt-in/mute audio, readable dialogue, source fidelity, ending and restart.
Include every nested asset's hash in QA receipts. Cache hits only avoid new image
generation; they do not reuse a previous build's PASS result.
