"""Controlled orchestration only: no native database, Temporal or providers."""
import asyncio
from copy import deepcopy
import threading
import time
from uuid import UUID, uuid4

import pytest

from apps.api.agent_storage import UserStorage
from scripts.issue14_progressive_readback import CASE_IDS, ProgressiveReadback
import scripts.issue14_subscription_runner as module


REVISION = '9895006f0aaec8425abb21a99f88e39a3a982c2f'


class Run:
    def __init__(self, seconds=10):
        self.run_id, self.source_revision = str(uuid4()), REVISION
        self.deadline = time.monotonic() + seconds
        self.reasons = []
        self.closed = False
        self.snapshot_changes = {}

    def remaining_seconds(self):
        return max(0, self.deadline - time.monotonic())

    def stop(self, reason):
        self.reasons.append(reason)

    def close(self):
        self.closed = True

    def snapshot(self):
        return {'run_id': self.run_id, 'source_revision': self.source_revision,
                'client_requests_reserved': 0, 'unresolved_requests': 0,
                'actual_upstream_provider_requests': None,
                'journal_durable': True, 'closed': self.closed,
                'stop_reason': self.reasons[0] if self.reasons else 'closed',
                'counted_boundary': 'client_to_existing_gateway_http_requests',
                'concurrency': 1, **self.snapshot_changes}


