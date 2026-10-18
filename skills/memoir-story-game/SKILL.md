---
name: memoir-story-game
description: Use in the integrated Memoir Codex harness to prepare a private, source-grounded side-scrolling game only in Shape after verified composition completion and separate adaptation consent. Validate reviewed data for a fixed browser renderer.
metadata:
  version: "0.3.0"
  product: "CopyMe2 Memoir"
---

# Memoir Story Game

Turn the author's completed memoir into a small, connected journey: the author
controls a generic protagonist, walks between scenes, and approaches people from
the memoir to explore “Who am I?” through reviewed dialogue. Portray only supported
memories and the author's attributed perspective, never invented personality,
motives, diagnoses or a supposed objective verdict on their identity.

This repository-native product skill runs through `story_game_routes.py` and
`story_game_runtime.py`. The host owns current Shape, immutable formal completion,
separate adaptation consent, exact-original validation and private publication.
Chat text, a strategy proposal or browser-supplied booleans cannot establish those
gates. Completion covers the frozen intended chapter plan, not every event in a life.

## Workflow

1. **Admit.** Read [runtime-contract.md](references/runtime-contract.md). Require
   authenticated, current Shape state, a durable completion receipt bound to the
   chosen manuscript revision and full chapter coverage, and separate private
   game-adaptation consent. Shape, `storytelling_complete`, an existing preview,
   or `formal_memoir` with `status=draft` is insufficient. Stop with the missing
   gate when the host cannot establish authority.
2. **Ground.** Read [privacy-and-grounding.md](references/privacy-and-grounding.md).
   Freeze the permitted manuscript and original evidence. Propose aliased, generic
   NPCs and modest scenes. Have every factual title, label and dialogue line
   reviewed server-side against both. Unsupported facts block the candidate.
3. **Propose.** When the host supplies a claimed job and its frozen chapters,
   follow [proposal.md](prompts/proposal.md). Return two scenes, each quoting one
   exact original-backed chapter block and mentioning a distinct supported person.
   Do not invent a second person or dialogue to meet the minimum. This is a draft
   for review; it grants no person permissions and cannot be played yet.
4. **Review.** The host assigns generic aliases and opaque IDs, validates every
   factual title and quotation against stored originals, then shows the exact
   candidate to the author. Require separate confirmation that each represented
   person is a distinct adult and that the exact passages are permitted for this
   private adaptation. Obtain approval of the whole candidate digest. Corrections,
   changed consent or revocation invalidate that review.
5. **Validate.** Use `scripts/validate.py` with synthetic fixtures during package
   development. For host integration, validate a fresh authenticated snapshot at
   admission, commit and each delivery. Return a blocked result on any mismatch;
   never release a “mostly valid” package. Local JSON cannot prove host identity,
   consent authenticity, factual entailment or atomic persistence.
6. **Handoff.** The host alone projects the validated `game` object, conforming to
   `schemas/game.schema.json`, to its fixed renderer. The browser receives approved
   text, aliases, opaque IDs and allowlisted local asset keys. Keep evidence,
   authority, canonical people IDs, review metadata and privacy decisions server-side.
7. **Advance by milestones.** Follow [acceptance.md](references/acceptance.md),
   stopping at each evidence-backed exit criterion. Begin with two synthetic
   scenes and two NPCs. Optimize only a measured bottleneck after correctness,
   accessibility and cleanup pass.

The fixed renderer uses local DOM/CSS silhouettes and the existing client
lifecycle; no engine or remote art is required. The host uses its configured,
verified composer gateway model. Never invent a model ID from a display name.
The offline request/candidate schemas exercise a richer design contract; production
authority comes from the database, never from those synthetic JSON documents.
