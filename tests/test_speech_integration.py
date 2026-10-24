from __future__ import annotations

import base64
import io
import json
import wave

import httpx
import pytest

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.speech import speech_character
from apps.api.speech import DoubaoSpeechService, GeminiSpeechService, LocalizedSpeechService, OpenAISpeechService


class FakeSpeechService:
    def __init__(self) -> None:
        self.transcription_calls: list[dict] = []
        self.synthesis_calls: list[dict] = []

    def transcribe(self, audio: bytes, **options):
        self.transcription_calls.append({"audio": audio, **options})
        return {
            "text": "我小时候和二舅一起走去学校。",
            "language": "zh",
            "segments": [],
            "model": "whisper-large-v3-turbo",
            "provider": "groq",
        }

    def synthesize(self, text: str, **options):
        self.synthesis_calls.append({"text": text, **options})
        return {
            "content": b"fake-mp3-audio",
            "mime_type": "audio/mpeg",
            "model": "gpt-4o-mini-tts",
            "voice": options.get("voice", "longwan_v3"),
            "provider": "cosyvoice",
        }


class FakeStoryStorage:
    def __init__(self) -> None:
        self.user_id = "story-user"
        self.is_anonymous = True
        self._profile: dict = {}
        self._memories: list[dict] = []

    def profile(self):
        return dict(self._profile)

    def save_profile(self, profile):
        self._profile = dict(profile)
        return [self._profile]

    def save_memory(self, text, *, kind="memoir", source_paths=None):
        row = {"id": f"story-memory-{len(self._memories) + 1}", "kind": kind, "content": text, "source_paths": source_paths or []}
        self._memories.append(row)
        return [row]

    def memories(self):
        return list(reversed(self._memories))


@pytest.mark.parametrize("language,voice,delivery", [
    ("zh-CN", "longwan_v3", "普通话"),
    ("zh_CN", "longwan_v3", "普通话"),
    ("en-AU", "longwan_v3", "Australian English"),
])
def test_spoken_replies_select_a_character_for_the_conversation_language(language, voice, delivery):
    speech = FakeSpeechService()
    storage = FakeStoryStorage()
    client = TestClient(create_app(MemoryStore(), speech_service=speech,
                                  story_storage_factory=lambda _authorization: storage))
    response = client.post("/api/v1/memoir/story/question-audio",
                           json={"text": "小时候，你最喜欢和谁一起玩？", "language": language},
                           headers={"Authorization": "Bearer story-token"})
    assert response.status_code == 201, response.text
    assert response.json()["voice"] == voice
    assert speech.synthesis_calls[0]["speed"] == (1.1 if language.startswith("zh") else 1.0)
    assert delivery in speech_character(language)['instructions']
    assert 'instructions' not in speech.synthesis_calls[0]


def test_spoken_character_uses_saved_interview_language_when_request_omits_it():
    speech = FakeSpeechService()
    storage = FakeStoryStorage()
    storage._profile = {"preferred_language": "zh-CN", "ui_locale": "en-AU"}
    client = TestClient(create_app(MemoryStore(), speech_service=speech,
                                  story_storage_factory=lambda _authorization: storage))
    response = client.post("/v1/story/question-audio", json={"text": "那时候，你住在哪里？"},
                           headers={"Authorization": "Bearer story-token"})
    assert response.status_code == 201, response.text
    assert response.json()["voice"] == "longwan_v3"
    assert speech.synthesis_calls[0]["language"] == "zh-CN"
    assert "普通话" in speech_character(speech.synthesis_calls[0]['language'])['instructions']
    assert 'instructions' not in speech.synthesis_calls[0]


