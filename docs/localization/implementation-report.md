# Localization implementation report

## Delivered

- The language selector is rendered inside the top-right profile dropdown on active Memoir screens. The pre-conversation landing screen keeps a selector in its header so a visitor can choose a language before starting.
- Locale changes update the active client catalogue and `<html lang>` without reloading the page, preserving the current conversation and voice state.
- Voice transcripts use the provider language metadata and a conservative Unicode script check. A supported Chinese transcript switches the UI to `zh-CN` before the next agent turn, so the next request and visible controls use the same locale. The inferred change updates the browser locale cookie but does not update signed-in account metadata; manual profile changes still persist account metadata.

## Verification

- `npm run build` — passed.
- `make browser-localization-test` — passed, including profile-menu placement, refresh persistence, and the mocked Chinese voice-turn assertion (`language: "zh-CN"`).
- `python3 -m pytest -q tests/test_speech.py tests/test_agent_routes.py tests/test_web_container_config.py` — 9 passed.
- `tests/browser_e2e.py --expect-thinking-steps` — passed.

The default `make browser-test` expectation is currently inconsistent with the repository `.env`: the API reports thinking steps enabled even when that command prefixes `MEMORY_SPARK_SHOW_THINKING_STEPS=0`. This is unrelated to the localization changes.

## Limitation

Voice auto-detection is intentionally limited to the existing `en-AU` and `zh-CN` choices. It is not a general-purpose speech-language classifier, and ambiguous or short transcripts leave the current locale unchanged.
