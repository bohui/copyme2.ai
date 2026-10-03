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
        assert storage.data['preferred_language'] == 'zh-CN'
        assert storage.data['conversation_language']['initialized'] is True
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


def test_first_reply_hint_cannot_override_legacy_saved_setting(monkeypatch):
    storage = Storage({'preferred_language': 'en-AU'})
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test')
    calls = []

    async def worker(**kwargs):
        calls.append(kwargs)
        if kwargs.get('agent_role', 'collector') == 'collector':
            assert kwargs['language'] == 'en-AU'
            assert kwargs['profile']['preferred_language'] == 'en-AU'
        return {'thread_id': 'conversation', 'reply': '你好。', 'artifacts': []}

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    result = asyncio.run(runtime.turn(
        storage,
        '我叫慧博，现在生活在悉尼。',
        language='zh-CN',
        on_delta=lambda _chunk: None,
        first_reply_localization=True,
    ))
    assert calls
    assert result['profile_updates']['preferred_language'] == 'en-AU'


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


def test_ambiguous_first_intake_freezes_fallback_without_claiming_detection(monkeypatch):
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test')

    async def worker(**kwargs):
        if kwargs.get('agent_role') == 'memory_context':
            return {'thread_id': 'intake', 'reply': '{"preferred_language":null}'}
        assert kwargs['language'] == 'en-AU'
        return {'thread_id': 'conversation', 'reply': 'Hello.', 'artifacts': []}

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    asyncio.run(runtime.turn(storage, '1983', language='en-AU'))
    assert storage.data['preferred_language'] == 'en-AU'
    assert storage.data['conversation_language']['first_reply_locale'] is None
    assert storage.data['conversation_language']['initialized'] is True


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


@pytest.mark.parametrize('later',['我记得花园里的花。','I remember our garden.','小时候 our garden 有很多 flowers。'])
def test_first_reply_survives_second_turn_workspace_failure_restart_and_hint_replay(monkeypatch,later):
    from unittest.mock import AsyncMock
    storage=Storage();seen=[]
    async def worker(**kwargs):
        seen.append(kwargs['language'])
        assert kwargs['language']=='zh-CN'
        return {'thread_id':'conversation','reply':'一条合成回复。','artifacts':[]}
    async def delta(text): pass
    first=CodexRuntime(worker_url='http://worker',worker_secret='fixture')
    monkeypatch.setattr(first,'_worker_turn',worker)
    monkeypatch.setattr(first,'_run_workspace_job',AsyncMock(side_effect=RuntimeError('synthetic interrupted workspace')))
    asyncio.run(first.turn(storage,'我记得小时候的花园。',language='en-AU',on_delta=delta,first_reply_localization=True))
    saved=dict(storage.data)
    second=CodexRuntime(worker_url='http://worker',worker_secret='fixture')
    monkeypatch.setattr(second,'_worker_turn',worker)
    monkeypatch.setattr(second,'_run_workspace_job',AsyncMock(side_effect=RuntimeError('synthetic interrupted workspace')))
    asyncio.run(second.turn(storage,later,language='en-AU',on_delta=delta,first_reply_localization=True))
    assert seen==['zh-CN','zh-CN'] and storage.data==saved


def test_legacy_missing_locale_derives_earliest_original_reply_not_latest(monkeypatch):
    storage=Storage()
    storage.memories=lambda:[
        {'id':'recent','created_at':'2026-10-02','kind':'agent','content':'Storyteller: My recent garden memory\nMemory Spark: Reply'},
        {'id':'first','created_at':'2026-10-01','kind':'agent','content':'Storyteller: The storyteller said: 我记得小时候的花园。\nAcknowledge the storyteller naturally, then ask one gentle open-ended follow-up question.\nMemory Spark: 回复'},
        {'id':'opening','created_at':'2026-09-30','kind':'agent','content':'Storyteller: The storyteller wants to begin exploring a memory. Invite them.\nMemory Spark: Opening'},
    ]
    runtime=CodexRuntime(worker_url='http://worker',worker_secret='fixture')
    async def worker(**kwargs):
        assert kwargs['language']=='zh-CN'
        return {'thread_id':'resume','reply':'合成回复。','artifacts':[]}
    monkeypatch.setattr(runtime,'_worker_turn',worker)
    asyncio.run(runtime.turn(storage,'This is the latest reply.',on_delta=lambda _:None))
    assert storage.data['conversation_language']['first_reply_id']=='first'
    assert storage.data['preferred_language']=='zh-CN'


