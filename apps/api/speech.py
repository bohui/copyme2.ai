"""Speech provider boundaries for Memoir audio processing."""

from __future__ import annotations

import asyncio
import base64
import binascii
import gzip
import io
import json
import os
import re
import struct
import subprocess
import wave
import zlib
from typing import Any
from uuid import uuid4

import httpx
from websockets.exceptions import WebSocketException
from websockets.asyncio.client import connect
from .prompt_artifact import load_prompt_artifact, prompt_path
from .model_request import prompt_manifest
from .llm_tracing import mark_llm_trace_error, trace_llm_call, update_llm_trace


_SPEECH_CHARACTERS = {
    'zh-cn': {'voice': 'longwan_v3', 'speed': 1.1, 'prompt_name': 'memoir/speech/zh-CN'},
    'en-au': {'voice': 'longwan_v3', 'prompt_name': 'memoir/speech/en-AU'},
}


def _speech_locale(language: str | None) -> str:
    locale = str(language or 'en-AU').strip().replace('_', '-').lower()
    return {'zh': 'zh-cn', 'en': 'en-au'}.get(locale, locale)


def speech_prompt_name(language, prompt_name=None):
    locale = _speech_locale(language)
    name = prompt_name or _SPEECH_CHARACTERS.get(locale, {}).get('prompt_name', 'memoir/speech/default')
    if name not in {'memoir/speech/default', 'memoir/speech/en-AU', 'memoir/speech/zh-CN'}:
        raise ValueError('Unknown managed speech prompt')
    return name


def speech_character(language: str | None, *, voice: str | None = None,
                     prompt_name: str | None = None, default_voice: str | None = None) -> dict[str, Any]:
    """Choose versioned delivery policy; voice remains a typed provider option."""
    locale = _speech_locale(language)
    suffix = re.sub(r'[^A-Z0-9]', '_', locale.upper())
    default = _SPEECH_CHARACTERS.get(locale, {'voice': 'longwan_v3'})
    return {
        'voice': (voice or '').strip() or os.getenv(f'MEMORY_SPARK_TTS_VOICE_{suffix}', '').strip() or default_voice or default['voice'],
        'instructions': load_prompt_artifact(prompt_path(speech_prompt_name(language, prompt_name))),
        'speed': default.get('speed', 1.0),
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
        self.api_key = api_key
        self.stt_model = stt_model
        self.tts_model = tts_model
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def transcribe(self, audio: bytes, **options: Any) -> dict[str, Any]:
        if not self.api_key:
            raise SpeechUnavailable('English transcription requires OPENAI_API_KEY')
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
        with trace_llm_call(
            "speech.transcription",
            data["model"],
            input_summary={"kind": "audio", "bytes": len(audio), "mime_type": mime_type},
            metadata={"provider": self.provider, "endpoint": "audio.transcriptions"},
        ) as trace:
            try:
                response = self._client.post(
                    "/audio/transcriptions",
                    files={"file": (filename, audio, mime_type)},
                    data=data,
                )
            except httpx.HTTPError as exc:
                mark_llm_trace_error(trace, "speech.transcription", exc)
                raise SpeechProviderError("Speech transcription could not reach the provider") from exc
            if response.status_code >= 400:
                error = SpeechProviderError("Speech transcription failed",
                                            retryable=response.status_code == 429 or response.status_code >= 500)
                update_llm_trace(trace, metadata={"http_status": response.status_code})
                mark_llm_trace_error(trace, "speech.transcription", error)
                raise error
            try:
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get('text'), str):
                    raise ValueError('Invalid transcript')
            except ValueError as exc:
                mark_llm_trace_error(trace, "speech.transcription", exc)
                raise SpeechProviderError("Speech transcription returned invalid data", retryable=False) from exc
            result = {
                "text": str(body.get("text") or "").strip(),
                "language": body.get("language"),
                "segments": body.get("segments") or [],
                "model": data["model"],
                "provider": self.provider,
            }
            update_llm_trace(
                trace,
                output={"kind": "transcript", "characters": len(result["text"]), "segments": len(result["segments"])},
                metadata={"http_status": response.status_code},
            )
            return result

    def synthesize(self, text: str, **options: Any) -> dict[str, Any]:
        if not self.api_key:
            raise SpeechUnavailable('Speech synthesis requires OPENAI_API_KEY')
        if options.get('instructions') is not None:
            raise ValueError('Use a managed speech prompt_name')
        model = str(options.get("model") or self.tts_model)
        language = options.get("language")
        legacy_voice = 'coral' if _speech_locale(language).split('-')[0] == 'zh' else 'marin'
        character = speech_character(language, voice=options.get("voice"),
                                     prompt_name=options.get("prompt_name"),
                                     default_voice=legacy_voice)
        payload: dict[str, Any] = {
            "model": model,
            "input": text,
            **character,
            "speed": float(options.get("speed") or character["speed"]),
            "response_format": str(options.get("output_format") or "mp3"),
        }
        with trace_llm_call(
            "speech.synthesis",
            model,
            input_summary={"kind": "text", "characters": len(text)},
            metadata={
                "provider": self.provider,
                "endpoint": "audio.speech",
                "voice": payload["voice"],
                "prompt_manifest": prompt_manifest(
                    [speech_prompt_name(options.get('language'), options.get('prompt_name'))], payload['instructions'],
                    variant='speech'),
                "response_format": payload["response_format"],
            },
        ) as trace:
            try:
                response = self._client.post("/audio/speech", json=payload)
            except httpx.HTTPError as exc:
                mark_llm_trace_error(trace, "speech.synthesis", exc)
                raise SpeechProviderError("Speech synthesis could not reach the provider") from exc
            if response.status_code >= 400:
                error = SpeechProviderError("Speech synthesis failed", retryable=response.status_code >= 500)
                update_llm_trace(trace, metadata={"http_status": response.status_code})
                mark_llm_trace_error(trace, "speech.synthesis", error)
                raise error
            result = {
                "content": response.content,
                "mime_type": _audio_mime_type(payload["response_format"]),
                "model": model,
                "voice": payload["voice"],
                "provider": self.provider,
            }
            update_llm_trace(
                trace,
                output={"kind": "audio", "bytes": len(response.content)},
                metadata={"http_status": response.status_code},
            )
            return result


