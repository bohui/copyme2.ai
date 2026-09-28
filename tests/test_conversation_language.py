import asyncio

import pytest

from apps.api.codex_runtime import CodexRuntime


class Storage:
    user_id = '11111111-1111-4111-8111-111111111111'

    def __init__(self, profile=None):
        self.data = profile or {}

    def acquire_agent_turn_lease(self, *args):
        return True

    renew_agent_turn_lease = acquire_agent_turn_lease
    release_agent_turn_lease = acquire_agent_turn_lease

    def agent_session(self):
        return None

    def memories(self):
        return []

    def profile(self):
        return self.data

    def save_profile(self, profile):
        self.data = profile

    def commit_agent_turn(self, *args):
        return {}


def test_first_chinese_message_resolves_and_saves_language_before_streaming(monkeypatch):
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test')
    calls = []
    chunks = []

    async def worker(**kwargs):
        calls.append(kwargs)
        assert kwargs['language'] == 'zh-CN'
        assert kwargs['profile']['preferred_language'] == 'zh-CN'
        assert kwargs['prior'] is None
        assert 'preferred_language' not in storage.data
        await kwargs['on_delta']('你好慧博。')
        return {'thread_id': 'conversation', 'reply': '你好慧博。', 'artifacts': []}

    async def emit(chunk):
        chunks.append(chunk)

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    result = asyncio.run(runtime.turn(storage, '我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河南省开封市中心医院',
                                      language='en-AU', on_delta=emit))
    assert len(calls) == 1
    assert chunks == ['你好慧博。']
    assert result['profile_updates']['preferred_language'] == 'zh-CN'


def test_saved_language_overrides_ui_locale_without_repeating_intake(monkeypatch):
    storage = Storage({'preferred_language': 'zh-CN'})
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test')

    async def worker(**kwargs):
        assert kwargs.get('agent_role', 'collector') == 'collector'
        assert kwargs['language'] == 'zh-CN'
        return {'thread_id': 'conversation', 'reply': '你好。', 'artifacts': []}

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    asyncio.run(runtime.turn(storage, '你好', language='en-AU'))


@pytest.mark.parametrize('reply', ['not JSON', '{}', '{"preferred_language":"fr"}',
                                  '{"preferred_language":[]}'])
def test_invalid_intake_stops_before_visible_generation(monkeypatch, reply):
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test')

    async def worker(**kwargs):
        assert kwargs['agent_role'] == 'memory_context'
        assert kwargs.get('on_delta') is None
        return {'thread_id': 'intake', 'reply': reply}

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    with pytest.raises(RuntimeError, match='Language intake'):
        asyncio.run(runtime.turn(storage, '你好'))
    assert storage.data == {}


def test_failed_profile_save_blocks_visible_generation(monkeypatch):
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test')

    async def worker(**kwargs):
        assert kwargs['agent_role'] == 'memory_context'
        return {'thread_id': 'intake', 'reply': '{"preferred_language":"zh-CN"}'}

    def fail_save(profile):
        raise RuntimeError('save unavailable')

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    monkeypatch.setattr(storage, 'save_profile', fail_save)
    with pytest.raises(RuntimeError, match='save unavailable'):
        asyncio.run(runtime.turn(storage, '你好'))


def test_ambiguous_intake_uses_fallback_without_saving_it(monkeypatch):
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test')

    async def worker(**kwargs):
        if kwargs.get('agent_role') == 'memory_context':
            return {'thread_id': 'intake', 'reply': '{"preferred_language":null}'}
        assert kwargs['language'] == 'en-AU'
        return {'thread_id': 'conversation', 'reply': 'Hello.', 'artifacts': []}

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    asyncio.run(runtime.turn(storage, '1983', language='en-AU'))
    assert storage.data == {}


def test_local_language_intake_is_private_and_ephemeral(monkeypatch, tmp_path):
    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, params):
            assert method == 'thread/start'
            assert params['ephemeral'] is True
            assert 'memoir-memory-context' in params['baseInstructions']
            assert 'Reply to the storyteller in English' not in params['baseInstructions']
            return {'thread': {'id': 'intake'}}

        async def turn(self, thread_id, prompt, **kwargs):
            assert thread_id == 'intake'
            assert '我叫慧博' in prompt
            assert kwargs['output_schema']['required'] == ['preferred_language']
            return '{"preferred_language":"zh-CN"}'

    monkeypatch.setattr('apps.api.codex_runtime.CodexConnection', Connection)
    runtime = CodexRuntime(home_root=tmp_path)
    runtime.worker_url = None
    assert asyncio.run(runtime._resolve_language(Storage.user_id, '我叫慧博', 'en-AU')) == 'zh-CN'
