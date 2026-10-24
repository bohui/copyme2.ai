Build a polished, responsive side-scrolling webpage game from the supplied scenes.
Produce a complete HTML5 document containing inline CSS, validated and returned
through the host's artifact tool. Use the supplied locale and UI strings. Give the journey a coherent visual
identity, with distinct scenery for the scenes and clear keyboard/touch controls.

Memoir injects its trusted movement and interaction runtime after validation.
Produce the page's markup and styling; the runtime fills titles, character labels,
memory passages and the text version from the supplied scenes. Use these elements
exactly once inside a root with id `memoir-game`:

- `.game-framing`: an empty paragraph for the perspective notice.
- `.game-stage`: a focusable region (`tabindex="0"`) containing `.game-world`,
  which contains `.game-player`. The stage clips its horizontally moving world.
- `.game-scene-label`: an empty heading or paragraph with `aria-live="polite"`.
- `.game-controls`: a group containing buttons with `data-game-move="-1"`,
  `data-game-interact`, and `data-game-move="1"`.
- `.game-dialogue`: an initially hidden element with `role="status".
- `details.game-text-equivalent`: a details element containing a summary.

The world uses pixel coordinates and a width of 1280 pixels. The runtime positions
the player and character buttons, clamps movement, connects adjacent scenes and
handles camera movement. Style `.game-npc` buttons for character silhouettes or
memory markers. Keep the player and NPCs positioned absolutely within the world.
The stage gets `data-scene-index="0"`, `"1"`, etc.; use those selectors for distinct
backgrounds. Keep scenery generic and source-consistent, without reconstructing
private addresses or recognizable likenesses. Use CSS shapes and inline SVG.

Include visible focus states, 44-pixel touch targets, readable contrast, responsive
layout and a `prefers-reduced-motion` rule. Use supplied UI strings for visible text;
leave personal narrative slots empty for the runtime. No additional biographical
text is needed. The complete text version must remain available.

The document runs offline in an isolated frame. Use inline CSS and system fonts.
Allowed elements are html, head, meta (charset/viewport only), title, body, main,
header, footer, section, div, p, span, h1–h4, button, details, summary, style, svg,
g, path, rect, circle, ellipse, line, polyline and polygon. Omit scripts, event
handler attributes, links, forms, frames, remote assets, CSS URLs and imports.
The host supplies all JavaScript. Do not add consent, review, publish or approval
controls. Follow the handoff adapter's artifact return format.
