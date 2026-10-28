"""Model settings inherit through environments and reach provider requests."""
import asyncio
import json

import httpx
import pytest

from apps.api.composer_configuration import composer_configuration
from apps.api.model_configuration import (background_effort, background_model,
    configured_effort, configured_model, game_configuration)
from apps.api.model_request import complete_json


def test_organiser_inherits_background_model_in_budget_and_worker(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from apps.api.codex_worker_service import CodexWorker
    from apps.api.lifetime_memory_collection_jobs import CollectionJobWorker
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'gpt-5.6-sol')
    worker = CodexWorker(home_root=tmp_path)
    assert worker._model_for(SimpleNamespace(agent_role='organiser', model=None)) == 'gpt-5.6-sol'
    assert CollectionJobWorker(None).budget.model == 'gpt-5.6-sol'


def test_blank_role_overrides_inherit_the_shared_environment():
    environment = {'MEMORY_SPARK_LLM_MODEL': 'gpt-5.6-sol',
        'MEMORY_SPARK_LLM_REASONING_EFFORT': ' medium ',
        'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL': '',
        'MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT': ' ',
        'MEMOIR_COMPOSER_MODEL': '', 'MEMOIR_COMPOSER_REASONING_EFFORT': '',
        'MEMOIR_GAME_MODEL': '', 'MEMOIR_GAME_REASONING_EFFORT': ''}
    assert background_model(environment) == 'gpt-5.6-sol'
    assert background_effort(environment) == 'medium'
    assert game_configuration(environment) == ('gpt-5.6-sol', 'medium')
    assert composer_configuration(environment).model == 'gpt-5.6-sol'
    assert composer_configuration(environment).effort == 'medium'
    environment.update(MEMORY_SPARK_MEMOIR_COMPOSER_MODEL='gpt-6.1-sol',
        MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT='high')
    assert game_configuration(environment) == ('gpt-6.1-sol', 'high')
    assert composer_configuration(environment).model == 'gpt-6.1-sol'
    assert composer_configuration(environment).effort == 'high'
    environment.update(MEMOIR_GAME_MODEL='dedicated-game', MEMOIR_GAME_REASONING_EFFORT='xhigh',
        MEMOIR_COMPOSER_MODEL='gpt-5.6-sol', MEMOIR_COMPOSER_REASONING_EFFORT='low')
    assert game_configuration(environment) == ('dedicated-game', 'xhigh')
    assert composer_configuration(environment).model == 'gpt-5.6-sol'
    assert composer_configuration(environment).effort == 'low'


@pytest.mark.parametrize('resolve,key,value', [
    (configured_model, 'MEMORY_SPARK_LLM_MODEL', ''),
    (configured_model, 'MEMORY_SPARK_LLM_MODEL', 'bad\nmodel'),
    (configured_model, 'MEMORY_SPARK_LLM_MODEL', 'a' * 257),
    (configured_effort, 'MEMORY_SPARK_LLM_REASONING_EFFORT', ''),
    (configured_effort, 'MEMORY_SPARK_LLM_REASONING_EFFORT', 'unbounded'),
])
def test_missing_or_invalid_settings_fail_before_dispatch(resolve, key, value):
    with pytest.raises(ValueError):
        resolve(environment={key: value})


@pytest.mark.parametrize('overrides', [False, True])
def test_structured_background_requests_use_environment_model_and_effort(monkeypatch, overrides):
    monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL', 'shared-model')
    monkeypatch.setenv('MEMORY_SPARK_LLM_REASONING_EFFORT', 'medium')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'background-model' if overrides else '')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT', 'high' if overrides else '')
    def provider(request):
        body = json.loads(request.content)
        assert body['model'] == ('background-model' if overrides else 'shared-model')
        assert body['reasoning']['effort'] == ('high' if overrides else 'medium')
        return httpx.Response(200, json={'id': 'controlled-response', 'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{}'}]}]})
    result, _ = asyncio.run(complete_json('memoir/skills/memoir-interviewer/policy-review', {}, {},
        base_url='https://controlled.invalid/v1', api_key='controlled-key',
        transport=httpx.MockTransport(provider)))
    assert result == {}
