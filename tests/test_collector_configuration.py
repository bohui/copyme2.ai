"""Current collector policy at the normal streamed turn/execution seams."""
import asyncio
import json
from uuid import uuid4

import pytest

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from test_name_only_opening import Storage, harness, proposal


@pytest.mark.parametrize('execution', ['local', 'worker'])
@pytest.mark.parametrize('completed', [0, 3, 18])
def test_current_collector_policy_on_resumed_turn_and_rollback(monkeypatch, tmp_path, execution, completed):
    observed = []
    response = proposal(name=None, question='那条河还有什么让您记得的事？')
    class Connection:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, params):
            observed.append({'method': method, **params})
            return {'thread': {'id': 'existing-thread'}}
        async def turn(self, thread, text, **kwargs):
            observed[-1].update(effort=kwargs.get('effort'), text=text)
            raw = json.dumps(response, ensure_ascii=False)
            if kwargs.get('on_delta'): await kwargs['on_delta'](raw)
            return raw

    storage = Storage({'name': '韩凤江', 'preferred_language': 'zh-CN'})
    runtime, _ = harness(monkeypatch, tmp_path, storage, response, 'local')
    runtime.model = 'legacy-route'
    storage.agent_session = lambda: {'codex_thread_id': 'existing-thread'} if completed else None
    storage.rounds = completed
    monkeypatch.setattr('apps.api.codex_runtime.CodexConnection', Connection)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    monkeypatch.setattr('apps.api.codex_worker_service.iter_artifacts', lambda *a, **kw: [])
    worker = CodexWorker(home_root=tmp_path / 'worker', model='legacy-route')
    monkeypatch.setattr(worker, '_home', lambda *a: tmp_path)
    source = '我还记得那条河。' * 3000
    async def run():
        for enabled in (True, False):
            if enabled:
                monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'memoir-luna-low')
                monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', 'low')
                monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'compact-v1')
            else:
                for key in ('MODEL', 'REASONING_EFFORT', 'PROMPT_VERSION'):
                    monkeypatch.delenv('MEMORY_SPARK_COLLECTOR_' + key)
            chunks, packets = [], []
            async def delta(value): chunks.append(value)
            async def event(value): packets.append(value)
            storage.turn = storage.memory = None
            if execution == 'local':
                result = await runtime.turn(storage, source, project_id='project', client_turn_id=str(uuid4()), on_delta=delta, on_event=event)
                assert result['conversation_saved']
                assert ''.join(chunks) == result['reply']
                assert storage.turn['source']['text'] == source
                assert any(p['type'] == 'conversation_saved' for p in packets)
            else:
                await worker.turn(WorkerTurnInput(user_id=storage.user_id, thread_id='existing-thread' if completed else None, text=source,
                    language='zh-CN', conversation_rounds_completed=completed,
                    interview_context={'source': {'id': str(uuid4()), 'version': 1, 'status': 'active', 'text': source},
                        'opening_turn': False}), on_delta=delta)
            assert observed[-1]['method'] == ('thread/resume' if completed else 'thread/start')
            if completed:
                assert observed[-1]['threadId'] == 'existing-thread'
            assert source in observed[-1]['text']
            assert observed[-1]['model'] == ('memoir-luna-low' if enabled else 'legacy-route')
            assert observed[-1]['effort'] == ('low' if enabled else None)
        assert len(observed) == 2
        assert len(observed[0]['baseInstructions']) < len(observed[1]['baseInstructions'])
    asyncio.run(run())


def test_invalid_collector_configuration_fails_without_provider_dispatch(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', 'not-an-effort')
    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *a: pytest.fail('Invalid policy must fail before runtime writes'))
    with pytest.raises(ValueError, match='collector'):
        asyncio.run(worker.turn(WorkerTurnInput(user_id='11111111-1111-4111-8111-111111111111', text='Hello')))


def test_entitlement_is_read_once_per_fenced_turn_not_cached_between_turns(monkeypatch, tmp_path):
    from unittest.mock import Mock
    storage = Storage()
    storage.story_entitlement = Mock(return_value=None)
    runtime, _ = harness(monkeypatch, tmp_path, storage, proposal(), 'worker')
    async def run():
        for expected in (1, 2):
            storage.turn = storage.memory = None
            await runtime.turn(storage, '我叫韩凤江', project_id='project', client_turn_id=str(uuid4()))
            assert storage.story_entitlement.call_count == expected
    asyncio.run(run())


@pytest.mark.parametrize('role', ['workspace', 'memory_context', 'composer', 'author_timeline', 'organiser'])
def test_collector_overrides_do_not_change_other_roles(monkeypatch, tmp_path, role):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'memoir-luna-low')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', 'low')
    # Invalid collector config must not affect independent roles either.
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'invalid')
    from unittest.mock import AsyncMock
    monkeypatch.setattr(CodexWorker, '_ensure_composer_provider', AsyncMock())
    seen = []
    class Connection:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, params):
            seen.append(params)
            return {'thread': {'id': 'other-role'}}
        async def turn(self, thread, text, **options):
            seen.append(options)
            return '{}'
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    monkeypatch.setattr('apps.api.codex_worker_service.iter_artifacts', lambda *a, **kw: [])
    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *a: tmp_path)
    asyncio.run(worker.turn(WorkerTurnInput(user_id='11111111-1111-4111-8111-111111111111', text='Hello',
        agent_role=role, model='unchanged-role-route')))
    assert seen[0]['model'] == 'unchanged-role-route'
    assert seen[1].get('effort') == ('low' if role in {'composer', 'author_timeline'} else None)


def test_unavailable_collector_route_fails_once_without_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'unavailable-collector')
    calls = []
    class Connection:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, params):
            calls.append(params['model'])
            raise RuntimeError('Route unavailable')
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *a: tmp_path)
    with pytest.raises(RuntimeError, match='Route unavailable'):
        asyncio.run(worker.turn(WorkerTurnInput(user_id='11111111-1111-4111-8111-111111111111', text='Hello')))
    assert calls == ['unavailable-collector']


def test_saved_result_replay_does_not_resolve_new_invalid_configuration(monkeypatch, tmp_path):
    storage = Storage()
    runtime, calls = harness(monkeypatch, tmp_path, storage, proposal(), 'worker')
    turn = str(uuid4())
    async def run():
        first = await runtime.turn(storage, '我叫韩凤江', project_id='project', client_turn_id=turn)
        monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'invalid')
        replay = await runtime.turn(storage, '我叫韩凤江', project_id='project', client_turn_id=turn)
        assert replay['cached'] and replay['reply'] == first['reply']
        assert len(calls) == 1 and storage.rounds == 1
    asyncio.run(run())


def test_diagnostic_configuration_receipt_does_not_claim_effective_low(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'memoir-luna-low')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', 'low')
    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *a: tmp_path)
    class Connection:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, *a): return {'thread': {'id': 'test'}}
        async def turn(self, *a, **kw): return 'A safe visible reply.'
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    monkeypatch.setattr('apps.api.codex_worker_service.iter_artifacts', lambda *a, **kw: [])
    captured = []
    monkeypatch.setattr('apps.api.codex_worker_service.log_diagnostic', lambda *args, **kw: captured.append((args[1], kw)))
    asyncio.run(worker.turn(WorkerTurnInput(user_id='11111111-1111-4111-8111-111111111111', text='private narrator material')))
    receipt = next(fields for event, fields in captured if event == 'collector_configuration')
    assert receipt['requested_effort'] == 'low'
    assert receipt['effective_effort'] == 'unavailable'
    assert 'private narrator material' not in json.dumps(captured)