class Storage(UserStorage):
    def __init__(self, session, plan):
        self.session, self.plan, self.user_id = session, plan, plan['owner_id']
        self.sources = []
        self.drafts = []
        self.extracted = 0

    def memory_events(self, project):
        assert project == self.plan['project_id']
        value = {'project_id': project, 'sources': deepcopy(self.sources), 'events': [],
                 'completed_rounds': len(self.sources),
                 'processing': {'extracted_through': self.extracted, 'pending_inputs': 0}}
        if self.session.read_hook:
            self.session.read_hook(value)
        return value

    def saved_memoir_draft(self, project, language):
        assert (project, language) == (self.plan['project_id'], self.plan['language'])
        ordinal = len(self.sources)
        self.session.events.append(('readback', self.plan['case_id'], ordinal))
        draft = {'status': 'ready', 'covered_round': ordinal, 'milestone': ordinal,
            'revision': ordinal // 5, 'updating': False, 'error': None,
            'proposal_pending': False, 'preview': {'locale': language, 'text': self.sources[0]['text']},
            'milestones': [{'milestone': n, 'covered_round': n, 'state': 'completed',
                            'manuscript_revision': n // 5} for n in range(5, ordinal + 1, 5)],
            'progress': {'extraction': {'extracted_through': ordinal, 'pending_inputs': 0}},
            'sections': [{'id': 'chapter__first', 'chapter_id': 'chapter', 'fingerprint': 'a' * 64,
                          'revision': 1, 'content': self.sources[0]['text'], 'event_ids': ['saved-event'],
                          'source_refs': [{'source_id': self.sources[0]['id'], 'version': 1,
                                           'quote': self.sources[0]['text']}]}]}
        if self.session.draft_hook:
            self.session.draft_hook(draft)
        self.drafts.append(draft)
        return draft


class Session:
    def __init__(self, seconds=10):
        self.run = Run(seconds)
        self.case_ids = CASE_IDS
        self.case_plans = {case: {'case_id': case, 'owner_id': str(uuid4()),
            'project_id': str(uuid4()), 'language': case.rsplit('.', 1)[-1]} for case in CASE_IDS}
        self.bridges = {case: ProgressiveReadback(case_id=case, run_id=self.run.run_id,
            project_id=plan['project_id'], source_revision=REVISION) for case, plan in self.case_plans.items()}
        self.storages = {case: Storage(self, plan) for case, plan in self.case_plans.items()}
        self.runtime = self
        self.broker = self
        self.temporal_client = object()
        self.worker_transport = object()
        self.task_queue = 'canary-subscription-controlled'
        self.events, self.calls, self.active = [], [], None
        self.read_hook = self.draft_hook = self.turn_hook = self.close_hook = None
        self.finish_hook = None
        self.closed = False
        self.close_started = asyncio.Event()
        self.turn_delay = 0
        self.lane_outcome = {'status': 'finished', 'pending': False}
        self.pending_lanes = []

    def bridge_for_case(self, case):
        return self.bridges[case]

    def storage_for_case(self, case):
        self.events.append(('storage', case))
        return self.storages[case]

    def activate_round(self, case, ordinal):
        assert self.active is None
        self.active = case, ordinal
        self.events.append(('activate', case, ordinal))
        return self.bridges[case].before_round(case, ordinal)

    def finish_round(self):
        if self.finish_hook:
            self.finish_hook()
        self.events.append(('finish', *self.active))
        self.active = None

    async def turn(self, storage, text, **kwargs):
        case, ordinal = self.active
        assert storage is self.storages[case]
        assert kwargs['evaluation'] == self.bridges[case].before_round(case, ordinal)
        assert kwargs['project_id'] == storage.plan['project_id']
        assert kwargs['language'] == storage.plan['language']
        assert kwargs['conversation_text'] == text
        assert kwargs['source_kind'] == 'narrator_chat'
        assert kwargs['include_trajectory'] is True
        UUID(kwargs['client_turn_id'])
        assert text == self.bridges[case].driver_inputs()['rounds'][ordinal - 1]
        self.events.append(('turn', case, ordinal))
        self.calls.append((case, text, kwargs))
        if self.turn_delay:
            await asyncio.sleep(self.turn_delay)
        source_id = str(uuid4())
        storage.sources.append({'id': source_id, 'project_id': kwargs['project_id'],
            'language': kwargs['language'], 'kind': 'narrator_chat', 'status': 'active',
            'version': 1, 'sequence': ordinal, 'text': text})
        value = {'reply': 'Controlled response', 'accepted_source_id': source_id,
            'tasks': [], 'task_errors': [], 'trace': [],
            'trajectory': {'correlation': kwargs['evaluation'], 'steps': [],
                           'final': {'status': 'completed'}}}
        if self.turn_hook:
            answer = self.turn_hook(value)
            if hasattr(answer, '__await__'):
                await answer
        return value

    async def drain_once(self):
        self.events.append(('drain', *self.active))
        return []

    async def rpc(self, name, **kwargs):
        assert name == 'pending_memoir_lanes'
        assert kwargs == {'p_limit': 100}
        self.events.append(('pending', *self.active))
        return self.pending_lanes

    async def close(self):
        self.events.append(('close_started',))
        self.close_started.set()
        if self.close_hook:
            await self.close_hook()
        self.closed = True
        self.run.close()
        self.events.append(('closed',))


@pytest.fixture
def controlled(monkeypatch):
    allowed = []
    def verify(session):
        if not any(session is candidate for candidate in allowed):
            raise ValueError('session_unverified')
    monkeypatch.setattr(module, 'assert_owned_subscription_session', verify)
    async def lanes(client, broker, queue, *, single_attempt):
        assert client is broker.temporal_client
        assert queue == broker.task_queue and single_attempt is True
        case, ordinal = broker.active
        broker.events.append(('dispatch', case, ordinal))
        class Handle:
            id = f'controlled:{case}:{ordinal}'
            async def result(self):
                await asyncio.sleep(0)
                broker.storages[case].extracted = ordinal
                broker.events.append(('settled', case, ordinal))
                return deepcopy(broker.lane_outcome)
        return [Handle()]
    monkeypatch.setattr(module, 'dispatch_memoir_lanes_once', lanes)
    def create(**kwargs):
        session = Session(**kwargs)
        allowed.append(session)
        return session
    return create


def execute(session):
    return asyncio.run(module.SubscriptionProgressiveRunner(session).run())


def test_progress_keeps_completed_round_readbacks_and_cannot_mutate_run(controlled):
    session=controlled();seen=[]
    async def progress(value):
        seen.append(deepcopy(value))
        value['cases'].clear()
    result=asyncio.run(module.SubscriptionProgressiveRunner(session).run(progress=progress))
    assert result['status']=='completed'
    assert len(result['cases'])==2
    assert any(len(v['cases'][0]['rounds'])==5 and v['cases'][0]['checkpoints'] for v in seen)
    assert seen[-1]['status']=='completed'


def test_progress_failure_stops_before_next_round(controlled):
    session=controlled()
    def progress(value):
        if value['cases'][0]['rounds']:
            raise RuntimeError('synthetic private callback error')
    result=asyncio.run(module.SubscriptionProgressiveRunner(session).run(progress=progress))
    assert result['status']=='incomplete'
    assert len(result['cases'][0]['rounds'])==1
    assert result['output'] is None
    assert 'synthetic private' not in str(result)


def test_two_exact_original_fifteen_turn_cases_settle_serially(controlled, monkeypatch):
    from scripts.canonical_evaluation import CanonicalEvaluationDriver
    async def forbidden(*args, **kwargs):
        pytest.fail('The historical five-turn live driver must remain unused')
    monkeypatch.setattr(CanonicalEvaluationDriver, 'run_case', forbidden)
    session = controlled()
    result = execute(session)
    assert result['status'] == 'completed'
    assert result['evidence_mode'] == 'subscription_progressive'
    assert result['semantic_acceptance'] == 'human_review_required'
    assert result['live_ready'] is False
    assert len(session.calls) == 30
    assert len({call[2]['client_turn_id'] for call in session.calls}) == 30
    assert [call[0] for call in session.calls] == [CASE_IDS[0]] * 15 + [CASE_IDS[1]] * 15
    assert session.closed and result['cleanup']['session_closed'] is True
    assert len(result['output']) == 2
    for case in result['cases']:
        assert case['status'] == 'completed'
        assert [checkpoint['milestone'] for checkpoint in case['checkpoints']] == [5, 10, 15]
        assert case['checkpoints'][0]['draft']['sections'][0]['event_ids'] == ['saved-event']
        assert all(record['background_settled'] for record in case['rounds'])
        assert len(case['workflow_ids']) == 15
    for index, event in enumerate(session.events):
        if event[0] == 'activate' and index:
            assert session.events[index - 1][0] == 'finish' or event[2] == 1
        if event[0] == 'finish':
            assert session.events[index - 1] == ('pending', *event[1:])
    session.storages[CASE_IDS[0]].drafts[0]['sections'][0]['content'] = 'later mutation'
    assert result['cases'][0]['checkpoints'][0]['draft']['sections'][0]['content'] != 'later mutation'


def test_unverified_session_rejected_before_attributes_or_storage():
    class Unverified:
        def __getattribute__(self, name):
            pytest.fail('Unverified session was dereferenced')
    with pytest.raises(ValueError):
        module.SubscriptionProgressiveRunner(Unverified())


@pytest.mark.parametrize('mode', ['mock_only', 'guarded_live_canary', None, 'live'])
def test_no_historical_or_implicit_evidence_mode(controlled, mode):
    session = controlled()
    with pytest.raises(ValueError):
        module.SubscriptionProgressiveRunner(session, evidence_mode=mode)
    assert session.events == []


@pytest.mark.parametrize('mutation', [
    lambda s: s.case_plans.pop(CASE_IDS[1]),
    lambda s: s.case_plans[CASE_IDS[1]].update(owner_id=s.case_plans[CASE_IDS[0]]['owner_id']),
    lambda s: s.case_plans[CASE_IDS[1]].update(project_id=s.case_plans[CASE_IDS[0]]['project_id']),
    lambda s: s.case_plans[CASE_IDS[0]].update(owner_id='not-a-uuid'),
    lambda s: s.case_plans[CASE_IDS[0]].update(language='en-GB'),
    lambda s: s.case_plans[CASE_IDS[0]].update(case_id=CASE_IDS[1]),
    lambda s: setattr(s, 'task_queue', 'production'),
])
def test_malformed_case_plan_rejected_without_storage_access(controlled, mutation):
    session = controlled()
    mutation(session)
    with pytest.raises(ValueError):
        module.SubscriptionProgressiveRunner(session)
    assert not session.events and not session.calls


def test_foreign_storage_or_dirty_second_project_prevents_all_turns(controlled):
    for foreign in (True, False):
        session = controlled()
        if foreign:
            session.storages[CASE_IDS[1]].user_id = str(uuid4())
        else:
            session.storages[CASE_IDS[1]].sources.append({'id': 'existing'})
        result = execute(session)
        assert result['status'] == 'incomplete' and result['output'] is None
        assert not session.calls and session.closed


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(reply=''),
    lambda r: r.update(accepted_source_id=None),
    lambda r: r['trajectory']['correlation'].update(round_id='15'),
    lambda r: r['trajectory']['final'].update(status='pending'),
    lambda r: r['trajectory']['final'].update(error='private-error'),
    lambda r: r.update(task_errors=[{'message': 'private-error'}]),
    lambda r: r.update(tasks=[{'status': 'QUEUED'}]),
    lambda r: r.update(trace=[{'status': 'failed', 'detail': 'private-error'}]),
    lambda r: r['trajectory']['steps'].append({'action': 'workspace.failed', 'output': {'retryable': True}}),
    lambda r: r['trajectory']['steps'].append({'protocol_failed': True}),
])
def test_failed_or_pending_runtime_work_stops_without_background_dispatch(controlled, mutation):
    session = controlled()
    session.turn_hook = mutation
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert len(session.calls) == 1 and session.closed
    assert not any(event[0] == 'dispatch' for event in session.events)
    assert 'private-error' not in str(result)


