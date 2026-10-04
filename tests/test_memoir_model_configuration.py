import asyncio
import tomllib

import pytest

from apps.api.codex_agent import CodexConnection, provider_config
from apps.api.codex_runtime import CodexRuntime
from apps.api.codex_worker_service import CodexWorker


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
