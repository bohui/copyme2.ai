from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore


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
            "model": "gpt-4o-mini-transcribe",
        }

    def synthesize(self, text: str, **options):
        self.synthesis_calls.append({"text": text, **options})
        return {
            "content": b"fake-mp3-audio",
            "mime_type": "audio/mpeg",
            "model": "gpt-4o-mini-tts",
            "voice": options.get("voice", "marin"),
            "provider": "openai",
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
    assert body["source_version"]["transcription_method"] == "openai"
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


def test_supabase_story_flow_uses_openai_speech_for_review_and_question_playback() -> None:
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
    assert transcript.status_code == 200, transcript.text
    assert transcript.json()["text"] == "我小时候和二舅一起走去学校。"

    question = client.post(
        "/v1/story/question-audio",
        json={"text": "What do you remember?", "language": "en-AU"},
        headers=headers,
    )
    assert question.status_code == 201, question.text
    assert question.json()["ai_generated"] is True
    assert base64.b64decode(question.json()["audio_base64"]) == b"fake-mp3-audio"

    answer = client.post(
        "/v1/story/rounds",
        json={"round": 1, "answer": transcript.json()["text"], "audio_base64": encoded, "audio_filename": "round.webm", "audio_mime_type": "audio/webm"},
        headers=headers,
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["transcript"] == transcript.json()["text"]
    assert json.loads(storage._memories[0]["content"])["answer"] == transcript.json()["text"]