class GroqSpeechService:
    """Server-side adapter for Groq's OpenAI-compatible Whisper endpoint."""

    provider = 'groq'

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = 'https://api.groq.com/openai/v1',
        stt_model: str = 'whisper-large-v3-turbo',
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.stt_model = stt_model
        self._client = client or httpx.Client(
            base_url=base_url.rstrip('/'),
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=timeout,
        )
        if client is not None:
            self._client.headers.update({'Authorization': f'Bearer {api_key}'})

    def transcribe(self, audio: bytes, **options: Any) -> dict[str, Any]:
        if not self.api_key:
            raise SpeechUnavailable('Speech transcription requires GROQ_API_KEY')
        filename = str(options.get('filename') or 'recording.webm')
        mime_type = str(options.get('mime_type') or 'application/octet-stream').split(';', 1)[0]
        data: dict[str, str] = {
            'model': str(options.get('model') or self.stt_model),
            'response_format': 'json',
        }
        language = options.get('language')
        if language:
            data['language'] = str(language).replace('_', '-').split('-', 1)[0].lower()
        prompt = options.get('prompt')
        if prompt:
            data['prompt'] = str(prompt).strip()
        with trace_llm_call(
            'speech.transcription',
            data['model'],
            input_summary={'kind': 'audio', 'bytes': len(audio), 'mime_type': mime_type},
            metadata={'provider': self.provider, 'endpoint': 'audio.transcriptions'},
        ) as trace:
            try:
                response = self._client.post(
                    '/audio/transcriptions',
                    files={'file': (filename, audio, mime_type)},
                    data=data,
                )
            except httpx.HTTPError as exc:
                mark_llm_trace_error(trace, 'speech.transcription', exc)
                raise SpeechProviderError('Groq speech transcription could not reach the provider') from exc
            if response.status_code >= 400:
                error = SpeechProviderError(
                    'Groq speech transcription failed',
                    retryable=response.status_code == 429 or response.status_code >= 500,
                )
                update_llm_trace(trace, metadata={'http_status': response.status_code})
                mark_llm_trace_error(trace, 'speech.transcription', error)
                raise error
            try:
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get('text'), str):
                    raise ValueError('Invalid transcript')
            except (ValueError, TypeError) as exc:
                mark_llm_trace_error(trace, 'speech.transcription', exc)
                raise SpeechProviderError(
                    'Groq speech transcription returned invalid data', retryable=False,
                ) from exc
            result = {
                'text': str(body.get('text') or '').strip(),
                'language': body.get('language'),
                'segments': body.get('segments') or [],
                'model': data['model'],
                'provider': self.provider,
            }
            update_llm_trace(
                trace,
                output={'kind': 'transcript', 'characters': len(result['text']),
                        'segments': len(result['segments'])},
                metadata={'http_status': response.status_code},
            )
            return result