def test_background_and_collector_language_markers_cannot_override_explicit_selection(monkeypatch):
    from apps.api.conversation_locale import explicit_profile
    storage=Storage(explicit_profile({},'zh-CN'))
    runtime=CodexRuntime(worker_url='http://worker',worker_secret='fixture')
    async def worker(**kwargs):
        assert kwargs['language']=='zh-CN'
        return {'thread_id':'fixture','reply':'合成回复。 [[MEMORY_SPARK_PROFILE]]{"preferred_language":"en-AU","birth_place":"Fixture city"}[[/MEMORY_SPARK_PROFILE]]','artifacts':[]}
    monkeypatch.setattr(runtime,'_worker_turn',worker)
    asyncio.run(runtime.turn(storage,'An English follow-up.',on_delta=lambda _:None))
    assert storage.data['preferred_language']=='zh-CN' and storage.data['birth_place']=='Fixture city'
    assert storage.data['conversation_language']['source']=='explicit'


def test_greeting_does_not_consume_first_reply_and_explicit_request_overrides_once(monkeypatch):
    storage=Storage();runtime=CodexRuntime(worker_url='http://worker',worker_secret='fixture');languages=[]
    async def worker(**kwargs):
        languages.append(kwargs['language'])
        return {'thread_id':'fixture','reply':'Synthetic reply','artifacts':[]}
    monkeypatch.setattr(runtime,'_worker_turn',worker)
    asyncio.run(runtime.turn(storage,'The storyteller wants to begin exploring a memory. Invite them.',on_delta=lambda _:None))
    assert 'conversation_language' not in storage.data
    asyncio.run(runtime.turn(storage,'我记得小时候的花园。',on_delta=lambda _:None))
    asyncio.run(runtime.turn(storage,'Please reply in English.',on_delta=lambda _:None))
    asyncio.run(runtime.turn(storage,'后来我又回去了。',on_delta=lambda _:None))
    assert languages==['en-AU','zh-CN','en-AU','en-AU']
    assert storage.data['conversation_language']['source']=='explicit'
    assert storage.data['conversation_language']['first_reply_locale']=='zh-CN'


def test_cross_replica_concurrent_first_turn_uses_durable_fenced_decision(monkeypatch):
    import threading
    from apps.api.agent_lock import AgentTurnBusyError
    storage=Storage();lock=threading.Lock()
    storage.acquire_agent_turn_lease=lambda *args:lock.acquire(blocking=False)
    storage.release_agent_turn_lease=lambda *args:(lock.release() or True)
    async def run():
        entered=asyncio.Event();release=asyncio.Event();seen=[]
        first=CodexRuntime(worker_url='http://worker',worker_secret='fixture')
        second=CodexRuntime(worker_url='http://worker',worker_secret='fixture')
        async def worker(**kwargs):
            seen.append(kwargs['language']);entered.set();await release.wait()
            return {'thread_id':'fixture','reply':'Synthetic reply','artifacts':[]}
        monkeypatch.setattr(first,'_worker_turn',worker);monkeypatch.setattr(second,'_worker_turn',worker)
        task=asyncio.create_task(first.turn(storage,'我记得小时候的花园。',on_delta=lambda _:None))
        await entered.wait()
        with pytest.raises(AgentTurnBusyError):await second.turn(storage,'An English memory.',on_delta=lambda _:None)
        release.set();await task
        await second.turn(storage,'An English memory.',on_delta=lambda _:None)
        assert seen==['zh-CN','zh-CN']
    asyncio.run(run())


