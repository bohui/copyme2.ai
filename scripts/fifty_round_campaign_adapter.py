"""Synthetic private-worker adapter for the existing fifty-round canonical driver.

The only transport endpoint is an in-process, data-only fixture. No provider,
credential, actor or socket factory exists here. The same structured worker
payloads and driver callbacks are used by the application; production admission
and lowest-level native send interception still require a separate adapter.
"""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from time import monotonic

import httpx

from scripts.fifty_round_budget_contract import _same_json_literal
from scripts.fifty_round_dispatch_budget import CampaignDispatchBudget, WorkerKey
from scripts.single_fifty_campaign import assess_campaign_receipt, ROOT, INPUTS_PATH, INPUTS_SHA256

SYNTHETIC_ORIGIN = 'http://campaign.synthetic.invalid'
_DRAIN_SECONDS = .05
_BACKGROUND = frozenset({'canonical_extraction', 'event_preparation', 'composer_draft', 'composer_review'})
_REPAIRS = frozenset({'focused_family', 'composer_draft', 'composer_review'})
_EXPECTED_INCOMPLETE = frozenset({'terminal_run_incomplete', 'execution_not_recorded',
    'fifty_completed_rounds_not_recorded', 'ten_saved_checkpoints_not_recorded',
    'cleanup_verification_missing', 'actual_request_count_unknown'})


class CampaignStopped(RuntimeError):
    """Only a fixed, content-free reason is exposed."""


@dataclass(frozen=True)
class SyntheticSend:
    response_id: str
    input_tokens: int = 1
    output_tokens: int = 1
    delay_seconds: float = 0
    failure: str | None = None


@dataclass(frozen=True)
class SyntheticWorkerReply:
    result: dict
    sends: tuple[SyntheticSend, ...]


def classify_worker_request(payload):
    """Classify actual WorkerTurnInput fields, never story text or prompt phrases."""
    if type(payload) is not dict:
        raise CampaignStopped('worker_shape_invalid')
    role, focus = payload.get('agent_role', 'collector'), payload.get('extraction_focus')
    if type(role) is not str or (focus is not None and type(focus) is not str):
        raise CampaignStopped('worker_stage_unknown')
    if role == 'workspace':
        stage = {None:'broad_workspace', 'place_journey':'focused_place', 'family_tree':'focused_family'}.get(focus)
    elif focus is not None:
        stage = None
    elif role == 'composer':
        phase = payload.get('composer_phase', 'draft')
        stage = {'prepare':'event_preparation','draft':'composer_draft','review':'composer_review'}.get(phase) if type(phase) is str else None
    else:
        stage = {'collector':'collector','author_timeline':'canonical_extraction',
                 'memory_context':'initial_locale'}.get(role)
    if stage is None:
        raise CampaignStopped('worker_stage_unknown')
    return stage


def _validate_plan(plan):
    try:
        case = plan['cases'][0]
        if (type(plan) is not dict or len(plan['cases']) != 1
                or plan['live_ready'] is not False or plan['execution_started'] is not False
                or type(case['family_enabled']) is not bool or len(case['rounds']) != 50
                or any(type(t) is not str or not t.strip() for t in case['rounds'])
                or len(plan['round_roots']) != 50
                or plan['budget']['family_enabled'] is not case['family_enabled']):
            raise ValueError
        originals = (ROOT / INPUTS_PATH).read_bytes()
        if hashlib.sha256(originals).hexdigest() != INPUTS_SHA256: raise ValueError
        original = next((c for c in json.loads(originals)['cases'] if c['id']==case['case_id']), None)
        if original is None or case['rounds'] != original['rounds'] or case['language'] != original['locale']:
            raise ValueError
        traces = set()
        for n, root in enumerate(plan['round_roots'], 1):
            expected_trace = hashlib.sha256(f"{plan['run_id']}:{case['case_id']}:{n}".encode()).hexdigest()[:32]
            if (type(root['round']) is not int or root['round'] != n
                    or any(root[k] != case[k] for k in ('case_id','owner_id','project_id'))
                    or root['trace_id'] != expected_trace
                    or root['original_input_sha256'] != hashlib.sha256(case['rounds'][n-1].encode()).hexdigest()):
                raise ValueError
            traces.add(root['trace_id'])
        if len(traces) != 50: raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError('An internally consistent blocked fifty-input plan is required') from None
    return deepcopy(plan)


