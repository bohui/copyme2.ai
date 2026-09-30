# Repository skill end-to-end testing

Run date: 2026-09-28. Scope: all six skills under `skills/` in the current working tree. Status: **browser and synthetic regression green; live-model browser journey remains unverified**. The checks below distinguish real model/source execution from deterministic browser contracts; they do not claim one uninterrupted browser → live agent → production persistence → browser journey.

## Latest rerun

- `tests/browser_ten_round_e2e.py --locale all` passed against an isolated local test-mode stack: 10 streamed rounds in `en-AU` and 10 streamed rounds in `zh-CN`.
- The two language cases verified the fixed opening, persisted `preferred_language`, first-reply localization metadata, streaming completion, memory answers, place journey, paid family tree, author timeline, public-photo cue rendering, renderer fallbacks, and absence of raw `MEMORY_SPARK_` markers in the UI. Screenshots: [English](/Users/bohuihan/memoir/output/playwright/chat-ten-rounds-en-AU.png) and [简体中文](/Users/bohuihan/memoir/output/playwright/chat-ten-rounds-zh-CN.png).
- Dedicated browser contracts also passed for localization, first-reply localization, paid family, entitlement gates, family/timeline renderers, and place photos. These tests use intercepted deterministic agent responses to isolate browser/runtime behavior.
- `make langfuse-eval` passed all 14 checked-in synthetic trajectory cases with no failure evidence. This exercises the actual `CodexRuntime`/worker seam and the six-skill manifest, including place, family, timeline, photo, entitlement, collection, and unrelated-request cases.
- Repository verification passed: `python3 -m pytest -q` (`318 passed, 15 skipped`), frontend production build, 26 JavaScript tests, 59 place-photo unit tests, 81 Node plus 16 Python localization self-tests, 429 localization messages, and `git diff --check`.

The browser evidence was run with `MEMORY_SPARK_TEST_MODE=1` because the long-lived Supabase-backed test container began rejecting repeated anonymous sessions during the rerun. That keeps the browser contracts deterministic but does not validate a live model response or live authenticated persistence across all 10 turns.

| Skill | Observed evidence | Remaining end-to-end gap |
|---|---|---|
| app-auto-localization | 81 Node and 16 Python bundle checks passed; 429 application catalogue messages validated; localization browser journey passed after updating an obsolete transcription mock endpoint | Authenticated account persistence was not tested against live storage |
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

- `python3 -m pytest -q`: 318 passed, 15 skipped. Two skipped modules lack `temporalio`; thirteen browser pytest cases require an explicitly configured server.
- `python3 -m unittest discover -s skills/place-photo-research/tests -q`: 59 passed.
- `bash skills/app-auto-localization/scripts/self_test.sh`: 81 Node and 16 Python checks passed. Full ICU validation was not run by that bundle.
- `python3 scripts/check_localization_catalog.py`: 429 messages valid across en-AU and zh-CN.
- Browser scripts passed: `browser_localization_e2e.py`, `browser_first_reply_localization.py`, `browser_family_e2e.py`, `browser_family_gate_e2e.py`, `browser_family_renderers_e2e.py`, `browser_ten_round_e2e.py`, and `browser_place_photos_e2e.py`. These intercept agent responses and are UI integration evidence, not live-model end-to-end proof.
- `make langfuse-eval`: 14 synthetic trajectory cases passed with an empty `var/evaluation-failures/` directory.
- `npm --prefix apps/web run build`: production frontend build passed with TypeScript validation.
- `node --test tests/js/*.test.mjs`: 26 passed.
- Real configured model (`deepseek-v4-flash`) through the actual Codex app-server: combined workspace extraction passed validation for memory context, place journey, family tree and author timeline. Canonical family merge and retry checked against that captured output.
- Focused regression check: 38 tests passed across family context/agent, place journey, profile intake, conversation language, and memoir skill configuration.
- Updated timeline skill passed skill validation. `git diff --check` passed.

## Local evidence and next work

Evidence is in `var/skill-e2e/2026-09-28/`: live model response/result, canonical family document, browser logs, runner, isolated frontend, localization bundle log, and `photos/` with request, source-page snapshots, evidence, candidates, manifest, report, gallery and downloaded originals. Early failed logs are retained; `localization-recheck.log` is the successful final localization run. `browser-results.json` contains only the latest two-case batch, not the full six-case history.

Remaining: run the same two-language ten-round browser journey against a healthy authenticated environment with the live configured model and production-like persistence. The deterministic browser and synthetic-runtime coverage is complete for this rerun; live-model browser evidence is the only material gap recorded here.
