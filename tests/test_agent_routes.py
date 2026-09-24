from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore


def test_agent_config_exposes_public_connection_settings(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    client = TestClient(create_app(MemoryStore()))

    response = client.get('/v1/agent/config')

    assert response.status_code == 200
    assert response.json() == {
        'enabled': True,
        'supabase_url': 'https://example.supabase.co',
        'supabase_publishable_key': 'public-key',
    }


def test_agent_turn_requires_a_supabase_bearer_token(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    client = TestClient(create_app(MemoryStore()))

    response = client.post('/v1/agent/turn', json={'text': 'Hello'})

    assert response.status_code == 401
    assert response.json()['detail'] == 'Supabase sign-in required'
