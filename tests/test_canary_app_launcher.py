"""Offline task contracts; no model, database or Temporal server calls."""
import asyncio
from copy import deepcopy
from uuid import uuid4
import pytest


def manifest():
    from scripts.run_codexlb_canary import build_manifest
    return build_manifest(run_id=str(uuid4()), source_revision='a' * 40)


def test_canary_validation_rejects_changed_originals_and_role_settings():
    from scripts.canary_app_launcher import validate_plan
    plan = manifest()
    validate_plan(plan)
    for field, value in [('family_enabled', False), ('rounds', ['changed'] * 5), ('language', 'zh-CN')]:
        changed = deepcopy(plan)
        changed['cases'][0][field] = value
        with pytest.raises(ValueError): validate_plan(changed)
    changed = deepcopy(plan)
    changed['proposed_limits']['activity_redeliveries'] = 1
    with pytest.raises(ValueError): validate_plan(changed)


def test_worker_registration_has_no_legacy_jobs_and_one_activity_slot():
    from scripts.canary_app_launcher import temporal_worker_options, task_environment
    from apps.api.temporal_workflows import MemoirSkillLane
    execute = object()
    options = temporal_worker_options('canary-' + str(uuid4()), execute)
    assert options['workflows'] == [MemoirSkillLane]
    assert options['activities'] == [execute]
    assert options['max_concurrent_activities'] == 1
    assert options['max_concurrent_activity_task_polls'] == 1
    environment = task_environment()
    assert environment['MEMORY_SPARK_MEMOIR_PREPARATION_CONCURRENCY'] == '1'
    assert environment['MEMORY_SPARK_PRIVATE_DRAFT_CADENCE'] == '5'
    assert environment['MEMORY_SPARK_LLM_MODEL'] == 'gpt-5.6-luna'
    assert environment['MEMORY_SPARK_MEMOIR_COMPOSER_MODEL'] == 'gpt-5.6-luna'


def test_canary_workflow_never_redelivers_or_restarts_pending_activity(monkeypatch):
    from apps.api.temporal_workflows import MemoirSkillLane, workflow
    calls = []
    async def execute(*args, **kwargs):
        calls.append(kwargs)
        return {'status': 'saved', 'pending': True}
    monkeypatch.setattr(workflow, 'execute_activity', execute)
    result = asyncio.run(MemoirSkillLane().run('lane', single_attempt=True))
    assert result['status'] == 'retry_required'
    assert len(calls) == 1
    assert calls[0]['retry_policy'].maximum_attempts == 1
    assert calls[0]['start_to_close_timeout'].total_seconds() <= 300


def test_registry_binds_every_worker_and_background_job_to_active_root():
    from scripts.canary_app_launcher import CanaryRunEvidence
    plan = manifest()
    evidence = CanaryRunEvidence(plan)
    case = plan['cases'][0]
    correlation = evidence.begin_round(case['case_id'], 1)
    assert correlation['trace_id'] == plan['round_roots'][0]['trace_id']
    payload = {'user_id': case['owner_id'], 'project_id': case['project_id'], 'agent_role': 'collector'}
    assert evidence.worker_correlation(payload)['trace_id'] == correlation['trace_id']
    with pytest.raises(ValueError): evidence.worker_correlation({**payload, 'project_id': 'other'})
    with evidence.background_job(lane_id=str(uuid4()), workflow_id='memoir-lane:abc',
                                 workflow_run_id=str(uuid4()), activity_id='1', attempt=1):
        linked = evidence.worker_correlation({**payload, 'agent_role': 'author_timeline'})
        assert linked['job_id']
        assert linked['trace_id'] == correlation['trace_id']
    assert evidence.background_jobs[0]['status'] == 'completed'
    assert 'job_id' not in evidence.worker_correlation(payload)
    with pytest.raises(ValueError):
        with evidence.background_job(lane_id='lane', workflow_id='w', workflow_run_id='r', activity_id='1', attempt=2):
            pytest.fail('Activity replay must fail before work')


def test_incomplete_manifest_never_promotes_controlled_evidence_to_live():
    from scripts.canary_app_launcher import CanaryRunEvidence
    plan = manifest()
    evidence = CanaryRunEvidence(plan)
    receipt = {'status': 'completed', 'cases': [], 'provider_requests_started': 0, 'evidence_mode': 'mock_only'}
    result = evidence.finish(receipt)
    assert result['status'] == 'incomplete'
    assert result['live_ready'] is False
    assert result['provider_requests_started'] == 0
    assert result['evidence']['gateway_requests'] == 'not_run'
    assert result['evidence']['langfuse_api'] == 'not_run'
    assert result['acceptance_scope'].startswith('Ten-round')


