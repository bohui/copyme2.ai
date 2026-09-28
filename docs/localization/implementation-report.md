# Localization implementation report

## Delivered

- The active Memoir profile menu contains profile settings without the removed artwork/language selectors. The pre-conversation landing screen keeps the reviewed UI language selector so a visitor can choose a fixed language before starting.
- Locale changes update the active client catalogue and `<html lang>` without reloading the page, preserving the current conversation and voice state.
- UI locale and interview language are separate contracts. The browser sends an explicit profile preference only when one exists; otherwise the API/runtime infers the conversation language without changing the UI cookie, account `ui_locale`, or page catalogue.
- Voice transcripts and first replies no longer change the UI locale. Speech synthesis and browser read-aloud use the selected interview language when configured, with the UI locale as the presentation fallback.
- Exact machine-readable dates and times use `Intl.DateTimeFormat(currentUiLocale())`; uncertain expressions such as `around 1976` and `the late 1960s` are preserved verbatim.
- The catalog checker now validates keys/placeholders and parses every message with FormatJS ICU syntax. Sensitive consent, payment, privacy, and Mira copy is listed in [`apps/web/messages/human-review.json`](../../apps/web/messages/human-review.json) for bilingual human/native-speaker review.

## Verification

- `npm run build` — passed before the independent-language slice; rerun after the final client patch is still required.
- `python3 scripts/check_localization_catalog.py` — passed: 427 messages plus ICU parsing and the human-review manifest.
- `node --test tests/js/dates.test.mjs` — passed: exact dates/times localize and uncertain expressions remain unchanged.
- `python3 -m pytest -q tests/test_conversation_language.py tests/test_profile_settings.py tests/test_trajectory_evaluation.py` — passed.
- `python3 scripts/run_langfuse_evaluation.py` — passed all four checked-in synthetic cases with no failure evidence.

The browser regression suite must be rerun against fresh API and Next.js processes before closing the localization ticket; a previous long-lived dev process still served the pre-decoupling client during part of this work.

## Limitation

The checked-in sensitive-copy manifest marks human/native-speaker review as required; automated checks do not claim that external bilingual sign-off has occurred.
