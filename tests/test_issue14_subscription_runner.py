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
