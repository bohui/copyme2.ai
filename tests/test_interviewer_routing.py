"""The low reply contract must reach the dedicated key, without changing other policies."""
import pytest

from apps.api.collector_configuration import collector_configuration


@pytest.mark.parametrize('configured,effort,version,expected', [
    ('', 'low', 'reply-v2', 'gpt-5.6-luna-memoir-low'),
    ('gpt-5.6-luna-pooled', 'low', 'reply-v2', 'gpt-5.6-luna-memoir-low'),
    ('gpt-5.6-luna-pooled', 'max', 'reply-v2', 'gpt-5.6-luna-pooled'),
    ('gpt-5.6-luna-pooled', '', 'reply-v2', 'gpt-5.6-luna-pooled'),
    ('gpt-5.6-luna-pooled', 'low', 'compact-v1', 'gpt-5.6-luna-pooled'),
    ('gpt-5.6-luna-pooled', 'low', 'two-lane-v1', 'gpt-5.6-luna-pooled'),
    ('custom-collector', 'low', 'reply-v2', 'custom-collector'),
])
def test_only_known_pooled_low_reply_configuration_changes_route(monkeypatch, configured, effort, version, expected):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', configured)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', effort)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', version)
    result = collector_configuration('gpt-5.6-luna-pooled')
    assert result.model == expected
    assert result.effort == (effort or None)
    assert result.prompt_version == version


def test_custom_runtime_default_is_preserved(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_COLLECTOR_MODEL', raising=False)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', 'low')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    assert collector_configuration('custom-runtime').model == 'custom-runtime'