def test_canary_dispatch_uses_single_attempt_workflow_argument():
    from scripts.task_runtime import dispatch_memoir_lanes_once
    class Broker:
        async def drain_once(self): return ['lane']
        async def rpc(self, *args, **kwargs): return []
    class Client:
        async def start_workflow(self, definition, **kwargs):
            assert kwargs['args'] == ['lane', True]
            assert kwargs['task_queue'].startswith('canary-')
            class Handle:
                async def result(self): return {'status': 'finished'}
            return Handle()
    result = asyncio.run(dispatch_memoir_lanes_once(Client(), Broker(), 'canary-test', single_attempt=True))
    assert len(result) == 1


def test_scoped_broker_orders_timeline_before_composer_and_rejects_foreign_receipts():
    from scripts.canary_app_launcher import CanaryRunEvidence, ScopedCanaryBroker
    plan = manifest()
    evidence = CanaryRunEvidence(plan)
    case = plan['cases'][0]
    evidence.begin_round(case['case_id'], 5)
    class Broker:
        foreign = False
        async def rpc(self, name, **payload):
            if name == 'pending_memoir_receipts': return ['receipt']
            if name == 'read_memoir_receipt_scope':
                return {'user_id': 'foreign' if self.foreign else case['owner_id'],
                        'project_id': case['project_id'], 'change_kind': 'accepted'}
            if name == 'queue_memoir_receipt':
                return {'composer_lane_id': 'composer', 'timeline_lane_id': 'timeline'}
            if name == 'pending_memoir_lanes': return ['composer', 'timeline']
    raw = Broker()
    broker = ScopedCanaryBroker(raw, evidence)
    async def scenario():
        assert await broker.drain_once() == ['timeline', 'composer']
        assert await broker.rpc('pending_memoir_lanes', p_limit=100) == ['timeline', 'composer']
        raw.foreign = True
        with pytest.raises(ValueError): await broker.drain_once()
    asyncio.run(scenario())


def test_manifest_rejects_unjoined_gateway_calls_and_keeps_durable_gates_open():
    from scripts.canary_app_launcher import CanaryRunEvidence
    plan = manifest()
    evidence = CanaryRunEvidence(plan)
    evidence.begin_round(plan['cases'][0]['case_id'], 1)
    gateway = {'guarded_send_entries': 1, 'attempts': [{'correlation': {
        'run_id': plan['run_id'], 'trace_id': 'wrong', 'request_id': 'request-1'}}]}
    result = evidence.finish({'status': 'completed', 'evidence_mode': 'guarded_live_canary',
                              'gateway': gateway, 'provider_requests_started': None})
    assert result['status'] == 'incomplete'
    assert result['provider_requests_started'] is None
    assert result['evidence_join_errors']
    assert result['evidence']['gateway_usage'] == 'binding_reported_not_durable_verified'
    assert result['evidence']['langfuse_database'] == 'not_run'


def test_canonical_driver_preserves_failed_round_and_trajectory_before_raise():
    from apps.api.agent_storage import UserStorage
    from scripts.canonical_evaluation import CanonicalEvaluationDriver
    class Storage(UserStorage):
        def __init__(self): pass
        def memory_events(self, project): return {'sources': [], 'events': [], 'completed_rounds': 0}
    class Failure(RuntimeError):
        trajectory = {'final': {'status': 'failed'}, 'steps': [{'action': 'provider.failed'}]}
    class Runtime:
        async def turn(self, *args, **kwargs): raise Failure('Do not persist raw external failure text')
    driver = CanonicalEvaluationDriver(storage=Storage(), runtime=Runtime(), broker=None,
                                       temporal_client=None, task_queue='mock')
    receipts = []
    async def progress(value): receipts.append(deepcopy(value))
    with pytest.raises(Failure):
        asyncio.run(driver.run_case(case_id='test', project_id='test', rounds=['Original'],
            language='en-AU', evidence_mode='mock_only', progress=progress))
    failed = receipts[-1]['rounds'][0]
    assert failed['status'] == 'failed'
    assert failed['trajectory'] == Failure.trajectory
    assert failed['error_class'] == 'Failure'
    assert 'raw external' not in str(receipts)


@pytest.mark.parametrize('mutation', ['account', 'evaluator', 'checkpoint_id', 'checkpoint_trace'])
def test_review_rejects_changed_approved_account_evaluator_and_checkpoint_pins(mutation):
    from scripts.canary_app_launcher import validate_plan
    plan = manifest()
    if mutation == 'account': plan['proposed_account_binding'] = 'c' * 64
    if mutation == 'evaluator': plan['evaluator_version'] = 'wrong-evaluator'
    if mutation == 'checkpoint_id': plan['checkpoints'][0]['checkpoint_id'] = 'other:5'
    if mutation == 'checkpoint_trace': plan['checkpoints'][0]['trace_id'] = plan['checkpoints'][1]['trace_id']
    with pytest.raises(ValueError): validate_plan(plan)


