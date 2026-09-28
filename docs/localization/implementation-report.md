# Localization implementation report

## Delivered

- The active Memoir profile menu contains profile settings without the removed artwork/language selectors. The pre-conversation landing screen keeps the reviewed UI language selector so a visitor can choose a fixed language before starting.
- Locale changes update the active client catalogue and `<html lang>` without reloading the page, preserving the current conversation and voice state.
- The first typed or transcribed storyteller reply uses a conservative Unicode script check to align the live UI before the first agent request. The detected locale is sent with that request so the first streamed reply and controls use the same language. This automatic session switch does not write the fixed `copyme2_ui_locale` cookie or signed-in account metadata; explicit selector changes still persist the device/account choice.
- Voice transcripts use the provider language metadata and the same safe live switch path. A fixed device cookie or account UI preference always wins over inference.

The first-reply text signal is an explicit product request for this memoir onboarding flow; it is deliberately limited to that first submitted reply rather than a global chat listener.

## Verification

- `npm run build` — passed.
- `make browser-localization-test` — the current rerun stopped at the initial page load with Playwright `ERR_EMPTY_RESPONSE` after the helper reported both servers ready; the targeted first-reply contract below passed against the running web server.
- `python3 tests/browser_first_reply_localization.py --base-url http://127.0.0.1:3011` — passed, including automatic Chinese first reply, first-request locale, no fixed-cookie write, and fixed-device precedence.
- `pytest -q tests/test_conversation_language.py tests/test_profile_settings.py` — 11 passed.
- `python3 -m pytest -q tests/test_speech.py tests/test_agent_routes.py tests/test_web_container_config.py` — 9 passed.
- `tests/browser_e2e.py --expect-thinking-steps` — passed.

The default `make browser-test` expectation is currently inconsistent with the repository `.env`: the API reports thinking steps enabled even when that command prefixes `MEMORY_SPARK_SHOW_THINKING_STEPS=0`. This is unrelated to the localization changes.

## Limitation

Voice auto-detection is intentionally limited to the existing `en-AU` and `zh-CN` choices. It is not a general-purpose speech-language classifier, and ambiguous or short transcripts leave the current locale unchanged.
