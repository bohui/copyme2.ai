"""Speech provider boundaries for Memoir audio processing."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx
from .prompt_artifact import load_prompt_artifact


_PROMPTS = Path(__file__).with_name("prompts")
_SPEECH_CHARACTERS = {
    "zh-cn": {
        "voice": "coral",
        "speed": 1.1,
        "instructions": load_prompt_artifact(_PROMPTS / "speech-zh-CN.md"),
    },
    "en-au": {
        "voice": "marin",
        "instructions": load_prompt_artifact(_PROMPTS / "speech-en-AU.md"),
    },
}


def speech_character(language: str | None, *, voice: str | None = None,
                     instructions: str | None = None) -> dict[str, Any]:
    """Choose server-owned voice and delivery defaults for an interview locale."""
    locale = str(language or "en-AU").strip().replace("_", "-").lower()
    locale = {"zh": "zh-cn", "en": "en-au"}.get(locale, locale)
    suffix = re.sub(r"[^A-Z0-9]", "_", locale.upper())
    default = _SPEECH_CHARACTERS.get(locale, {
        "voice": "marin", "instructions": load_prompt_artifact(_PROMPTS / "speech-default.md"),
    })
    return {
        "voice": (voice or "").strip() or os.getenv(f"MEMORY_SPARK_TTS_VOICE_{suffix}", "").strip() or default["voice"],
        "instructions": (instructions or "").strip() or os.getenv(f"MEMORY_SPARK_TTS_INSTRUCTIONS_{suffix}", "").strip() or default["instructions"],
        "speed": default.get("speed", 1.0),
    }


class SpeechUnavailable(Exception):
    """Speech is not configured for this deployment."""


class SpeechProviderError(Exception):
    """The configured speech provider could not complete a request."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class UnavailableSpeechService:
    """Default service used when no provider credentials are configured."""

    def transcribe(self, audio: bytes, **options: Any) -> dict[str, Any]:
        raise SpeechUnavailable("Speech transcription is not configured")

    def synthesize(self, text: str, **options: Any) -> dict[str, Any]:
        raise SpeechUnavailable("Speech synthesis is not configured")


class OpenAISpeechService:
    """Small server-side adapter for OpenAI's file transcription and speech APIs."""

    provider = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        stt_model: str = "gpt-4o-mini-transcribe",
        tts_model: str = "gpt-4o-mini-tts",
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.stt_model = stt_model
        self.tts_model = tts_model
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def transcribe(self, audio: bytes, **options: Any) -> dict[str, Any]:
        filename = str(options.get("filename") or "recording.webm")
        mime_type = str(options.get("mime_type") or "application/octet-stream")
        data: dict[str, str] = {"model": str(options.get("model") or self.stt_model), "response_format": "json"}
        for key in ("language", "prompt"):
            value = options.get(key)
            if value:
                normalized = str(value).strip()
                if key == "language":
                    normalized = normalized.replace("_", "-").split("-", 1)[0].lower()
                data[key] = normalized
        try:
            response = self._client.post(
                "/audio/transcriptions",
                files={"file": (filename, audio, mime_type)},
                data=data,
            )
        except httpx.HTTPError as exc:
            raise SpeechProviderError("Speech transcription could not reach the provider") from exc
        if response.status_code >= 400:
            raise SpeechProviderError("Speech transcription failed", retryable=response.status_code >= 500)
        try:
            body = response.json()
        except ValueError as exc:
            raise SpeechProviderError("Speech transcription returned invalid data", retryable=False) from exc
        return {
            "text": str(body.get("text") or "").strip(),
            "language": body.get("language"),
            "segments": body.get("segments") or [],
            "model": data["model"],
            "provider": self.provider,
        }

    def synthesize(self, text: str, **options: Any) -> dict[str, Any]:
        model = str(options.get("model") or self.tts_model)
        character = speech_character(options.get("language"), voice=options.get("voice"),
                                     instructions=options.get("instructions"))
        payload: dict[str, Any] = {
            "model": model,
            "input": text,
            **character,
            "speed": float(options.get("speed") or character["speed"]),
            "response_format": str(options.get("output_format") or "mp3"),
        }
        try:
            response = self._client.post("/audio/speech", json=payload)
        except httpx.HTTPError as exc:
            raise SpeechProviderError("Speech synthesis could not reach the provider") from exc
        if response.status_code >= 400:
            raise SpeechProviderError("Speech synthesis failed", retryable=response.status_code >= 500)
        return {
            "content": response.content,
            "mime_type": _audio_mime_type(payload["response_format"]),
            "model": model,
            "voice": payload["voice"],
            "provider": self.provider,
        }


def _audio_mime_type(output_format: str) -> str:
    return {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(output_format, "application/octet-stream")


def build_speech_service() -> OpenAISpeechService | UnavailableSpeechService:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return UnavailableSpeechService()
    return OpenAISpeechService(
        api_key,
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        stt_model=os.getenv("MEMORY_SPARK_STT_MODEL", "gpt-4o-mini-transcribe"),
        tts_model=os.getenv("MEMORY_SPARK_TTS_MODEL", "gpt-4o-mini-tts"),
    )
