"""Separate, owned-session orchestration for two progressive chapter cases.

This module has no CLI, provider factory, credentials, native service startup,
judge or publication route. An independently issued session must own and verify
the runtime, scoped stores, workers and shared client-request boundary. Controlled
tests exercise this sequence; they do not establish native/provider evidence.
The historical five-turn CanonicalEvaluationDriver remains entirely untouched.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import math
import inspect
from uuid import UUID, uuid4

from apps.api.agent_storage import UserStorage
from apps.api.diagnostics import failure_class
from scripts.issue14_progressive_readback import CASE_IDS, ProgressiveReadback
from scripts.issue14_subscription_transport import SubscriptionStopped
from scripts.task_runtime import dispatch_memoir_lanes_once
from scripts.memoir_subscription_profiles import profile_for


EVIDENCE_MODE = 'subscription_progressive'
CHECKPOINTS = (5, 10, 15)
_ERROR_REASONS = frozenset({'session_unverified', 'turn_incomplete', 'correlation_mismatch',
    'background_incomplete', 'readback_incomplete', 'checkpoint_incomplete',
    'evidence_mode_invalid', 'case_plan_invalid', 'storage_scope_invalid',
    'project_not_fresh', 'lane_incomplete', 'runner_already_used',
    'session_binding_changed', 'deadline_exceeded', 'requests_unsettled',
    'accounting_unavailable', 'requests_stopped'})


class SubscriptionRunnerError(ValueError):
    """Fixed, content-free execution reason; never a provider exception body."""


def _error_reason(error):
    # Even a caller raising our exception class cannot inject arbitrary content
    # into an evidence error field. Do not invoke an overridden __str__ method.
    reason = error.args[0] if error.args else None
    return reason if type(reason) is str and reason in _ERROR_REASONS else 'execution_failed'


def assert_owned_subscription_session(value):
    """Resolve the issuer's exact ownership gate, never a duck-typed assertion.

    Keeping this import lazy makes an absent binding fail closed before reading
    the supplied object, and keeps import alone free of runtime construction.
    Tests replace this function only for one explicitly registered fake session.
    """
    try:
        from scripts.issue14_subscription_session import assert_owned_subscription_session as verify
    except ImportError:
        raise SubscriptionRunnerError('session_unverified') from None
    verify(value)


def _require(condition, reason):
    if not condition:
        raise SubscriptionRunnerError(reason)


def _exact_integer(value, expected):
    return type(value) is int and value == expected


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


async def _settle_task(task):
    """Join already-owned work even if the parent receives more cancellations."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    return task.result(), cancelled


async def _storage_read(function, *args):
    # Cancellation of to_thread alone does not stop its database request. Keep
    # ownership of that request and join it before closing or changing scope.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await _settle_task(task)
        except Exception:
            pass
        raise


