# Final build — The Blue Gate

buildStage: production
buildPath: custom
targetFinish: playable-prototype
experienceProfile: hybrid
signature_command: N/A

A fresh NovelToGame RPG side-scroller from the complete fictional age-eight source: ten composer chapters, ten timeline events, five connected settings and ten complete original passages. The player walks the author, approaches characters/memory markers, explores nine memories to unlock the garden, and reaches the fixed next-morning drawing finale after the tenth. Exploration order is explicitly not a timeline. All remembered outcomes and unknowns stay fixed.

## Generation and repairs
Seven new live GPT-6.1 Sol max calls produced concept, design, layout, runtime, replay, art direction and final CSS. The earlier full-source analysis was reused only after its exact input fingerprint matched. Original model outputs and request/response receipts remain in the private workspace. A host repair makes held Enter/Space on movement buttons move rather than interact; arrows/A/D and E/Enter remain supported. The replay's first interaction uses the on-screen control so the phone route is entirely touch-operated. These changes are recorded separately.

## Actual toolchain and verification
Native HTML/CSS/JavaScript; system fonts and original CSS graphics; no package manager, engine dependency, network or runtime models. Tested runtime: Chromium 151.0.7922.34 on Darwin, with desktop keyboard/pointer and phone touch emulation.

Start: `python3 experiments/novel-to-game/serve.py --output var/novel-to-game-rpg-scroller`. The generated `export/age-eight.html` is also playable offline.

Verify: `python3 experiments/novel-to-game/verify.py --output var/novel-to-game-rpg-scroller --stage production`, then repeat with `--phone`. Additional checks/export: `python3 experiments/novel-to-game/extra_checks.py --output var/novel-to-game-rpg-scroller --stage production`.

The final desktop and fully touch-operated phone runs each passed launch, rendering, real movement/camera/scene input, the complete core loop, ten-memory ending and restart in a single clean run. Independent 1280px/320px checks passed exact source fidelity, no duplicate/full-text credit, paused movement during reading, restored focus, movement bounds, camera travel, blocked early garden entry, Enter/Space movement controls and offline interaction. No page errors or external requests were observed. A fresh source-blind agent reached the whitebox ending without solutions; its report is preserved in whitebox-feedback.json.

Authoritative current QA: qa/verification.json. Additional phone and invariant evidence plus exact model/file fingerprints are linked from result.json. Physical devices, Safari/Firefox, assistive technologies, app authentication/sharing and subjective enjoyment remain untested. Higgsfield and the active Memoir flow are unchanged; this is a local experimental preview.
