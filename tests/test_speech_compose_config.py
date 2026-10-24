from pathlib import Path


def _api_service_block() -> str:
    compose = Path("compose.yml").read_text(encoding="utf-8")
    return compose.split("\n  codex-worker:", 1)[0]


def test_api_service_receives_speech_provider_configuration() -> None:
    api = _api_service_block()

    expected = {
        "OPENAI_API_KEY": "${OPENAI_API_KEY:-}",
        "OPENAI_BASE_URL": "${OPENAI_BASE_URL:-https://api.openai.com/v1}",
        "GROQ_API_KEY": "${GROQ_API_KEY:-}",
        "GROQ_BASE_URL": "${GROQ_BASE_URL:-https://api.groq.com/openai/v1}",
        "DASHSCOPE_API_KEY": "${DASHSCOPE_API_KEY:-}",
        "DASHSCOPE_WORKSPACE_ID": "${DASHSCOPE_WORKSPACE_ID:-}",
        "DASHSCOPE_REGION": "${DASHSCOPE_REGION:-ap-southeast-1}",
        "DASHSCOPE_COSYVOICE_WS_URL": "${DASHSCOPE_COSYVOICE_WS_URL:-}",
        "MEMORY_SPARK_STT_MODEL": "${MEMORY_SPARK_STT_MODEL:-whisper-large-v3-turbo}",
        "MEMORY_SPARK_QWEN_STT_MODEL": "${MEMORY_SPARK_QWEN_STT_MODEL:-qwen3-asr-flash}",
        "MEMORY_SPARK_TTS_MODEL": "${MEMORY_SPARK_TTS_MODEL:-cosyvoice-v3-flash}",
        "MEMORY_SPARK_TTS_VOICE_EN_AU": "${MEMORY_SPARK_TTS_VOICE_EN_AU:-longwan_v3}",
        "MEMORY_SPARK_TTS_VOICE_ZH_CN": "${MEMORY_SPARK_TTS_VOICE_ZH_CN:-longwan_v3}",
    }

    for name, value in expected.items():
        assert f"      {name}: {value}" in api
