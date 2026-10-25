from pathlib import Path


def _api_service_block() -> str:
    return Path("compose.speech-local.yml").read_text(encoding="utf-8")


def test_api_service_receives_speech_provider_configuration() -> None:
    api = _api_service_block()

    expected = {
        "GROQ_API_KEY": "${GROQ_API_KEY:-}",
        "GROQ_BASE_URL": "${GROQ_BASE_URL:-https://api.groq.com/openai/v1}",
        "COSYVOICE_API_KEY": "${COSYVOICE_API_KEY:-}",
        "COSYVOICE_BASE_URL": "${COSYVOICE_BASE_URL:-http://192.168.0.50:50001}",
        "MEMOIR_ORIGINAL_RECORDINGS": "${MEMOIR_ORIGINAL_RECORDINGS:-0}",
        "DASHSCOPE_API_KEY": "${DASHSCOPE_API_KEY:-}",
        "DASHSCOPE_WORKSPACE_ID": "${DASHSCOPE_WORKSPACE_ID:-}",
        "DASHSCOPE_REGION": "${DASHSCOPE_REGION:-ap-southeast-1}",
        "MEMORY_SPARK_STT_MODEL": "${MEMORY_SPARK_STT_MODEL:-whisper-large-v3-turbo}",
        "MEMORY_SPARK_QWEN_STT_MODEL": "${MEMORY_SPARK_QWEN_STT_MODEL:-qwen3-asr-flash}",
        "MEMORY_SPARK_TTS_MODEL": "${MEMORY_SPARK_TTS_MODEL:-cosyvoice-v3-flash}",
        "MEMORY_SPARK_TTS_VOICE_EN_AU": "${MEMORY_SPARK_TTS_VOICE_EN_AU:-longwan_v3}",
        "MEMORY_SPARK_TTS_VOICE_ZH_CN": "${MEMORY_SPARK_TTS_VOICE_ZH_CN:-longwan_v3}",
    }

    for name, value in expected.items():
        assert f"      {name}: {value}" in api
