from pathlib import Path


def _api_service_block() -> str:
    compose = Path("compose.yml").read_text(encoding="utf-8")
    return compose.split("\n  codex-worker:", 1)[0]


def test_api_service_receives_speech_provider_configuration() -> None:
    api = _api_service_block()

    expected = {
        "OPENAI_API_KEY": "${OPENAI_API_KEY:-}",
        "OPENAI_BASE_URL": "${OPENAI_BASE_URL:-https://api.openai.com/v1}",
        "MEMORY_SPARK_STT_MODEL": "${MEMORY_SPARK_STT_MODEL:-gpt-4o-mini-transcribe}",
        "MEMORY_SPARK_TTS_MODEL": "${MEMORY_SPARK_TTS_MODEL:-gpt-4o-mini-tts}",
    }

    for name, value in expected.items():
        assert f"      {name}: {value}" in api