def test_changing_a_localized_character_does_not_reuse_audio_from_the_previous_character(monkeypatch):
    speech = FakeSpeechService()
    storage = FakeStoryStorage()
    client = TestClient(create_app(MemoryStore(), speech_service=speech,
                                  story_storage_factory=lambda _authorization: storage))
    request = {"text": "你还记得那条街吗？", "language": "zh-CN"}
    headers = {"Authorization": "Bearer story-token"}
    monkeypatch.setenv("MEMORY_SPARK_TTS_VOICE_ZH_CN", "coral")
    first = client.post("/v1/story/question-audio", json=request, headers=headers)
    replay = client.post("/v1/story/question-audio", json=request, headers=headers)
    monkeypatch.setenv("MEMORY_SPARK_TTS_VOICE_ZH_CN", "shimmer")
    monkeypatch.setenv("MEMORY_SPARK_TTS_INSTRUCTIONS_ZH_CN", "温柔自然地说普通话。")
    changed = client.post("/v1/story/question-audio", json=request, headers=headers)
    assert first.status_code == changed.status_code == 201
    assert replay.json()["cached"] is True
    assert changed.json()["voice"] == "shimmer"
    assert 'instructions' not in speech.synthesis_calls[-1]
    assert len(speech.synthesis_calls) == 2
    monkeypatch.setenv("MEMORY_SPARK_TTS_INSTRUCTIONS_ZH_CN", "轻松亲切地说普通话。")
    restyled = client.post("/v1/story/question-audio", json=request, headers=headers)
    assert restyled.status_code == 200
    assert restyled.json()["voice"] == "shimmer"
    assert 'instructions' not in speech.synthesis_calls[-1]
    assert len(speech.synthesis_calls) == 2


def test_a_first_spoken_reply_infers_chinese_from_text_without_using_the_interface_locale():
    speech = FakeSpeechService()
    storage = FakeStoryStorage()
    storage._profile = {"ui_locale": "en-AU"}
    client = TestClient(create_app(MemoryStore(), speech_service=speech,
                                  story_storage_factory=lambda _authorization: storage))
    response = client.post("/v1/story/question-audio", json={"text": "你还记得那条街吗？"},
                           headers={"Authorization": "Bearer story-token"})
    assert response.status_code == 201, response.text
    assert response.json()["voice"] == "longwan_v3"
    assert speech.synthesis_calls[0]["language"] == "zh-CN"


def _project_and_session(client: TestClient) -> tuple[dict, dict]:
    headers = {"X-Account-Id": "speech-owner"}
    project = client.post("/v1/projects", json={"mode": "self"}, headers=headers).json()
    consent = client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=headers,
    )
    assert consent.status_code == 200
    session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers=headers,
    ).json()
    return project, session


def test_audio_answer_is_transcribed_before_the_memory_turn_is_created() -> None:
    speech = FakeSpeechService()
    client = TestClient(create_app(MemoryStore(), speech_service=speech))
    project, session = _project_and_session(client)
    headers = {"X-Account-Id": "speech-owner"}
    raw_audio = b"recorded-story"

    created = client.post(
        "/v1/uploads",
        json={
            "project_id": project["id"],
            "kind": "audio",
            "filename": "answer.webm",
            "mime_type": "audio/webm",
            "expected_size": len(raw_audio),
            "duration_seconds": 12,
        },
        headers=headers,
    )
    assert created.status_code == 201
    upload_id = created.json()["id"]
    assert client.post(
        f"/v1/uploads/{upload_id}/parts",
        json={"sequence": 0, "content": base64.b64encode(raw_audio).decode()},
        headers=headers,
    ).status_code == 200
    assert client.post(f"/v1/uploads/{upload_id}/finalize", json={}, headers=headers).status_code == 200

    answered = client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"upload_id": upload_id, "turn_type": "initial"},
        headers=headers,
    )

    assert answered.status_code == 200, answered.text
    body = answered.json()
    assert body["turns"][0]["text"] == "我小时候和二舅一起走去学校。"
    assert body["source_version"]["source_kind"] == "transcript"
    assert body["source_version"]["transcription_method"] == "groq"
    assert body["source_version"]["original_asset_id"]
    assert speech.transcription_calls[0]["audio"] == raw_audio
    assert speech.transcription_calls[0]["filename"] == "answer.webm"
    uploaded = client.get(f"/v1/uploads/{upload_id}", headers=headers)
    assert uploaded.status_code == 200
    assert uploaded.json()["asset"]["transcript_source_version_id"] == body["source_version"]["id"]