def test_parser_failure_summary_survives_rejected_runtime_readback_without_private_payloads(controlled):
    session = controlled()
    captured = {}
    def mutate(value):
        captured['source_id'] = value['accepted_source_id']
        value['reply'] = 'REPLY_SECRET'
        value['trajectory']['private'] = 'TRAJECTORY_SECRET'
        value['trajectory']['steps'].append({'action': 'workspace.failed', 'output': {
            'error_type': 'JSONDecodeError', 'retryable': True,
            'parser_boundary': 'postgres_rest_json_record',
            'json_line': 3, 'json_column': 11, 'json_position': 78,
            'message': 'MESSAGE_SECRET', 'doc': 'DOCUMENT_SECRET',
            'frames': [{'filename': 'apps/api/codex_runtime.py', 'function': '_persist_workspace',
                        'line': 2451, 'source': 'SOURCE_SECRET', 'locals': {'key': 'LOCAL_SECRET'}}],
        }})
    session.turn_hook = mutate
    published = []
    result = asyncio.run(module.SubscriptionProgressiveRunner(session).run(progress=published.append))
    failed = result['cases'][0]['rounds'][0]
    assert failed['failure_summary'] == {
        'action': 'workspace.failed', 'error_type': 'JSONDecodeError', 'retryable': True,
        'parser_boundary': 'postgres_rest_json_record',
        'json_line': 3, 'json_column': 11, 'json_position': 78,
        'frames': [{'filename': 'apps/api/codex_runtime.py', 'function': '_persist_workspace', 'line': 2451}],
        'accepted_source_id': captured['source_id'],
    }
    assert failed['status'] == 'failed' and failed['background_settled'] is False
    assert 'reply' not in failed and 'trajectory' not in failed
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['failure_stage'] == 'runtime_readback'
    assert result['stop_reason'] == 'background_incomplete'
    assert published[-1]['cases'][0]['rounds'][0]['failure_summary'] == failed['failure_summary']
    assert len(session.calls) == 1
    assert not any(event[0] == 'dispatch' for event in session.events)
    for secret in ('REPLY_SECRET', 'TRAJECTORY_SECRET', 'MESSAGE_SECRET', 'DOCUMENT_SECRET',
                   'SOURCE_SECRET', 'LOCAL_SECRET'):
        assert secret not in str(result)


@pytest.mark.parametrize('mutation', [
    lambda v: v['trajectory']['correlation'].update(round_id='50'),
    lambda v: v['trajectory']['steps'][0].update(action='provider.failed'),
    lambda v: v['trajectory']['steps'][0]['output'].update(error_type='SECRET_ERROR'),
])
def test_failure_summary_does_not_trust_other_rounds_or_arbitrary_events(controlled, mutation):
    session = controlled()
    def mutate(value):
        value['trajectory']['steps'].append({'action': 'workspace.failed', 'output': {
            'error_type': 'JSONDecodeError', 'parser_boundary': 'postgres_rest_json_record'}})
        mutation(value)
    session.turn_hook = mutate
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert 'failure_summary' not in result['cases'][0]['rounds'][0]
    assert 'SECRET_ERROR' not in str(result)


def test_failure_summary_omits_invalid_accepted_source_id(controlled):
    session = controlled()
    def mutate(value):
        value['accepted_source_id'] = 'SOURCE_SECRET'
        value['trajectory']['steps'].append({'action': 'workspace.failed', 'output': {
            'error_type': 'JSONDecodeError', 'parser_boundary': 'SECRET_BOUNDARY',
            'json_line': True, 'json_column': 'COLUMN_SECRET', 'json_position': 2**100,
            'frames': [{'filename': '/private/SECRET/path.py', 'function': 'secret', 'line': 2}],
        }})
    session.turn_hook = mutate
    result = execute(session)
    assert result['cases'][0]['rounds'][0]['failure_summary'] == {
        'action': 'workspace.failed', 'error_type': 'JSONDecodeError'}
    assert 'SECRET' not in str(result)


def test_saturated_trajectory_terminal_parser_summary_survives_round_rejection(controlled):
    from apps.api.trajectory_evaluation import TrajectoryRecorder
    session = controlled()
    def mutate(value):
        recorder = TrajectoryRecorder(value['trajectory']['correlation'])
        for _ in range(recorder.max_steps):
            recorder.record('worker', 'synthetic.completed')
        failure = {'action': 'workspace.failed', 'error_type': 'JSONDecodeError', 'retryable': True,
                   'parser_boundary': 'postgres_rest_json_record',
                   'json_line': 2, 'json_column': 4, 'json_position': 12,
                   'message': 'MESSAGE_SECRET', 'doc': 'DOCUMENT_SECRET',
                   'frames': [{'filename': 'apps/api/codex_runtime.py', 'function': '_persist_workspace',
                               'line': 2500, 'source': 'SOURCE_SECRET'}]}
        assert recorder.record('application', 'workspace.failed', output=failure)['accepted'] is False
        recorder.finish('REPLY_SECRET', status='completed', state={'workspace_failure': failure})
        value['trajectory'] = recorder.payload()
        assert not any(step['action'] == 'workspace.failed' for step in value['trajectory']['steps'])
    session.turn_hook = mutate
    published = []
    result = asyncio.run(module.SubscriptionProgressiveRunner(session).run(progress=published.append))
    record = result['cases'][0]['rounds'][0]
    summary = record['failure_summary']
    assert summary['json_position'] == 12
    assert summary['frames'] == [{'filename': 'apps/api/codex_runtime.py',
                                  'function': '_persist_workspace', 'line': 2500}]
    assert summary['accepted_source_id'] == session.storages[CASE_IDS[0]].sources[0]['id']
    assert record['status'] == 'failed' and record['background_settled'] is False
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['stop_reason'] == 'background_incomplete'
    assert result['failure_stage'] == 'runtime_readback'
    assert len(session.calls) == 1 and not any(event[0] == 'dispatch' for event in session.events)
    assert published[-1]['cases'][0]['rounds'][0]['failure_summary'] == summary
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize('mutation', [
    lambda v: v['trajectory']['correlation'].update(round_id='50'),
    lambda v: v['trajectory']['final']['state']['workspace_failure'].update(action='provider.failed'),
    lambda v: v['trajectory']['final']['state']['workspace_failure'].update(error_type='SECRET_ERROR'),
])
def test_terminal_parser_evidence_keeps_exact_scope_and_type_guard(controlled, mutation):
    session = controlled()
    def mutate(value):
        value['trajectory']['limits'] = {'overflowed': True, 'dropped_steps': 1}
        value['trajectory']['final']['state'] = {'workspace_failure': {
            'action': 'workspace.failed', 'error_type': 'JSONDecodeError'}}
        mutation(value)
    session.turn_hook = mutate
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert 'failure_summary' not in result['cases'][0]['rounds'][0]
    assert 'SECRET_ERROR' not in str(result)


