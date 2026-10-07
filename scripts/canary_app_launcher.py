"""Task-only application canary, using the normal authenticated application seam.

The native owner supplies already-owned PostgreSQL, Temporal and a task worker.
This module never obtains credentials, starts shared services or authorizes a run.
A live worker must use the installed gateway binding in the same authorized
runtime; controlled workers remain unmistakably synthetic evidence.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import time
import subprocess
from uuid import UUID, uuid4

from apps.api.agent_storage import UserStorage
from apps.api.temporal_workflows import MemoirSkillLane

MODEL = 'gpt-5.6-luna'


def task_environment():
    return {'MEMORY_SPARK_MEMOIR_PREPARATION_CONCURRENCY': '1',
            'MEMORY_SPARK_DISABLE_PRIVDROP': '1',
            'MEMORY_SPARK_LEGACY_CODEX_HOME': '',
            'MEMORY_SPARK_PRIVATE_DRAFT_CADENCE': '5',
            'MEMORY_SPARK_MEMOIR_RUN_SECONDS': '300',
            'MEMORY_SPARK_LLM_MODEL': MODEL,
            'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL': MODEL}


@contextmanager
def pinned_environment():
    """Only for the new, isolated task process; no persistent configuration."""
    previous = {key: os.environ.get(key) for key in task_environment()}
    os.environ.update(task_environment())
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def temporal_worker_options(queue, execute):
    if not queue.startswith('canary-'):
        raise ValueError('A task-owned canary queue is required')
    return {'task_queue': queue, 'workflows': [MemoirSkillLane], 'activities': [execute],
            'max_concurrent_activities': 1, 'max_concurrent_activity_task_polls': 1}


def validate_plan(plan):
    from scripts.run_codexlb_canary import build_manifest
    expected = build_manifest(run_id=plan['run_id'], source_revision=plan['source_revision'])
    if (plan.get('requested_model') != MODEL or plan.get('proposed_limits') != expected['proposed_limits']
            or plan.get('proposed_account_binding') != expected['proposed_account_binding']
            or plan.get('evaluator_version') != expected['evaluator_version']
            or plan.get('inputs_sha256') != expected['inputs_sha256']
            or plan.get('source_sha256') != expected['source_sha256']
            or plan.get('skill_manifest') != expected['skill_manifest']
            or plan.get('gateway_source_sha256') != expected['gateway_source_sha256']
            or plan.get('integration_provenance') != expected['integration_provenance']
            or plan.get('source_claim') != expected['source_claim']
            or len(plan.get('cases', [])) != 2):
        raise ValueError('The approved canary plan differs')
    owners, projects = set(), set()
    for case, original in zip(plan['cases'], expected['cases']):
        if any(case.get(key) != original[key] for key in ('case_id', 'language', 'family_enabled', 'rounds')):
            raise ValueError('Original canary inputs or case configuration differ')
        if str(UUID(case['owner_id'])) != case['owner_id'] or not case['project_id'].startswith('canary-'):
            raise ValueError('Fresh synthetic owner/project identities are required')
        owners.add(case['owner_id'])
        projects.add(case['project_id'])
    if len(owners) != 2 or len(projects) != 2:
        raise ValueError('Canary identities must be distinct')
    wanted = {(c['case_id'], str(i)) for c in plan['cases'] for i in range(1, 6)}
    roots = plan.get('round_roots', [])
    if (len(roots) != 10 or {(r['case_id'], r['round_id']) for r in roots} != wanted
            or len({r['trace_id'] for r in roots}) != 10):
        raise ValueError('Exactly ten distinct round roots are required')
    for root in roots:
        case = next(c for c in plan['cases'] if c['case_id'] == root['case_id'])
        trace = hashlib.sha256(f"{plan['run_id']}:{root['case_id']}:{root['round_id']}".encode()).hexdigest()[:32]
        if root['trace_id'] != trace or any(root[key] != case[key] for key in ('owner_id', 'project_id')):
            raise ValueError('Round root scope differs from its case')
    checkpoints = plan.get('checkpoints', [])
    if (len(checkpoints) != 2 or {c['case_id'] for c in checkpoints} != {c['case_id'] for c in plan['cases']}
            or any(c['milestone'] != 5 for c in checkpoints)):
        raise ValueError('Exactly two round-five checkpoints are required')
    expected_checkpoints = {c['case_id']: c for c in expected['checkpoints']}
    for checkpoint in checkpoints:
        pinned = expected_checkpoints[checkpoint['case_id']]
        if any(checkpoint.get(key) != pinned[key] for key in ('checkpoint_id', 'trace_id', 'milestone')):
            raise ValueError('Checkpoint identity differs from its exact round-five root')


class CanaryRunEvidence:
    def __init__(self, plan):
        validate_plan(plan)
        self.plan = deepcopy(plan)
        self.active = None
        self.background_jobs = []
        self._job = ContextVar('canary_background_job', default=None)
        self._started = set()

    def begin_round(self, case_id, ordinal):
        key = (case_id, str(ordinal))
        if key in self._started:
            raise ValueError('A canary round cannot be replayed')
        root = next((r for r in self.plan['round_roots'] if (r['case_id'], r['round_id']) == key), None)
        if root is None:
            raise ValueError('Round is outside this canary')
        if self.active and self.active['status'] != 'completed':
            raise ValueError('The preceding canary round has not settled')
        self._started.add(key)
        self.active = root
        root['status'] = 'started'
        return self._correlation()

    def _correlation(self):
        if self.active is None:
            raise ValueError('No active canary round')
        return {'run_id': self.plan['run_id'], **{k: self.active[k] for k in ('case_id', 'round_id', 'trace_id')}}

    def worker_correlation(self, payload):
        if self.active is None or any(str(payload.get(key)) != self.active[field]
                for key, field in (('user_id', 'owner_id'), ('project_id', 'project_id'))):
            raise ValueError('Worker scope is outside the active synthetic round')
        correlation = self._correlation()
        job = self._job.get()
        if payload.get('agent_role') == 'author_timeline' and job is None:
            raise ValueError('Canonical extraction requires its background job')
        if job:
            correlation['job_id'] = job['job_id']
        if payload.get('agent_role') == 'composer':
            if self.active['round_id'] != '5' or job is None:
                raise ValueError('Composer requires the round-five background job')
            correlation['checkpoint_id'] = self.active['case_id'] + ':5'
        return correlation

    @contextmanager
    def background_job(self, *, lane_id, workflow_id, workflow_run_id, activity_id, attempt):
        if attempt != 1 or self._job.get() is not None:
            raise ValueError('Canary activity redelivery is forbidden')
        job = {**self._correlation(), 'lane_id': lane_id, 'workflow_id': workflow_id,
               'workflow_run_id': workflow_run_id, 'activity_id': activity_id,
               'job_id': workflow_run_id + ':' + activity_id, 'status': 'started'}
        if any(previous['job_id'] == job['job_id'] for previous in self.background_jobs):
            raise ValueError('Canary activity replay is forbidden')
        self.background_jobs.append(job)
        self.active['background_job_ids'].append(job['job_id'])
        if self.active['round_id'] == '5':
            checkpoint = next(c for c in self.plan['checkpoints'] if c['case_id'] == self.active['case_id'])
            checkpoint['background_job_ids'].append(job['job_id'])
        token = self._job.set(job)
        try:
            yield job
            job['status'] = 'completed'
        except BaseException as error:
            job['status'] = 'failed'
            job['error_class'] = type(error).__name__
            raise
        finally:
            self._job.reset(token)

    def progress(self, value):
        if self.active is None:
            return
        records = value.get('rounds', [])
        record = next((r for r in records if str(r['round']) == self.active['round_id']), None)
        if record:
            self.active['application_result'] = deepcopy(record)
            if record.get('accepted_source_id'):
                next(c for c in self.plan['cases'] if c['case_id'] == self.active['case_id'])['data_created'] = True
            if record.get('background_settled'):
                self.active['status'] = 'completed'
            elif record.get('status') == 'failed':
                self.active['status'] = 'failed'
        for checkpoint in value.get('checkpoints', []):
            target = next(c for c in self.plan['checkpoints'] if c['case_id'] == self.active['case_id'])
            draft = checkpoint['draft']
            target.update(draft_saved=bool(draft.get('revision', 0) > 0 and draft.get('covered_round') == 5),
                          draft=deepcopy(draft), background_job_ids=list(self.active['background_job_ids']))

    def _observation_joins(self, result, workers):
        """Bind each observation to one complete, exact application context."""
        errors, observations, jobs = [], {}, {}
        roots = {root['trace_id']: root for root in result['round_roots']}
        checkpoints = {item['checkpoint_id']: item for item in result['checkpoints']}
        root_keys = ('case_id', 'round_id', 'trace_id')

        def root_for(correlation):
            if not isinstance(correlation, dict):
                return None
            if not isinstance(correlation.get('trace_id'), str):
                return None
            root = roots.get(correlation.get('trace_id'))
            if (root is None or correlation.get('run_id') != result['run_id']
                    or any(correlation.get(key) != root[key] for key in root_keys)):
                return None
            return root

        for job in self.background_jobs:
            job_id = job.get('job_id')
            root = root_for(job)
            if not isinstance(job_id, str) or not job_id or job_id in jobs or root is None:
                errors.append('background_job_join_unavailable')
                continue
            if root['background_job_ids'].count(job_id) != 1:
                errors.append('background_job_join_unavailable')
                continue
            jobs[job_id] = job

        seen_observations = set()
        for worker in workers:
            correlation = worker.get('correlation', {})
            if not isinstance(correlation, dict):
                errors.append('worker_observation_join_unavailable')
                continue
            observation_id = correlation.get('observation_id')
            root = root_for(correlation)
            if not isinstance(observation_id, str) or not observation_id:
                errors.append('worker_observation_join_unavailable')
                continue
            if observation_id in seen_observations:
                observations.pop(observation_id, None)
                errors.append('duplicate_worker_observation')
                continue
            seen_observations.add(observation_id)
            role = worker.get('role')
            background = role in {'author_timeline', 'composer'}
            job_id = correlation.get('job_id')
            job = jobs.get(job_id) if isinstance(job_id, str) else None
            valid = (root is not None and role in {'collector', 'workspace', 'memory_context',
                'author_timeline', 'composer'})
            if background:
                valid = valid and job is not None and all(job.get(key) == correlation.get(key)
                    for key in ('run_id', *root_keys))
            elif job_id is not None:
                valid = False
            checkpoint_id = correlation.get('checkpoint_id')
            if role == 'composer':
                checkpoint = checkpoints.get(checkpoint_id) if isinstance(checkpoint_id, str) else None
                valid = (valid and checkpoint is not None and correlation.get('round_id') == '5'
                    and checkpoint['case_id'] == correlation.get('case_id')
                    and checkpoint['trace_id'] == correlation.get('trace_id')
                    and checkpoint['background_job_ids'].count(job_id) == 1)
            elif checkpoint_id is not None:
                valid = False
            if not valid:
                errors.append('worker_observation_join_unavailable')
                continue
            observations[observation_id] = worker
        return observations, errors

    def finish(self, receipt):
        result = deepcopy(self.plan)
        observations, join_errors = self._observation_joins(result, receipt.get('worker_requests', []))
        gateway = receipt.get('gateway')
        if gateway is not None:
            seen = set()
            for attempt in gateway.get('attempts', []):
                correlation = attempt.get('correlation', {})
                if not isinstance(correlation, dict):
                    join_errors.append('gateway_request_join_unavailable')
                    continue
                root = next((r for r in result['round_roots'] if r['trace_id'] == correlation.get('trace_id')), None)
                request_id = correlation.get('request_id')
                observation_id = correlation.get('observation_id')
                worker = observations.get(observation_id) if isinstance(observation_id, str) else None
                worker_correlation = worker['correlation'] if worker else {}
                if (root is None or correlation.get('run_id') != result['run_id']
                        or any(correlation.get(k) != root[k] for k in ('case_id', 'round_id'))
                        or worker is None or any(correlation.get(key) != worker_correlation.get(key)
                            for key in ('run_id', 'case_id', 'round_id', 'trace_id',
                                        'observation_id', 'job_id', 'checkpoint_id'))
                        or any(key in correlation and correlation[key] != worker.get(key)
                               for key in ('role', 'phase'))
                        or not isinstance(request_id, str) or not request_id or request_id in seen
                        or (correlation.get('job_id') and correlation['job_id'] not in root['background_job_ids'])):
                    join_errors.append('gateway_request_join_unavailable')
                    continue
                seen.add(request_id)
                root['gateway_request_ids'].append(request_id)
            result['gateway_binding_receipt'] = deepcopy(gateway)
            result['evidence']['gateway_requests'] = 'binding_reported_not_durable_verified'
            result['evidence']['gateway_usage'] = 'binding_reported_not_durable_verified'
            if gateway.get('guarded_send_entries') != len(seen) or len(seen) > 80:
                join_errors.append('gateway_request_count_differs')
        complete = (receipt['status'] == 'completed'
                    and not join_errors
                    and all(r['status'] == 'completed' for r in result['round_roots'])
                    and all(c['draft_saved'] for c in result['checkpoints']))
        result.update(status='app_completed_evidence_pending' if complete else 'incomplete',
                      execution_started=bool(self._started), live_ready=False,
                      background_jobs=deepcopy(self.background_jobs), app_receipt=deepcopy(receipt))
        result['evidence_join_errors'] = sorted(set(join_errors))
        if receipt['evidence_mode'] == 'guarded_live_canary':
            result['credentials_loaded'] = True
            result['reservation_created'] = gateway is not None
            result['blockers'] = ['durable_gateway_accounting_not_verified',
                'durable_langfuse_and_browser_evidence_not_verified', 'full_250_round_acceptance_not_run']
        # Neither model-quality acceptance nor durable publication follows from
        # invoking the real app path or having ten planned IDs.
        result['provider_requests_started'] = receipt.get('provider_requests_started', 0)
        if complete:
            kind = 'controlled_verified' if receipt['evidence_mode'] == 'mock_only' else 'app_verified'
            for field in ('real_app_replies', 'private_drafts', 'background_joins'):
                result['evidence'][field] = kind
        return result


def _save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


async def run_application_canary(plan, *, storages, broker, temporal_client, worker,
                                 run_dir, deadline=None):
    """Execute ten real application turns and two canonical draft checkpoints.

    Dependencies must already belong to this isolated native task. The installed
    actor supplies a live CanaryWorker without exporting its existing consumer
    credential. The same routine also supports a checked-in controlled worker
    for regression tests; those outputs stay mock_only. No provider readiness
    file or command-line Boolean can grant live access.
    """
    from fastapi import FastAPI
    import httpx
    from temporalio import activity
    from temporalio.worker import Worker
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.codex_worker_service import WorkerTurnInput
    from apps.api.memory_event_worker import MemoryEventWorker
    from scripts.canary_worker import CanaryWorker
    from scripts.canonical_evaluation import CanonicalEvaluationDriver
    from scripts.evaluation_budget import RequestLimitedTransport

    validate_plan(plan)
    if not isinstance(worker, CanaryWorker):
        raise TypeError('A task-owned CanaryWorker is required')
    live = worker.evidence_mode == 'guarded_live_canary'
    if live:
        worker.assert_live_ready(run_id=plan['run_id'], source_revision=plan['source_revision'],
                                 account_binding=plan['proposed_account_binding'])
        root = Path(__file__).resolve().parents[1]
        head, tree = subprocess.check_output(['git', 'rev-parse', 'HEAD', 'HEAD^{tree}'], cwd=root, text=True).splitlines()
        if (head != plan['source_revision'] or tree != plan['source_tree']
                or subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=root)):
            raise ValueError('Live canary requires its exact clean reviewed source head')
    expected_projects = {case['project_id'] for case in plan['cases']}
    if set(storages) != expected_projects:
        raise ValueError('Only both planned synthetic projects may enter the canary')
    for case in plan['cases']:
        storage = storages[case['project_id']]
        if not isinstance(storage, UserStorage) or str(storage.user_id) != case['owner_id']:
            raise ValueError('Authenticated storage owner differs from the synthetic case')
        view = await asyncio.to_thread(storage.memory_events, case['project_id'])
        if view['sources'] or view['events'] or view['completed_rounds']:
            raise ValueError('Both canary projects must be fresh before any dispatch')
        entitlement = await asyncio.to_thread(storage.story_entitlement) or {}
        from apps.api.family_context import family_features_enabled
        if family_features_enabled(entitlement) != case['family_enabled']:
            raise ValueError('Synthetic family entitlement differs from the original case')
    if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
        raise ValueError('A finite absolute canary deadline is required')
    deadline = min(deadline if deadline is not None else time.monotonic() + 900, time.monotonic() + 900)
    if live:
        deadline = min(deadline, worker.gateway_lease.deadline)
    if deadline <= time.monotonic():
        raise ValueError('Canary run deadline already expired')
    run_dir = Path(run_dir)
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    evidence = CanaryRunEvidence(plan)
    broker = ScopedCanaryBroker(broker, evidence)
    receipt = {'run_id': plan['run_id'], 'evidence_mode': 'guarded_live_canary' if live else 'mock_only',
               'status': 'started', 'cases': [], 'worker_requests': [],
               'provider_requests_started': 0, 'cleanup': {}, 'live_acceptance': 'not_run',
               'model_output_quality': 'ungraded', 'judge': 'not_run', 'photo': 'not_run',
               'geocoding': 'not_run', 'all_seven_skills': 'not_run', '250_rounds': 'not_run'}
    queue = 'canary-' + plan['run_id']
    app = FastAPI()
    def save():
        _save(run_dir / 'manifest.json', evidence.finish(receipt))
    save()

    @app.post('/internal/codex/turn')
    async def private_turn(payload: WorkerTurnInput):
        if payload.model not in {None, MODEL}:
            raise ValueError('A worker attempted an unsupported role model')
        correlation = evidence.worker_correlation(payload.model_dump())
        correlation['observation_id'] = uuid4().hex[:16]
        # Background composer/extraction currently do not carry evaluation
        # metadata themselves. Inject IDs at the real private-worker seam;
        # content, model behavior and canonical validators remain unchanged.
        payload = payload.model_copy(update={'evaluation': correlation, 'model': MODEL,
                                              'diagnostic_request_id': str(uuid4())})
        record = {'correlation': correlation, 'role': payload.agent_role,
                  'phase': payload.composer_phase, 'status': 'started',
                  'worker_request_id': payload.diagnostic_request_id}
        receipt['worker_requests'].append(record)
        save()
        try:
            result = await worker.turn(payload)
            record.update(status='completed', trajectory=result.get('trajectory'))
            return result
        except BaseException as error:
            record.update(status='failed', error_class=type(error).__name__,
                          trajectory=getattr(error, 'trajectory', None))
            raise
        finally:
            save()

    transport = RequestLimitedTransport(httpx.ASGITransport(app=app), max_requests=80,
                                         max_elapsed_seconds=deadline - time.monotonic())
    runtime = CodexRuntime(home_root=run_dir / 'api-homes', base_url=worker.base_url,
                          model=MODEL, worker_url='http://canary-worker.invalid',
                          worker_secret='task-in-process-only', worker_transport=transport,
                          task_publisher_enabled=False)
    runtime.composer_model = MODEL
    lane_worker = MemoryEventWorker(broker, worker_url=runtime.worker_url,
                                   worker_secret=runtime.worker_secret, worker_transport=transport)

    @activity.defn(name='memoir.execute_lane')
    async def execute(lane_id: str):
        info = activity.info()
        with evidence.background_job(lane_id=lane_id, workflow_id=info.workflow_id,
                workflow_run_id=info.workflow_run_id, activity_id=info.activity_id, attempt=info.attempt) as job:
            save()
            result = await lane_worker.execute_lane(lane_id)
            state = await broker.rpc('read_memoir_lane_state', p_lane_id=lane_id)
            job['result'] = deepcopy(result)
            job['state'] = deepcopy(state)
            save()
            return {'status': result['status'], 'pending': bool(state and state['pending'])}

    try:
        with pinned_environment():
            async with asyncio.timeout_at(deadline):
                async with Worker(temporal_client, **temporal_worker_options(queue, execute)):
                    for case in plan['cases']:
                        storage = storages[case['project_id']]
                        partial = {'case_id': case['case_id'], 'owner_id': case['owner_id'],
                                   'project_id': case['project_id'], 'status': 'started',
                                   'rounds': [], 'checkpoints': []}
                        receipt['cases'].append(partial)
                        async def progress(value):
                            partial.update(value)
                            evidence.progress(value)
                            if value.get('rounds') and value['rounds'][-1].get('background_settled'):
                                # Extraction can publish an events outbox row.
                                # Drain that bookkeeping before another owner
                                # becomes active; never retry failed model work.
                                await broker.drain_once()
                                if await broker.rpc('pending_memoir_lanes', p_limit=100):
                                    raise RuntimeError('Canary left unsettled work; redelivery is forbidden')
                            save()
                        driver = CanonicalEvaluationDriver(storage=storage, runtime=runtime,
                            broker=broker, temporal_client=temporal_client, task_queue=queue)
                        result = await driver.run_case(case_id=case['case_id'], project_id=case['project_id'],
                            rounds=case['rounds'], language=case['language'],
                            evidence_mode=receipt['evidence_mode'], single_attempt=True,
                            before_round=evidence.begin_round, progress=progress,
                            live_worker=worker if live else None,
                            settle_timeout=min(300, max(.001, deadline - time.monotonic())))
                        partial.update(result)
                        save()
        receipt['status'] = 'completed'
    except (Exception, asyncio.CancelledError) as error:
        receipt.update(status='incomplete', error_class=type(error).__name__)
        if evidence.active and evidence.active['status'] != 'completed':
            evidence.active['status'] = 'failed'
        if receipt['cases'] and receipt['cases'][-1]['status'] != 'completed':
            failed = receipt['cases'][-1]
            failed.update(status='incomplete', error_class=type(error).__name__)
            if failed.get('rounds') and not failed['rounds'][-1].get('background_settled'):
                failed['rounds'][-1].update(status='failed', error_class=type(error).__name__)
                evidence.progress(failed)
    finally:
        # Worker/CodexConnection reaps its own processes on cancellation. This
        # runner owns the transport; the native actor/fixture retains ownership
        # of gateway, database and Temporal resources and must supply receipts.
        async def cleanup():
            for name, close in [('worker_transport_closed', transport.transport.aclose),
                                 *([('gateway_stopped', worker.gateway_lease.stop)] if live else [])]:
                try:
                    async with asyncio.timeout(25 if name == 'gateway_stopped' else 10):
                        await close()
                    receipt['cleanup'][name] = True
                except (Exception, asyncio.CancelledError) as error:
                    receipt['cleanup'][name] = False
                    receipt['cleanup'][name + '_error_class'] = type(error).__name__
                    receipt['status'] = 'incomplete'
            receipt['private_worker_requests_started'] = transport.requests_started
            if live:
                receipt['gateway'] = worker.gateway_lease.receipt()
                receipt['guarded_send_entries'] = receipt['gateway']['guarded_send_entries']
                receipt['provider_requests_started'] = None
            receipt['cleanup']['native_resources'] = 'owner_must_verify'
            save()
        closing = asyncio.create_task(cleanup())
        while not closing.done():
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                receipt['status'] = 'incomplete'
        await closing
    return evidence.finish(receipt)


class ScopedCanaryBroker:
    """Reject foreign work and keep canonical extraction ahead of composition."""
    def __init__(self, broker, evidence):
        self.broker, self.evidence = broker, evidence
        self._round_lanes = []

    async def rpc(self, name, **payload):
        result = await self.broker.rpc(name, **payload)
        if name == 'pending_memoir_lanes':
            if set(result) - set(self._round_lanes):
                raise ValueError('Unrelated or replayed work appeared in the canary store')
            return [lane for lane in self._round_lanes if lane in result]
        if name == 'claim_memoir_lane' and result:
            active = self.evidence.active
            if (not active or result['user_id'] != active['owner_id']
                    or result['project_id'] != active['project_id']):
                raise ValueError('Claimed work is outside the active canary case')
        return result

    async def drain_once(self):
        active = self.evidence.active
        if active is None:
            raise ValueError('Canary background work requires an active root')
        receipts = await self.broker.rpc('pending_memoir_receipts', p_limit=50)
        timeline, composer = [], []
        for receipt in receipts:
            scope = await self.broker.rpc('read_memoir_receipt_scope', p_receipt_id=receipt)
            if (not scope or scope['user_id'] != active['owner_id']
                    or scope['project_id'] != active['project_id']
                    or scope['change_kind'] not in {'round', 'accepted', 'events'}):
                raise ValueError('Receipt is outside the approved canary scope')
            queued = await self.broker.rpc('queue_memoir_receipt', p_receipt_id=receipt, p_cadence=5)
            if queued:
                if queued.get('timeline_lane_id'): timeline.append(queued['timeline_lane_id'])
                if queued.get('composer_lane_id'): composer.append(queued['composer_lane_id'])
        self._round_lanes = list(dict.fromkeys(timeline + composer))
        return self._round_lanes