def test_question_audio_is_cached_and_can_be_played_by_the_authorized_storyteller() -> None:
    speech = FakeSpeechService()
    client = TestClient(create_app(MemoryStore(), speech_service=speech))
    project, session = _project_and_session(client)
    headers = {"X-Account-Id": "speech-owner"}

    first = client.post(
        f"/v1/memory-sessions/{session['id']}/question-audio",
        json={"voice": "marin", "language": "zh-CN"},
        headers=headers,
    )

    assert first.status_code == 201, first.text
    first_body = first.json()
    assert first_body["ai_generated"] is True
    assert first_body["cached"] is False
    assert first_body["mime_type"] == "audio/mpeg"
    assert first_body["text"] == session["question"]["text"]

    replay = client.post(
        f"/v1/memory-sessions/{session['id']}/question-audio",
        json={"voice": "marin", "language": "zh-CN"},
        headers=headers,
    )

    assert replay.status_code == 200
    assert replay.json()["audio_asset_id"] == first_body["audio_asset_id"]
    assert replay.json()["cached"] is True
    assert len(speech.synthesis_calls) == 1

    audio = client.get(first_body["audio_url"], headers=headers)
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/mpeg")
    assert audio.content == b"fake-mp3-audio"


def test_uploaded_audio_can_be_transcribed_and_replayed_before_answer_submission() -> None:
    speech = FakeSpeechService()
    client = TestClient(create_app(MemoryStore(), speech_service=speech))
    project, _session = _project_and_session(client)
    headers = {"X-Account-Id": "speech-owner"}
    raw_audio = b"review-before-send"
    created = client.post(
        "/v1/uploads",
        json={
            "project_id": project["id"],
            "kind": "audio",
            "filename": "review.webm",
            "mime_type": "audio/webm",
            "expected_size": len(raw_audio),
        },
        headers=headers,
    )
    upload_id = created.json()["id"]
    client.post(
        f"/v1/uploads/{upload_id}/parts",
        json={"sequence": 0, "content": base64.b64encode(raw_audio).decode()},
        headers=headers,
    )
    client.post(f"/v1/uploads/{upload_id}/finalize", json={}, headers=headers)

    first = client.post(
        f"/v1/uploads/{upload_id}/transcription",
        json={"language": "zh-CN"},
        headers=headers,
    )

    assert first.status_code == 201, first.text
    assert first.json()["source"]["text"] == "我小时候和二舅一起走去学校。"
    assert first.json()["source"]["source_kind"] == "transcript"
    assert first.json()["cached"] is False

    replay = client.post(
        f"/v1/uploads/{upload_id}/transcription",
        json={"language": "zh-CN"},
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["source"]["id"] == first.json()["source"]["id"]
    assert replay.json()["cached"] is True
    assert len(speech.transcription_calls) == 1


def test_disabled_retention_blocks_anonymous_transcription_and_keeps_question_playback() -> None:
    speech = FakeSpeechService()
    storage = FakeStoryStorage()
    client = TestClient(
        create_app(
            MemoryStore(),
            speech_service=speech,
            story_storage_factory=lambda _authorization: storage,
        )
    )
    headers = {"Authorization": "Bearer story-token"}
    encoded = base64.b64encode(b"story-flow-audio").decode()

    transcript = client.post(
        "/v1/story/transcriptions",
        json={"audio_base64": encoded, "filename": "round.webm", "mime_type": "audio/webm", "language": "zh-CN"},
        headers=headers,
    )
    assert transcript.status_code == 503, transcript.text
    assert transcript.headers["X-Error-Code"] == "ORIGINAL_RECORDINGS_DISABLED"
    assert speech.transcription_calls == []

    question = client.post(
        "/v1/story/question-audio",
        json={"text": "What do you remember?", "language": "en-AU"},
        headers=headers,
    )
    assert question.status_code == 201, question.text
    assert question.json()["ai_generated"] is True
    assert base64.b64decode(question.json()["audio_base64"]) == b"fake-mp3-audio"

    typed = "Typed correction while recording retention is disabled."
    answer = client.post(
        "/v1/story/rounds", json={"round": 1, "answer": typed}, headers=headers,
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["transcript"] is None
    assert json.loads(storage._memories[0]["content"])["answer"] == typed


def _native_speech_service():
    audio = io.BytesIO()
    with wave.open(audio, 'wb') as output:
        output.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        output.writeframes(b'\x00\x00' * 100)

    def provider(request):
        if request.url.path.endswith('generateContent'):
            return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'inlineData': {
                'mimeType': 'audio/wav', 'data': base64.b64encode(audio.getvalue()).decode(),
            }}]}}]})
        return httpx.Response(200, text=json.dumps({'code': 0, 'data': base64.b64encode(b'doubao-mp3').decode()}))

    def client():
        return httpx.Client(base_url='https://native-speech.test', transport=httpx.MockTransport(provider))

    return LocalizedSpeechService(OpenAISpeechService('test'),
        GeminiSpeechService('test', client=client()), DoubaoSpeechService('test', client=client()))


