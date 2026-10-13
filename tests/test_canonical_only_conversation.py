"""The development app has one conversation engine, including spoken input."""
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api.main import create_app
from apps.api.store import MemoryStore


def test_direct_webrtc_creation_is_removed_from_app_and_schema():
    client = TestClient(create_app(MemoryStore()))
    response = client.post('/api/v1/memoir/realtime/calls', json={'sdp': 'v=0'})
    assert response.status_code == 404
    assert not any('realtime/calls' in path for path in client.get('/openapi.json').json()['paths'])


@pytest.mark.parametrize('route,payload', [
    ('turn', {'text': 'Recorded words', 'source_kind': 'narrator_transcript'}),
    ('greeting', {'action': 'begin'}),
])
def test_requests_always_use_canonical_engine(monkeypatch, route, payload):
    from apps.api import agent_routes, lifetime_memory_runtime
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', '0')
    storage = SimpleNamespace(user_id=str(UUID(int=4)), client=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda authorization: storage)
    calls = []

    async def canonical(runtime, selected_storage, text, **options):
        assert selected_storage is storage
        calls.append((text, options))
        return {'engine': 'canonical'}

    monkeypatch.setattr(lifetime_memory_runtime, 'lifetime_http_turn', canonical)
    client = TestClient(create_app(MemoryStore()))
    response = client.post('/api/v1/memoir/agent/' + route, json=payload)
    assert response.status_code == 200, response.text
    assert response.json() == {'engine': 'canonical'}
    assert len(calls) == 1
    if route == 'turn':
        assert calls[0][0] == 'Recorded words'
        assert calls[0][1]['options']['source_kind'] == 'narrator_transcript'


def test_unbounded_worker_context_is_rejected_before_execution():
    from apps.api.codex_worker_service import WorkerTurnInput
    with pytest.raises(ValidationError, match='canonical execution contract'):
        WorkerTurnInput(user_id=UUID(int=4), text='Old raw context', profile={'name': 'private'})


def test_disabled_rollout_flag_cannot_select_old_engine(monkeypatch):
    from apps.api.lifetime_memory_runtime import lifetime_enabled, lifetime_generation_paused
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', '0')
    monkeypatch.delenv('MEMOIR_LIFETIME_GENERATION_PAUSED', raising=False)
    assert lifetime_enabled()
    assert not lifetime_generation_paused()
    monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED', '1')
    assert lifetime_generation_paused()
