"""Actual turn orchestration with synthetic storage and model activity."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from apps.api.codex_runtime import CodexRuntime
from apps.api.lifetime_memory_runtime import LifetimePublicationContext
from test_lifetime_memory_engine import FENCE, IDENTITY, TEXT, fixture, valid_reply


class Storage:
    user_id = str(IDENTITY.owner_id)

    def __init__(self):
        self.source = {'id': str(uuid4()), 'version': 1, 'sequence': 1,
                       'text': TEXT, 'language': 'en-AU', 'kind': 'narrator_chat', 'status': 'active'}

    def story_entitlement(self):
        return None

    def profile(self):
        return {'preferred_language': 'en-AU'}

    def accept_interview_turn(self, *args, **kwargs):
        return {'source': deepcopy(self.source), 'sequence': 1, 'photo_context': []}

    def lifetime_rpc(self, name, **kwargs):
        if name == 'resolve_lifetime_conversation':
            return {'outcome': 'resolved', **IDENTITY.model_dump(mode='json')}
        if name == 'capture_lifetime_fence':
            return FENCE.model_dump(mode='json')
        if name == 'validate_lifetime_replay_input':
            return False
        if name in {'read_lifetime_reply', 'read_lifetime_checkpoint', 'claim_lifetime_memory_obligation',
                    'read_lifetime_policy_review'}:
            return None
        if name == 'read_lifetime_policy_status':
            return {'pending': False}
        if name == 'read_lifetime_interview_context':
            return {'historical_news': {},
                    'has_accepted_narration': False, 'events': [], 'photo_context': []}
        if name == 'read_lifetime_tail':
            return {'records': [], 'tombstones': [], 'complete': True}
        if name == 'commit_lifetime_turn':
            return {'fence': FENCE.model_dump(mode='json'), 'interview': {'plan': kwargs['p_plan']}}
        raise AssertionError(f'Unexpected storage call: {name}')


class Lease:
    lease_token = str(FENCE.lease_token)

    async def io(self, operation, *args, **kwargs):
        return operation(*args, **kwargs)


@pytest.mark.parametrize('execution', ['worker', 'local'])
@pytest.mark.parametrize('streaming', [True, False])
@pytest.mark.parametrize('thinking,drafts', [(True,True),(True,False),(False,True),(False,False)])
def test_model_tool_activity_and_question_pool_share_the_same_turn_trace(tmp_path, monkeypatch, execution, streaming, thinking, drafts):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '1' if thinking else '0')
    monkeypatch.setenv('MEMORY_SPARK_SHOW_DRAFT_UPDATES', '1' if drafts else '0')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'synthetic-byte-bpe')
    monkeypatch.delenv('MEMORY_SPARK_CODEX_WORKER_URL', raising=False)
    storage = Storage()
    runtime = CodexRuntime(home_root=tmp_path, worker_url='http://controlled.invalid' if execution == 'worker' else None)
    packet = json.loads(fixture()[0].packet)
    monkeypatch.setattr('apps.api.lifetime_memory_service.LifetimeMemoryService.assemble', lambda self, **kwargs: packet)
    monkeypatch.setattr('apps.api.recall.storage_recall_status', lambda *args: {'payment_required': False})

    @asynccontextmanager
    async def lease(*args, **kwargs):
        yield Lease()

    monkeypatch.setattr(runtime, '_storage_lease', lease)
    calls, events, deltas = [], [], []

    async def collector(**kwargs):
        calls.append(kwargs)
        if kwargs.get('on_event'):
            for status in ('running', 'completed'):
                await kwargs['on_event']({'type': 'codex_activity', 'data': {
                    'id': 'tool-1', 'kind': 'tool_call', 'label': 'read_file', 'status': status}})
        if kwargs.get('on_delta'):
            await kwargs['on_delta'](valid_reply())
        return {'thread_id': 'controlled-thread', 'reply': valid_reply()}

    monkeypatch.setattr(runtime, '_worker_turn', collector)
    monkeypatch.setattr('apps.api.lifetime_memory_engine.run_governed_collector', collector)

    async def run():
        publication = LifetimePublicationContext()
        async def event(value):
            events.append(deepcopy(value))
        async def delta(value):
            deltas.append(value)
        try:
            return await runtime.turn(storage, TEXT, project_id='p', client_turn_id=str(uuid4()),
                                      lifetime_context=publication, on_event=event if streaming else None,
                                      on_delta=delta if streaming else None)
        finally:
            await publication.close()

    result = asyncio.run(run())
    assert len(calls) == 1
    assert result['reply'].endswith('Where did you carry it?')
    if streaming:
        assert result['reply'] == ''.join(deltas)
    if not thinking:
        assert result['trace'] == []
        assert not any(event['type'] == 'progress' for event in events)
        if streaming:
            assert any(event['type'] == 'conversation_saved' for event in events)
        return
    if streaming:
        assert [event['data']['status'] for event in events
                if event['type'] == 'progress' and event['data']['id'] == 'tool-1'] == ['running', 'completed']
    activity = next((step for step in result['trace'] if step['id'] == 'tool-1'), None)
    assert activity is not None, 'Tool calls disappeared from thinking steps; only the question pool remains'
    assert activity['status'] == 'completed'
    assert [step['id'] for step in result['trace']] == ['memory-context', 'collector-call', 'tool-1', 'save', 'question-pool']
    assert all(step['status'] == 'completed' for step in result['trace'])
    pool = next(step for step in result['trace'] if step['id'] == 'question-pool')
    assert 'question_pool' not in pool
    if streaming:
        saved = next(event['data'] for event in events if event['type'] == 'conversation_saved')
        assert activity in saved['trace'] and pool in saved['trace']
