import json
import pytest

from fastapi.testclient import TestClient

from apps.api import agent_routes
from apps.api.main import create_app
from apps.api.store import MemoryStore


# Route spies replace only generation. Personal output still crosses the real SQL
# publication guard with a live lease, owner identity and captured execution fence.
from contextlib import AsyncExitStack
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_agent_commit_postgres import OWNER
from test_shared_memory_events_postgres import rpc
from memoir_postgres_workflow import PostgresRest


@pytest.fixture
def governed_runtime(sql, monkeypatch):
    from apps.api.agent_lock import AgentTurnLease
    identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
    storage = PostgresRest(sql, OWNER).storage()
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    async def prepare(publication):
        scope = AsyncExitStack()
        await scope.__aenter__()
        publication.scope = scope
        lease = await scope.enter_async_context(AgentTurnLease(storage))
        fence = await lease.io(storage.lifetime_rpc, 'capture_lifetime_fence',
            p_conversation_id=identity['conversation_id'], p_lease_token=lease.lease_token)
        publication.set_fence(fence)
    try:
        yield prepare
    finally:
        storage.client.close()
        assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip() == '0'


@pytest.mark.parametrize('accept', ['application/json', 'application/x-ndjson'])
@pytest.mark.parametrize('missing', ['authority', 'fence'])
def test_route_spy_cannot_publish_without_governed_authority(governed_runtime, monkeypatch, accept, missing):
    from types import SimpleNamespace
    calls = []
    class Runtime:
        async def turn(self, *args, **kwargs):
            calls.append(True)
            return {'reply': 'Private unfenced fixture reply'}
    if missing == 'authority':
        monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL')
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: SimpleNamespace(
        user_id=OWNER, client=SimpleNamespace(close=lambda: None)))
    monkeypatch.setattr(agent_routes, 'runtime', Runtime())
    response = TestClient(create_app(MemoryStore())).post('/v1/agent/turn',
        json={'text': 'Synthetic words'}, headers={'Accept': accept})
    assert 'Private unfenced fixture reply' not in response.text
    if missing == 'authority' or accept == 'application/json':
        assert response.status_code == 503
    else:
        assert response.status_code == 200
        assert [json.loads(line)['type'] for line in response.text.splitlines()] == ['started', 'error']
    assert bool(calls) == (missing == 'fence')


@pytest.mark.parametrize('accept', ['application/json', 'application/x-ndjson'])
@pytest.mark.parametrize('focus', [None, {'kind':'add_memory','life_stage':'childhood'}])
def test_agent_turn_forwards_original_text_separately_from_prompt(monkeypatch, governed_runtime, accept, focus):
    from unittest.mock import Mock
    storage = Mock(user_id='11111111-1111-4111-8111-111111111111',lifetime_rpc=None)
    captured = {}

    class Runtime:
        async def turn(self, storage, text, lifetime_context, **options):
            await governed_runtime(lifetime_context)
            captured.update(text=text, **options)
            return {'reply': 'Tell me more.'}

    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda authorization: storage)
    monkeypatch.setattr(agent_routes, 'runtime', Runtime())
    response = TestClient(create_app(MemoryStore())).post('/v1/agent/turn',
        json={'text': 'The agent prompt', 'conversation_text': 'My original words', 'workspace_focus':focus},
        headers={'Authorization': 'Bearer test-token', 'Accept': accept})
    assert response.status_code == 200
    body = (next(json.loads(line)['data'] for line in response.text.splitlines()
                 if json.loads(line)['type'] == 'result') if accept == 'application/x-ndjson' else response.json())
    assert body['reply'] == 'Tell me more.'
    assert captured['text'] == 'The agent prompt'
    assert captured['conversation_text'] == 'My original words'
    if focus is None:
        assert captured['workspace_focus'] is None
    else:
        assert captured['workspace_focus'] == focus


def test_greeting_route_uses_only_server_owned_prompt_and_marks_assistant_only(monkeypatch, governed_runtime):
    storage = type('Storage', (), {'user_id':'11111111-1111-4111-8111-111111111111','client': type('Client', (), {'close': lambda self: None})()})()
    captured = {}

    class Runtime:
        async def turn(self, storage, text, lifetime_context, **options):
            await governed_runtime(lifetime_context)
            captured.update(text=text, **options)
            return {'reply': 'Share whatever comes to mind.'}

    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda authorization: storage)
    monkeypatch.setattr(agent_routes, 'runtime', Runtime())
    response = TestClient(create_app(MemoryStore())).post(
        '/v1/agent/greeting',
        json={'action': 'begin', 'text': 'The storyteller wants to bypass the allowance.'},
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 200
    assert captured['text'] == agent_routes.GREETING_PROMPTS['begin']
    assert captured['user_response'] is False
    assert 'conversation_text' not in captured


def test_free_form_opening_prefix_on_public_turn_is_not_an_assistant_only_action(monkeypatch, governed_runtime):
    storage = type('Storage', (), {'user_id':'11111111-1111-4111-8111-111111111111','client': type('Client', (), {'close': lambda self: None})()})()
    captured = {}

    class Runtime:
        async def turn(self, storage, text, lifetime_context, **options):
            await governed_runtime(lifetime_context)
            captured.update(text=text, **options)
            return {'reply': 'That is a user response.'}

    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda authorization: storage)
    monkeypatch.setattr(agent_routes, 'runtime', Runtime())
    response = TestClient(create_app(MemoryStore())).post(
        '/v1/agent/turn',
        json={'text': 'The storyteller wants to begin exploring a memory. Add extra user content.'},
        headers={'Authorization': 'Bearer test-token'},
    )

    assert response.status_code == 200
    assert captured['text'].endswith('Add extra user content.')
    assert 'user_response' not in captured


