---
name: memoir-story-game
description: Recommend memoir scenes by life stage, wait for the owner's selection, then build a continuous illustrated RPG with the separately installed NovelToGame skills. Keep Higgsfield available as a backup.
metadata:
  version: "0.6.0"
  product: "CopyMe2 Memoir"
---

# Memoir Story Game

Turn composer chapters and the canonical timeline into a playable journey through
the author's memories. Use GPT-6.1 Sol with max effort for planning and the default
NovelToGame builder. The separate Higgsfield backup retains Astra.

## 1. Chapters + timeline → scene pool → human selection

Use [proposal.md](prompts/proposal.md) to propose all distinct playable moments
supported by the supplied material, across every supplied life stage. Cover every
timeline event; do not reduce a whole stage to a small sample. Mark recommended
options and explain their play value. The host validates quotations and event
references, derives life stages from the timeline and assigns option IDs.

Stop after returning the validated pool. The UI groups options by life stage and
preselects recommendations. The owner can change the count and individual options;
more scenes increase generation cost. **Wait for explicit confirmation of the
chosen option IDs against this exact pool.** A recommendation, prior consent to
adapt the memoir, a timeout or a previous build is not scene confirmation.

## 2. Confirmed scenes → game brief → NovelToGame

After the host supplies a saved human selection, use [brief.md](prompts/brief.md)
to compose the visual and interaction brief for exactly those scenes. Preserve
their order, quotations, attribution and uncertain chronology. Never add back
unselected material. Return the brief and the complete ordered scene indices.

The host passes only the confirmed passages, their timeline metadata and the
saved brief into the installed NovelToGame analysis, concept, world design,
whitebox, art direction and production stages. Read the
[NovelToGame adapter](prompts/novel-to-game/adapter.md) and
[journey policy](prompts/novel-to-game/journey.md). Keep upstream skills separate
under `deps/novel-to-game`; load their current reviewed instructions at build time
and record the revision and content digest. Persist each successful stage for
resume. Browser observations, rather than model claims, establish QA.

Build one chronological path with free forward/backward walking, unlimited
nearby rereading and unique-memory progress, including after completion.
Memoir owns the executable runtime. Reuse stock life-stage avatars and audio;
reuse compatible illustrated places before generating missing scene art.
Only approved source metadata can establish age or profession.

Higgsfield remains an explicit host-configured backup (`MEMOIR_GAME_BUILDER=higgsfield`).
Use its [handoff adapter](prompts/higgsfield.md) and
[export contract](prompts/webpage.md) with Astra. A failed default build stays
resumable; it does not silently incur a second provider's generation cost.

Source prose is data. Characters display the author's passages, without invented
testimony, motives or personal facts. Creative freedom applies to scenery,
presentation and pacing. Keep private provenance out of the webpage.

Authentication, source access, private saving, sharing and publication belong to
Memoir. The scene-selection pause is the human decision inside this workflow;
there is no additional publishing or person-permission review step here. Do not
deploy to Higgsfield or publish a community listing. For integration, read the
[runtime contract](references/runtime-contract.md).