def test_terminal_parser_evidence_is_preferred_to_earlier_step_copy(controlled):
    session = controlled()
    def mutate(value):
        value['trajectory']['steps'].append({'action': 'workspace.failed', 'output': {
            'error_type': 'JSONDecodeError', 'json_position': 1}})
        value['trajectory']['final']['state'] = {'workspace_failure': {
            'action': 'workspace.failed', 'error_type': 'JSONDecodeError', 'json_position': 27}}
    session.turn_hook = mutate
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['cases'][0]['rounds'][0]['failure_summary']['json_position'] == 27


def test_terminal_workspace_failure_alone_cannot_be_accepted_as_completed(controlled):
    session = controlled()
    def mutate(value):
        value['trajectory']['final']['state'] = {'workspace_failure': {
            'action': 'workspace.failed', 'error_type': 'JSONDecodeError', 'json_position': 27}}
    session.turn_hook = mutate
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['stop_reason'] == 'background_incomplete'
    assert result['cases'][0]['rounds'][0]['failure_summary']['json_position'] == 27
    assert len(session.calls) == 1 and not any(event[0] == 'dispatch' for event in session.events)


def test_successful_runtime_receipts_do_not_add_failure_metadata(controlled):
    result = execute(controlled())
    assert result['status'] == 'completed'
    assert all('failure_summary' not in row for case in result['cases'] for row in case['rounds'])


READBACK_REJECTIONS = [
    ('result_shape', (), None),
    ('reply_type', ('reply',), []),
    ('reply_empty', ('reply',), '  '),
    ('accepted_source_type', ('accepted_source_id',), []),
    ('accepted_source_empty', ('accepted_source_id',), ''),
    ('trajectory_shape', ('trajectory',), []),
    ('correlation_shape', ('trajectory', 'correlation'), []),
    ('correlation_mismatch', ('trajectory', 'correlation', 'round_id'), 'SECRET_ROUND'),
    ('final_shape', ('trajectory', 'final'), []),
    ('final_status', ('trajectory', 'final', 'status'), 'SECRET_STATUS'),
    ('final_error', ('trajectory', 'final', 'error'), 'SECRET_ERROR'),
    ('task_errors', ('task_errors',), ['SECRET_ERROR']),
    ('tasks_shape', ('tasks',), None),
    ('task_shape', ('tasks',), ['SECRET_TASK']),
    ('task_status', ('tasks',), [{'status': 'SECRET_STATUS', 'id': 'SECRET_ID'}]),
    ('trace_shape', ('trace',), None),
    ('trace_entry_shape', ('trace',), ['SECRET_TRACE']),
    ('trace_status', ('trace',), [{'status': 'running', 'message': 'SECRET_MESSAGE'}]),
    ('steps_shape', ('trajectory', 'steps'), None),
    ('step_shape', ('trajectory', 'steps'), ['SECRET_STEP']),
    ('step_error', ('trajectory', 'steps'), [{'error': 'SECRET_ERROR'}]),
    ('step_protocol_failed', ('trajectory', 'steps'), [{'protocol_failed': True}]),
    ('step_status_shape', ('trajectory', 'steps'), [{'status': ['SECRET_STATUS']}]),
    ('step_status', ('trajectory', 'steps'), [{'status': 'failed'}]),
    ('step_action_status', ('trajectory', 'steps'), [{'action': 'SECRET_ACTION.retry_required'}]),
    ('step_output_error', ('trajectory', 'steps'), [{'output': {'error': 'SECRET_ERROR'}}]),
    ('step_output_retryable', ('trajectory', 'steps'), [{'output': {'retryable': True}}]),
    ('step_output_pending', ('trajectory', 'steps'), [{'output': {'pending': True}}]),
    ('step_output_status_shape', ('trajectory', 'steps'), [{'output': {'status': ['SECRET_STATUS']}}]),
    ('step_output_status', ('trajectory', 'steps'), [{'output': {'status': 'pending'}}]),
    ('limits_shape', ('trajectory', 'limits'), []),
    ('trajectory_overflow', ('trajectory', 'limits'), {'max_steps': 512, 'observed_steps': 512,
                                                     'dropped_steps': 19, 'overflowed': True}),
    ('trajectory_dropped_steps', ('trajectory', 'limits'), {'dropped_steps': 1}),
    ('final_state_shape', ('trajectory', 'final', 'state'), []),
    ('workspace_failure', ('trajectory', 'final', 'state'), {'workspace_failure': {'message': 'SECRET_ERROR'}}),
    ('task_error_count', ('trajectory', 'final', 'state'), {'task_error_count': 1}),
    ('task_statuses_shape', ('trajectory', 'final', 'state'), {'task_statuses': None}),
    ('final_task_status', ('trajectory', 'final', 'state'), {'task_statuses': ['SECRET_STATUS']}),
]


def _replace_readback(value, path, replacement):
    if not path:
        return deepcopy(replacement)
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = deepcopy(replacement)
    return value


@pytest.mark.parametrize('predicate,path,replacement', READBACK_REJECTIONS,
                         ids=[row[0] for row in READBACK_REJECTIONS])