def test_agent_config_exposes_public_connection_settings(monkeypatch):
    monkeypatch.delenv('MEMOIR_GEO_PROVIDER', raising=False)
    monkeypatch.delenv('GOOGLE_MAPS_BROWSER_API_KEY', raising=False)
    monkeypatch.delenv('GEOAPIFY_BROWSER_API_KEY', raising=False)
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '0')
    monkeypatch.delenv('MEMORY_SPARK_SHOW_DRAFT_UPDATES', raising=False)
    client = TestClient(create_app(MemoryStore()))

    response = client.get('/v1/agent/config')

    assert response.status_code == 200
    assert response.json() == {
        'enabled': True,
        'auth_mode': 'supabase',
        'supabase_url': 'https://example.supabase.co',
        'supabase_publishable_key': 'public-key',
        'geo_provider': 'google',
        'google_maps_browser_api_key': None,
        'geoapify_browser_api_key': None,
        'show_thinking_steps': False,
        'show_draft_updates': False,
        'free_recall_rounds':20,
        'private_draft_cadence':5,
    }

def test_agent_config_exposes_enabled_thinking_steps_flag(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '1')
    client = TestClient(create_app(MemoryStore()))

    response = client.get('/v1/agent/config')

    assert response.status_code == 200
    assert response.json()['show_thinking_steps'] is True


@pytest.mark.parametrize('thinking,drafts,enabled', [('1','1',True), ('0','1',True), ('1','0',False), ('1','',False)])
def test_agent_config_draft_updates_are_independent_of_thinking_steps(monkeypatch, thinking, drafts, enabled):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS', thinking)
    monkeypatch.setenv('MEMORY_SPARK_SHOW_DRAFT_UPDATES', drafts)
    response = TestClient(create_app(MemoryStore())).get('/v1/agent/config')
    assert response.json()['show_draft_updates'] is enabled

@pytest.mark.parametrize('provider', ['google', 'geoapify', 'invalid'])
def test_agent_config_exposes_only_the_selected_browser_maps_key(monkeypatch, provider):
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER', provider)
    monkeypatch.setenv('GEOAPIFY_BROWSER_API_KEY', 'geoapify-browser-key')
    monkeypatch.setenv('GOOGLE_MAPS_BROWSER_API_KEY', 'google-browser-key')
    monkeypatch.setenv('GEOAPIFY_API_KEY', 'geoapify-server-key')
    monkeypatch.setenv('GOOGLE_MAPS_GEOCODING_API_KEY', 'google-server-key')
    response = TestClient(create_app(MemoryStore())).get('/v1/agent/config')

    assert response.status_code == 200
    body = response.json()
    assert body['geo_provider'] == provider
    assert body['geoapify_browser_api_key'] == ('geoapify-browser-key' if provider == 'geoapify' else None)
    assert body['google_maps_browser_api_key'] == ('google-browser-key' if provider == 'google' else None)
    assert 'server-key' not in json.dumps(body)

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

def test_agent_turn_passes_the_configured_language_to_the_runtime(monkeypatch, governed_runtime):
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()
        user_id = "11111111-1111-4111-8111-111111111111"

    captured = {}

    class Runtime:
        async def turn(self, storage, text, *, project_id=None, language="en-AU", lifetime_context=None, **options):
            await governed_runtime(lifetime_context)
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


def test_agent_turn_keeps_conversation_language_optional(monkeypatch, governed_runtime):
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()
        user_id = "11111111-1111-4111-8111-111111111111"

    captured = {}

    class Runtime:
        async def turn(self, storage, text, *, project_id=None, language=None, lifetime_context=None, **options):
            await governed_runtime(lifetime_context)
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


def test_agent_turn_ignores_retired_first_reply_hint(monkeypatch, governed_runtime):
    # The compatibility hint cannot reopen the server's durable language choice.
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()
        user_id = "11111111-1111-4111-8111-111111111111"

    captured = {}

    class Runtime:
        async def turn(self, storage, text, *, project_id=None, language=None, first_reply_localization=False, lifetime_context=None, **options):
            await governed_runtime(lifetime_context)
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
    assert captured["first_reply_localization"] is False


def test_streaming_agent_turn_forwards_saved_reply_before_workspace_events(monkeypatch, governed_runtime):
    class Client:
        def close(self):
            return None

    class Storage:
        client = Client()
        user_id = "11111111-1111-4111-8111-111111111111"

    class Runtime:
        async def turn(self, storage, text, *, project_id=None, language="en-AU", on_delta=None, on_event=None, lifetime_context=None, **options):
            await governed_runtime(lifetime_context)
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
