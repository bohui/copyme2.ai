import asyncio
import tomllib

import pytest

from apps.api.codex_agent import CodexConnection, provider_config
from apps.api.codex_runtime import CodexRuntime
from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput


def test_memoir_defaults_to_chatgpt_pooled_luna_with_max_reasoning(monkeypatch, tmp_path):
    monkeypatch.delenv('MEMORY_SPARK_LLM_MODEL', raising=False)
    monkeypatch.delenv('MEMORY_SPARK_LLM_REASONING_EFFORT', raising=False)
    runtime = CodexRuntime(home_root=tmp_path / 'api')
    worker = CodexWorker(home_root=tmp_path / 'worker')

    assert runtime.model == worker.model == 'gpt-5.6-luna-pooled'
    config = tomllib.loads((runtime._home('test-user') / 'config.toml').read_text())
    assert config['model'] == runtime.model
    assert config['model_reasoning_effort'] == 'max'


@pytest.mark.parametrize('effort', ['max', 'high'])
def test_every_turn_explicitly_selects_configured_reasoning(monkeypatch, tmp_path, effort):
    # An existing thread can retain its old effort. A turn override must win
    # even when the caller resumes that thread instead of starting a new one.
    monkeypatch.setenv('MEMORY_SPARK_LLM_REASONING_EFFORT', effort)
    config = tomllib.loads(provider_config('http://gateway.test/v1', 'gpt-5.6-luna-pooled'))
    connection = CodexConnection([], tmp_path)

    async def request(method, params):
        assert method == 'turn/start'
        assert params['threadId'] == 'existing-thread'
        assert params['effort'] == config['model_reasoning_effort'] == effort
        return {'turn': {'id': 'test-turn'}}

    async def receive():
        return {'method': 'turn/completed', 'params': {
            'threadId': 'existing-thread', 'turn': {'id': 'test-turn', 'status': 'completed'},
        }}

    monkeypatch.setattr(connection, 'request', request)
    monkeypatch.setattr(connection, 'receive', receive)
    asyncio.run(connection.turn('existing-thread', 'synthetic input'))


@pytest.mark.parametrize('role,configured,override,expected', [
    ('author_timeline', None, None, 'low'),
    ('author_timeline', 'medium', None, 'medium'),
    ('author_timeline', 'medium', 'high', 'high'),
    ('collector', 'low', None, None),
    ('composer', None, None, 'low'),
])
def test_background_extraction_has_a_separate_reasoning_budget(
    monkeypatch, tmp_path, role, configured, override, expected,
):
    monkeypatch.setenv('MEMORY_SPARK_LLM_REASONING_EFFORT', 'max')
    monkeypatch.delenv('MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT', raising=False)
    monkeypatch.delenv('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT', raising=False)
    if configured:
        monkeypatch.setenv('MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT', configured)
    seen = []

    class Connection:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, params):
            return {'thread': {'id': 'synthetic-thread'}}
        async def turn(self, thread_id, prompt, **kwargs):
            seen.append(kwargs.get('effort'))
            return '{"events":[]}'

    worker = CodexWorker(home_root=tmp_path, reasoning_effort=override)
    monkeypatch.setattr(worker, '_home', lambda *args: tmp_path)
    async def reachable(): pass
    monkeypatch.setattr(worker, '_ensure_composer_provider', reachable)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    asyncio.run(worker.turn(WorkerTurnInput(
        user_id='11111111-1111-4111-8111-111111111111',
        agent_role=role, text='I started school.',
    )))
    assert seen == [expected]


@pytest.mark.parametrize('role,override,expected', [
    ('author_timeline', None, 'memoir-luna-low'),
    ('composer', None, 'memoir-luna-low'),
    ('collector', None, 'gpt-5.6-luna-pooled'),
    ('author_timeline', 'explicit-test-model', 'explicit-test-model'),
])
def test_background_roles_use_the_dedicated_model_route(monkeypatch, tmp_path, role, override, expected):
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'memoir-luna-low')
    seen = []

    class Connection:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, params):
            seen.append(params['model'])
            return {'thread': {'id': 'synthetic-thread'}}
        async def turn(self, *args, **kwargs): return '{"events":[]}'

    worker = CodexWorker(home_root=tmp_path, model='gpt-5.6-luna-pooled')
    monkeypatch.setattr(worker, '_home', lambda *args: tmp_path)
    async def reachable(): pass
    monkeypatch.setattr(worker, '_ensure_composer_provider', reachable)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    asyncio.run(worker.turn(WorkerTurnInput(
        user_id='11111111-1111-4111-8111-111111111111', agent_role=role,
        model=override, text='I started school.',
    )))
    assert seen == [expected]
