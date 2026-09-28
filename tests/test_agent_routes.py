import json

from fastapi.testclient import TestClient

from apps.api import agent_routes
from apps.api.main import create_app
from apps.api.store import MemoryStore


def test_agent_config_exposes_public_connection_settings(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '0')
    client = TestClient(create_app(MemoryStore()))

    response = client.get('/v1/agent/config')

    assert response.status_code == 200
    assert response.json() == {
        'enabled': True,
        'auth_mode': 'supabase',
        'supabase_url': 'https://example.supabase.co',
        'supabase_publishable_key': 'public-key',
        'show_thinking_steps': False,
    }


def test_agent_config_exposes_enabled_thinking_steps_flag(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '1')
    client = TestClient(create_app(MemoryStore()))

    response = client.get('/v1/agent/config')

    assert response.status_code == 200
    assert response.json()['show_thinking_steps'] is True


def test_agent_turn_requires_a_supabase_bearer_token(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    client = TestClient(create_app(MemoryStore()))

    response = client.post('/v1/agent/turn', json={'text': 'Hello'})

    assert response.status_code == 401
    assert response.json()['detail'] == 'Supabase sign-in required'


def test_project_creation_does_not_turn_missing_conversation_language_into_ui_language():
    client = TestClient(create_app(MemoryStore()))

    response = client.post(
        "/v1/projects",
        json={"mode": "self"},
        headers={"X-Account-Id": "independent-language-user"},
    )

    assert response.status_code == 201
    assert response.json()["profile"]["preferred_language"] is None


def test_agent_turn_passes_the_configured_language_to_the_runtime(monkeypatch):
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()
        user_id = "11111111-1111-4111-8111-111111111111"

    captured = {}

    class Runtime:
        async def turn(self, storage, text, *, project_id=None, language="en-AU"):
            captured.update(storage=storage, text=text, project_id=project_id, language=language)
            return {"reply": "好的，我们用中文继续。"}

    monkeypatch.setattr(agent_routes, "authenticated_storage", lambda authorization: Storage())
    monkeypatch.setattr(agent_routes, "runtime", Runtime())
    client = TestClient(create_app(MemoryStore()))

    response = client.post(
        "/v1/agent/turn",
        json={"text": "我想从小时候开始。", "project_id": "project-1", "language": "zh-CN"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "好的，我们用中文继续。"
    assert captured["text"] == "我想从小时候开始。"
    assert captured["project_id"] == "project-1"
    assert captured["language"] == "zh-CN"


def test_agent_turn_keeps_conversation_language_optional(monkeypatch):
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()
        user_id = "11111111-1111-4111-8111-111111111111"

    captured = {}

    class Runtime:
        async def turn(self, storage, text, *, project_id=None, language=None):
            captured.update(text=text, project_id=project_id, language=language)
            return {"reply": "The conversation language is selected independently."}

    monkeypatch.setattr(agent_routes, "authenticated_storage", lambda authorization: Storage())
    monkeypatch.setattr(agent_routes, "runtime", Runtime())
    client = TestClient(create_app(MemoryStore()))

    response = client.post(
        "/v1/agent/turn",
        json={"text": "A Mandarin interview can have an English interface."},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert captured["language"] is None


def test_agent_turn_passes_first_reply_localization_only_when_requested(monkeypatch):
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()
        user_id = "11111111-1111-4111-8111-111111111111"

    captured = {}

    class Runtime:
        async def turn(self, storage, text, *, project_id=None, language=None, first_reply_localization=False):
            captured.update(text=text, project_id=project_id, language=language,
                            first_reply_localization=first_reply_localization)
            return {"reply": "你好。"}

    monkeypatch.setattr(agent_routes, "authenticated_storage", lambda authorization: Storage())
    monkeypatch.setattr(agent_routes, "runtime", Runtime())
    client = TestClient(create_app(MemoryStore()))

    response = client.post(
        "/v1/agent/turn",
        json={"text": "我叫慧博", "project_id": "project-1", "language": "zh-CN",
              "first_reply_localization": True},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert captured["first_reply_localization"] is True


def test_streaming_agent_turn_forwards_saved_reply_before_workspace_events(monkeypatch):
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()
        user_id = "11111111-1111-4111-8111-111111111111"

    class Runtime:
        async def turn(self, storage, text, *, project_id=None, language="en-AU", on_delta=None, on_event=None):
            await on_delta("Hello")
            await on_event({"type": "reply_complete", "data": {"reply": "Hello"}})
            await on_event({"type": "conversation_saved", "data": {"reply": "Hello"}})
            await on_event({"type": "workspace_update", "data": {"workspace_status": "ready"}})
            return {"reply": "Hello"}

    monkeypatch.setattr(agent_routes, "authenticated_storage", lambda authorization: Storage())
    monkeypatch.setattr(agent_routes, "runtime", Runtime())
    client = TestClient(create_app(MemoryStore()))

    response = client.post(
        "/v1/agent/turn",
        json={"text": "Hello"},
        headers={"Authorization": "Bearer test-token", "Accept": "application/x-ndjson"},
    )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert [event["type"] for event in events] == [
        "started", "text_delta", "reply_complete", "conversation_saved",
        "workspace_update", "result",
    ]


def test_agent_turn_rejects_unsupported_conversation_language(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    client = TestClient(create_app(MemoryStore()))

    response = client.post(
        "/v1/agent/turn",
        json={"text": "Hello", "language": "fr-FR"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 422


def test_place_journey_endpoint_returns_the_public_record_shape(monkeypatch):
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()

        @staticmethod
        def place_journey():
            return {
                'schema_version': 1,
                'status': 'active',
                'revision': 2,
                'place': 'Anshan',
                'hierarchy': ['Earth', 'China', 'Liaoning', 'Anshan'],
                'granularity': 'city',
                'latitude': 41.1086,
                'longitude': 122.99,
                'duration_ms': 5200,
                'created_at': '2026-09-25T00:00:00Z',
                'updated_at': '2026-09-26T00:00:00Z',
            }

    monkeypatch.setattr('apps.api.agent_routes.authenticated_storage', lambda authorization: Storage())
    client = TestClient(create_app(MemoryStore()))

    response = client.get('/v1/agent/place-journey', headers={'Authorization': 'Bearer test-token'})

    assert response.status_code == 200
    assert response.json() == {
        'place_journey': {
            'schema_version': 1,
            'status': 'active',
            'revision': 2,
            'place': 'Anshan',
            'hierarchy': ['Earth', 'China', 'Liaoning', 'Anshan'],
            'granularity': 'city',
            'latitude': 41.1086,
            'longitude': 122.99,
            'duration_ms': 5200,
            'updated_at': '2026-09-26T00:00:00Z',
        }
    }


def test_family_context_endpoint_returns_the_persisted_renderable_document(monkeypatch):
    class Client:
        def close(self):
            return None

    document = {
        "schema_version": 1,
        "project_id": "project-family",
        "revision": 3,
        "updated_at": "2026-09-26T00:00:00Z",
        "people": [{"id": "person-1", "name": "Avery"}],
        "relationships": [],
        "timeline": [],
        "life_periods": [],
    }

    class Storage:
        client = Client()

        @staticmethod
        def story_entitlement():
            return {
                "status": "paid",
                "plan_key": "family_memoir_v1",
                "family_tree": True,
                "timeline": True,
                "stripe_price_id": "price_family_test",
            }

        @staticmethod
        def family_context(project_id):
            assert project_id == "project-family"
            return document

    monkeypatch.setenv("STRIPE_PRICE_FAMILY", "price_family_test")
    monkeypatch.setattr("apps.api.agent_routes.authenticated_storage", lambda authorization: Storage())
    client = TestClient(create_app(MemoryStore()))

    response = client.get(
        "/v1/agent/family-context?project_id=project-family",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "project_id": "project-family",
        "family_features_enabled": True,
        "family_context": document,
        "family_context_update": None,
    }
