from __future__ import annotations

from typing import Any
import json

import httpx
import pytest

from apps.api.speech import OpenAISpeechService


class RecordingSpeechClient:
    def __init__(self) -> None:
        self.path: str | None = None
        self.data: dict[str, str] | None = None

    def post(self, path: str, *, files: Any, data: dict[str, str]) -> httpx.Response:
        self.path = path
        self.data = data
        return httpx.Response(200, json={"text": "A short story.", "language": "en"})


def test_transcription_converts_regional_locale_to_provider_language_code() -> None:
    provider_client = RecordingSpeechClient()
    speech = OpenAISpeechService("test-key", client=provider_client)  # type: ignore[arg-type]

    result = speech.transcribe(
        b"audio",
        filename="answer.webm",
        mime_type="audio/webm",
        language="en-AU",
    )

    assert result["text"] == "A short story."
    assert provider_client.path == "/audio/transcriptions"
    assert provider_client.data == {
        "model": "gpt-4o-mini-transcribe",
        "response_format": "json",
        "language": "en",
    }


@pytest.mark.parametrize("language,voice,delivery", [
    ("zh-CN", "coral", "普通话"), ("zh_CN", "coral", "普通话"),
    ("zh", "coral", "普通话"), ("en-AU", "marin", "Australian English"),
    ("en", "marin", "Australian English"),
    ("fr-FR", "marin", "language of the supplied text"),
])
def test_provider_receives_the_localized_voice_and_delivery(language, voice, delivery):
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=b"audio")

    client = httpx.Client(base_url="https://speech.test/v1", transport=httpx.MockTransport(provider))
    speech = OpenAISpeechService("test-key", client=client)
    result = speech.synthesize("A short memory.", language=language)
    assert result["voice"] == voice
    assert requests[0]["voice"] == voice
    assert requests[0]["speed"] == (1.1 if voice == "coral" else 1.0)
    assert delivery in requests[0]["instructions"]
    assert "language" not in requests[0]  # Language selects delivery; it is not a speech API field.


def test_additional_locales_and_explicit_options_can_choose_their_own_character(monkeypatch):
    requests = []

    def provider(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=b"audio")

    client = httpx.Client(base_url="https://speech.test/v1", transport=httpx.MockTransport(provider))
    speech = OpenAISpeechService("test-key", client=client)
    monkeypatch.setenv("MEMORY_SPARK_TTS_VOICE_FR_FR", "shimmer")
    monkeypatch.setenv("MEMORY_SPARK_TTS_INSTRUCTIONS_FR_FR", "Parlez avec douceur en français.")
    speech.synthesize("Un souvenir.", language="fr-FR")
    speech.synthesize("Un souvenir.", language="fr-FR", voice="nova", instructions="Une autre voix.")
    assert requests[0]["voice"] == "shimmer"
    assert requests[0]["instructions"] == "Parlez avec douceur en français."
    assert requests[1]["voice"] == "nova"
    assert requests[1]["instructions"] == "Une autre voix."