def test_every_runtime_readback_rejection_retains_safe_predicate(controlled, predicate, path, replacement):
    from types import SimpleNamespace
    session = controlled()
    owned_turn = session.turn
    async def rejected_turn(*args, **kwargs):
        value = await owned_turn(*args, **kwargs)
        value['reply'] = 'SECRET_REPLY'
        value['trajectory']['arbitrary_metadata'] = 'SECRET_METADATA'
        return _replace_readback(value, path, replacement)
    session.runtime = SimpleNamespace(turn=rejected_turn)
    published = []
    result = asyncio.run(module.SubscriptionProgressiveRunner(session).run(progress=published.append))
    record = result['cases'][0]['rounds'][0]
    diagnostic = record['runtime_readback_diagnostic']
    assert diagnostic['schema_version'] == 'memoir-runtime-readback-diagnostic/1'
    assert diagnostic['predicate'] == predicate
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['failure_stage'] == 'runtime_readback'
    assert record['status'] == 'failed' and record['background_settled'] is False
    assert len(session.calls) == 1 and not any(event[0] == 'dispatch' for event in session.events)
    assert 'reply' not in record and 'trajectory' not in record
    assert published[-1]['cases'][0]['rounds'][0]['runtime_readback_diagnostic'] == diagnostic
    assert 'SECRET' not in str(result)
    assert len(str(diagnostic)) < 1500


@pytest.mark.parametrize('predicate,mutation', [
    ('trajectory_overflow', lambda v: v['trajectory'].update(limits={
        'max_steps': 512, 'observed_steps': 512, 'dropped_steps': 31, 'overflowed': True})),
    ('trace_status', lambda v: v.update(trace=[{'status': 'completed'}, {'status': 'running'}])),
    ('step_output_pending', lambda v: v['trajectory']['steps'].append({
        'action': 'SECRET_ACTION', 'phase': 'application', 'output': {'pending': True}})),
])
def test_successful_workspace_can_still_fail_strict_readback_with_a_specific_reason(controlled, predicate, mutation):
    session = controlled()
    def mutate(value):
        value['tasks'] = [{'status': 'SUCCEEDED'}]
        value['trajectory']['final']['state'] = {'task_statuses': ['completed'], 'task_error_count': 0}
        value['trajectory']['steps'].append({'phase': 'application', 'action': 'workspace.completed',
                                           'output': {'status': 'completed'}})
        mutation(value)
    session.turn_hook = mutate
    result = execute(session)
    diagnostic = result['cases'][0]['rounds'][0]['runtime_readback_diagnostic']
    assert diagnostic['predicate'] == predicate
    if predicate == 'trajectory_overflow':
        assert diagnostic['trajectory_limits'] == {
            'max_steps': 512, 'observed_steps': 512, 'dropped_steps': 31, 'overflowed': True}
    elif predicate == 'trace_status':
        assert diagnostic['collection'] == 'trace' and diagnostic['index'] == 1
        assert diagnostic['status'] == 'running'
    else:
        assert diagnostic['collection'] == 'steps' and diagnostic['index'] == 1
    assert result['stop_reason'] == 'background_incomplete'
    assert result['status'] == 'incomplete' and result['output'] is None
    assert 'failure_summary' not in result['cases'][0]['rounds'][0]
    assert 'SECRET' not in str(result)


def test_runtime_readback_diagnostic_omits_unknown_fields_unbounded_limits_and_identifiers(controlled):
    session = controlled()
    def mutate(value):
        value['trace'] = [{'status': 'SECRET_STATUS', 'id': 'SECRET_ID', 'message': 'SECRET_MESSAGE'}]
        value['trajectory']['limits'] = {'max_steps': True, 'observed_steps': 2**100,
            'dropped_steps': 'SECRET_LIMIT', 'overflowed': 'SECRET_FLAG', 'path': '/SECRET_PATH'}
    session.turn_hook = mutate
    result = execute(session)
    diagnostic = result['cases'][0]['rounds'][0]['runtime_readback_diagnostic']
    assert diagnostic['predicate'] == 'trace_status' and diagnostic['status'] == 'unrecognized'
    assert not diagnostic.get('trajectory_limits')
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize('trace_id,category', [('memoir-family-tree', 'memoir-family-tree'),
    ('memoir-author-timeline', 'memoir-author-timeline'), ('SECRET_TRACE_ID', 'other')])
def test_triggered_trace_keeps_fixed_status_and_known_component_only(controlled, trace_id, category):
    session = controlled()
    session.turn_hook = lambda value: value.update(trace=[{'id': trace_id, 'status': 'triggered',
                                                         'detail': 'SECRET_DETAIL'}])
    result = execute(session)
    diagnostic = result['cases'][0]['rounds'][0]['runtime_readback_diagnostic']
    assert diagnostic['predicate'] == 'trace_status'
    assert diagnostic['status'] == 'triggered' and diagnostic['trace_category'] == category
    assert result['stop_reason'] == 'background_incomplete'
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize('action,category', [('artifact.sync.failed', 'artifact'),
    ('workspace.failed', 'workspace'), ('workspace.family_recovery.failed', 'recovery'),
    ('protocol.failed', 'protocol'), ('codex.worker.failed', 'worker'), ('SECRET_ACTION.failed', 'other')])
def test_failed_step_keeps_only_fixed_action_category(controlled, action, category):
    session = controlled()
    session.turn_hook = lambda value: value['trajectory']['steps'].append({'action': action})
    result = execute(session)
    diagnostic = result['cases'][0]['rounds'][0]['runtime_readback_diagnostic']
    assert diagnostic['predicate'] == 'step_action_status'
    assert diagnostic['action_status'] == 'failed' and diagnostic['action_category'] == category
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize('empty', [[], (), {}, ''])
def test_empty_iterable_defaults_keep_historical_runtime_acceptance(empty):
    correlation = {'run_id': 'controlled', 'case_id': 'controlled', 'round_id': '1'}
    value = {'reply': 'Controlled reply', 'accepted_source_id': 'controlled-source',
        'tasks': empty, 'trace': empty,
        'trajectory': {'correlation': correlation, 'steps': empty,
                       'final': {'status': 'completed', 'state': {'task_statuses': empty}}}}
    assert module._runtime_readback(value, correlation)['reply'] == value['reply']
    value.pop('tasks'); value.pop('trace')
    value['trajectory'].pop('steps'); value['trajectory']['final'].pop('state')
    assert module._runtime_readback(value, correlation)['reply'] == value['reply']


