---
name: memoir-novel-to-game
description: Build and evaluate a Memoir RPG side scroller with the separate NovelToGame pipeline, checkpointed stages, reusable stock art and newly illustrated scenes.
metadata:
  version: "0.2.0"
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

Run `make deps-install` when the dependency is missing. Read the pinned
[upstream entrypoint](../../deps/novel-to-game/skills/novel-to-game/SKILL.md) and its
pipeline contract. Keep its stage skills separate and unmodified. Use GPT-6.1 Sol
with max effort for this experiment. Source analysis may be reused only when its
receipt and complete input match; the fictional age-eight source analysis is
preserved under `examples/age-eight-patch/`.

Use `stages.py` for one stage at a time: `analyze` for fresh source analysis,
concept, design, whitebox layout,
`whitebox_logic`, `whitebox_replay`, art and production. The layout stage is named
`whitebox`; it is not playable until logic and replay are saved. After art,
prepare the scene assets below and use `production` to integrate them. Use
`production_style` only for CSS repairs after the assets are integrated. A matching checkpoint reuses
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
Read the [asset policy](asset-policy.md) at this point. The runner supplies the
approved `illustrated-childhood-v1` pack: animated child, CSS markers and original
opt-in music. Reuse these files; generate only scene backgrounds. This generic
childhood pack suits the age-eight benchmark. Choose an appropriate reusable pack
before adapting other ages. Upstream NovelToGame remains independently updatable.

The art stage saves `ART_DIRECTION.md` and `SCENE_ART_PLAN.json`. Restore cached
illustrations before making image calls:

```sh
python3 experiments/novel-to-game/game_assets.py prepare --output <workspace>
```

For each `missing` scene illustration, apply the image-generation skill with that
entry's complete prompt. Prefer one atlas for compatible locations. Inspect the
result, then register the original PNG:

```sh
python3 experiments/novel-to-game/game_assets.py record --output <workspace> --id places --image /absolute/generated.png
```

The cache uses the exact scene prompt, style and grid; a changed requirement gets
a new key. It lives under ignored `var/novel-to-game-scene-cache/`. The host stages
verified stock bytes and cached scenes into the app and passes paths, hashes and
actual cell dimensions to production. Production execution waits for ready scene
assets; previews remain offline. Shared characters, UI, portraits, music and sound
are reused, so only missing scene illustrations incur image-generation calls.

For a runnable candidate, run `verify.py --output <workspace> --stage production`
and repeat with `--phone`. The replay must demonstrate player movement, camera
movement, travel between settings, an interaction, progress, ending and restart.
Add independent probes for passage fidelity, revisit/full-text credit, movement
bounds, locked areas, focus, 320px layout and offline assets. `extra_checks.py`
targets the archived first RPG's selectors and state; adapt these probes to the
actual build before using them on another game. Also exercise stock avatar
idle/walk/facing, reduced motion, scene atlas cells and opt-in/mute audio as
specified in the asset policy.
Record all six upstream QA checks from one complete clean run. Physical-device
and subjective-experience claims require their own evidence.

## Branch boundary and provenance

`deps/novel-to-game/` is an unmodified MIT-licensed Git submodule. Git records the
reviewed revision; `make deps-install` restores it and `make deps-update` checks
out upstream's latest `main`. Review and commit the changed submodule pin before
sharing an upgrade. The runner records the installed commit in every request and
receipt, and rejects local upstream edits. Memoir requirements belong in the adapter.

Repository agents discover the seven upstream skills and this Memoir entrypoint
through `.agents/skills/` links. Codex lists the upstream plugin's skills as
`novel-to-game:<skill>`. Dependency updates preserve the adapter and the
historical examples, whose recorded upstream revisions describe their original runs.

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

The [live-generated age-eight RPG](examples/age-eight-rpg/build/app/index.html)
and its [run receipt](examples/age-eight-rpg/run-receipt.json) preserve the fresh
Sol max example, observed browser results and separately recorded host repairs.
Serve its `build/app/` directory or open its HTML directly for offline play.