@pytest.mark.parametrize('language,model,voice,mime_type', [
    ('zh-CN', 'doubao-seed-tts-2.0', 'zh_female_vv_uranus_bigtts', 'audio/mpeg'),
    ('en-AU', 'gemini-3.8-flash-lite-tts', 'Kore', 'audio/wav'),
])
def test_story_audio_uses_native_provider_for_saved_interview_language(language, model, voice, mime_type):
    service = _native_speech_service()
    storage = FakeStoryStorage()
    storage._profile = {'preferred_language': language, 'ui_locale': 'en-AU' if language == 'zh-CN' else 'zh-CN'}
    client = TestClient(create_app(MemoryStore(), speech_service=service,
                                  story_storage_factory=lambda authorization: storage))
    response = client.post('/v1/story/question-audio', json={'text': 'A saved question.'},
                           headers={'Authorization': 'Bearer story-token'})
    assert response.status_code == 201, response.text
    body = response.json()
    assert (body['model'], body['voice'], body['mime_type']) == (model, voice, mime_type)
    audio = base64.b64decode(body['audio_base64'])
    assert audio.startswith(b'RIFF') if language == 'en-AU' else audio == b'doubao-mp3'
    replay = client.post('/v1/story/question-audio', json={'text': 'A saved question.'},
                         headers={'Authorization': 'Bearer story-token'})
    assert replay.status_code == 200
    assert replay.json()['cached'] is True


def test_story_audio_cache_changes_when_the_configured_native_model_changes():
    service = _native_speech_service()
    client = TestClient(create_app(MemoryStore(), speech_service=service,
                                  story_storage_factory=lambda authorization: FakeStoryStorage()))
    headers, request = {'Authorization': 'Bearer story-token'}, {'text': 'Question', 'language': 'en-AU'}
    assert client.post('/v1/story/question-audio', json=request, headers=headers).status_code == 201
    assert client.post('/v1/story/question-audio', json=request, headers=headers).status_code == 200
    service.gemini.tts_model = 'gemini-3.8-flash-tts'
    changed = client.post('/v1/story/question-audio', json=request, headers=headers)
    assert changed.status_code == 201
    assert changed.json()['model'] == 'gemini-3.8-flash-tts'


def test_session_question_audio_uses_the_native_model_and_playable_format():
    client = TestClient(create_app(MemoryStore(), speech_service=_native_speech_service()))
    project, session = _project_and_session(client)
    headers = {'X-Account-Id': 'speech-owner'}
    response = client.post(f"/v1/memory-sessions/{session['id']}/question-audio",
                           json={'language': 'en-AU'}, headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body['model'] == 'gemini-3.8-flash-lite-tts'
    assert body['voice'] == 'Kore'
    assert body['mime_type'] == 'audio/wav'
    audio = client.get(body['audio_url'], headers=headers)
    assert audio.status_code == 200
    assert audio.content.startswith(b'RIFF')


def test_transcription_inherits_saved_interview_language_without_using_ui_locale(monkeypatch):
    from apps.api.original_recordings import RecordingStore
    languages = []

    def transcribe(self, payload, service):
        languages.append(payload.language)
        return {'language': payload.language}

    monkeypatch.setattr(RecordingStore, 'transcribe', transcribe)
    storage = FakeStoryStorage()
    storage._profile = {'conversation_language': {'locale': 'zh-CN'}, 'ui_locale': 'en-AU'}
    client = TestClient(create_app(MemoryStore(), speech_service=_native_speech_service(),
                                  story_storage_factory=lambda authorization: storage))
    response = client.post('/v1/story/transcriptions', json={
        'audio_base64': base64.b64encode(b'audio').decode(), 'filename': 'answer.webm', 'mime_type': 'audio/webm',
    }, headers={'Authorization': 'Bearer story-token'})
    assert response.status_code == 200, response.text
    assert languages == ['zh-CN']