def test_runtime_readback_exception_diagnostic_is_reprojected_before_receipt(controlled, monkeypatch):
    session = controlled()
    def rejected(*args):
        error = module.SubscriptionRunnerError('background_incomplete')
        error.readback_diagnostic = {'schema_version': 'SECRET_SCHEMA', 'predicate': 'trace_status',
            'collection': 'trace', 'index': 0, 'status': 'SECRET_STATUS', 'message': 'SECRET_MESSAGE',
            'accepted_source_id': 'SECRET_SOURCE', 'trajectory_limits': {'max_steps': 512, 'secret': 'SECRET_LIMIT'}}
        raise error
    monkeypatch.setattr(module, '_runtime_readback', rejected)
    result = execute(session)
    diagnostic = result['cases'][0]['rounds'][0]['runtime_readback_diagnostic']
    assert diagnostic['schema_version'] == 'memoir-runtime-readback-diagnostic/1'
    assert diagnostic['predicate'] == 'trace_status'
    assert diagnostic['trajectory_limits'] == {'max_steps': 512}
    assert 'SECRET' not in str(result)


CANONICAL_REJECTIONS = [
    ('state_shape', (), []), ('project_mismatch', ('project_id',), 'SECRET_PROJECT'),
    ('completed_rounds', ('completed_rounds',), 0), ('processing_shape', ('processing',), []),
    ('extracted_through', ('processing', 'extracted_through'), 0),
    ('pending_inputs', ('processing', 'pending_inputs'), 1), ('sources_shape', ('sources',), None),
    ('source_count', ('sources',), []), ('source_shape', ('sources', 0), 'SECRET_SOURCE'),
    ('source_id', ('sources', 0, 'id'), 'SECRET_SOURCE'),
    ('source_text', ('sources', 0, 'text'), 'SECRET_TEXT'),
    ('source_project', ('sources', 0, 'project_id'), 'SECRET_PROJECT'),
    ('source_language', ('sources', 0, 'language'), 'SECRET_LANGUAGE'),
    ('source_kind', ('sources', 0, 'kind'), 'SECRET_KIND'),
    ('source_status', ('sources', 0, 'status'), 'SECRET_STATUS'),
    ('source_version', ('sources', 0, 'version'), True),
    ('source_sequence', ('sources', 0, 'sequence'), 2),
]


@pytest.mark.parametrize('predicate,path,replacement', CANONICAL_REJECTIONS,
                         ids=[row[0] for row in CANONICAL_REJECTIONS])
def test_canonical_readback_failures_retain_only_fixed_comparison_reason(controlled, predicate, path, replacement):
    session = controlled()
    storage = session.storages[CASE_IDS[0]]
    read = storage.memory_events
    def mutate(project):
        value = read(project)
        return _replace_readback(value, path, replacement) if storage.sources else value
    storage.memory_events = mutate
    result = execute(session)
    diagnostic = result['cases'][0]['rounds'][0]['canonical_readback_diagnostic']
    assert diagnostic['predicate'] == predicate and diagnostic['boundary'] == 'canonical'
    assert result['stop_reason'] == 'readback_incomplete'
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['failure_stage'] == 'canonical_readback'
    assert 'SECRET' not in str(result)


CHECKPOINT_REJECTIONS = [
    ('draft_shape', (), []), ('draft_status', ('status',), 'SECRET_STATUS'),
    ('updating', ('updating',), True), ('error', ('error',), 'SECRET_ERROR'),
    ('proposal_pending', ('proposal_pending',), True), ('covered_round', ('covered_round',), 4),
    ('milestone', ('milestone',), 4), ('revision', ('revision',), True),
    ('progress_shape', ('progress',), []), ('extraction_shape', ('progress', 'extraction'), []),
    ('extracted_through', ('progress', 'extraction', 'extracted_through'), 4),
    ('pending_inputs', ('progress', 'extraction', 'pending_inputs'), 1),
    ('preview_shape', ('preview',), []), ('preview_locale', ('preview', 'locale'), 'SECRET_LOCALE'),
    ('preview_text_type', ('preview', 'text'), []), ('preview_text_empty', ('preview', 'text'), ' '),
    ('milestones_shape', ('milestones',), None), ('milestone_count', ('milestones',), []),
    ('milestone_shape', ('milestones', 0), 'SECRET_MILESTONE'),
    ('milestone_status', ('milestones', 0, 'state'), 'SECRET_STATUS'),
    ('milestone_ordinal', ('milestones', 0, 'milestone'), 4),
    ('milestone_covered_round', ('milestones', 0, 'covered_round'), 4),
    ('sections_shape', ('sections',), None), ('sections_empty', ('sections',), []),
]


@pytest.mark.parametrize('predicate,path,replacement', CHECKPOINT_REJECTIONS,
                         ids=[row[0] for row in CHECKPOINT_REJECTIONS])
def test_saved_checkpoint_failures_retain_only_fixed_comparison_reason(controlled, predicate, path, replacement):
    session = controlled()
    storage = session.storages[CASE_IDS[0]]
    read = storage.saved_memoir_draft
    storage.saved_memoir_draft = lambda *args: _replace_readback(read(*args), path, replacement)
    result = execute(session)
    record = result['cases'][0]['rounds'][-1]
    diagnostic = record['checkpoint_readback_diagnostic']
    assert diagnostic['predicate'] == predicate and diagnostic['boundary'] == 'checkpoint'
    assert record['round'] == 5 and len(session.calls) == 5
    assert result['stop_reason'] == 'checkpoint_incomplete'
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['failure_stage'] == 'checkpoint_readback'
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize('boundary,function_name', [('runtime', '_runtime_readback'),
    ('canonical', '_canonical_state'), ('checkpoint', '_saved_checkpoint')])
def test_unexpected_readback_exception_records_fixed_category_and_reraises(boundary, function_name, monkeypatch):
    record = {}
    error = RuntimeError('SECRET_EXCEPTION_TEXT')
    def broken(*args): raise error
    with pytest.raises(RuntimeError) as caught:
        module._readback_call(record, boundary, broken)
    assert caught.value is error
    assert record[f'{boundary}_readback_diagnostic'] == {
        'schema_version': f'memoir-{boundary}-readback-diagnostic/1',
        'boundary': boundary, 'predicate': 'helper_exception'}
    assert 'SECRET' not in str(record)


def test_duplicate_accepted_sources_have_fixed_canonical_predicate():
    record = {}
    value = {'project_id': 'controlled-project', 'completed_rounds': 2,
        'processing': {'extracted_through': 2, 'pending_inputs': 0}, 'sources': [{}, {}]}
    with pytest.raises(module.SubscriptionRunnerError, match='readback_incomplete'):
        module._readback_call(record, 'canonical', module._canonical_state,
            value, {'project_id': 'controlled-project'}, ['SECRET_SOURCE', 'SECRET_SOURCE'])
    assert record['canonical_readback_diagnostic']['predicate'] == 'accepted_source_uniqueness'
    assert 'SECRET' not in str(record)