def test_synthetic_resume_without_eligible_history_keeps_existing_preference(monkeypatch):
    storage = Storage({'preferred_language': 'zh-CN'})
    storage.agent_session = lambda: {'codex_thread_id': 'fixture'}
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='fixture')
    async def worker(**kwargs):
        assert kwargs['language'] == 'zh-CN'
        return {'thread_id': 'fixture', 'reply': 'Synthetic reply', 'artifacts': []}
    monkeypatch.setattr(runtime, '_worker_turn', worker)
    asyncio.run(runtime.turn(storage, 'The storyteller wants to continue with another memory.', on_delta=lambda _: None))
    assert 'conversation_language' not in storage.data


@pytest.mark.parametrize('existing', [{}, {'preferred_language': 'en-AU'}])
def test_read_side_backfill_uses_earliest_reply_once_and_preserves_unmarked_preferences(existing):
    from apps.api.agent_storage import UserStorage
    from apps.api.conversation_locale import restore_from_history, explicit_profile
    storage = UserStorage.__new__(UserStorage)
    storage.user_id = Storage.user_id
    data = dict(existing)
    storage.profile = lambda: dict(data)
    storage.save_profile = lambda profile: (data.clear(), data.update(profile))
    storage.first_narrator_reply = lambda: {'id': 'first', 'text': '我记得小时候的花园。'}
    storage.acquire_agent_turn_lease = lambda *args: True
    storage.renew_agent_turn_lease = lambda *args: True
    storage.release_agent_turn_lease = lambda *args: True
    first = asyncio.run(restore_from_history(storage, dict(existing)))
    assert first['preferred_language'] == existing.get('preferred_language', 'zh-CN')
    assert first['conversation_language']['first_reply_locale'] == 'zh-CN'
    assert first['conversation_language']['first_reply_id'] == 'first'
    storage.first_narrator_reply = lambda: pytest.fail('Initialized profiles must not redetect')
    assert asyncio.run(restore_from_history(storage, first)) == first
    override = explicit_profile(first, 'en-AU')
    assert asyncio.run(restore_from_history(storage, override)) == override


def test_resume_backfill_reads_fresh_explicit_choice_after_acquiring_lease():
    from apps.api.agent_storage import UserStorage
    from apps.api.conversation_locale import restore_from_history, explicit_profile
    storage = UserStorage.__new__(UserStorage)
    storage.user_id = Storage.user_id
    override = explicit_profile({}, 'en-AU')
    storage.profile = lambda: override
    storage.save_profile = lambda _: pytest.fail('A concurrent explicit choice must win')
    storage.first_narrator_reply = lambda: {'id': 'first', 'text': '我记得小时候的花园。'}
    storage.acquire_agent_turn_lease = lambda *args: True
    storage.renew_agent_turn_lease = lambda *args: True
    storage.release_agent_turn_lease = lambda *args: True
    assert asyncio.run(restore_from_history(storage, {})) == override


def test_ambiguous_first_reply_freezes_ui_fallback_across_later_text_and_reset(monkeypatch):
    from apps.api.conversation_locale import explicit_profile
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='fixture')
    languages = []
    async def worker(**kwargs):
        languages.append(kwargs['language'])
        return {'thread_id':'fixture', 'reply':'Synthetic reply', 'artifacts':[]}
    monkeypatch.setattr(runtime, '_worker_turn', worker)
    asyncio.run(runtime.turn(storage, '1983', language='zh-CN', on_delta=lambda _:None))
    asyncio.run(runtime.turn(storage, 'A later English reply.', language='en-AU', on_delta=lambda _:None))
    storage.data = explicit_profile(explicit_profile(storage.data, 'en-AU'), None)
    asyncio.run(runtime.turn(storage, 'Another English reply.', language='en-AU', on_delta=lambda _:None))
    assert languages == ['zh-CN']*3
    assert storage.data['conversation_language']['first_reply_locale'] is None
    assert storage.data['conversation_language']['first_reply_fallback'] == 'zh-CN'
