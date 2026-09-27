from __future__ import annotations

from typing import Any

import httpx

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