def test_initial_canonical_readback_failure_is_retained_before_any_round(controlled):
    session = controlled()
    session.read_hook = lambda value: value.update(processing=None)
    result = execute(session)
    assert result['canonical_readback_diagnostic']['predicate'] == 'processing_shape'
    assert result['failure_stage'] == 'initial_readback'
    assert result['status'] == 'incomplete' and result['output'] is None
    assert not session.calls


@pytest.mark.parametrize('predicate,outcome', [
    ('outcome_shape', None), ('outcome_status', {'status': 'SECRET_STATUS'}),
    ('outcome_pending', {'status': 'finished', 'pending': True}),
    ('outcome_error', {'status': 'finished', 'error': 'SECRET_ERROR'}),
    ('outcome_retryable', {'status': 'finished', 'retryable': True}),
    ('outcome_attempt', {'status': 'finished', 'attempt': 2}),
])
def test_settlement_validation_retains_fixed_rejection_without_outcome_data(controlled, predicate, outcome):
    session = controlled()
    session.lane_outcome = outcome
    result = execute(session)
    diagnostic = result['cases'][0]['rounds'][0]['settlement_readback_diagnostic']
    assert diagnostic['predicate'] == predicate
    assert diagnostic['collection'] == 'handles' and diagnostic['index'] == 0
    assert result['stop_reason'] == 'lane_incomplete'
    assert result['status'] == 'incomplete' and result['output'] is None
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize('pending,predicate', [(None, 'pending_shape'), (['SECRET_WORKFLOW'], 'pending_lanes')])
def test_background_drain_validation_retains_fixed_rejection(controlled, pending, predicate):
    session = controlled()
    session.pending_lanes = pending
    result = execute(session)
    diagnostic = result['cases'][0]['rounds'][0]['settlement_readback_diagnostic']
    assert diagnostic['predicate'] == predicate
    if predicate == 'pending_lanes': assert diagnostic['count'] == 1
    assert result['stop_reason'] == 'background_incomplete'
    assert result['status'] == 'incomplete' and result['output'] is None
    assert 'SECRET' not in str(result)


def test_bad_lane_handle_id_retains_fixed_reason_without_workflow_id(controlled, monkeypatch):
    from types import SimpleNamespace
    session = controlled()
    async def bad_lanes(*args, **kwargs): return [SimpleNamespace(id=[])]
    monkeypatch.setattr(module, 'dispatch_memoir_lanes_once', bad_lanes)
    result = execute(session)
    assert result['cases'][0]['rounds'][0]['settlement_readback_diagnostic']['predicate'] == 'handle_id'
    assert result['stop_reason'] == 'lane_incomplete'


def test_final_case_unavailable_observation_retains_fixed_reason(controlled):
    session = controlled()
    runner = module.SubscriptionProgressiveRunner(session)
    runner._bridges[CASE_IDS[0]].observation = lambda value: {'output': None, 'metadata': {'private': 'SECRET'}}
    result = asyncio.run(runner.run())
    record = result['cases'][0]['rounds'][-1]
    assert record['case_readback_diagnostic']['predicate'] == 'observation_unavailable'
    assert result['stop_reason'] == 'readback_incomplete'
    assert result['status'] == 'incomplete' and result['output'] is None
    assert 'SECRET' not in str(result)


@pytest.mark.parametrize('lane', [
    {'status': 'retry_required'}, {'status': 'failed'}, {'status': 'cancelled'},
    {'status': 'finished', 'pending': True}, {'status': 'finished', 'pending': 1},
    {'status': 'finished', 'error': 'private-error'}, None,
])
def test_failed_or_unsettled_lane_is_fatal(controlled, lane):
    session = controlled()
    session.lane_outcome = lane
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert len(session.calls) == 1 and session.closed
    assert not any(event[0] == 'finish' for event in session.events)
    assert 'private-error' not in str(result)


def test_bookkeeping_pending_work_and_unsettled_worker_block_next_scope(controlled):
    for worker in (True, False):
        session = controlled()
        if worker:
            def fail():
                raise RuntimeError('private-error')
            session.finish_hook = fail
        else:
            session.pending_lanes = ['unsettled']
        result = execute(session)
        assert result['status'] == 'incomplete' and len(session.calls) == 1
        assert session.closed and 'private-error' not in str(result)


@pytest.mark.parametrize('mutation', [
    lambda v: v.update(completed_rounds=0),
    lambda v: v.update(project_id=str(uuid4())),
    lambda v: v['processing'].update(extracted_through=0),
    lambda v: v['processing'].update(pending_inputs=1),
    lambda v: v['sources'][0].update(text='replaced original'),
    lambda v: v['sources'][0].update(language='wrong'),
])
def test_round_readback_mismatch_blocks_later_turns(controlled, mutation):
    session = controlled()
    def mutate_nonempty(value):
        if value['sources']:
            mutation(value)
    session.read_hook = mutate_nonempty
    result = execute(session)
    assert result['status'] == 'incomplete' and len(session.calls) == 1
    assert session.closed


@pytest.mark.parametrize('mutation', [
    lambda d: d.update(status='stale'), lambda d: d.update(updating=True),
    lambda d: d.update(proposal_pending=True), lambda d: d.update(covered_round=4),
    lambda d: d['progress']['extraction'].update(pending_inputs=1),
])
def test_pending_checkpoint_stops_at_five(controlled, mutation):
    session = controlled()
    session.draft_hook = mutation
    result = execute(session)
    assert result['status'] == 'incomplete' and len(session.calls) == 5
    assert result['output'] is None and session.closed


def test_partial_saved_checkpoints_survive_content_free_failure(controlled):
    session = controlled()
    def fail(value):
        if len(session.calls) == 6:
            raise RuntimeError('secret provider body')
    session.turn_hook = fail
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['cases'][0]['checkpoints'][0]['milestone'] == 5
    assert result['cases'][0]['rounds'][-1]['status'] == 'failed'
    assert 'secret provider body' not in str(result)
    assert session.run.reasons and session.closed


def test_structurally_invalid_saved_readback_prevents_second_case(controlled):
    session = controlled()
    def alter_same_fingerprint(draft):
        if draft['milestone'] == 10:
            draft['sections'][0]['content'] = 'Inconsistent saved text'
    session.draft_hook = alter_same_fingerprint
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['cases'][0]['status'] == 'incomplete'
    assert result['cases'][1]['status'] == 'not_started'
    assert len(session.calls) == 15 and session.closed