def _dashscope_base_url(workspace_id: str, region: str) -> str:
    return f'https://{workspace_id}.{region}.maas.aliyuncs.com'


def _dashscope_region(value: str | None) -> str:
    region = str(value or 'ap-southeast-1').strip().lower()
    if region not in {'ap-southeast-1', 'cn-beijing'}:
        raise ValueError('Unsupported DashScope region')
    return region


def _qwen_transcript(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get('text'), str):
                parts.append(item['text'])
        return ''.join(parts).strip()
    return ''


class QwenASRService:
    """Optional Mandarin fallback using DashScope's OpenAI-compatible Qwen ASR API."""

    provider = 'qwen'

    def __init__(
        self,
        api_key: str,
        *,
        workspace_id: str = '',
        region: str = 'ap-southeast-1',
        stt_model: str = 'qwen3-asr-flash',
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.workspace_id = workspace_id.strip()
        self.region = _dashscope_region(region)
        self.stt_model = stt_model
        self._client = client or httpx.Client(
            base_url=_dashscope_base_url(self.workspace_id, self.region).rstrip('/'),
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            timeout=timeout,
        )
        if client is not None:
            self._client.headers.update({
                'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json',
            })

    def transcribe(self, audio: bytes, **options: Any) -> dict[str, Any]:
        if not self.api_key or not self.workspace_id:
            raise SpeechUnavailable(
                'Mandarin transcription fallback requires DASHSCOPE_API_KEY and DASHSCOPE_WORKSPACE_ID',
            )
        model = str(options.get('model') or self.stt_model)
        mime_type = str(options.get('mime_type') or 'application/octet-stream').split(';', 1)[0]
        encoded = base64.b64encode(audio).decode('ascii')
        payload = {
            'model': model,
            'messages': [{
                'role': 'user',
                'content': [{
                    'type': 'input_audio',
                    'input_audio': {'data': f'data:{mime_type};base64,{encoded}'},
                }],
            }],
            'stream': False,
            'asr_options': {'enable_itn': False},
        }
        with trace_llm_call(
            'speech.transcription',
            model,
            input_summary={'kind': 'audio', 'bytes': len(audio), 'mime_type': mime_type},
            metadata={'provider': self.provider, 'endpoint': 'compatible-mode/v1/chat/completions'},
        ) as trace:
            try:
                response = self._client.post('/compatible-mode/v1/chat/completions', json=payload)
            except httpx.HTTPError as exc:
                mark_llm_trace_error(trace, 'speech.transcription', exc)
                raise SpeechProviderError('Qwen speech transcription could not reach the provider') from exc
            if response.status_code >= 400:
                error = SpeechProviderError(
                    'Qwen speech transcription failed',
                    retryable=response.status_code == 429 or response.status_code >= 500,
                )
                update_llm_trace(trace, metadata={'http_status': response.status_code})
                mark_llm_trace_error(trace, 'speech.transcription', error)
                raise error
            try:
                body = response.json()
                content = body['choices'][0]['message']['content']
                text = _qwen_transcript(content)
                if not text:
                    raise ValueError('Empty transcript')
            except (ValueError, TypeError, KeyError, IndexError) as exc:
                mark_llm_trace_error(trace, 'speech.transcription', exc)
                raise SpeechProviderError(
                    'Qwen speech transcription returned invalid data', retryable=False,
                ) from exc
            result = {
                'text': text,
                'language': 'zh',
                'segments': [],
                'model': model,
                'provider': self.provider,
            }
            update_llm_trace(
                trace,
                output={'kind': 'transcript', 'characters': len(text), 'segments': 0},
                metadata={'http_status': response.status_code},
            )
            return result


def _audio_mime_type(output_format: str) -> str:
    return {
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(output_format, "application/octet-stream")


def _transcode_audio(content: bytes, output_format: str, *, sample_rate: int = 24000) -> bytes:
    codecs = {'pcm': ('s16le', 'pcm_s16le'), 'wav': ('wav', 'pcm_s16le'),
              'mp3': ('mp3', 'libmp3lame'), 'opus': ('ogg', 'libopus'),
              'aac': ('adts', 'aac'), 'flac': ('flac', 'flac')}
    if output_format not in codecs:
        raise SpeechProviderError('Unsupported speech audio format', retryable=False)
    container, codec = codecs[output_format]
    try:
        result = subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-protocol_whitelist', 'pipe',
             '-i', 'pipe:0', '-vn', '-ac', '1', '-ar', str(sample_rate),
             '-acodec', codec, '-f', container, 'pipe:1'],
            input=content, capture_output=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SpeechProviderError('Speech audio conversion is unavailable') from exc
    if result.returncode or not result.stdout:
        raise SpeechProviderError('Speech audio could not be converted', retryable=False)
    return result.stdout


def _check_speech_response(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise SpeechProviderError('Speech provider rejected the request',
                                  retryable=response.status_code == 429 or response.status_code >= 500)


def _synthesis_metadata(provider: str, language: str | None, character: dict[str, Any],
                        output_format: str, prompt_name: str | None) -> dict[str, Any]:
    return {
        'provider': provider, 'voice': character['voice'], 'response_format': output_format,
        'prompt_manifest': prompt_manifest(
            [speech_prompt_name(language, prompt_name)], character['instructions'], variant='speech'),
    }


class GeminiSpeechService:
    provider = 'gemini'
    default_voice = 'Kore'
    default_format = 'wav'

    def __init__(self, api_key: str, *, tts_model: str = 'gemini-3.8-flash-lite-tts',
                 client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.tts_model = tts_model
        self._client = client or httpx.Client(
            base_url='https://generativelanguage.googleapis.com/v1beta',
            headers={'x-goog-api-key': api_key}, timeout=60,
        )

    def synthesize(self, text: str, **options: Any) -> dict[str, Any]:
        if not self.api_key:
            raise SpeechUnavailable('English speech synthesis requires GEMINI_API_KEY')
        if options.get('instructions') is not None:
            raise ValueError('Use a managed speech prompt_name')
        language, prompt_name = options.get('language'), options.get('prompt_name')
        character = speech_character(language, voice=options.get('voice'), prompt_name=prompt_name,
                                     default_voice=self.default_voice)
        model = str(options.get('model') or self.tts_model)
        output_format = str(options.get('output_format') or self.default_format)
        if _audio_mime_type(output_format) == 'application/octet-stream':
            raise SpeechProviderError('Unsupported speech audio format', retryable=False)
        payload = {
            'contents': [{'role': 'user', 'parts': [{'text': text,
                'speech_metadata': {'style': character['instructions']}}]}],
            'generationConfig': {
                'responseModalities': ['AUDIO'],
                'responseFormat': {'audio': {'mimeType': 'AUDIO_WAV', 'sampleRate': 24000}},
                'speechConfig': {'voiceConfig': {'voice': character['voice']}},
            },
        }
        with trace_llm_call('speech.synthesis', model,
                input_summary={'kind': 'text', 'characters': len(text)},
                metadata=_synthesis_metadata(self.provider, language, character, output_format, prompt_name)) as trace:
            try:
                response = self._client.post(f'/models/{model}:generateContent', json=payload)
                _check_speech_response(response)
                parts = response.json()['candidates'][0]['content']['parts']
                audio_part = next(part['inlineData'] for part in parts if 'inlineData' in part)
                content = base64.b64decode(audio_part['data'], validate=True)
                mime_type = audio_part['mimeType'].lower()
                if not content:
                    raise ValueError('Empty audio')
                if mime_type.startswith(('audio/l16', 'audio/pcm')):
                    # Older compatible models return raw PCM instead of a WAV container.
                    buffer = io.BytesIO()
                    with wave.open(buffer, 'wb') as audio_file:
                        audio_file.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                        audio_file.writeframes(content)
                    content = buffer.getvalue()
                elif (mime_type not in {'audio/wav', 'audio/x-wav'} or len(content) < 44
                      or content[:4] != b'RIFF' or content[8:12] != b'WAVE'):
                    raise ValueError('Unexpected audio format')
                if output_format != 'wav':
                    content = _transcode_audio(content, output_format)
            except (httpx.HTTPError, SpeechProviderError, ValueError, KeyError, IndexError,
                    TypeError, AttributeError, StopIteration, binascii.Error) as exc:
                mark_llm_trace_error(trace, 'speech.synthesis', exc)
                if isinstance(exc, SpeechProviderError):
                    raise
                raise SpeechProviderError('Gemini speech synthesis failed',
                                          retryable=isinstance(exc, httpx.HTTPError)) from exc
            update_llm_trace(trace, output={'kind': 'audio', 'bytes': len(content)})
            return {'content': content, 'mime_type': _audio_mime_type(output_format),
                    'model': model, 'voice': character['voice'], 'provider': self.provider}


def _doubao_frame(message_type: int, payload: bytes, *, final: bool = False) -> bytes:
    compressed = gzip.compress(payload)
    header = bytes((0x11, (message_type << 4) | (2 if final else 0),
                    0x11 if message_type == 1 else 0x01, 0))
    return header + struct.pack('>I', len(compressed)) + compressed


def _doubao_result(message: bytes | str) -> tuple[dict[str, Any], bool]:
    if not isinstance(message, bytes) or len(message) < 8 or message[0] >> 4 != 1:
        raise SpeechProviderError('Doubao transcription returned an invalid frame', retryable=False)
    message_type, flags = message[1] >> 4, message[1] & 15
    offset = (message[0] & 15) * 4
    if offset < 4 or len(message) < offset + 4:
        raise SpeechProviderError('Doubao transcription returned an invalid frame', retryable=False)
    if message_type == 15:
        code = struct.unpack_from('>I', message, offset)[0]
        raise SpeechProviderError(f'Doubao transcription failed (code {code})', retryable=code >= 50000000)
    if message_type != 9 or message[2] >> 4 != 1 or message[2] & 15 not in (0, 1):
        raise SpeechProviderError('Doubao transcription returned an unsupported frame', retryable=False)
    if flags & 1:
        offset += 4
    if len(message) < offset + 4:
        raise SpeechProviderError('Doubao transcription returned an incomplete frame', retryable=False)
    size = struct.unpack_from('>I', message, offset)[0]
    payload = message[offset + 4:]
    try:
        if size != len(payload):
            raise ValueError('Incorrect frame size')
        if message[2] & 15:
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
                payload = compressed.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            raise ValueError('Oversized response')
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise ValueError('Invalid response')
    except (ValueError, OSError, EOFError, zlib.error) as exc:
        raise SpeechProviderError('Doubao transcription returned invalid data', retryable=False) from exc
    return result, bool(flags & 2)


class DoubaoSpeechService:
    provider = 'doubao'
    stt_model = 'doubao-seed-asr-2.0'
    tts_model = 'doubao-seed-tts-2.0'
    default_voice = 'zh_female_vv_uranus_bigtts'
    default_format = 'mp3'

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self._client = client or httpx.Client(base_url='https://openspeech.bytedance.com', timeout=60)

    async def _recognize(self, pcm: bytes) -> dict[str, Any]:
        request = {
            'audio': {'format': 'pcm', 'codec': 'raw', 'rate': 16000, 'bits': 16, 'channel': 1},
            'request': {'model_name': 'bigmodel', 'enable_itn': True, 'enable_punc': True,
                        'enable_ddc': False, 'show_utterances': True, 'result_type': 'full'},
        }
        request_id = str(uuid4())
        headers = {'X-Api-Key': self.api_key, 'X-Api-Resource-Id': 'volc.seedasr.sauc.duration',
                   'X-Api-Connect-Id': request_id, 'X-Api-Request-Id': request_id, 'X-Api-Sequence': '-1'}
        async with asyncio.timeout(60):
            async with connect('wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream',
                               additional_headers=headers, open_timeout=15, close_timeout=2,
                               max_size=4 * 1024 * 1024) as socket:
                await socket.send(_doubao_frame(1, json.dumps(request).encode()))

                async def send_audio():
                    for start in range(0, len(pcm), 6400):
                        await socket.send(_doubao_frame(2, pcm[start:start + 6400],
                                                       final=start + 6400 >= len(pcm)))

                # Read while uploading: some modes acknowledge chunks, others wait for the last one.
                sender = asyncio.create_task(send_audio())
                try:
                    async for message in socket:
                        body, complete = _doubao_result(message)
                        if complete:
                            await sender
                            return body
                finally:
                    sender.cancel()
                    await asyncio.gather(sender, return_exceptions=True)
        raise SpeechProviderError('Doubao transcription ended before the final result')

    def transcribe(self, audio: bytes, **options: Any) -> dict[str, Any]:
        if not self.api_key:
            raise SpeechUnavailable('Chinese transcription requires DOUBAO_API_KEY')
        with trace_llm_call('speech.transcription', self.stt_model,
                input_summary={'kind': 'audio', 'bytes': len(audio), 'mime_type': options.get('mime_type')},
                metadata={'provider': self.provider, 'endpoint': 'sauc/bigmodel_nostream'}) as trace:
            try:
                pcm = _transcode_audio(audio, 'pcm', sample_rate=16000)
                body = asyncio.run(self._recognize(pcm))
                result = body.get('result')
                if not isinstance(result, dict) or not isinstance(result.get('text'), str):
                    raise SpeechProviderError('Doubao transcription returned no transcript', retryable=False)
                result = {'text': result['text'].strip(), 'language': 'zh',
                          'segments': result.get('utterances') or [], 'model': self.stt_model, 'provider': self.provider}
            except (OSError, TimeoutError, WebSocketException, SpeechProviderError) as exc:
                mark_llm_trace_error(trace, 'speech.transcription', exc)
                if isinstance(exc, SpeechProviderError):
                    raise
                raise SpeechProviderError('Doubao transcription could not reach the provider') from exc
            update_llm_trace(trace, output={'kind': 'transcript', 'characters': len(result['text']),
                                           'segments': len(result['segments'])})
            return result

    def synthesize(self, text: str, **options: Any) -> dict[str, Any]:
        if not self.api_key:
            raise SpeechUnavailable('Chinese speech synthesis requires DOUBAO_API_KEY')
        if options.get('instructions') is not None:
            raise ValueError('Use a managed speech prompt_name')
        language, prompt_name = options.get('language'), options.get('prompt_name')
        character = speech_character(language, voice=options.get('voice'), prompt_name=prompt_name,
                                     default_voice=self.default_voice)
        output_format = str(options.get('output_format') or self.default_format)
        if output_format not in {'mp3', 'pcm', 'wav', 'opus'}:
            raise SpeechProviderError('Unsupported Doubao audio format', retryable=False)
        payload = {'req_params': {
            'text': text, 'speaker': character['voice'],
            'audio_params': {'format': 'ogg_opus' if output_format == 'opus' else output_format,
                             'sample_rate': 48000 if output_format == 'opus' else 24000,
                             'speech_rate': round((character['speed'] - 1) * 100)},
            'additions': json.dumps({'context_texts': [character['instructions']]}, ensure_ascii=False),
        }}
        headers = {'X-Api-Key': self.api_key, 'X-Api-Resource-Id': 'seed-tts-2.0',
                   'X-Api-Request-Id': str(uuid4())}
        with trace_llm_call('speech.synthesis', self.tts_model,
                input_summary={'kind': 'text', 'characters': len(text)},
                metadata=_synthesis_metadata(self.provider, language, character, output_format, prompt_name)) as trace:
            try:
                chunks = []
                with self._client.stream('POST', '/api/v3/tts/unidirectional', json=payload, headers=headers) as response:
                    _check_speech_response(response)
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        body = json.loads(line)
                        if body.get('code') == 20000000:
                            break
                        if body.get('code') != 0:
                            raise SpeechProviderError('Doubao speech synthesis failed', retryable=False)
                        if body.get('data'):
                            chunks.append(base64.b64decode(body['data'], validate=True))
                content = b''.join(chunks)
                if not content:
                    raise ValueError('Empty audio')
            except (httpx.HTTPError, SpeechProviderError, ValueError, TypeError, AttributeError, binascii.Error) as exc:
                mark_llm_trace_error(trace, 'speech.synthesis', exc)
                if isinstance(exc, SpeechProviderError):
                    raise
                raise SpeechProviderError('Doubao speech synthesis failed',
                                          retryable=isinstance(exc, httpx.HTTPError)) from exc
            update_llm_trace(trace, output={'kind': 'audio', 'bytes': len(content)})
            return {'content': content, 'mime_type': _audio_mime_type(output_format),
                    'model': self.tts_model, 'voice': character['voice'], 'provider': self.provider}


class CosyVoiceSpeechService:
    """Bilingual streaming TTS adapter for Alibaba Cloud Model Studio CosyVoice."""

    provider = 'cosyvoice'
    tts_model = 'cosyvoice-v3-flash'
    default_voice = 'longwan_v3'
    default_format = 'mp3'

    def __init__(
        self,
        api_key: str,
        *,
        workspace_id: str = '',
        region: str = 'ap-southeast-1',
        tts_model: str = 'cosyvoice-v3-flash',
        ws_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.workspace_id = workspace_id.strip()
        self.region = _dashscope_region(region)
        self.tts_model = tts_model
        self.ws_url = (ws_url or '').strip()
        self.timeout = timeout

    def _websocket_url(self) -> str:
        if self.ws_url:
            return self.ws_url
        if not self.workspace_id:
            raise SpeechUnavailable('CosyVoice speech synthesis requires DASHSCOPE_WORKSPACE_ID')
        return f'wss://{self.workspace_id}.{self.region}.maas.aliyuncs.com/api-ws/v1/inference'

    async def _synthesize(self, text: str, *, model: str, voice: str, output_format: str,
                          speed: float) -> bytes:
        task_id = str(uuid4())
        headers = {'Authorization': f'Bearer {self.api_key}'}
        if self.workspace_id:
            headers['X-DashScope-WorkSpace'] = self.workspace_id
        parameters = {
            'text_type': 'PlainText',
            'voice': voice,
            'format': output_format,
            'sample_rate': 22050,
            'volume': 50,
            'rate': speed,
            'pitch': 1,
            'enable_ssml': False,
        }
        run_task = {
            'header': {'action': 'run-task', 'task_id': task_id, 'streaming': 'duplex'},
            'payload': {
                'task_group': 'audio',
                'task': 'tts',
                'function': 'SpeechSynthesizer',
                'model': model,
                'parameters': parameters,
                'input': {},
            },
        }
        continue_task = {
            'header': {'action': 'continue-task', 'task_id': task_id, 'streaming': 'duplex'},
            'payload': {'input': {'text': text}},
        }
        finish_task = {
            'header': {'action': 'finish-task', 'task_id': task_id, 'streaming': 'duplex'},
            'payload': {'input': {}},
        }
        chunks: list[bytes] = []
        async with asyncio.timeout(self.timeout):
            async with connect(
                self._websocket_url(),
                additional_headers=headers,
                open_timeout=15,
                close_timeout=2,
                max_size=4 * 1024 * 1024,
            ) as socket:
                await socket.send(json.dumps(run_task, ensure_ascii=False))
                started = False
                async for message in socket:
                    if isinstance(message, bytes):
                        chunks.append(message)
                        continue
                    try:
                        body = json.loads(message)
                    except (TypeError, ValueError) as exc:
                        raise SpeechProviderError(
                            'CosyVoice speech synthesis returned invalid data', retryable=False,
                        ) from exc
                    header = body.get('header') if isinstance(body, dict) else None
                    event = header.get('event') if isinstance(header, dict) else None
                    if event in {'task-failed', 'error'}:
                        raise SpeechProviderError('CosyVoice speech synthesis failed', retryable=False)
                    if event == 'task-started' and not started:
                        started = True
                        await socket.send(json.dumps(continue_task, ensure_ascii=False))
                        await socket.send(json.dumps(finish_task, ensure_ascii=False))
                    elif event == 'task-finished':
                        content = b''.join(chunks)
                        if not content:
                            raise SpeechProviderError(
                                'CosyVoice speech synthesis returned no audio', retryable=False,
                            )
                        return content
        raise SpeechProviderError('CosyVoice speech synthesis ended before completion')

    def synthesize(self, text: str, **options: Any) -> dict[str, Any]:
        if not self.api_key:
            raise SpeechUnavailable('Speech synthesis requires DASHSCOPE_API_KEY')
        if options.get('instructions') is not None:
            raise ValueError('Use a managed speech prompt_name')
        language, prompt_name = options.get('language'), options.get('prompt_name')
        character = speech_character(
            language,
            voice=options.get('voice'),
            prompt_name=prompt_name,
            default_voice=self.default_voice,
        )
        model = str(options.get('model') or self.tts_model)
        output_format = str(options.get('output_format') or self.default_format).lower()
        if output_format not in {'mp3', 'wav', 'pcm', 'opus'}:
            raise SpeechProviderError('Unsupported CosyVoice audio format', retryable=False)
        speed = float(options.get('speed') or character['speed'])
        with trace_llm_call(
            'speech.synthesis',
            model,
            input_summary={'kind': 'text', 'characters': len(text)},
            metadata=_synthesis_metadata(self.provider, language, character, output_format, prompt_name),
        ) as trace:
            try:
                content = asyncio.run(self._synthesize(
                    text,
                    model=model,
                    voice=character['voice'],
                    output_format=output_format,
                    speed=speed,
                ))
            except (OSError, TimeoutError, WebSocketException, SpeechProviderError, ValueError) as exc:
                mark_llm_trace_error(trace, 'speech.synthesis', exc)
                if isinstance(exc, SpeechProviderError):
                    raise
                raise SpeechProviderError(
                    'CosyVoice speech synthesis could not reach the provider',
                ) from exc
            update_llm_trace(trace, output={'kind': 'audio', 'bytes': len(content)})
            return {
                'content': content,
                'mime_type': _audio_mime_type(output_format),
                'model': model,
                'voice': character['voice'],
                'provider': self.provider,
            }


class LocalizedSpeechService:
    """Route STT/TTS by interview language and fall back to Qwen for Mandarin STT."""

    def __init__(self, stt: Any, tts: Any, fallback: Any | None = None) -> None:
        self.stt, self.tts, self.fallback = stt, tts, fallback
        # Keep the old attributes available to callers that construct the legacy
        # OpenAI/Gemini/Doubao combination directly in tests or integrations.
        self._legacy = (
            getattr(stt, 'provider', None) == 'openai'
            and getattr(tts, 'provider', None) == 'gemini'
            and getattr(fallback, 'provider', None) == 'doubao'
        )
        if self._legacy:
            self.openai, self.gemini, self.doubao = stt, tts, fallback

    def transcribe(self, audio: bytes, **options: Any) -> dict[str, Any]:
        language = _speech_locale(options.get('language'))
        if self._legacy:
            service = self.doubao if language.split('-')[0] == 'zh' else self.openai
            return service.transcribe(audio, **options)
        try:
            return self.stt.transcribe(audio, **options)
        except (SpeechUnavailable, SpeechProviderError) as primary_error:
            if language.split('-')[0] != 'zh' or self.fallback is None:
                raise
            try:
                return self.fallback.transcribe(audio, **options)
            except (SpeechUnavailable, SpeechProviderError) as fallback_error:
                raise primary_error from fallback_error

    def synthesis_options(self, language: str | None, *, voice: str | None = None,
                          prompt_name: str | None = None, model: str | None = None,
                          output_format: str | None = None) -> dict[str, Any]:
        if self._legacy:
            service = self.doubao if _speech_locale(language).split('-')[0] == 'zh' else self.gemini
            return {
                **speech_character(language, voice=voice, prompt_name=prompt_name,
                                   default_voice=service.default_voice),
                'model': service.tts_model if service is self.doubao else model or service.tts_model,
                'provider': service.provider,
                'output_format': output_format or service.default_format,
            }
        return {
            **speech_character(language, voice=voice, prompt_name=prompt_name,
                               default_voice=self.tts.default_voice),
            'model': model or self.tts.tts_model,
            'provider': self.tts.provider,
            'output_format': output_format or self.tts.default_format,
        }

    def synthesize(self, text: str, **options: Any) -> dict[str, Any]:
        if self._legacy:
            service = self.doubao if _speech_locale(options.get('language')).split('-')[0] == 'zh' else self.gemini
            return service.synthesize(text, **options)
        return self.tts.synthesize(text, **options)


def speech_synthesis_options(service: Any, language: str | None, **options: Any) -> dict[str, Any]:
    if hasattr(service, 'synthesis_options'):
        return service.synthesis_options(language, **options)
    return {**speech_character(language, voice=options.get('voice'), prompt_name=options.get('prompt_name')),
            'model': options.get('model') or getattr(service, 'tts_model', 'gpt-4o-mini-tts'),
            'provider': getattr(service, 'provider', 'openai'), 'output_format': options.get('output_format') or 'mp3'}


def build_speech_service() -> LocalizedSpeechService:
    dashscope_key = os.getenv('DASHSCOPE_API_KEY', '').strip()
    workspace_id = os.getenv('DASHSCOPE_WORKSPACE_ID', '').strip()
    region = os.getenv('DASHSCOPE_REGION', 'ap-southeast-1').strip()
    return LocalizedSpeechService(
        GroqSpeechService(
            os.getenv('GROQ_API_KEY', '').strip(),
            base_url=os.getenv('GROQ_BASE_URL', 'https://api.groq.com/openai/v1'),
            stt_model=os.getenv('MEMORY_SPARK_STT_MODEL', 'whisper-large-v3-turbo'),
        ),
        CosyVoiceSpeechService(
            dashscope_key,
            workspace_id=workspace_id,
            region=region,
            tts_model=os.getenv('MEMORY_SPARK_TTS_MODEL', 'cosyvoice-v3-flash'),
            ws_url=os.getenv('DASHSCOPE_COSYVOICE_WS_URL'),
        ),
        QwenASRService(
            dashscope_key,
            workspace_id=workspace_id,
            region=region,
            stt_model=os.getenv('MEMORY_SPARK_QWEN_STT_MODEL', 'qwen3-asr-flash'),
        ),
    )
