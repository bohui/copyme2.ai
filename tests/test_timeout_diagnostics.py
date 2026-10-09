"""Synthetic timeout evidence only; no provider, database or native process."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from scripts import issue14_subscription_session as sessions
from scripts import memoir_fifty_browser as browser
from scripts.issue14_subscription_transport import (
    SubscriptionLimits, SubscriptionRun, SubscriptionStopped, SubscriptionTransport,
)


def test_pure_plan_exposes_native_deadlines_without_importing_worker(monkeypatch):
    from scripts.run_issue14_subscription_evaluation import build_plan
    monkeypatch.setitem(sys.modules, 'apps.api.codex_worker_service', None)
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_TIMEOUT', '239')
    binary = Path(sys.executable).resolve()
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    value = build_plan(run_id=str(uuid4()), source_revision='a' * 40,
        codex_binary=binary, codex_sha256=digest, temporal_binary=binary,
        temporal_sha256=digest, max_client_requests=160, max_elapsed_seconds=1800)
    assert value['worker_deadlines'] == {
        'scope': 'whole_worker_execution', 'timeout_override_inherited': False,
        'seconds_by_role': {'collector': 120, 'organiser': 120, 'memory_context': 120,
            'author_timeline': 120, 'workspace': 240,
            'composer': {'index': 240, 'prepare': 240, 'draft': 600, 'review': 240}},
    }
    assert value['execution_started'] is False


def test_plan_defaults_agree_with_all_enforced_worker_roles(tmp_path, monkeypatch):
    from apps.api.codex_timeout_policy import native_worker_deadlines
    from apps.api.codex_worker_service import CodexWorker
    from scripts.run_isolated_check import offline_environment
    monkeypatch.delenv('MEMORY_SPARK_CODEX_WORKER_TIMEOUT', raising=False)
    worker = CodexWorker(home_root=tmp_path, api_key='synthetic-token')
    for role, seconds in native_worker_deadlines()['seconds_by_role'].items():
        if role == 'composer':
            for phase, timeout in seconds.items():
                assert worker._execution_timeout(role, phase) == timeout
        else:
            assert worker._execution_timeout(role) == seconds
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_TIMEOUT', '239')
    assert 'MEMORY_SPARK_CODEX_WORKER_TIMEOUT' not in offline_environment(tmp_path)


@pytest.fixture
def diagnostic_owner(monkeypatch):
    from scripts.memoir_fifty_readback import FiftyReadback, case_plans_for_run
    run_id = str(uuid4())
    plans = case_plans_for_run(run_id)
    case = next(iter(plans))
    bridge = FiftyReadback(case_id=case, run_id=run_id, project_id=plans[case]['project_id'],
        source_revision='a' * 40)
    ids = bridge.before_round(case, 1)
    record = {'case_id': case, 'round': 1, 'role': 'collector', 'correlation': ids,
        'status': 'failed', 'failure_stage': 'worker_turn', 'failure_class': 'timeout',
        'execution_timeout_seconds': 120, 'elapsed_ms': 120050,
        'client_requests_before': 28, 'client_requests_after': 31,
        'completed_responses_before': 28, 'completed_responses_after': 30,
        'exception': 'PRIVATE_EXCEPTION', 'provider': {'secret': 'PRIVATE_PROVIDER'}}
    owner = SimpleNamespace(_plans=plans, _profile=SimpleNamespace(rounds=50),
        _worker_records=[record], _worker_diagnostic_contexts=[(record, deepcopy(ids), 'collector')],
        bridge_for_case=lambda case: bridge)
    monkeypatch.setattr(sessions, 'assert_owned_subscription_session', lambda value:
        None if value is owner else pytest.fail('Foreign synthetic owner'))
    return owner, ids, record


def test_owned_timeout_projection_is_detached_and_omits_hostile_metadata(diagnostic_owner):
    owner, ids, record = diagnostic_owner
    cause = sessions.OwnedSubscriptionSession.worker_failure_for(owner, ids)
    assert cause['request_accounting'] == {'started': 3, 'completed': 2, 'unresolved': 1}
    assert cause['correlation'] == ids and cause['execution_timeout_seconds'] == 120
    assert 'PRIVATE' not in json.dumps(cause)
    cause['correlation']['run_id'] = 'changed'
    assert record['correlation'] == ids


@pytest.mark.parametrize('mutation', [
    lambda ids, r: r['correlation'].update(run_id=str(uuid4())),
    lambda ids, r: r['correlation'].update(round_id='2'),
    lambda ids, r: r['correlation'].update(application_revision='b' * 40),
    lambda ids, r: r.update(case_id='foreign'),
    lambda ids, r: r.update(round=True),
    lambda ids, r: r.update(role=[]),
    lambda ids, r: r.update(role='PRIVATE_ROLE'),
    lambda ids, r: r.update(status='completed'),
    lambda ids, r: r.update(failure_stage='PRIVATE_STAGE'),
    lambda ids, r: r.update(failure_class='cancelled'),
    lambda ids, r: r.update(execution_timeout_seconds=True),
    lambda ids, r: r.update(execution_timeout_seconds=float('nan')),
    lambda ids, r: r.update(execution_timeout_seconds=601),
    lambda ids, r: r.update(elapsed_ms=-1),
    lambda ids, r: r.update(elapsed_ms=True),
    lambda ids, r: r.update(client_requests_after=27),
    lambda ids, r: r.update(completed_responses_after=32),
    lambda ids, r: r.update(completed_responses_before=True),
    lambda ids, r: r.update(timeout_origin='PRIVATE_ORIGIN'),
    lambda ids, r: r.update(timeout_origin='worker_execution_deadline', worker_deadline_expired=False),
    lambda ids, r: r.update(worker_deadline_expired='true'),
])
def test_timeout_projection_rejects_mismatched_or_malformed_local_records(diagnostic_owner, mutation):
    owner, ids, record = diagnostic_owner
    owner._worker_records = [deepcopy(record)]
    owner._worker_diagnostic_contexts = [(owner._worker_records[0], deepcopy(ids), 'collector')]
    mutation(ids, owner._worker_records[0])
    assert sessions.OwnedSubscriptionSession.worker_failure_for(owner, ids) is None


def test_timeout_projection_inspects_only_last_sixteen_records(diagnostic_owner):
    owner, ids, record = diagnostic_owner
    owner._worker_records = [record] + [{} for _ in range(16)]
    assert sessions.OwnedSubscriptionSession.worker_failure_for(owner, ids) is None


def test_failure_future_cannot_bypass_success_admission_check():
    async def scenario():
        future = asyncio.get_running_loop().create_future()
        future.set_result({'ok': True, 'value': {'reply': 'private'}})
        def check():
            raise SubscriptionStopped('send_interrupted_or_failed')
        api = SimpleNamespace(_armed={'case_id': 'synthetic', 'ordinal': 1, 'future': future}, _check=check)
        with pytest.raises(SubscriptionStopped):
            await browser.OwnedFiftyBrowserAPI.wait_turn(api, 'synthetic', 1)
    asyncio.run(scenario())


def test_two_responses_then_blocked_third_preserves_timeout_through_owned_future(tmp_path, monkeypatch):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from scripts.memoir_fifty_readback import FiftyReadback, case_plans_for_run
    async def scenario():
        ledger = SubscriptionRun.create(reservation_root=tmp_path, run_id=str(uuid4()),
            source_revision='a' * 40, limits=SubscriptionLimits(10, 5))
        plans = case_plans_for_run(ledger.run_id)
        case = next(iter(plans))
        plan = plans[case]
        bridge = FiftyReadback(case_id=case, run_id=ledger.run_id,
            project_id=plan['project_id'], source_revision=ledger.source_revision)
        correlation = bridge.before_round(case, 1)
        owner = SimpleNamespace(run=ledger, _active=(case, 1), _plans=plans,
            _pending=set(), _worker_lock=asyncio.Lock(), _job_context=ContextVar('test-job', default=None),
            _payload_type=WorkerTurnInput, _worker_records=[], _worker_diagnostic_contexts=[],
            worker_url=sessions._WORKER_URL,
            bridge_for_case=lambda value: bridge,
            _profile=SimpleNamespace(rounds=50, family_enabled_for_round=lambda *args: False))
        monkeypatch.setattr(sessions, 'assert_owned_subscription_session', lambda value:
            None if value is owner else pytest.fail('Foreign synthetic owner'))
        owner.worker_failure_for = lambda ids: sessions.OwnedSubscriptionSession.worker_failure_for(owner, ids)
        worker = CodexWorker(home_root=tmp_path / 'worker', timeout=.1,
            api_key='synthetic-token', base_url='http://synthetic.invalid')
        owner._workers = {'collector': worker}
        transport = SubscriptionTransport.controlled(run=ledger,
            endpoint='http://127.0.0.1:12345/v1/responses')
        contacts, cancelled = [], []
        class Wire(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                contacts.append(len(contacts) + 1)
                if len(contacts) == 3:
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cancelled.append(True)
                return httpx.Response(200, stream=httpx.ByteStream(b'{"synthetic":true}'))
        await transport._wire.aclose()
        transport._wire = Wire()
        async def synthetic_turn(payload, **kwargs):
            async with httpx.AsyncClient(transport=transport) as client:
                for _ in range(4):
                    await client.post(transport.endpoint, json={'input': 'SYNTHETIC_PRIVATE'},
                        headers={'authorization': 'Bearer synthetic-token'})
        monkeypatch.setattr(worker, '_turn', synthetic_turn)
        worker_transport = sessions._WorkerTransport(owner)
        class Runtime:
            async def turn(self, storage, text, **options):
                async with httpx.AsyncClient(transport=worker_transport, base_url=owner.worker_url) as client:
                    await client.post('/internal/codex/turn', json={
                        'user_id': plan['owner_id'], 'project_id': plan['project_id'],
                        'language': plan['language'], 'text': 'synthetic', 'evaluation': correlation})
        storage = object()
        arm = {**plan, 'ordinal': 1, 'state': 'accepted', 'correlation': correlation,
            'client_turn_id': str(uuid4()), 'language': plan['language'],
            'text': 'synthetic', 'allowed_texts': ('synthetic',),
            'future': asyncio.get_running_loop().create_future()}
        api = SimpleNamespace(_armed=arm, _session=owner, _check=lambda: None,
            _turn_storages={storage: arm}, _running_turns=set(), _runtime_invocations=0, _runtime=Runtime())
        try:
            with pytest.raises(RuntimeError, match='^Owned browser turn failed$'):
                await browser._ArmedRuntime(api, case).turn(storage, 'synthetic',
                    client_turn_id=arm['client_turn_id'], project_id=plan['project_id'], language=plan['language'])
            with pytest.raises(ValueError, match='^Owned browser turn failed$') as caught:
                await browser.OwnedFiftyBrowserAPI.wait_turn(api, case, 1)
            cause = caught.value.worker_failure
            assert cause['failure_class'] == 'timeout'
            assert cause['timeout_origin'] == 'worker_execution_deadline'
            assert cause['worker_deadline_expired'] is True
            assert cause['correlation'] == correlation and cause['role'] == 'collector'
            assert cause['execution_timeout_seconds'] == .1
            assert cause['request_accounting'] == {'started': 3, 'completed': 2, 'unresolved': 1}
            assert 0 <= cause['elapsed_ms'] < 5000
            assert owner._worker_records[0]['execution_timeout_seconds'] == .1
            assert owner._worker_records[0]['status'] == 'failed'
            with pytest.raises(SubscriptionStopped):
                async with httpx.AsyncClient(transport=transport) as client:
                    await client.post(transport.endpoint, json={}, headers={'authorization': 'Bearer synthetic-token'})
        finally:
            await transport.aclose()
            ledger.close()
        receipt = ledger.snapshot()
        assert contacts == [1, 2, 3] and cancelled == [True]
        assert receipt['client_requests_started'] == 3
        assert receipt['completed_http_responses'] == 2 and receipt['unresolved_requests'] == 1
        assert receipt['closed'] is True and receipt['restart_allowed'] is False
        assert receipt['stop_reason'] == 'send_interrupted_or_failed'
        for entry in receipt['attempts']:
            assert entry['reserved_at_monotonic'] <= entry['started_at_monotonic']
            if entry['status'] == 'completed':
                assert entry['started_at_monotonic'] <= entry['completed_at_monotonic']
                assert entry['elapsed_ms'] >= 0
            else:
                assert 'completed_at_monotonic' not in entry
        journal = [json.loads(line) for line in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
        assert len([r for r in journal if r['event'] == 'send_started']) == 3
        assert all('started_at_monotonic' in r for r in journal if r['event'] == 'send_started')
        assert all('completed_at_monotonic' in r for r in journal if r['event'] == 'http_response_completed')
        assert 'SYNTHETIC_PRIVATE' not in json.dumps(receipt) + json.dumps(cause) + json.dumps(journal)
        with pytest.raises(SubscriptionStopped):
            SubscriptionRun.create(reservation_root=tmp_path, run_id=ledger.run_id,
                source_revision=ledger.source_revision, limits=SubscriptionLimits(10, 5))
    asyncio.run(scenario())


async def _issued_timeout_session(tmp_path, monkeypatch):
    from apps.api.agent_storage import UserStorage
    from apps.api.memory_event_worker import MemoirLaneBroker
    async def ready(self):
        self._workflow_ready = True  # Synthetic Temporal seam, never a service.
    monkeypatch.setattr(sessions.OwnedSubscriptionSession, '_start_workflows', ready)
    ledger = SubscriptionRun.create(reservation_root=tmp_path, run_id=str(uuid4()),
        source_revision='a' * 40, limits=SubscriptionLimits(10, 5))
    transport = SubscriptionTransport.controlled(run=ledger,
        endpoint='http://127.0.0.1:12345/v1/responses')
    plans = sessions.case_plans_for_run(ledger.run_id)
    stores = {case: UserStorage('http://synthetic.invalid', 'synthetic-public', 'synthetic-token',
        client=httpx.Client(transport=httpx.MockTransport(lambda r, owner=p['owner_id']:
            httpx.Response(200, json={'id': owner, 'is_anonymous': False}))))
        for case, p in plans.items()}
    broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service',
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))))
    binary = Path(sys.executable).resolve()
    owner = await sessions.OwnedSubscriptionSession.create(run=ledger, provider_transport=transport,
        storages=stores, broker=broker, temporal_client=object(), home_root=tmp_path / 'issued-home',
        codex_binary=binary, codex_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), api_key='synthetic-token')
    return owner, stores, broker


@pytest.mark.parametrize('role', ['author_timeline', 'composer'])
def test_real_issued_background_timeout_matches_base_and_owned_job_context(tmp_path, monkeypatch, role):
    from apps.api import codex_worker_service as service
    async def scenario():
        owner, stores, broker = await _issued_timeout_session(tmp_path, monkeypatch)
        try:
            case = owner.case_ids[0]
            plan = owner.case_plans[case]
            for n in range(1, 5):
                owner.activate_round(case, n)
                owner.finish_round()
            base = owner.activate_round(case, 5)
            job = 'synthetic-workflow:activity'
            token = owner._job_context.set({'job_id': job})
            expected = {**base, 'job_id': job}
            if role == 'composer':
                expected['checkpoint_id'] = f'{case}:5'
            worker = owner._workers[role]
            worker.timeout = .02
            monkeypatch.setattr(service, 'composer_timeout', lambda phase: .02)
            async def blocked(*args, **kwargs):
                await asyncio.Event().wait()
            async def no_provider():
                pass
            monkeypatch.setattr(worker, '_turn', blocked)
            monkeypatch.setattr(worker, '_ensure_composer_provider', no_provider)
            async with httpx.AsyncClient(transport=owner.worker_transport, base_url=owner.worker_url) as client:
                with pytest.raises(TimeoutError):
                    await client.post('/internal/codex/turn', json={'user_id': plan['owner_id'],
                        'project_id': plan['project_id'], 'language': plan['language'], 'text': 'synthetic',
                        'agent_role': role, 'evaluation': expected})
            owner._job_context.reset(token)
            # Temporal activity context has ended; retained dispatch authority
            # must still bind the job without borrowing a later activity.
            for ids in (base, expected):
                cause = owner.worker_failure_for(ids)
                assert cause is not None and cause['correlation'] == expected
                assert cause['role'] == role and cause['timeout_origin'] == 'worker_execution_deadline'
                assert cause['worker_deadline_expired'] is True
            for changes in ({'job_id': 'foreign:activity'}, {'round_id': '4'},
                {'checkpoint_id': f'{case}:10'}, {'application_revision': 'b' * 40}):
                assert owner.worker_failure_for({**expected, **changes}) is None
            record = owner._worker_records[-1]
            record['correlation']['job_id'] = 'foreign:activity'
            assert owner.worker_failure_for(base) is None
        finally:
            await owner.close()
            for storage in stores.values():
                storage.client.close()
            await broker.client.aclose()
    asyncio.run(scenario())


@pytest.mark.parametrize('kind,origin', [('transport', 'transport_timeout'), ('builtin', 'unknown_timeout')])
def test_real_issued_nonexpired_timeout_does_not_claim_worker_deadline(tmp_path, monkeypatch, kind, origin):
    async def scenario():
        owner, stores, broker = await _issued_timeout_session(tmp_path, monkeypatch)
        try:
            case = owner.case_ids[0]
            plan = owner.case_plans[case]
            ids = owner.activate_round(case, 1)
            worker = owner._workers['collector']
            async def immediate(*args, **kwargs):
                error = (httpx.ReadTimeout('PRIVATE_TRANSPORT_TIMEOUT') if kind == 'transport'
                    else TimeoutError('PRIVATE_TIMEOUT'))
                error.worker_deadline_expired = True
                error.timeout_origin = 'worker_execution_deadline'
                raise error
            monkeypatch.setattr(worker, '_turn', immediate)
            async with httpx.AsyncClient(transport=owner.worker_transport, base_url=owner.worker_url) as client:
                with pytest.raises((httpx.ReadTimeout, TimeoutError)):
                    await client.post('/internal/codex/turn', json={'user_id': plan['owner_id'],
                        'project_id': plan['project_id'], 'language': plan['language'], 'text': 'synthetic'})
            cause = owner.worker_failure_for(ids)
            assert cause['failure_class'] == 'timeout' and cause['timeout_origin'] == origin
            assert cause['worker_deadline_expired'] is False
            assert cause['execution_timeout_seconds'] == 120
            assert 'PRIVATE' not in json.dumps(cause)
            assert cause['request_accounting'] == {'started': 0, 'completed': 0, 'unresolved': 0}
        finally:
            await owner.close()
            for storage in stores.values():
                storage.client.close()
            await broker.client.aclose()
    asyncio.run(scenario())


def test_worker_deadline_evidence_is_task_local_payload_bound_and_reset(tmp_path, monkeypatch):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    async def scenario():
        worker = CodexWorker(home_root=tmp_path, timeout=.01, api_key='synthetic-token')
        payload = WorkerTurnInput(user_id=str(uuid4()), text='synthetic')
        async def blocked(*args, **kwargs):
            await asyncio.Event().wait()
        monkeypatch.setattr(worker, '_turn', blocked)
        with pytest.raises(TimeoutError):
            await worker.turn(payload)
        assert worker.execution_deadline_expired(payload) is True
        assert worker.execution_deadline_expired(payload.model_copy()) is False
        async def other_task():
            # A child inheriting context cannot reuse its parent's expiry.
            return worker.execution_deadline_expired(payload)
        assert await asyncio.create_task(other_task()) is False
        async def completed(*args, **kwargs):
            return {'reply': 'synthetic'}
        monkeypatch.setattr(worker, '_turn', completed)
        await worker.turn(payload)
        assert worker.execution_deadline_expired(payload) is False
    asyncio.run(scenario())
