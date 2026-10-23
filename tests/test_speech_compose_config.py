from pathlib import Path


def _api_service_block() -> str:
    compose = Path("compose.yml").read_text(encoding="utf-8")
    return compose.split("\n  codex-worker:", 1)[0]


def test_api_service_receives_speech_provider_configuration() -> None:
    api = _api_service_block()

    expected = {
        "OPENAI_API_KEY": "${OPENAI_API_KEY:-}",
        "OPENAI_BASE_URL": "${OPENAI_BASE_URL:-https://api.openai.com/v1}",
        "GEMINI_API_KEY": "${GEMINI_API_KEY:-}",
        "DOUBAO_API_KEY": "${DOUBAO_API_KEY:-}",
        "MEMORY_SPARK_STT_MODEL": "${MEMORY_SPARK_STT_MODEL:-gpt-4o-mini-transcribe}",
        "MEMORY_SPARK_TTS_MODEL": "${MEMORY_SPARK_TTS_MODEL:-gemini-3.8-flash-lite-tts}",
        "MEMORY_SPARK_TTS_VOICE_EN_AU": "${MEMORY_SPARK_TTS_VOICE_EN_AU:-Kore}",
        "MEMORY_SPARK_TTS_VOICE_ZH_CN": "${MEMORY_SPARK_TTS_VOICE_ZH_CN:-zh_female_vv_uranus_bigtts}",
    }

    for name, value in expected.items():
        assert f"      {name}: {value}" in api