def _fixtures(replies):
    if type(replies) not in (list, tuple) or not 1 <= len(replies) <= 10000:
        raise ValueError('A bounded data-only synthetic fixture is required')
    for reply in replies:
        if (type(reply) is not SyntheticWorkerReply or type(reply.result) is not dict
                or type(reply.sends) is not tuple or not 1 <= len(reply.sends) <= 10000):
            raise ValueError('A worker fixture requires data and synthetic sends')
        json.dumps(reply.result, allow_nan=False)
        for send in reply.sends:
            if (type(send) is not SyntheticSend or type(send.response_id) is not str
                    or type(send.delay_seconds) not in (int,float) or not math.isfinite(send.delay_seconds)
                    or not 0 <= send.delay_seconds <= 3600
                    or any(type(v) is not int or v < 0 for v in (send.input_tokens,send.output_tokens))
                    or send.failure not in (None,'quota','provider_error','usage_unknown','protocol_error')):
                raise ValueError('Synthetic send data is invalid')
    return deepcopy(replies)


class FiftyRoundSyntheticAdapter(httpx.AsyncBaseTransport):
    """One immutable proposal, ledger and fixture stream for all worker roles.

    `before_round`/`observe_progress` plug directly into CanonicalEvaluationDriver.
    Background activity code must bind its trusted round/job before making its
    ordinary HTTP worker request; request JSON alone cannot invent a job scope.
    Declared alias/effort/account consistency is not native verification.
    """

    @classmethod
    def create(cls, *, plan, reservation_root, replies):
        pinned, fixtures = _validate_plan(plan), _fixtures(replies)
        case, proposal = pinned['cases'][0], pinned['budget']
        scope = {key: pinned[key] for key in ('run_id','source_revision','source_tree','source_sha256')}
        scope.update({key: case[key] for key in ('case_id','owner_id','project_id')})
        scope.update(account_binding=proposal['routing']['account']['proposed_binding_sha256'],
            roles={stage:{'model_alias':role['configuration_alias'],'wire_model':'synthetic-model',
                'reasoning':role['configuration_reasoning']} for stage,role in proposal['routing']['stages'].items()})
        self = object.__new__(cls)
        self._plan, self._fixtures = pinned, fixtures
        self._ledger = CampaignDispatchBudget.create(reservation_root=reservation_root, proposal=proposal, scope=scope)
        self._round = self._fixture_index = 0
        self._progress = {'rounds':[], 'checkpoints':[], 'status':'not_run'}
        self._job = ContextVar('synthetic_campaign_job', default=None)
        self._attempt = ContextVar('synthetic_campaign_attempt', default=None)
        self._tasks, self._pending_at_close = set(), False
        self._closed = self._complete = False
        self._stop_reason = None
        return self

    def __init__(self):
        raise TypeError('Use create; this adapter has no live mode')

    @property
    def plan(self): return deepcopy(self._plan)

    def _stop(self, reason='protocol_error'):
        self._stop_reason = self._stop_reason or reason
        self._ledger.stop(reason)

    def _reject(self, reason):
        self._stop('protocol_error')
        raise CampaignStopped(reason)

    def _open(self):
        if self._closed or self._stop_reason:
            raise CampaignStopped(self._stop_reason or 'closed')

    def correlation(self):
        if not 1 <= self._round <= 50: self._reject('round_not_bound')
        return {'run_id':self._plan['run_id'],'case_id':self._plan['cases'][0]['case_id'],
            'round_id':str(self._round),'trace_id':self._plan['round_roots'][self._round-1]['trace_id']}

    def before_round(self, case_id, ordinal):
        self._open()
        completed = sum(r.get('status') == 'completed' for r in self._progress['rounds'])
        if (type(ordinal) is not int or ordinal != self._round+1 or ordinal > 50
                or completed != self._round or case_id != self._plan['cases'][0]['case_id']):
            self._reject('round_sequence_differs')
        self._round = ordinal
        return self.correlation()

    @contextmanager
    def background_job(self, *, round_number, job_id):
        self._open()
        if (type(round_number) is not int or round_number != self._round or self._job.get() is not None
                or type(job_id) is not str or not job_id):
            self._reject('job_scope_differs')
        token = self._job.set({'round':round_number,'job_id':job_id})
        try: yield
        finally: self._job.reset(token)

    @contextmanager
    def semantic_attempt(self, *, stage, attempt):
        # A trusted application repair loop must bind this. Changed request IDs
        # or narrative text cannot turn a transport replay into a new attempt.
        self._open()
        if (type(stage) is not str or stage not in _REPAIRS or type(attempt) is not int
                or not 1 <= attempt <= 3 or self._attempt.get() is not None):
            self._reject('semantic_attempt_invalid')
        token = self._attempt.set((self._round, stage, attempt))
        try: yield
        finally: self._attempt.reset(token)

    def _case_receipt(self):
        case = self._plan['cases'][0]
        return {**{k:case[k] for k in ('case_id','owner_id','project_id','language','family_enabled')},
            **deepcopy(self._progress)}

    def _assessment(self, *, complete=False):
        return assess_campaign_receipt(self._plan, {
            **{k:self._plan[k] for k in ('run_id','source_revision','source_tree')},
            'cases':[self._case_receipt()], 'status':'completed' if complete else 'incomplete',
            'execution_started':self._round>0,'evidence_mode':'mock_only','provider_requests_started':None})

    async def observe_progress(self, value):
        self._open()
        if type(value) is not dict or type(value.get('rounds')) is not list or type(value.get('checkpoints')) is not list:
            self._reject('progress_invalid')
        old = self._progress
        self._progress = deepcopy(value)
        try:
            assessment = self._assessment()
            records = value['rounds']
            if (len(records) != self._round or any(type(r) is not dict for r in records)
                    or any(r.get('round') != n for n,r in enumerate(records,1))
                    or any(r.get('status') != 'completed' for r in records[:-1])
                    or set(assessment['errors']) - _EXPECTED_INCOMPLETE
                    or any(not _same_json_literal(r, records[n]) for n,r in enumerate(old['rounds']) if r.get('status')=='completed')):
                self._reject('canonical_progress_invalid')
        except (KeyError, TypeError, ValueError, IndexError):
            self._reject('canonical_progress_invalid')

    async def _drain(self, tasks):
        pending = {t for t in tasks if not t.done()}
        for task in pending: task.cancel()
        if pending:
            _, pending = await asyncio.wait(pending, timeout=_DRAIN_SECONDS)
        self._pending_at_close |= bool(pending)

    async def _bounded(self, awaitable, deadline):
        task = asyncio.ensure_future(awaitable)
        self._tasks.add(task)
        def observed(done):
            self._tasks.discard(done)
            if not done.cancelled(): done.exception()
        task.add_done_callback(observed)
        try:
            done, _ = await asyncio.wait({task}, timeout=max(0, deadline-monotonic()))
            if not done:
                self._stop('operation_failed')
                raise CampaignStopped('operation_deadline')
            return task.result()
        except BaseException:
            self._stop('cancelled' if asyncio.current_task().cancelling() else 'operation_failed')
            await self._drain({task})
            raise

    async def supervise(self, awaitable):
        """Bound the existing driver coroutine; does not create or admit a runtime."""
        self._open()
        return await self._bounded(awaitable, self._ledger.deadline)

    async def _contact_fixture(self, send):
        await asyncio.sleep(send.delay_seconds)
        if send.failure:
            self._stop(send.failure)
            raise CampaignStopped(send.failure)
        return {'response_id':send.response_id, 'wire_model':'synthetic-model',
                'input_tokens':send.input_tokens,'output_tokens':send.output_tokens}

    async def handle_async_request(self, request):
        self._open()
        try:
            if str(request.url) != SYNTHETIC_ORIGIN+'/internal/codex/turn' or request.method != 'POST':
                self._reject('synthetic_endpoint_required')
            data = json.loads(request.content)
            stage = classify_worker_request(data)
            case, correlation = self._plan['cases'][0], self.correlation()
            # Canonical broad extraction deliberately disables legacy Family
            # writes; timeline/locale/composer also carry false (or default false).
            expected_family = case['family_enabled'] if stage in {'collector','focused_place','focused_family'} else False
            family = data.get('family_enabled', False)
            if (data.get('user_id') != case['owner_id']
                    or type(family) is not bool or family != expected_family
                    or (data.get('project_id') != case['project_id'] and not
                        (stage=='initial_locale' and self._round==1 and data.get('project_id') is None))):
                self._reject('worker_scope_differs')
            alias = self._plan['budget']['routing']['stages'][stage]['configuration_alias']
            if data.get('model') not in (None,alias): self._reject('model_policy_differs')
            job = self._job.get()
            if stage in _BACKGROUND and job is None: self._reject('background_job_unbound')
            if job is not None and job['round'] != self._round: self._reject('background_round_stale')
            if (job is None and stage != 'initial_locale') or data.get('evaluation') is not None:
                if not _same_json_literal(data.get('evaluation'),correlation): self._reject('trace_scope_differs')
            if stage=='focused_family' and not case['family_enabled']: self._reject('family_disabled')
            checkpoint = self._round if stage in {'event_preparation','composer_draft','composer_review'} else None
            bound_attempt = self._attempt.get()
            if bound_attempt is not None and bound_attempt[:2] != (self._round,stage):
                self._reject('semantic_attempt_scope_differs')
            attempt = bound_attempt[2] if bound_attempt else 1
            linkage = {'trace_id':correlation['trace_id'], 'request_id':f'worker-{self._fixture_index+1}',
                'observation_id':f'observation-{self._fixture_index+1}'}
            if job: linkage['job_id']=job['job_id']
            if checkpoint: linkage['checkpoint_id']=f"{case['case_id']}:{checkpoint}"
            ticket = self._ledger.begin_worker(WorkerKey(stage,self._round,checkpoint,
                data.get('preparation_id'),attempt),correlation=linkage)
            if self._fixture_index >= len(self._fixtures): self._reject('fixture_exhausted')
            fixture = self._fixtures[self._fixture_index]; self._fixture_index += 1
            for ordinal, send in enumerate(fixture.sends,1):
                send_ticket = self._ledger.reserve_send(ticket,continuation_ordinal=ordinal,
                    observed_scope=self._ledger.declared_send_scope(ticket))
                self._ledger.mark_started(send_ticket)
                completion = await self._bounded(self._contact_fixture(send),send_ticket.deadline)
                self._ledger.settle(send_ticket,completion)
            self._ledger.finish_worker(ticket)
            if request.headers.get('accept') == 'application/x-ndjson':
                return httpx.Response(200, content=json.dumps({'type':'result','data':fixture.result})+'\n',
                    headers={'content-type':'application/x-ndjson'})
            return httpx.Response(200,json=deepcopy(fixture.result))
        except asyncio.CancelledError:
            self._stop('cancelled'); raise
        except BaseException as error:
            self._stop('operation_failed')
            if not isinstance(error, Exception): raise
            raise CampaignStopped('worker_exchange_incomplete') from None

    async def aclose(self):
        # An httpx client is only a borrower. One campaign owns ledger lifecycle.
        pass

    async def finish(self, result=None):
        if self._closed: return
        if result is not None and not self._stop_reason:
            try:
                case = self._plan['cases'][0]
                if (type(result) is not dict or result.get('case_id') != case['case_id']
                        or result.get('project_id') != case['project_id'] or result.get('evidence_mode') != 'mock_only'):
                    self._reject('driver_result_scope_differs')
                await self.observe_progress(result)
                errors = set(self._assessment(complete=True)['errors']) - {'cleanup_verification_missing','actual_request_count_unknown'}
                if errors: self._reject('driver_result_incomplete')
                dispatch = self._ledger.receipt()
                workers = dispatch['workers']
                for stage in ('collector','broad_workspace','canonical_extraction'):
                    if sorted(w['key']['round_number'] for w in workers if
                            w['key']['stage']==stage and w['status']=='completed') != list(range(1,51)):
                        self._reject('required_worker_evidence_missing')
                if dispatch['unsettled_requests'] or any(w['status']!='completed' for w in workers):
                    self._reject('worker_evidence_unsettled')
                self._complete = True
            except Exception:
                self._stop('protocol_error')
        candidate_complete = self._complete
        self._complete = False
        self._closed = True
        # Fence BEFORE cancellation; a late result can never reserve or settle.
        try:
            self._ledger.close()
        finally:
            await self._drain(set(self._tasks))
        cleanup = self._ledger.receipt()['cleanup']
        self._complete = (candidate_complete and not self._stop_reason and not self._pending_at_close
            and cleanup['active_finished'] and cleanup['journal_durable'])

    def receipt(self):
        dispatch = self._ledger.receipt()
        return {'schema_version':'memoir-fifty-synthetic-adapter/1',
            **{k:self._plan[k] for k in ('run_id','source_revision','source_tree')},
            'status':'completed_synthetic' if self._complete and self._closed else 'incomplete',
            'evidence_mode':'mock_only','execution_started':self._round>0,
            'synthetic_pipeline_complete':self._complete and self._closed,
            'cases':[self._case_receipt()], 'budget':deepcopy(self._plan['budget']),
            'dispatch':dispatch, 'provider_requests_started':None, 'live_ready':False,
            'live_execution_authorized':False, 'acceptance_status':'not_established',
            'native_durable_checkpoints_verified':False, 'native_account_and_role_binding_verified':False,
            'cleanup':{'synthetic_tasks_finished':self._closed and not self._pending_at_close and not self._tasks,
                'journal_closed':dispatch['cleanup']['closed'],'native_cleanup_verified':False},
            'coverage':{'canonical_driver':'synthetic_dependencies_only','postgres_temporal':'not_run',
                'browser_login_recovery':'not_run','normal_free_20_round_gate':'separate_required_test',
                'model_quality':'not_graded'}, 'stop_reason':self._stop_reason}
