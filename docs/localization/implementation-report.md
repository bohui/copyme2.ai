# Localization implementation report

## Delivered

- The active Memoir profile menu contains profile settings without the removed artwork/language selectors. The pre-conversation landing screen keeps the reviewed UI language selector so a visitor can choose a fixed language before starting.
- Locale changes update the active client catalogue and `<html lang>` without reloading the page, preserving the current conversation and voice state.
- UI locale and interview language remain separately stored after a bounded onboarding bridge. A saved profile language seeds the UI locale on boot when no explicit page-language cookie or account `ui_locale` exists, so the choice survives refresh. When no fixed device-source cookie, account `ui_locale`, or saved conversation language exists, the first substantive reply detects `en-AU`/`zh-CN` locally, switches the current UI session, and sends the same temporary language to the runtime before the visible reply. If the profile already contains a conversation language, the detector is skipped and that explicit value is sent directly to Mira. Automatic detection does not write fixed account metadata; explicit device/account choices remain authoritative.
- Later voice transcripts and interview replies do not change the UI locale. Speech synthesis and browser read-aloud use the selected interview language when configured, with the UI locale as the presentation fallback.
- Exact machine-readable dates and times use `Intl.DateTimeFormat(currentUiLocale())`; uncertain expressions such as `around 1976` and `the late 1960s` are preserved verbatim.
- The catalog checker now validates keys/placeholders and parses every message with FormatJS ICU syntax. Sensitive consent, payment, privacy, and Mira copy is listed in [`apps/web/messages/human-review.json`](../../apps/web/messages/human-review.json) for bilingual human/native-speaker review.

## Verification

- `npm run build` — passed after the independent-language and date-formatting patches.
- `python3 scripts/check_localization_catalog.py` — passed: 427 messages plus ICU parsing and the human-review manifest.
- `node --test tests/js/*.test.mjs` — passed: locale precedence, exact dates/times, uncertain expressions, and live traces are covered.
- `python3 -m pytest -q tests/test_conversation_language.py tests/test_profile_settings.py tests/test_trajectory_evaluation.py tests/test_evaluation_cases.py` — passed.
- `python3 scripts/run_langfuse_evaluation.py --variant baseline --variant candidate --baseline-variant baseline --concurrency 3` — passed all 28 case/variant runs with no failure evidence and produced comparison rows. The dataset covers current-day and historical place references, ambiguous and unrelated requests, all paid/unpaid/pending/revoked Family states, and collection review/handoff/source/task paths; collection task cases execute deterministic results through the runtime workspace branch.
- `python3 tests/browser_localization_e2e.py --base-url http://127.0.0.1:3011` — passed the rendered locale, interview-language, error, and voice contract against the running Next.js frontend.
- `python3 tests/browser_first_reply_localization.py --base-url http://127.0.0.1:3011` — passed the first-reply auto-switch and fixed-choice contract.

The browser checks were run against the existing local API/Next.js services because the repository's `with_server.py` helper cannot start a second Next.js process while the shared `.next/dev` lock is held. The production build also passed, and no browser assertion failed.

The semantic judge path now rejects calibration data unless its manifest is
explicitly marked `human-reviewed`; no such external calibration or live
Langfuse publish is claimed by this local report.

## Limitation

The checked-in sensitive-copy manifest marks human/native-speaker review as required; automated checks do not claim that external bilingual sign-off has occurred.