def test_absolute_total_deadline_does_not_reset_at_each_round(controlled):
    session = controlled(seconds=.09)
    session.turn_delay = .025
    deadline = session.run.deadline
    result = execute(session)
    assert result['status'] == 'incomplete' and result['stop_reason'] == 'deadline_exceeded'
    # Setup is included in the same absolute deadline. A loaded machine may
    # correctly expire before its first turn; that must not make the test flaky.
    assert 0 <= len(session.calls) < 6
    assert session.run.deadline == deadline and time.monotonic() >= deadline
    assert session.closed and result['output'] is None


def test_expired_run_never_reads_storage_or_dispatches(controlled):
    session = controlled(seconds=-1)
    result = execute(session)
    assert result['status'] == 'incomplete' and not session.calls
    assert not any(event[0] == 'storage' for event in session.events)
    assert session.closed


def test_cancellation_waits_for_current_storage_read_and_owned_cleanup(controlled):
    async def check():
        session = controlled()
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def block(value):
            started.set()
            release.wait(3)
            finished.set()
        session.read_hook = block
        closing_release = asyncio.Event()
        async def close():
            assert finished.is_set()
            await closing_release.wait()
        session.close_hook = close
        task = asyncio.create_task(module.SubscriptionProgressiveRunner(session).run())
        while not started.is_set():
            await asyncio.sleep(.001)
        task.cancel()
        await asyncio.sleep(.02)
        assert not task.done() and not session.close_started.is_set()
        assert session.run.reasons == ['send_interrupted_or_failed']
        release.set()
        await session.close_started.wait()
        task.cancel()
        await asyncio.sleep(.01)
        assert not task.done()
        closing_release.set()
        result = await task
        assert result['status'] == 'incomplete' and result['output'] is None
        assert session.closed and not session.calls
    asyncio.run(check())


def test_cleanup_failure_invalidates_otherwise_complete_result(controlled):
    session = controlled()
    async def fail():
        raise RuntimeError('private-error')
    session.close_hook = fail
    result = execute(session)
    assert len(session.calls) == 30
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['cleanup']['session_closed'] is False
    assert 'private-error' not in str(result)


def test_runner_is_one_shot_and_revalidates_session_before_execution(controlled, monkeypatch):
    session = controlled()
    runner = module.SubscriptionProgressiveRunner(session)
    assert asyncio.run(runner.run())['status'] == 'completed'
    with pytest.raises(ValueError):
        asyncio.run(runner.run())
    assert len(session.calls) == 30
    other = controlled()
    runner = module.SubscriptionProgressiveRunner(other)
    def revoked(value):
        raise ValueError('session_unverified')
    monkeypatch.setattr(module, 'assert_owned_subscription_session', revoked)
    with pytest.raises(ValueError, match='session_unverified'):
        asyncio.run(runner.run())
    assert not other.events


@pytest.mark.parametrize('mutation', [
    lambda s: s.case_plans[CASE_IDS[0]].update(owner_id=str(uuid4())),
    lambda s: setattr(s, 'task_queue', 'production'),
    lambda s: setattr(s.run, 'run_id', str(uuid4())),
    lambda s: setattr(s.run, 'source_revision', '1' * 40),
])
def test_session_drift_after_construction_denies_before_storage(controlled, mutation):
    session = controlled()
    runner = module.SubscriptionProgressiveRunner(session)
    mutation(session)
    with pytest.raises(ValueError):
        asyncio.run(runner.run())
    assert not session.events and not session.calls


@pytest.mark.parametrize('changes', [
    {'unresolved_requests': 1}, {'journal_durable': False}, {'closed': False},
    {'stop_reason': 'requests_limit'}, {'run_id': 'wrong'}, {'source_revision': '1' * 40},
    {'counted_boundary': 'provider'}, {'concurrency': 2},
])
def test_terminal_accounting_cannot_promote_failed_or_mismatched_run(controlled, changes):
    session = controlled()
    session.run.snapshot_changes = changes
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert session.closed and len(session.calls) == 30
    assert all(case['observation']['output'] is None for case in result['cases'])


def test_cancelled_turn_is_joined_before_owned_cleanup(controlled):
    async def check():
        session = controlled()
        started, settled = asyncio.Event(), asyncio.Event()
        async def block(value):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(.01)
                settled.set()
        async def close():
            assert settled.is_set()
        session.turn_hook, session.close_hook = block, close
        task = asyncio.create_task(module.SubscriptionProgressiveRunner(session).run())
        await started.wait()
        task.cancel()
        result = await task
        assert result['status'] == 'incomplete' and result['stop_reason'] == 'cancelled'
        assert len(session.calls) == 1 and session.closed and settled.is_set()
        assert not any(event[0] == 'dispatch' for event in session.events)
    asyncio.run(check())


@pytest.mark.parametrize('exception_type', [RuntimeError, module.SubscriptionRunnerError])
def test_exception_text_is_never_an_error_reason(controlled, exception_type):
    session = controlled()
    def fail(value):
        raise exception_type('private provider secret')
    session.turn_hook = fail
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert 'private provider secret' not in str(result)


@pytest.mark.parametrize('expires', [False, True])
def test_actual_shared_ledger_stop_vocabulary_and_terminal_snapshot(controlled, tmp_path, expires):
    from scripts.issue14_subscription_transport import SubscriptionLimits, SubscriptionRun
    session = controlled()
    session.run = SubscriptionRun.create(reservation_root=tmp_path, run_id=session.run.run_id,
        source_revision=REVISION, limits=SubscriptionLimits(max_requests=10,
            max_elapsed_seconds=.01 if expires else 10))
    if expires:
        time.sleep(.02)
    result = execute(session)
    assert result['status'] == ('incomplete' if expires else 'completed')
    assert result['request_accounting']['closed'] is True
    assert result['request_accounting']['journal_durable'] is True
    assert result['request_accounting']['client_requests_reserved'] == 0
    if expires:
        assert result['stop_reason'] == 'deadline_exceeded'
        assert result['request_accounting']['stop_reason'] == 'elapsed_limit'
        assert not session.calls


def test_failure_diagnostics_name_only_the_fixed_stage_and_safe_class(controlled):
    session = controlled()
    def fail(_value):
        raise RuntimeError('private prompt credential exception detail')
    session.turn_hook = fail
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert result['failure_stage'] == 'collector_turn'
    assert result['failure_class'] == 'runtime_error'
    assert 'private prompt credential exception detail' not in str(result)
    assert session.closed
