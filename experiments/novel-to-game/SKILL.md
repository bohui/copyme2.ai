---
name: memoir-novel-to-game
description: Evaluate the separate NovelToGame pipeline for a Memoir RPG side scroller, using checkpointed stages and the approved memoir source.
metadata:
  version: "0.1.0"
  status: experimental
---

# Memoir NovelToGame experiment

This branch keeps the NovelToGame evaluation separate from the active
`memoir-story-game` skill. The active Memoir workflow and its independently
installed Higgsfield builder remain available.

## Fixed game format

Build an RPG side-scrolling journey: the player controls the author, moves
horizontally through connected settings, and approaches characters or memory
markers to interact. Keep a scrolling camera, distinct scenery, visible progress,
an ending and restart. Support keyboard and touch movement, readable dialogue,
visible focus, reduced motion and the complete source-text view. Source-supported
activities may be encounters within the journey; travel and interaction remain
central.

Treat this format as a product requirement throughout analysis, concept, design,
art, build and QA. Concept selection chooses the route, encounters and pacing
within it. The [adapter](adapter.md) and structured `format_contract` supply this
requirement to every model stage.

## Stage workflow

Read the pinned [upstream entrypoint](upstream/novel-to-game/SKILL.md) and its
pipeline contract. Keep its stage skills separate and unmodified. Use GPT-6.1 Sol
with max effort for this experiment. Source analysis may be reused only when its
receipt and complete input match; the fictional age-eight source analysis is
preserved under `examples/age-eight-patch/`.

Use `stages.py` for one stage at a time: concept, design, whitebox layout,
`whitebox_logic`, `whitebox_replay`, art and production. The layout stage is named
`whitebox`; it is not playable until logic and replay are saved. A
`production_style` pass changes only CSS and can finish the visual production
when the tested structure and rules already meet the approved design. A matching checkpoint reuses
the saved result. Changing the request invalidates reuse. Keep failed attempts;
split a failed large build by output file before retrying. Report observed usage;
the previous pool exceeded requested token ceilings, so they are not hard bounds.

The runner prepares a request without credentials or network by default:

```sh
python3 experiments/novel-to-game/stages.py concept --output var/novel-to-game-rpg-scroller
```

Add `--execute --env-file /path/to/owner.env` only for an authorised live run.
Continue later stages in the same output directory after their required
handoffs exist. The current runner supports the complete fictional age-eight
benchmark; it is not connected to authenticated production generation.

After whitebox play, save actual feedback as `whitebox-feedback.json` before art.
For a runnable candidate, run `verify.py --output <workspace> --stage production`
and repeat with `--phone`. The replay must demonstrate player movement, camera
movement, travel between settings, an interaction, progress, ending and restart.
Run `extra_checks.py --output <workspace> --stage production` for independent
passage fidelity, revisit/full-text credit, movement bounds, locked-garden,
focus, 320px layout and offline-export checks.
Record all six upstream QA checks from one complete clean run. Physical-device
and subjective-experience claims require their own evidence.

## Branch boundary and provenance

`upstream/` is the unchanged MIT-licensed v0.6.1 snapshot at
`c3075f35cc14d4bc94e2829df2bfcc0d9971229e`; replace that separate snapshot when
explicitly updating upstream. Memoir requirements belong in the adapter.

`examples/age-eight-patch/` preserves the earlier repair-puzzle experiment,
including its original instructions, code, handoffs and receipts. It is a
historical comparison, and its PASS receipts do not establish RPG QA. Full raw
requests, responses and screenshots remain private under ignored `var/` in this
worktree. `snapshot.json` fingerprints the tracked historical files.

These experimental instructions are unpublished branch artifacts. Keep the
active skill, managed prompts, Langfuse pins, production routes and saved games
unchanged. Future integration must retain Memoir's ownership, consent, selection
and access checks. Publishing follows the repository's merged-main prompt
workflow.
