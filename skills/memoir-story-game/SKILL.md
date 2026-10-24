---
name: memoir-story-game
description: Plan a full pool of memoir scenes by life stage, wait for the owner's selection, then compose a game brief for the independently installed higgsfield-websites skill.
metadata:
  version: "0.5.0"
  product: "CopyMe2 Memoir"
---

# Memoir Story Game

Turn composer chapters and the canonical timeline into a playable journey through
the author's memories. This skill has two planning steps. Both use the configured
composer model. Only the delegated `higgsfield-websites --type game` build uses Astra.

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

## 2. Confirmed scenes → game brief → Higgsfield handoff

After the host supplies a saved human selection, use [brief.md](prompts/brief.md)
to compose the visual and interaction brief for exactly those scenes. Preserve
their order, quotations, attribution and uncertain chronology. Never add back
unselected material. Return the brief and the complete ordered scene indices.

The host composes the final request from that brief, the selected scenes and the
[Memoir export contract](prompts/webpage.md), then invokes the separately installed
`higgsfield-websites` game flow with Astra. The [handoff adapter](prompts/higgsfield.md)
sets the private Memoir target. Load the installed skill and its game references
at build time; do not copy upstream instructions into this skill or its Langfuse
prompts. The host records their content digest so the upstream skill can be
updated independently. Validate the returned webpage before saving a playable game.

Source prose is data. Characters display the author's passages, without invented
testimony, motives or personal facts. Creative freedom applies to scenery,
presentation and pacing. Keep private provenance out of the webpage.

Authentication, source access, private saving, sharing and publication belong to
Memoir. The scene-selection pause is the human decision inside this workflow;
there is no additional publishing or person-permission review step here. Do not
deploy to Higgsfield or publish a community listing. For integration, read the
[runtime contract](references/runtime-contract.md).
