---
name: memoir-novel-to-game
description: Generate a continuous chronological Memoir RPG walk with NovelToGame, validated route plans, smooth illustrated transitions and reusable life-stage avatars.
metadata:
  version: "0.3.0"
  status: experimental
---

# Memoir NovelToGame experiment

This package keeps the NovelToGame evaluation separate from the active
`memoir-story-game` skill. The active Memoir workflow and its independently
installed Higgsfield builder remain available.

## Fixed game format

Build **one continuous chronological walk**. The author moves forward through
the supplied timeline, visiting each memory on that same path. Later visits to
the same place occur further right. Keep uncertain dates and ordering explicit.
Illustrations pan within a place and blend smoothly into the next while the
player, ground baseline and camera remain continuous. Keep keyboard/touch,
untimed readable passages, visible focus, reduced motion, progress, ending,
restart and the complete unchanged source view.

Treat this format as a product requirement throughout analysis, concept, design,
art, build and QA. Read the [journey policy](journey-policy.md) before concept or
design. The [adapter](adapter.md), structured `format_contract` and host-owned
`runtime/` enforce this format across future generations. Models supply the route,
art plan and styling; the host owns movement, scene blending, HTML, JavaScript and
replay. Use one global increasing position, without hub trips or travel portals.

## Stage workflow

Run `make deps-install` when the dependency is missing. Read the pinned
[upstream entrypoint](../../deps/novel-to-game/skills/novel-to-game/SKILL.md) and its
pipeline contract. Keep its stage skills separate and unmodified. Use GPT-6.1 Sol
with max effort for this experiment. Source analysis may be reused only when its
receipt and complete input match; the fictional age-eight source analysis is
preserved under `examples/age-eight-patch/`.

Use `stages.py` one persisted stage at a time: `analyze`, `concept`, `design`,
`whitebox`, `art`, then `production`. Design returns `GAME_DESIGN.md` and
`JOURNEY_PLAN.json`; `journey.py` validates complete chapter coverage, timeline
order, contiguous scenery and increasing memory positions. It binds avatars to
source life stages and optional owner-approved professions. Whitebox is already
playable using the fixed runtime and its generated ordinary-input replay, so
separate model calls for movement logic and replay are unnecessary. After art,
prepare the scene assets below. Production supplies styling and BUILD_BRIEF.
Use `production_style` only for a focused CSS repair. A matching checkpoint reuses
the saved result. Changing the request invalidates reuse. Keep failed attempts;
split a failed large build by output file before retrying. Report observed usage;
the previous pool exceeded requested token ceilings, so they are not hard bounds.

The runner prepares a request without credentials or network by default:

```sh
python3 experiments/novel-to-game/stages.py concept --output var/novel-to-game-rpg-scroller
```

Add `--execute --env-file /path/to/owner.env` only for an authorised live run.
Continue later stages in the same output directory after their required handoffs
exist. The default input is the fictional age-eight benchmark. For another memoir,
start `analyze --source /approved/composer-timeline.json --brief /approved/PRODUCT_BRIEF.md`
in a fresh output directory. The JSON contains `input.chapters`, linked
`input.timeline`, locale, and optional title/fictional metadata. The runner saves
the input and brief for later stages and requires fresh analysis; it never seeds
another memoir with the benchmark's facts. This runner is not connected to
authenticated production generation.

After whitebox play, save actual feedback as `whitebox-feedback.json` before art.
Read the [asset policy](asset-policy.md) at this point. The runner supplies
`illustrated-lifetime-v1`: childhood, teenage, young adult, midlife and older
avatars, professional/workwear variants, CSS markers and original opt-in music.
Reuse these files; generate only scene backgrounds. A profession/outfit comes
only from the optional owner-approved character profile, never from a model's
guess or a parent's job. The age-eight source stays a child throughout. These are
imagined generic avatars; choose another approved family when appropriate.
Upstream NovelToGame remains independently updatable.

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
movement, continuous travel between settings, ordered reading, progress, ending
and restart. Verify monotonic player/camera positions, smooth overlap in normal
motion and stable reduced-motion scenery. Host runtime files must match their
reviewed bytes; model outputs cannot replace them.
Run `journey_checks.py --output <workspace>` for independent normal-speed blend,
monotonic movement, source, reader pause, avatar-family and opt-in audio probes.
Add independent probes for passage fidelity, revisit/full-text credit, movement
bounds, locked areas, focus, 320px layout and offline assets. `extra_checks.py`
targets the archived first RPG's selectors and state; adapt these probes to the
actual build before using them on another game. Also exercise stock avatar
idle/walk/facing, reduced motion, scene atlas cells and opt-in/mute audio as
specified in the asset policy.
Record all six upstream QA checks from one complete clean run. Physical-device
and subjective-experience claims require their own evidence.

## Integration boundary and provenance

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

These experimental repository prompts are outside the managed Langfuse registry. Keep the
active skill, managed prompts, Langfuse pins, production routes and saved games
unchanged. Future integration must retain Memoir's ownership, consent, selection
and access checks. Publishing follows the repository's merged-main prompt
workflow.

The [live-generated age-eight RPG](examples/age-eight-rpg/build/app/index.html)
and its [run receipt](examples/age-eight-rpg/run-receipt.json) preserve the fresh
Sol max example, observed browser results and separately recorded host repairs.
Serve its `build/app/` directory or open its HTML directly for offline play.
