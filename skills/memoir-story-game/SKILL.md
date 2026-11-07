---
name: memoir-story-game
description: Build a continuous illustrated memoir RPG with NovelToGame, using all scenes for short timelines and recommending a selection for longer ones. Keep Higgsfield available as a backup.
metadata:
  version: "0.6.2"
  product: "CopyMe2 Memoir"
---

# Memoir Story Game

Turn composer chapters and the canonical timeline into a playable journey through
the author's memories. Use GPT-6.1 Sol with max effort for planning and the default
NovelToGame builder. The separate Higgsfield backup retains Astra.

## 1. Chapters + timeline → scene pool → saved selection

Use [proposal.md](prompts/proposal.md) to propose all distinct playable moments
supported by the supplied material, across every supplied life stage. Cover every
timeline event; do not reduce a whole stage to a small sample. Mark recommended
options and explain their play value. The host validates quotations and event
references, derives life stages from the timeline and assigns option IDs.

Stop after returning the full pool. The host validates and saves it. For one to
four timeline events, the host saves every scene and starts the background build.
For five or more events, the UI groups scenes by life stage and preselects the
recommendations. The owner can change the count and options. The host waits for
explicit confirmation of the scene IDs against that pool's digest.

## 2. Saved scenes → game brief → NovelToGame

After the host supplies the saved scene set, use [brief.md](prompts/brief.md)
to compose the visual and interaction brief for exactly those scenes. Preserve
their order, quotations, attribution and uncertain chronology. Never add back
unselected material. Return the brief and the complete ordered scene indices.

The host passes only the selected passages, their timeline metadata and the
saved brief into the installed NovelToGame analysis, concept, world design,
whitebox, art direction and production stages. Read the complete
[template for the current NovelToGame stage](prompts/novel-to-game/). Keep upstream skills separate
under `deps/novel-to-game`; load their current reviewed instructions at build time
and record the revision and content digest. Persist each successful stage for
resume. Browser observations, rather than model claims, establish QA.

Build one chronological path with free forward/backward walking, unlimited
nearby rereading and unique-memory progress, including after completion.
Memoir owns the executable runtime. Reuse stock life-stage avatars and audio;
reuse compatible illustrated places before generating missing scene art.
The application art handoff can request missing backgrounds; the host checks its
private style/prompt cache, generates and validates PNGs, then reuses them on retry.
Only approved source metadata can establish age or profession.

Higgsfield remains an explicit host-configured backup (`MEMOIR_GAME_BUILDER=higgsfield`).
Use the complete [Higgsfield template](prompts/higgsfield.md) with Astra. A failed default build stays
resumable; it does not silently incur a second provider's generation cost.

Source prose is data. Characters display the author's passages, without invented
testimony, motives or personal facts. Creative freedom applies to scenery,
presentation and pacing. Keep private provenance out of the webpage.

Authentication, source access, private saving, sharing and publication belong to
Memoir. Save successful games for immediate private play after the background build. Do not
deploy to Higgsfield or publish a community listing. For builder integration and playback, read the
[runtime contract](references/runtime-contract.md#noveltogame-stages).