def _runtime_readback(value, correlation):
    _require(type(value) is dict and type(value.get('reply')) is str
             and value['reply'].strip() and type(value.get('accepted_source_id')) is str
             and value['accepted_source_id'], 'turn_incomplete')
    trajectory = value.get('trajectory')
    _require(type(trajectory) is dict and type(trajectory.get('correlation')) is dict
             and all(trajectory['correlation'].get(key) == expected
                     for key, expected in correlation.items()), 'correlation_mismatch')
    final = trajectory.get('final')
    _require(type(final) is dict and final.get('status') == 'completed'
             and not final.get('error'), 'turn_incomplete')
    _require(not value.get('task_errors'), 'background_incomplete')
    for task in value.get('tasks', []):
        _require(type(task) is dict and task.get('status') in {'completed', 'succeeded', 'SUCCEEDED'},
                 'background_incomplete')
    # User-visible trace entries are the latest states, unlike protocol steps
    # which legitimately retain earlier running events from a completed call.
    for step in value.get('trace', []):
        _require(type(step) is dict and step.get('status') in {'completed', 'succeeded', 'SUCCEEDED'},
                 'background_incomplete')
    failures = {'failed', 'cancelled', 'canceled', 'retry', 'retry_required', 'pending'}
    for step in trajectory.get('steps', []):
        _require(type(step) is dict, 'background_incomplete')
        action = step.get('action', '')
        output = step.get('output')
        _require(not step.get('error') and step.get('protocol_failed') is not True
                 and step.get('status') not in failures
                 and not (type(action) is str and action.rsplit('.', 1)[-1] in failures),
                 'background_incomplete')
        if type(output) is dict:
            _require(not output.get('error') and not output.get('retryable')
                     and not output.get('pending') and output.get('status') not in failures,
                     'background_incomplete')
    limits = trajectory.get('limits', {})
    _require(type(limits) is dict and not limits.get('overflowed')
             and not limits.get('dropped_steps'), 'background_incomplete')
    state = final.get('state', {})
    _require(type(state) is dict and not state.get('task_error_count')
             and all(status in {'completed', 'succeeded', 'SUCCEEDED'}
                     for status in state.get('task_statuses', [])), 'background_incomplete')
    # The canonical bridge needs only correlation and final state. Never copy
    # arbitrary runtime metadata or hidden reasoning into the returned artifact.
    return {'reply': value['reply'], 'accepted_source_id': value['accepted_source_id'],
            'trajectory': {'correlation': deepcopy(correlation), 'final': {'status': 'completed'}}}


def _canonical_state(value, inputs, accepted):
    ordinal = len(accepted)
    _require(type(value) is dict and value.get('project_id') == inputs['project_id']
             and _exact_integer(value.get('completed_rounds'), ordinal), 'readback_incomplete')
    processing = value.get('processing')
    _require(type(processing) is dict and _exact_integer(processing.get('extracted_through'), ordinal)
             and _exact_integer(processing.get('pending_inputs'), 0), 'readback_incomplete')
    sources = value.get('sources')
    _require(type(sources) is list and len(sources) == ordinal
             and len(set(accepted)) == ordinal, 'readback_incomplete')
    for index, source in enumerate(sources, 1):
        _require(type(source) is dict and source.get('id') == accepted[index - 1]
                 and source.get('text') == inputs['rounds'][index - 1]
                 and source.get('project_id') == inputs['project_id']
                 and source.get('language') == inputs['language']
                 and source.get('kind') == 'narrator_chat' and source.get('status') == 'active'
                 and _exact_integer(source.get('version'), 1)
                 and _exact_integer(source.get('sequence'), index), 'readback_incomplete')


