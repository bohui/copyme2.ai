"""Model-selected work through the same collector harness as every story turn."""
import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from apps.api.codex_runtime import CodexRuntime
from test_interview_photo_runtime import Storage as ProjectStorage


class Storage(ProjectStorage):
    def __init__(self, profile=None):
        super().__init__()
        self.data = profile or {}

    def profile(self): return deepcopy(self.data)
    def save_profile(self, profile): self.data = deepcopy(profile)
    def interview_context(self, project): return {}
    def memory_events(self, project): return {'sources': [], 'events': []}
    def narrator_source_by_turn(self, *args): return deepcopy(self.turn['source'])

    def accept_interview_turn(self, project, turn, text, **kwargs):
        self.turn = self.turn or {'source': {'id': str(uuid4()), 'version': 1,
            'status': 'active', 'text': text}, 'photo_context': [], 'sequence': 1}
        return deepcopy(self.turn)


def proposal(mode='reply_only', name='韩凤江', question='您最早记得的一段往事是什么？'):
    return {'acknowledgement': f'{name}，很高兴认识您。' if name else '您提到小时候住在开封。',
        'plan': {'candidates': [{'id': 'next-memory', 'question': question, 'order': 0,
            'bridge': '', 'context': {'event_id': None, 'photo_id': None, 'life_stage': None, 'year': None}}],
            'chosen_id': 'next-memory', 'active_event_id': None, 'work': {'mode': mode, 'name': name}},
        'associations': [], 'response_photo_ids': [], 'stopped': False}


def harness(monkeypatch, tmp_path, storage, response, execution):
    runtime = CodexRuntime(worker_url='http://worker' if execution == 'worker' else None, worker_secret='fixture')
    calls = []
    # Existing locale intake has separate coverage. There is no new classifier.
    monkeypatch.setattr(runtime, '_resolve_language', AsyncMock(return_value='zh-CN'))

    async def output(options):
        raw = json.dumps(response, ensure_ascii=False)
        if options.get('on_delta'):
            for offset in range(0, len(raw), 7):
                await options['on_delta'](raw[offset:offset + 7])
        return raw

    async def worker(**kwargs):
        calls.append(kwargs)
        assert kwargs.get('agent_role', 'collector') == 'collector'
        assert kwargs['language'] == storage.data['preferred_language']
        return {'thread_id': 'real-collector-thread', 'reply': await output(kwargs), '_workspace_capable': True}

    class Connection:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, params):
            assert method == 'thread/start' and params['ephemeral'] is False
            assert 'plan.work.mode' in params['baseInstructions']
            return {'thread': {'id': 'real-collector-thread'}}
        async def turn(self, thread, prompt, **kwargs):
            calls.append({'text': prompt, **kwargs})
            assert 'work' in kwargs['output_schema']['$defs']['InterviewPlan']['properties']
            return await output(kwargs)

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    monkeypatch.setattr(runtime, '_home', lambda *args: tmp_path)
    monkeypatch.setattr('apps.api.codex_runtime.CodexConnection', Connection)
    monkeypatch.setattr(runtime, '_workspace_extraction', AsyncMock(side_effect=AssertionError('No speculative extraction')))
    monkeypatch.setattr(runtime, '_enqueue_workspace_intent', AsyncMock(return_value=None))
    monkeypatch.setattr(runtime, '_resume_pending_workspace', AsyncMock(return_value=None))
    monkeypatch.setattr(runtime, '_run_workspace_job', AsyncMock(return_value={
        'place_journey': None, 'place_journey_change': None, 'family_context': None,
        'family_context_update': None, 'tasks': [], 'task_errors': [], 'source_paths': []}))
    return runtime, calls