def completed_evidence():
    """Controlled evidence records only; no claimed native actor/model execution."""
    from scripts.canary_app_launcher import CanaryRunEvidence
    evidence = CanaryRunEvidence(manifest())
    workers = []
    for root in evidence.plan['round_roots']:
        root['status'] = 'completed'
        correlation = {'run_id': evidence.plan['run_id'], **{k: root[k] for k in ('case_id', 'round_id', 'trace_id')}}
        workers.append({'role': 'collector', 'phase': 'draft',
                        'correlation': {**correlation, 'observation_id': uuid4().hex[:16]}})
        job_id = str(uuid4()) + ':1'
        root['background_job_ids'].append(job_id)
        evidence.background_jobs.append({**correlation, 'job_id': job_id, 'status': 'completed'})
        workers.append({'role': 'author_timeline', 'phase': 'draft',
                        'correlation': {**correlation, 'job_id': job_id, 'observation_id': uuid4().hex[:16]}})
        if root['round_id'] == '5':
            checkpoint = next(c for c in evidence.plan['checkpoints'] if c['case_id'] == root['case_id'])
            checkpoint.update(draft_saved=True, background_job_ids=[job_id])
            workers.append({'role': 'composer', 'phase': 'draft', 'correlation': {**correlation,
                'job_id': job_id, 'checkpoint_id': checkpoint['checkpoint_id'], 'observation_id': uuid4().hex[:16]}})
    attempts = [{'correlation': {**worker['correlation'], 'request_id': f'request-{ordinal}'}}
                for ordinal, worker in enumerate(workers)]
    receipt = {'status': 'completed', 'evidence_mode': 'guarded_live_canary', 'worker_requests': workers,
               'gateway': {'guarded_send_entries': len(attempts), 'attempts': attempts}, 'provider_requests_started': None}
    return evidence, receipt


def test_review_valid_exact_observation_joins_keep_only_durable_gates_open():
    evidence, receipt = completed_evidence()
    result = evidence.finish(receipt)
    assert result['status'] == 'app_completed_evidence_pending'
    assert result['evidence_join_errors'] == []
    assert result['evidence']['langfuse_database'] == 'not_run'


@pytest.mark.parametrize('mutation', ['cross_root', 'duplicate_observation', 'missing_observation',
    'missing_background_job', 'missing_composer_checkpoint', 'wrong_checkpoint', 'borrowed_job', 'gateway_missing_job'])
def test_review_rejects_incomplete_or_cross_root_observation_joins(mutation):
    evidence, receipt = completed_evidence()
    workers, attempts = receipt['worker_requests'], receipt['gateway']['attempts']
    extraction = next(i for i, w in enumerate(workers) if w['role'] == 'author_timeline')
    composer = next(i for i, w in enumerate(workers) if w['role'] == 'composer')
    if mutation == 'cross_root':
        other = next(w for w in workers if w['correlation']['case_id'] != workers[0]['correlation']['case_id'])
        attempts[0]['correlation']['observation_id'] = other['correlation']['observation_id']
    if mutation == 'duplicate_observation': workers.append(deepcopy(workers[0]))
    if mutation == 'missing_observation':
        workers[0]['correlation'].pop('observation_id')
        attempts[0]['correlation'].pop('observation_id')
    if mutation == 'missing_background_job':
        workers[extraction]['correlation'].pop('job_id')
        attempts[extraction]['correlation'].pop('job_id')
    if mutation == 'missing_composer_checkpoint':
        workers[composer]['correlation'].pop('checkpoint_id')
        attempts[composer]['correlation'].pop('checkpoint_id')
    if mutation == 'wrong_checkpoint':
        workers[composer]['correlation']['checkpoint_id'] = 'other:5'
        attempts[composer]['correlation']['checkpoint_id'] = 'other:5'
    if mutation == 'borrowed_job':
        other = next(w for w in workers if w['role'] == 'author_timeline'
                     and w['correlation']['case_id'] != workers[extraction]['correlation']['case_id'])
        attempts[extraction]['correlation']['job_id'] = other['correlation']['job_id']
    if mutation == 'gateway_missing_job': attempts[extraction]['correlation'].pop('job_id')
    result = evidence.finish(receipt)
    assert result['status'] == 'incomplete'
    assert result['evidence_join_errors']
