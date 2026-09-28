# Repository skill end-to-end testing

Run date: 2026-09-28. Scope: all six skills under `skills/` in the current working tree. Status: **in progress**. The checks below distinguish real model/source execution from mocked browser contracts; they do not yet prove one uninterrupted browser → real agent → production persistence → browser journey.

| Skill | Observed evidence | Remaining end-to-end gap |
|---|---|---|
| app-auto-localization | 81 Node and 16 Python bundle checks passed; 411 application catalogue messages validated; localization browser journey passed after updating an obsolete transcription mock endpoint | Reconcile skill's UI/conversation independence rule with current first-reply UI switching; authenticated account persistence was not tested against live storage |
| memoir-memory-context | Real configured model extracted childhood stage and profile from a synthetic memoir; first-reply browser contract passed | Live first-language intake and real persisted profile rendered in browser |
| memoir-place-journey | Real model returned validated Hobart hierarchy/coordinates; place/gallery browser contract passed | Same live result through authenticated storage and browser hydration |
| memoir-family-tree | Real model returned Mei/Avery and parent relationship; canonical merge and idempotent retry passed; paid and unpaid browser contracts passed | Live entitlement and authenticated persistence path with synthetic user |
| memoir-author-timeline | Real model returned school event and Hobart life period after precision vocabulary fix; canonical merge/retry passed; ten-turn browser contract passed | Same live result through authenticated persistence and browser hydration |
| place-photo-research | Real web search, 10 original Commons records inspected, 10 audited candidates, 4 distinct downloaded originals, local gallery with 10 cards and 4 decoded previews visually inspected | Six downloads received HTTP 429; current-mode live sourcing not yet exercised |

## Changes supported by failures

- The real model emitted `precision: "exact"` for a life period. The parser rejected the entire timeline marker. Added the parser's accepted precision vocabulary to `skills/memoir-author-timeline/SKILL.md`. The repeated live case passed with `range`, retaining `around 1964` as approximate.
- The ten-turn browser test targeted a removed Photos tab. Updated it to inspect the current gallery, supply explicit embed permission in its photo fixture, and isolate the fixture from live photo search. All ten turns then passed.
- The localization browser test intercepted the retired upload transcription route. Updated its mock to the current story transcription endpoint and response shape. Its complete browser journey then passed.
- A second Next.js dev server could not use the active checkout's dev lock. Tests ran against a copied frontend with shared dependencies and separate ports, preserving the existing server.

## Verification

- `python3 -m pytest -q`: 292 passed, 14 skipped. Two skipped modules lack `temporalio`; twelve browser pytest cases require an explicitly configured server.
- `python3 -m unittest discover -s skills/place-photo-research/tests -q`: 58 passed.
- `bash skills/app-auto-localization/scripts/self_test.sh`: 81 Node and 16 Python checks passed. Full ICU validation was not run by that bundle.
- `python3 scripts/check_localization_catalog.py`: 411 messages valid across en-AU and zh-CN.
- Browser scripts passed: `browser_localization_e2e.py`, `browser_first_reply_localization.py`, `browser_family_e2e.py`, `browser_family_gate_e2e.py`, `browser_ten_round_e2e.py`, `browser_place_photos_e2e.py`. These intercept agent responses and are UI integration evidence, not live-model end-to-end proof.
- Real configured model (`deepseek-v4-flash`) through the actual Codex app-server: combined workspace extraction passed validation for memory context, place journey, family tree and author timeline. Canonical family merge and retry checked against that captured output.
- Focused regression check: 35 tests passed across family context/agent, place journey, profile intake and conversation language.
- Updated timeline skill passed skill validation. `git diff --check` passed.

## Local evidence and next work

Evidence is in `var/skill-e2e/2026-09-28/`: live model response/result, canonical family document, browser logs, runner, isolated frontend, localization bundle log, and `photos/` with request, source-page snapshots, evidence, candidates, manifest, report, gallery and downloaded originals. Early failed logs are retained; `localization-recheck.log` is the successful final localization run. `browser-results.json` contains only the latest two-case batch, not the full six-case history.

Next: build an isolated synthetic storage/browser fixture that exercises the actual CodexRuntime and displays its persisted output without replacing agent replies; cover language intake and paid/unpaid boundaries. Resolve the documented UI-language contract conflict from project requirements before changing existing behavior. Retry rate-limited photo acquisition only after a suitable cooldown and preserve observed failures.
