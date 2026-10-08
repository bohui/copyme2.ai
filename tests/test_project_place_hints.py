"""Synthetic regression for project history reaching the extraction boundary."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes
from apps.api.codex_runtime import CodexRuntime, build_workspace_extraction_prompt
from apps.api.main import create_app
from apps.api.store import MemoryStore

OWNER = '11111111-1111-4111-8111-111111111111'
CITY = {'place': '承德市', 'hierarchy': ['Earth', '中国', '河北省', '承德市'],
        'granularity': 'city', 'latitude': 40.9517, 'longitude': 117.9632}


@pytest.mark.parametrize('accept', ['application/json', 'application/x-ndjson'])
def test_turn_loads_saved_project_places_instead_of_only_user_profile(monkeypatch, accept):
    store = MemoryStore()
    store.projects['project-synthetic'] = {'owner_id': OWNER, 'storyteller_id': OWNER,
        'members': {OWNER: {}}, 'profile': {'memory_places': [{**CITY,
            'pictures': [{'caption': 'must not enter extraction'}], 'life_stage': 'baby'}]}}
    storage = SimpleNamespace(user_id=OWNER, client=SimpleNamespace(close=lambda: None))
    captured = {}
    class Runtime:
        async def turn(self, storage, text, **options):
            captured.update(options)
            return {'reply': 'Synthetic reply.'}
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: storage)
    monkeypatch.setattr(agent_routes, 'runtime', Runtime())
    client = TestClient(create_app(store))
    response = client.post('/v1/agent/turn', headers={'Accept': accept},
        json={'project_id': 'project-synthetic', 'text': '后来又回到承德。'})
    assert response.status_code == 200
    hints = captured.get('saved_place_hints')
    assert hints and hints[0]['place'] == CITY['place']
    assert 'pictures' not in hints[0] and 'life_stage' not in hints[0]


def test_project_hints_are_bounded_and_other_projects_are_forbidden():
    store = MemoryStore()
    store.projects['project-synthetic'] = {'members': {OWNER: {}}, 'storyteller_id': OWNER,
        'profile': {'memory_places': [CITY] * 60}}
    assert len(agent_routes._project_place_hints(store, 'project-synthetic', OWNER)) == 50
    with pytest.raises(Exception) as error:
        agent_routes._project_place_hints(store, 'project-synthetic', 'other')
    assert error.value.status_code == 403


def test_runtime_keeps_project_hints_in_workspace_context_only(monkeypatch, tmp_path):
    class Storage:
        user_id = OWNER
        def __init__(self): self.profile_data = {'preferred_language': 'zh-CN'}
        def acquire_agent_turn_lease(self, *args): return True
        def renew_agent_turn_lease(self, *args): return True
        def release_agent_turn_lease(self, *args): return True
        def agent_session(self): return None
        def memories(self): return []
        def profile(self): return self.profile_data
        def save_profile(self, value): self.profile_data = value
        def place_journey(self): return None
        def commit_agent_turn(self, *args): return {'content': 'Synthetic exchange.'}
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://synthetic-worker', worker_secret='synthetic',
                           home_root=tmp_path, task_publisher_enabled=False)
    captured = {}
    async def worker(**options):
        assert 'memory_places' not in options['profile']
        return {'thread_id': 'synthetic', 'reply': 'Synthetic reply.', 'artifacts': []}
    async def workspace(**options):
        captured.update(options)
        raise RuntimeError('Synthetic stop after capturing extraction context')
    async def enqueue(**options): return None
    monkeypatch.setattr(runtime, '_worker_turn', worker)
    monkeypatch.setattr(runtime, '_persist_workspace', workspace)
    monkeypatch.setattr(runtime, '_enqueue_workspace_intent', enqueue)
    asyncio.run(runtime.turn(storage, '后来又回到承德。', project_id='project-synthetic',
                             saved_place_hints=[CITY]))
    assert captured['profile']['memory_places'] == [CITY]
    prompt = build_workspace_extraction_prompt('(none)', captured['profile'], language='zh-CN')
    assert '40.9517' in prompt and '承德市' in prompt
    assert 'memory_places' not in storage.profile_data
