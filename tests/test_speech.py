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


def test_voice_override_uses_only_managed_delivery_policy(monkeypatch):
    from apps.api.speech import speech_character
    monkeypatch.setenv('MEMORY_SPARK_TTS_VOICE_FR_FR', 'shimmer')
    monkeypatch.setenv('MEMORY_SPARK_TTS_INSTRUCTIONS_FR_FR', 'Unmanaged policy must not be sent')
    character = speech_character('fr-FR')
    assert character['voice']=='shimmer'
    assert character['instructions'] != 'Unmanaged policy must not be sent'
    assert speech_character('fr-FR',voice='nova',prompt_name='memoir/speech/en-AU')['voice']=='nova'
    with pytest.raises(ValueError,match='managed'):
        speech_character('fr-FR',prompt_name='unmanaged')
    with pytest.raises(ValueError,match='managed'):
        OpenAISpeechService('test').synthesize('Text',instructions='Unmanaged')
