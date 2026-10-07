"""Speech provider boundaries for Memoir audio processing."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx


_STABLE_DELIVERY = (
    "Speak as Mira, a patient oral-history interviewer. Keep one consistent vocal "
    "identity, natural pitch and timbre throughout. Read the supplied text faithfully. "
    "Read quotations in your own voice without imitating other speakers. "
)
_SPEECH_CHARACTERS = {
    "zh-cn": {
        "voice": "coral",
        "speed": 1.1,
        "instructions": (
            "你是 Mira，一位亲切、熟悉的访谈者。使用温柔、自然的成年女性声音，"
            "说流利地道的普通话，像和熟悉的人轻松聊天。声调连贯，轻声和变调自然，"
            "按语意停顿，不要逐字拖长；语速从容但不刻意放慢，避免播音腔和机械的朗读感。"
            "保持同一种音色和自然音高，遇到英文名字时自然发音，随后顺畅回到普通话。"
            "忠实读出提供的文字，不增删内容；引用别人的话时也保持自己的声音，不模仿其他角色。"
        ),
    },
    "en-au": {
        "voice": "marin",
        "instructions": _STABLE_DELIVERY + (
            "Use warm, relaxed, conversational Australian English, as if talking with "
            "someone familiar. Use natural sentence stress and pauses, with an easy "
            "pace rather than an exaggerated slow reading or a formal announcer delivery."
        ),
    },
}


def speech_character(language: str | None, *, voice: str | None = None,
                     instructions: str | None = None) -> dict[str, Any]:
    """Choose server-owned voice and delivery defaults for an interview locale."""
    locale = str(language or "en-AU").strip().replace("_", "-").lower()
    locale = {"zh": "zh-cn", "en": "en-au"}.get(locale, locale)
    suffix = re.sub(r"[^A-Z0-9]", "_", locale.upper())
    default = _SPEECH_CHARACTERS.get(locale, {
        "voice": "marin", "instructions": _STABLE_DELIVERY + "Speak naturally in the language of the supplied text.",
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
