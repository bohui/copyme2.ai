---
name: memoir-story-game
description: Use in the integrated Memoir Codex harness to prepare a private, source-grounded side-scrolling game only in Shape after verified composition completion and separate adaptation consent. Validate reviewed data for a fixed browser renderer.
metadata:
  version: "0.2.0"
  product: "CopyMe2 Memoir"
---

# Memoir Story Game

Turn the author's completed memoir into a small, connected journey: the author
controls a generic protagonist, walks between scenes, and approaches people from
the memoir to explore “Who am I?” through reviewed dialogue. Portray only supported
memories and the author's attributed perspective, never invented personality,
motives, diagnoses or a supposed objective verdict on their identity.

This is a repository-native product harness skill, like `memoir-place-journey`,
not a personal coding-session skill. Repository registration supplies a loader,
manifest discovery and blocked admission. It does **not** install a skill,
implement a game renderer or make a Shape feature available. Missing host bindings
are blockers, not permission to simulate success.

The companion [formal workflow](references/formal-workflow.md) implements private
extractive composition, durable completion and separate consent in an additive,
unapplied migration. Its authenticated eligibility result remains `available=false`.
Completion covers the frozen intended chapter plan, not every event in a life.

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
3. **Review.** Create a server-only candidate with
   `schemas/candidate.schema.json`; keep the authority/evidence request separate
   under `schemas/request.schema.json`. Obtain author review of the exact game
   digest. Corrections, changed consent or revocation invalidate that review.
4. **Validate.** Use `scripts/validate.py` with synthetic fixtures during package
   development. For host integration, validate a fresh authenticated snapshot at
   admission, commit and each delivery. Return a blocked result on any mismatch;
   never release a “mostly valid” package. Local JSON cannot prove host identity,
   consent authenticity, factual entailment or atomic persistence.
5. **Handoff.** The host alone projects the validated `game` object, conforming to
   `schemas/game.schema.json`, to its fixed renderer. The browser receives approved
   text, aliases, opaque IDs and allowlisted local asset keys. Keep evidence,
   authority, canonical people IDs, review metadata and privacy decisions server-side.
6. **Advance by milestones.** Follow [acceptance.md](references/acceptance.md),
   stopping at each evidence-backed exit criterion. Begin with two synthetic
   scenes and two NPCs. Optimize only a measured bottleneck after correctness,
   accessibility and cleanup pass.

Recommend Phaser 4.2.1 (MIT) and reuse the official Next template's client lifecycle
patterns, with the restrictions and verified sources in the acceptance reference.
Use generic project art initially; optional Kenney CC0 references need no download
for this package. The user's Astra preference does not establish a product API
model ID. Keep existing model allowlists unchanged; block model execution until
the host verifies its model binding. No paid-service assumption is needed.