@pytest.mark.parametrize('execution', ['local', 'worker'])
@pytest.mark.parametrize('streaming', [False, True])
def test_name_only_reply_uses_one_collector_call_and_skips_workspace(monkeypatch, tmp_path, execution, streaming):
    storage = Storage()
    runtime, calls = harness(monkeypatch, tmp_path, storage, proposal(), execution)
    chunks, packets = [], []
    async def emit(chunk): chunks.append(chunk)
    async def event(packet): packets.append(packet)
    options = {'on_delta': emit, 'on_event': event} if streaming else {}
    result = asyncio.run(runtime.turn(storage, '我叫韩凤江', project_id='project', client_turn_id=str(uuid4()), **options))
    assert len(calls) == 1 and '我叫韩凤江' in calls[0]['text']
    assert result['reply'] == '韩凤江，很高兴认识您。\n\n您最早记得的一段往事是什么？'
    assert result['thread_id'] == 'real-collector-thread'
    assert storage.data['name'] == '韩凤江' and storage.data['preferred_language'] == 'zh-CN'
    assert storage.saved_plan['work'] == {'mode': 'reply_only', 'name': '韩凤江'}
    assert 'plan' not in result and 'work' not in result
    for method in ('_workspace_extraction', '_enqueue_workspace_intent', '_resume_pending_workspace', '_run_workspace_job'):
        getattr(runtime, method).assert_not_called()
    if streaming:
        assert ''.join(chunks) == result['reply']
        saved = next(p['data'] for p in packets if p['type'] == 'conversation_saved')
        assert saved['profile_updates']['name'] == '韩凤江'


@pytest.mark.parametrize('text', ['我叫韩凤江', '我出生在开封。',
    '我叫韩凤江，小时候住在开封。父亲在铁路工作，我和姐姐每天放学后到河边玩。' * 40])
def test_model_can_select_extraction_for_short_or_long_first_reply(monkeypatch, tmp_path, text):
    storage = Storage()
    response = proposal('extract', None, '您还记得放学后的什么事？')
    runtime, calls = harness(monkeypatch, tmp_path, storage, response, 'worker')
    result = asyncio.run(runtime.turn(storage, text, project_id='project', client_turn_id=str(uuid4()),
        on_delta=AsyncMock(), on_event=AsyncMock()))
    assert len(calls) == 1 and calls[0]['text'] == text
    assert calls[0]['interview_context']['source']['text'] == text
    assert calls[0]['interview_context']['opening_turn'] is True
    assert '放学后' in result['reply'] and '最早' not in result['reply']
    runtime._run_workspace_job.assert_awaited_once()
    assert runtime._run_workspace_job.call_args.kwargs['workspace_kwargs']['text'] == text
    runtime._workspace_extraction.assert_not_called()


def test_retry_reuses_saved_work_plan_without_model_or_workspace(monkeypatch, tmp_path):
    storage = Storage()
    runtime, calls = harness(monkeypatch, tmp_path, storage, proposal(), 'worker')
    turn = str(uuid4())
    storage.failed_commit = True
    with pytest.raises(RuntimeError, match='controlled lost database response'):
        asyncio.run(runtime.turn(storage, '我叫韩凤江', project_id='project', client_turn_id=turn))
    result = asyncio.run(runtime.turn(storage, '我叫韩凤江', project_id='project', client_turn_id=turn))
    assert result['conversation_saved'] and storage.rounds == 1 and len(calls) == 1
    runtime._run_workspace_job.assert_not_called()
    again = asyncio.run(runtime.turn(storage, '我叫韩凤江', project_id='project', client_turn_id=turn))
    assert again['cached'] and storage.rounds == 1 and len(calls) == 1


def test_returning_simple_reply_uses_same_harness_and_continues_current_memory(monkeypatch, tmp_path):
    storage = Storage({'name': '韩凤江', 'preferred_language': 'zh-CN'})
    storage.memories = lambda: [{'id': 'earlier', 'kind': 'agent',
        'content': 'Storyteller: 我记得小时候的花园。\nMemory Spark: 花园里有什么？'}]
    response = proposal(name=None, question='您还记得花园里的什么？')
    runtime, calls = harness(monkeypatch, tmp_path, storage, response, 'worker')
    result = asyncio.run(runtime.turn(storage, '想不起来了', project_id='project', client_turn_id=str(uuid4()), on_delta=AsyncMock()))
    assert len(calls) == 1 and calls[0]['interview_context']['opening_turn'] is False
    assert '花园' in result['reply'] and '最早' not in result['reply']
    assert storage.data['name'] == '韩凤江'
    runtime._run_workspace_job.assert_not_called()
