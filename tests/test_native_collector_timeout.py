"""Explicit native timeout configuration; synthetic storage/content only."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

import httpx
import pytest

from scripts import run_issue14_subscription_evaluation as launcher
from scripts.issue14_subscription_session import OwnedSubscriptionSession
from scripts import issue14_subscription_transport as budget
from scripts.memoir_subscription_profiles import profile_for


def plan(**changes):
    binary = Path(sys.executable).resolve()
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    return launcher.build_plan(**{'run_id': str(uuid4()), 'source_revision': 'a' * 40,
        'codex_binary': binary, 'codex_sha256': digest, 'temporal_binary': binary,
        'temporal_sha256': digest, 'max_client_requests': 2969, 'max_elapsed_seconds': 28800,
        'max_case_client_requests': 569, 'max_case_elapsed_seconds': 7200,
        'evaluation_profile': 'subscription_fifty', **changes})


def test_native_default_stays_120_and_explicit_180_changes_collector_only(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_TIMEOUT', '239')
    default = plan()
    selected = plan(collector_timeout_seconds=180)
    assert default['collector_timeout_seconds'] == 120
    assert selected['collector_timeout_seconds'] == 180
    expected = dict(default['worker_deadlines']['seconds_by_role'], collector=180)
    assert selected['worker_deadlines']['seconds_by_role'] == expected
    for key in ('max_client_requests', 'max_elapsed_seconds',
        'max_case_client_requests', 'max_case_elapsed_seconds'):
        assert selected[key] == default[key]
    assert selected['worker_deadlines']['timeout_override_inherited'] is False


@pytest.mark.parametrize('value', [None, True, False, '180', 0, -1, .0001, 240.01,
    999, float('nan'), float('inf'), float('-inf')])
@pytest.mark.parametrize('boundary', ['plan', 'session'])
def test_invalid_native_collector_timeout_fails_before_allocation(tmp_path, monkeypatch, value, boundary):
    monkeypatch.setattr(launcher, 'native_resources', lambda *a, **k: pytest.fail('Native allocation'))
    with pytest.raises(ValueError, match='collector timeout'):
        if boundary == 'plan':
            plan(collector_timeout_seconds=value)
        else:
            asyncio.run(OwnedSubscriptionSession.create(run=None, provider_transport=None,
                storages=None, broker=None, temporal_client=None, home_root=tmp_path / 'home',
                codex_binary=None, codex_sha256=None, api_key='synthetic-token',
                collector_timeout_seconds=value))
    assert not (tmp_path / 'home').exists()


@pytest.mark.parametrize('seconds', [.001, 120, 180, 240])
def test_native_timeout_bounds_are_validated_without_clamping(seconds):
    value = plan(collector_timeout_seconds=seconds)
    assert value['collector_timeout_seconds'] == seconds
    assert value['worker_deadlines']['seconds_by_role']['collector'] == seconds


@pytest.mark.parametrize('args,seconds', [([], 120), (['--collector-timeout-seconds', '180'], 180)])
def test_plan_only_cli_exposes_selected_budget_without_native_or_credential_access(tmp_path, monkeypatch, capsys, args, seconds):
    value = plan()
    monkeypatch.setattr(launcher, 'configured_credential', lambda: pytest.fail('Credential read'))
    monkeypatch.setattr(launcher, 'execute_native', lambda *a: pytest.fail('Native allocation'))
    argv = ['--evaluation-profile', 'subscription_fifty', '--run-id', value['run_id'],
        '--source-revision', value['source_revision'], '--run-dir', str(tmp_path / 'run'),
        '--max-client-requests', '2969', '--max-elapsed-seconds', '28800',
        '--max-case-client-requests', '569', '--max-case-elapsed-seconds', '7200',
        '--codex-binary', value['codex_binary'], '--codex-sha256', value['codex_sha256'],
        '--temporal-binary', value['temporal_binary'], '--temporal-sha256', value['temporal_sha256'], *args]
    assert launcher.main(argv) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['collector_timeout_seconds'] == seconds
    assert result['worker_deadlines']['seconds_by_role']['collector'] == seconds
    assert not (tmp_path / 'run').exists()


@pytest.mark.parametrize('mutation', [
    lambda p: p.update(collector_timeout_seconds=181),
    lambda p: p['worker_deadlines']['seconds_by_role'].update(collector=120),
    lambda p: p['worker_deadlines']['seconds_by_role'].update(workspace=180),
])
def test_execute_rejects_plan_timeout_or_diagnostic_drift_before_allocation(tmp_path, monkeypatch, mutation):
    value = plan(collector_timeout_seconds=180)
    mutation(value)
    monkeypatch.setattr(launcher, 'native_resources', lambda *a, **k: pytest.fail('Native allocation'))
    with pytest.raises(ValueError, match='Exact freshly validated'):
        asyncio.run(launcher.execute_native(value, tmp_path / 'run', 'synthetic-token'))
    assert not (tmp_path / 'run').exists()


def resources(run):
    from apps.api.memory_event_worker import MemoirLaneBroker
    from memoir_postgres_workflow import PostgresRest
    profile = profile_for('subscription_fifty')
    facades = {case: PostgresRest(lambda *a, **k: pytest.fail('PostgreSQL contact'),
        details['owner_id'], entitlement=profile.entitlement(details, 1))
        for case, details in profile.plans(run.run_id).items()}
    stores = {case: facade.storage() for case, facade in facades.items()}
    broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service',
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))))
    return {'storages': stores, 'entitlement_facades': facades, 'broker': broker,
        'temporal_client': object()}


async def close_resources(value):
    for storage in value['storages'].values():
        storage.client.close()
    await value['broker'].client.aclose()


@pytest.mark.parametrize('selection', [{}, {'collector_timeout_seconds': 180}])
def test_issued_native_workers_use_explicit_budget_precedence_and_keep_case_global_clocks(tmp_path, monkeypatch, selection):
    from apps.api.codex_worker_service import CodexWorker
    now = [100.0]
    monkeypatch.setattr(budget, 'time', type('Clock', (), {'monotonic': staticmethod(lambda: now[0])}))
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_TIMEOUT', '239')
    async def ready(self):
        self._workflow_ready = True  # Synthetic Temporal startup seam.
    monkeypatch.setattr(OwnedSubscriptionSession, '_start_workflows', ready)
    async def scenario():
        value = plan(**selection)
        profile = profile_for('subscription_fifty')
        run = budget.SubscriptionRun.create(reservation_root=tmp_path, run_id=value['run_id'],
            source_revision=value['source_revision'], limits=budget.SubscriptionLimits(2969, 28800),
            case_ids=profile.case_ids, case_limits=budget.SubscriptionLimits(569, 7200))
        transport = budget.SubscriptionTransport.controlled(run=run, endpoint='http://127.0.0.1:12345/v1/responses')
        scope = resources(run)
        owner = None
        try:
            owner = await OwnedSubscriptionSession.create(run=run, provider_transport=transport,
                **scope, home_root=tmp_path / 'home', codex_binary=value['codex_binary'],
                codex_sha256=value['codex_sha256'], api_key='synthetic-token',
                evaluation_profile='subscription_fifty', **selection)
            seconds = selection.get('collector_timeout_seconds', 120)
            for role, worker in owner._workers.items():
                assert worker.timeout == (seconds if role == 'collector' else 120)
            assert owner._workers['workspace']._execution_timeout('workspace') == 240
            assert owner._workers['composer']._execution_timeout('composer', 'draft') == 600
            case = owner.case_ids[0]
            details = owner.case_plans[case]
            owner.activate_round(case, 1)
            before = run.snapshot()
            async def completed(*a, **k):
                payload, deadline, task = owner._workers['collector']._deadline_context.get()
                assert payload.evaluation == a[0].evaluation and task is asyncio.current_task()
                remaining = deadline.when() - asyncio.get_running_loop().time()
                assert seconds - .1 < remaining <= seconds
                now[0] += 1
                return {'reply': 'synthetic'}
            monkeypatch.setattr(owner._workers['collector'], '_turn', completed)
            async with httpx.AsyncClient(transport=owner.worker_transport, base_url=owner.worker_url) as client:
                response = await client.post('/internal/codex/turn', json={'user_id': details['owner_id'],
                    'project_id': details['project_id'], 'language': details['language'], 'text': 'synthetic'})
            assert response.status_code == 200
            record = owner.worker_receipts()[-1]
            assert record['execution_timeout_seconds'] == seconds and record['status'] == 'completed'
            after = run.snapshot()
            assert after['started_at_monotonic'] == before['started_at_monotonic'] == 100
            assert after['global_deadline_monotonic'] == before['global_deadline_monotonic'] == 28900
            assert after['cases'][0]['deadline_monotonic'] == before['cases'][0]['deadline_monotonic'] == 7300
            assert after['limits'] == before['limits'] and after['case_limits'] == before['case_limits']
            assert after['elapsed_seconds'] == after['cases'][0]['elapsed_seconds'] == 1
            assert after['client_requests_started'] == after['completed_http_responses'] == 0
            # The ordinary product worker retains its separate environment policy.
            assert CodexWorker(home_root=tmp_path / 'product', api_key='synthetic-token').timeout == 239
        finally:
            if owner is not None:
                await owner.close()
            else:
                await transport.aclose()
                run.close()
            await close_resources(scope)
    asyncio.run(scenario())


def test_execute_passes_validated_180_to_native_session_constructor(tmp_path, monkeypatch):
    from scripts import issue14_subscription_runner as runners
    value = plan(collector_timeout_seconds=180)
    seen = []
    monkeypatch.setattr(launcher, 'verify_main_source', lambda revision: None)
    @asynccontextmanager
    async def fake_resources(*args):
        yield {}
    monkeypatch.setattr(launcher, 'native_resources', fake_resources)
    async def create(**kwargs):
        seen.append(kwargs['collector_timeout_seconds'])
        class Session:
            def worker_receipts(self):
                return []
            async def close(self):
                await kwargs['provider_transport'].aclose()
                kwargs['run'].close()
        return Session()
    monkeypatch.setattr(OwnedSubscriptionSession, 'create', create)
    class Runner:
        def __init__(self, *a, **k):
            pass
        async def run(self, **kwargs):
            return {'status': 'incomplete'}  # Configuration seam, no acceptance claim.
    monkeypatch.setattr(runners, 'SubscriptionProgressiveRunner', Runner)
    result = asyncio.run(launcher.execute_native(value, tmp_path / 'run', 'synthetic-token'))
    assert result['status'] == 'incomplete' and seen == [180]
    assert result['request_accounting']['client_requests_started'] == 0


def test_product_default_and_upper_bound_remain_120_and_240(tmp_path, monkeypatch):
    from apps.api.codex_worker_service import CodexWorker
    monkeypatch.delenv('MEMORY_SPARK_CODEX_WORKER_TIMEOUT', raising=False)
    assert CodexWorker(home_root=tmp_path / 'default', api_key='synthetic-token').timeout == 120
    assert CodexWorker(home_root=tmp_path / 'upper', timeout=999, api_key='synthetic-token').timeout == 240
