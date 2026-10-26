# Final build — A Patch That Stays

buildStage: production
buildPath: custom
experienceProfile: system-led
targetFinish: playable-prototype
signature_command: N/A

The fictional age-eight example uses all ten composer chapters and linked timeline events. Two deterministic tyre-repair challenges form the playable loop; all ten unchanged passages remain available through the complete-memory dialog. Practice results leave the remembered events and explicit uncertainty unchanged.

The final candidate combines the live Sol max whitebox with its separately generated Enamel & Chalk stylesheet. The HTML and JavaScript are byte-identical to the verified whitebox. The broader production request failed upstream; its receipt is preserved and the successful CSS-only repair is in stages/production_style/.

## Toolchain and reproduction

- Native offline HTML/CSS/JavaScript; no package manager, external assets or build dependency.
- Tested runtime: Chromium 151.0.7922.34 on Darwin; desktop pointer/keyboard and mobile touch emulation.
- Start: `python3 var/novel-to-game-age-eight-20261025/serve.py` (loopback preview), or open `export/age-eight.html` offline.
- Verify: `python3 var/novel-to-game-age-eight-20261025/verify.py --stage production`; add `--phone` for mobile touch.
- Additional checks/export: `python3 var/novel-to-game-age-eight-20261025/extra_checks.py`.

## Observed result

Final desktop and touch runs independently passed launch, rendering, input, the core loop, ending and restart in one clean run each. The replay covers early pressing and a missed leak before recovery. Additional keyboard runs at 1280px and 320px passed, including combined faults, retained observations, memory-dialog focus/state, exact source text and offline play. No page errors or external requests were observed.

The authoritative final fact source is qa/verification.json; phone observations and additional diagnostics are linked from result.json. Final public file hashes are recorded there. Physical devices, Safari, Firefox, app authentication/sharing, subjective enjoyment and session duration remain untested. No publication or canonical generator switch occurred. Higgsfield remains the separate backup.
