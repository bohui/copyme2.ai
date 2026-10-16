"""Synthetic complete media and the authenticated API are the acceptance seam."""
import base64
import hashlib
import subprocess

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore
from test_speech_integration import FakeSpeechService, FakeStoryStorage


@pytest.fixture(scope='module', params=['webm', 'm4a', 'wav'])
def media(request, tmp_path_factory):
    path = tmp_path_factory.mktemp('original-audio') / ('synthetic.' + request.param)
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'sine=frequency=440:duration=0.2', '-y', str(path)], check=True)
    return path.read_bytes(), {'webm':'audio/webm', 'm4a':'audio/mp4', 'wav':'audio/wav'}[request.param]


def test_complete_original_validation_has_server_checksum_and_decoded_metadata(media):
    from apps.api.original_recordings import validate_original
    content, mime = media
    metadata = validate_original(base64.b64encode(content).decode(), mime)
    assert metadata['content_type'] == mime
    assert metadata['content_sha256'] == hashlib.sha256(content).hexdigest()
    assert metadata['byte_size'] == len(content)
    assert 0 < metadata['duration_seconds'] < 1
    assert metadata['codec']


@pytest.mark.parametrize('encoded,mime', [('!', 'audio/webm'), ('', 'audio/webm'),
    (base64.b64encode(b'not a complete recording').decode(), 'audio/webm')])
def test_invalid_original_is_rejected_before_external_processing(encoded, mime):
    from fastapi import HTTPException
    from apps.api.original_recordings import validate_original
    with pytest.raises(HTTPException):
        validate_original(encoded, mime)


def test_anonymous_authentication_and_microphone_permission_do_not_authorize_retention(monkeypatch, media):
    storage, speech = FakeStoryStorage(), FakeSpeechService()
    monkeypatch.setenv('MEMOIR_ORIGINAL_RECORDINGS', '1')
    client = TestClient(create_app(MemoryStore(), speech_service=speech,
        story_storage_factory=lambda _: storage))
    content, mime = media
    result = client.post('/api/v1/memoir/story/transcriptions',
        headers={'Authorization':'Bearer synthetic'}, json={
            'audio_base64':base64.b64encode(content).decode(), 'mime_type':mime})
    assert result.status_code == 403
    assert result.headers['X-Error-Code'] == 'RECORDING_AUTHORITY_REQUIRED'
    assert speech.transcription_calls == []


def test_rollout_defaults_off_without_provider_or_storage_work(media):
    storage, speech = FakeStoryStorage(), FakeSpeechService()
    client = TestClient(create_app(MemoryStore(), speech_service=speech,
        story_storage_factory=lambda _: storage))
    content, mime = media
    result = client.post('/v1/story/transcriptions', json={
        'audio_base64':base64.b64encode(content).decode(), 'mime_type':mime})
    assert result.status_code == 503
    assert result.headers['X-Error-Code'] == 'ORIGINAL_RECORDINGS_DISABLED'
    assert speech.transcription_calls == []


def test_reference_and_new_payload_are_mutually_exclusive():
    from apps.api.story_routes import StoryTranscriptionInput
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        StoryTranscriptionInput(audio_base64='YQ==', recording_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')


def test_mislabeled_media_and_decoded_byte_duration_limits(media,monkeypatch):
    from fastapi import HTTPException
    from apps.api import original_recordings as recordings
    content,mime=media;encoded=base64.b64encode(content).decode()
    with pytest.raises(HTTPException) as failure:recordings.validate_original(encoded,'audio/ogg' if mime!='audio/ogg' else 'audio/mp4')
    assert failure.value.status_code==415
    monkeypatch.setattr(recordings,'MAX_DURATION',0.01)
    with pytest.raises(HTTPException) as failure:recordings.validate_original(encoded,mime)
    assert failure.value.status_code==413
    monkeypatch.setattr(recordings,'MAX_AUDIO_BYTES',1)
    with pytest.raises(HTTPException) as failure:recordings.validate_original(encoded,mime)
    assert failure.value.status_code==413


def test_encoded_request_is_bounded_and_validation_never_echoes_audio():
    from apps.api.original_recordings import MAX_REQUEST_BYTES
    client=TestClient(create_app(MemoryStore()))
    secret='PRIVATE_AUDIO_PAYLOAD_DO_NOT_ECHO'
    invalid=client.post('/api/v1/memoir/story/transcriptions',json={'audio_base64':secret,'recording_id':'bad'})
    assert invalid.status_code==422
    assert secret not in invalid.text
    oversized=client.post('/api/v1/memoir/story/transcriptions',content=b'A'*(MAX_REQUEST_BYTES+1))
    assert oversized.status_code==413