def _saved_checkpoint(draft, ordinal, language):
    # Stop immediately on a pending/failed saved milestone. Full references,
    # fingerprints and revision consistency are checked by the pure bridge.
    _require(type(draft) is dict and draft.get('status') == 'ready'
             and draft.get('updating') is False and draft.get('error') is None
             and draft.get('proposal_pending') is False
             and _exact_integer(draft.get('covered_round'), ordinal)
             and _exact_integer(draft.get('milestone'), ordinal)
             and type(draft.get('revision')) is int and draft['revision'] > 0,
             'checkpoint_incomplete')
    progress = draft.get('progress')
    extraction = progress.get('extraction') if type(progress) is dict else None
    _require(type(extraction) is dict and _exact_integer(extraction.get('extracted_through'), ordinal)
             and _exact_integer(extraction.get('pending_inputs'), 0), 'checkpoint_incomplete')
    preview = draft.get('preview')
    _require(type(preview) is dict and preview.get('locale') == language
             and type(preview.get('text')) is str and preview['text'].strip(), 'checkpoint_incomplete')
    milestones = draft.get('milestones')
    _require(type(milestones) is list and len(milestones) == ordinal // 5, 'checkpoint_incomplete')
    for row, milestone in zip(milestones, range(5, ordinal + 1, 5)):
        _require(type(row) is dict and row.get('state') == 'completed'
                 and _exact_integer(row.get('milestone'), milestone)
                 and _exact_integer(row.get('covered_round'), milestone), 'checkpoint_incomplete')
    _require(type(draft.get('sections')) is list and draft['sections'], 'checkpoint_incomplete')


class SubscriptionProgressiveRunner:
    """One-shot, serial original-turn/readback execution on an issued session.

    A session is never admitted by this class. Its issuer must already establish
    authority, synthetic owner/project isolation, single-attempt worker binding,
    cleanup ownership and one shared run-wide transport gate. No requested
    numerical limits are defaulted or inferred here.
    """

    def __init__(self, session, *, evidence_mode=EVIDENCE_MODE):
        _require(evidence_mode in (EVIDENCE_MODE, 'subscription_fifty'), 'evidence_mode_invalid')
        self._profile = profile_for(evidence_mode)
        assert_owned_subscription_session(session)
        # No attribute on an unverified object is inspected above this line.
        _require(getattr(session, 'evaluation_profile', EVIDENCE_MODE) == evidence_mode, 'evidence_mode_invalid')
        case_ids = self._profile.case_ids
        canonical_plans = self._profile.plans(session.run.run_id)
        plans = session.case_plans
        _require(type(plans) is dict and set(plans) == set(case_ids)
                 and tuple(session.case_ids) == case_ids, 'case_plan_invalid')
        owners, projects = set(), set()
        for case in case_ids:
            plan = plans[case]
            _require(type(plan) is dict and plan.get('case_id') == case
                     and plan.get('language') == canonical_plans[case]['language']
                     and _uuid(plan.get('owner_id')) and _uuid(plan.get('project_id')),
                     'case_plan_invalid')
            owners.add(plan['owner_id'])
            projects.add(plan['project_id'])
        if evidence_mode == 'subscription_fifty':
            _require(plans == canonical_plans, 'case_plan_invalid')
        _require(len(owners) == len(projects) == len(case_ids) and not owners.intersection(projects), 'case_plan_invalid')
        _require(type(session.task_queue) is str and session.task_queue.startswith('canary-'), 'case_plan_invalid')
        self._session, self._plans, self._used = session, deepcopy(plans), False
        self._progress = None
        self._run_id, self._revision, self._queue = session.run.run_id, session.run.source_revision, session.task_queue
        self._bridges = {case: self._profile.bridge(case_id=case, run_id=session.run.run_id,
            project_id=plans[case]['project_id'], source_revision=session.run.source_revision) for case in case_ids}

    async def _emit(self, receipt):
        if self._progress is not None:
            try:
                result = self._progress(deepcopy(receipt))
                if inspect.isawaitable(result):
                    await result
            except Exception:
                self._progress = None
                raise SubscriptionRunnerError('execution_failed') from None

    async def _execute(self, receipt):
        session = self._session
        receipt['execution_stage'] = 'initial_readback'
        storages = {}
        # Validate every fresh project before dispatching any original narration.
        for case in self._profile.case_ids:
            storage = session.storage_for_case(case)
            _require(isinstance(storage, UserStorage)
                     and storage.user_id == self._plans[case]['owner_id'], 'storage_scope_invalid')
            initial = await _storage_read(storage.memory_events, self._plans[case]['project_id'])
            _canonical_state(initial, self._bridges[case].driver_inputs(), [])
            _require(initial.get('events') == [], 'project_not_fresh')
            storages[case] = storage
        for partial in receipt['cases']:
            case = partial['case_id']
            bridge, storage = self._bridges[case], storages[case]
            inputs, accepted = bridge.driver_inputs(), []
            partial['status'] = 'running'
            for ordinal, text in enumerate(inputs['rounds'], 1):
                record = {'round': ordinal, 'status': 'started', 'background_settled': False}
                partial['rounds'].append(record)
                correlation = bridge.before_round(case, ordinal)
                _require(session.activate_round(case, ordinal) == correlation, 'correlation_mismatch')
                async with asyncio.timeout(session.run.remaining_seconds()):
                    receipt['execution_stage'] = 'collector_turn'
                    browser = getattr(session, 'browser_readback', None)
                    if browser is not None and browser.turns_enabled:
                        record['turn_delivery'] = 'browser_form'
                        value = await browser.turn(case, ordinal, text)
                    else:
                        record['turn_delivery'] = 'direct_api'
                        value = await session.runtime.turn(storage, text, project_id=inputs['project_id'],
                            language=inputs['language'], client_turn_id=str(uuid4()), include_trajectory=True,
                            evaluation=deepcopy(correlation), conversation_text=text, source_kind='narrator_chat')
                    receipt['execution_stage'] = 'runtime_readback'
                    record.update(_runtime_readback(value, correlation), status='delivered')
                    accepted.append(record['accepted_source_id'])
                    receipt['execution_stage'] = 'background_dispatch'
                    handles = await dispatch_memoir_lanes_once(session.temporal_client, session.broker,
                                                             session.task_queue, single_attempt=True)
                    receipt['execution_stage'] = 'background_settlement'
                    for handle in handles:
                        _require(type(handle.id) is str and handle.id, 'lane_incomplete')
                        if handle.id not in partial['workflow_ids']:
                            partial['workflow_ids'].append(handle.id)
                        outcome = await handle.result()
                        _require(type(outcome) is dict and outcome.get('status') == 'finished'
                                 and outcome.get('pending', False) is False and not outcome.get('error')
                                 and not outcome.get('retryable')
                                 and _exact_integer(outcome.get('attempt', 1), 1), 'lane_incomplete')
                    receipt['execution_stage'] = 'canonical_readback'
                    view = await _storage_read(storage.memory_events, inputs['project_id'])
                    _canonical_state(view, inputs, accepted)
                    record['canonical_state'] = deepcopy(view)
                    draft = None
                    if ordinal in self._profile.checkpoints:
                        receipt['execution_stage'] = 'checkpoint_readback'
                        draft = await _storage_read(storage.saved_memoir_draft, inputs['project_id'], inputs['language'])
                        _saved_checkpoint(draft, ordinal, inputs['language'])
                        partial['checkpoints'].append({'milestone': ordinal, 'draft': deepcopy(draft)})
                    if self._profile.name == 'subscription_fifty':
                        from scripts.memoir_fifty_coverage import round_skill_coverage, runtime_family_decision
                        receipt['execution_stage'] = 'skill_readback'
                        profile = await _storage_read(storage.profile)
                        family = await _storage_read(storage.family_context, inputs['project_id'])
                        journey = await _storage_read(storage.place_journey)
                        record['planned_family_enabled'] = self._profile.family_enabled_for_round(self._plans[case], ordinal)
                        record['skill_coverage'] = round_skill_coverage(
                            project_id=inputs['project_id'], round_number=ordinal,
                            runtime_result=value, profile=profile, family_context=family,
                            place_journey=journey, canonical_state=view, saved_draft=draft,
                            family_enabled=runtime_family_decision(value))
                    if self._profile.name == 'subscription_fifty' and getattr(session, 'photo_research', None) is not None:
                        receipt['execution_stage'] = 'photo_research'
                        record['photo_research'] = await session.photo_research.observe_round(
                            case_id=case, ordinal=ordinal, runtime_result=value)
                    # Extraction may create a bookkeeping outbox row. Drain it while
                    # the same case/round owns the scope; never dispatch a retry.
                    receipt['execution_stage'] = 'background_drain'
                    await session.broker.drain_once()
                    pending = await session.broker.rpc('pending_memoir_lanes', p_limit=100)
                    _require(type(pending) is list and not pending, 'background_incomplete')
                    session.finish_round()
                    record.update(background_settled=True, status='completed')
                    receipt['execution_stage'] = 'progress_receipt'
                    await self._emit(receipt)
            partial['status'] = 'completed'
            partial['workflow_ids'].sort()
            receipt['execution_stage'] = 'case_observation'
            observation = bridge.observation(partial)
            if observation['output'] is None:
                partial['status'] = 'incomplete'
            _require(observation['output'] is not None, 'readback_incomplete')
            partial['observation'] = observation
            if self._profile.name == 'subscription_fifty':
                from scripts.memoir_fifty_coverage import case_skill_coverage
                partial['skill_coverage'] = case_skill_coverage(case_id=case, rounds=partial['rounds'])
                if getattr(session, 'browser_readback', None) is not None:
                    receipt['execution_stage'] = 'browser_case_readback'
                    partial['browser_readback'] = await session.browser_readback.observe_case(case)
                session.finish_case(case)
        receipt['status'] = 'completed'
        if self._profile.name == 'subscription_fifty':
            receipt['e2e_status'] = 'partial'
            receipt['e2e_passed'] = False
            receipt['coverage_basis'] = 'saved_application_readbacks_not_full_browser_or_photo_judge_evidence'
        receipt['execution_stage'] = 'completed'

    async def run(self, *, progress=None):
        _require(progress is None or callable(progress), 'execution_failed')
        _require(not self._used, 'runner_already_used')
        assert_owned_subscription_session(self._session)
        _require(self._session.case_plans == self._plans
                 and tuple(self._session.case_ids) == self._profile.case_ids
                 and getattr(self._session, 'evaluation_profile', EVIDENCE_MODE) == self._profile.name
                 and self._session.task_queue == self._queue
                 and self._session.run.run_id == self._run_id
                 and self._session.run.source_revision == self._revision, 'session_binding_changed')
        self._used = True
        self._progress = progress
        session = self._session
        metadata_key = ('memoir_fifty_readback_status' if self._profile.name == 'subscription_fifty'
                        else 'issue14_progressive_readback_status')
        receipt = {'schema_version': 'memoir-subscription-progressive-run/1',
            'run_id': session.run.run_id, 'source_revision': session.run.source_revision,
            'evidence_mode': self._profile.name, 'status': 'running', 'output': None,
            'execution_stage': 'runner_start',
            **({'e2e_status': 'partial', 'e2e_passed': False} if self._profile.name == 'subscription_fifty' else {}),
            'semantic_acceptance': 'human_review_required', 'live_ready': False,
            'rounds_per_case': self._profile.rounds, 'checkpoints': list(self._profile.checkpoints),
            'cases': [{**deepcopy(self._plans[case]), 'evidence_mode': self._profile.name,
                       'status': 'not_started', 'rounds': [], 'checkpoints': [], 'workflow_ids': [],
                       'observation': {'output': None, 'metadata': {'live_ready': False,
                           metadata_key: 'unavailable'}}} for case in self._profile.case_ids],
            'cleanup': {'session_closed': False}}

        def fail(reason, classification='exception'):
            receipt.setdefault('failure_stage', receipt['execution_stage'])
            receipt.setdefault('failure_class', classification)
            receipt.update(status='incomplete', output=None)
            receipt.setdefault('stop_reason', reason)
            for case in receipt['cases']:
                if case['status'] == 'running':
                    case['status'] = 'incomplete'
                    if case['rounds'] and not case['rounds'][-1]['background_settled']:
                        case['rounds'][-1].update(status='failed', stop_reason=reason)
            try:
                session.run.stop('elapsed_limit' if reason == 'deadline_exceeded'
                                 else reason if reason in ('case_requests_limit', 'case_elapsed_limit')
                                 else 'send_interrupted_or_failed')
            except Exception:
                receipt['stop_recorded'] = False

        work = None
        try:
            remaining = session.run.remaining_seconds()
            _require(type(remaining) in (int, float) and math.isfinite(remaining)
                     and remaining > 0, 'deadline_exceeded')
            # One absolute timeout covers preflight, every original turn, readbacks,
            # workflow settlement and scope teardown; it never resets per turn.
            deadline = asyncio.get_running_loop().time() + remaining
            async with asyncio.timeout_at(deadline):
                await self._emit(receipt)
                # Shield execution so the outer handler can first close the
                # shared admission gate, then cancel/join all owned work.
                work = asyncio.create_task(self._execute(receipt))
                await asyncio.shield(work)
                _require(session.run.remaining_seconds() > 0, 'deadline_exceeded')
        except asyncio.CancelledError:
            fail('cancelled', 'cancelled')
        except TimeoutError:
            reason = ('case_elapsed_limit' if self._profile.name == 'subscription_fifty'
                      and session.run.timeout_reason() == 'case_elapsed_limit' else 'deadline_exceeded')
            fail(reason, 'timeout')
        except SubscriptionRunnerError as error:
            fail(_error_reason(error), 'validation')
        except SubscriptionStopped as error:
            fail({'elapsed_limit': 'deadline_exceeded', 'requests_limit': 'requests_limit'}
                 .get(str(error), str(error) if str(error) in ('case_requests_limit', 'case_elapsed_limit') else 'execution_failed'))
        except Exception as error:
            fail('execution_failed', failure_class(error))
        finally:
            if work is not None and not work.done():
                work.cancel()
                try:
                    await _settle_task(work)
                except (Exception, asyncio.CancelledError):
                    pass
            closing = asyncio.create_task(session.close())
            try:
                _, cancelled = await _settle_task(closing)
                receipt['cleanup']['session_closed'] = True
                if cancelled:
                    fail('cancelled')
            except (Exception, asyncio.CancelledError):
                fail('cleanup_failed')
            try:
                receipt['request_accounting'] = deepcopy(session.run.snapshot())
                accounting = receipt['request_accounting']
                _require(type(accounting) is dict
                         and _exact_integer(accounting.get('unresolved_requests'), 0),
                         'requests_unsettled')
                _require(accounting.get('run_id') == self._run_id
                         and accounting.get('source_revision') == self._revision
                         and accounting.get('journal_durable') is True
                         and accounting.get('closed') is True
                         and accounting.get('counted_boundary') == 'client_to_existing_gateway_http_requests'
                         and _exact_integer(accounting.get('concurrency'), 1), 'accounting_unavailable')
                if receipt['status'] == 'completed':
                    _require(accounting.get('stop_reason') in (None, 'closed'), 'requests_stopped')
                    if self._profile.name == 'subscription_fifty':
                        cases = accounting.get('cases')
                        _require(type(cases) is list and len(cases) == 5
                            and [c.get('case_id') for c in cases] == list(self._profile.case_ids)
                            and all(c.get('status') == 'completed' and c.get('unresolved_requests') == 0
                                    for c in cases), 'accounting_unavailable')
            except SubscriptionRunnerError as error:
                fail(_error_reason(error), 'validation')
            except Exception:
                fail('accounting_unavailable')
        if receipt['status'] == 'completed':
            receipt['output'] = [deepcopy(case['observation']['output']) for case in receipt['cases']]
        else:
            # Partial actual saved readbacks remain available above. An aborted
            # run never exposes experiment output as though the run completed.
            for case in receipt['cases']:
                case['observation']['output'] = None
                case['observation']['metadata'][metadata_key] = 'unavailable'
        try:
            worker_receipts = getattr(session, 'worker_receipts', None)
            if callable(worker_receipts):
                receipt['worker_receipts'] = worker_receipts()
            await self._emit(receipt)
        except (Exception, asyncio.CancelledError):
            fail('execution_failed')
            for case in receipt['cases']:
                case['observation']['output'] = None
        return receipt
