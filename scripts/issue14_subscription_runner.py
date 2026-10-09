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
from apps.api.diagnostics import failure_class, sanitize_json_failure_details
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


_READBACK_PREDICATES = {
    'runtime': frozenset({
        'result_shape', 'reply_type', 'reply_empty', 'accepted_source_type', 'accepted_source_empty',
        'trajectory_shape', 'correlation_shape', 'correlation_mismatch', 'final_shape', 'final_status',
        'final_error', 'task_errors', 'tasks_shape', 'task_shape', 'task_status', 'trace_shape',
        'trace_entry_shape', 'trace_status', 'steps_shape', 'step_shape', 'step_error',
        'step_protocol_failed', 'step_status_shape', 'step_status', 'step_action_status',
        'step_output_error', 'step_output_retryable', 'step_output_pending', 'step_output_status_shape',
        'step_output_status', 'limits_shape', 'trajectory_overflow', 'trajectory_dropped_steps',
        'final_state_shape', 'workspace_failure', 'task_error_count', 'task_statuses_shape',
        'final_task_status', 'helper_exception',
    }),
    'canonical': frozenset({
        'state_shape', 'project_mismatch', 'completed_rounds', 'processing_shape', 'extracted_through',
        'pending_inputs', 'sources_shape', 'source_count', 'accepted_source_uniqueness', 'source_shape',
        'source_id', 'source_text', 'source_project', 'source_language', 'source_kind', 'source_status',
        'source_version', 'source_sequence', 'helper_exception',
    }),
    'checkpoint': frozenset({
        'draft_shape', 'draft_status', 'updating', 'error', 'proposal_pending', 'covered_round',
        'milestone', 'revision', 'progress_shape', 'extraction_shape', 'extracted_through',
        'pending_inputs', 'preview_shape', 'preview_locale', 'preview_text_type', 'preview_text_empty',
        'milestones_shape', 'milestone_count', 'milestone_shape', 'milestone_status', 'milestone_ordinal',
        'milestone_covered_round', 'sections_shape', 'sections_empty', 'helper_exception',
    }),
    'settlement': frozenset({'handle_id', 'outcome_shape', 'outcome_status', 'outcome_pending',
        'outcome_error', 'outcome_retryable', 'outcome_attempt', 'pending_shape', 'pending_lanes', 'helper_exception'}),
    'case': frozenset({'observation_unavailable', 'helper_exception'}),
}
_COMPLETED_STATUSES = frozenset({'completed', 'succeeded', 'SUCCEEDED'})
_FAILED_STATUSES = frozenset({'failed', 'cancelled', 'canceled', 'retry', 'retry_required', 'pending'})
_DIAGNOSTIC_STATUSES = _COMPLETED_STATUSES | _FAILED_STATUSES | frozenset({
    'running', 'started', 'queued', 'QUEUED', 'ready', 'finished', 'incomplete',
    'triggered', 'skipped', 'active', 'missing', 'invalid', 'unrecognized',
})
_TRACE_CATEGORIES = frozenset({'memoir-family-tree', 'memoir-author-timeline',
    'context', 'reply', 'save', 'workspace', 'place', 'memory-context', 'language', 'other'})
_ACTION_CATEGORIES = frozenset({'artifact', 'workspace', 'recovery', 'worker', 'protocol', 'other'})


def _trace_category(value):
    return value if type(value) is str and value in _TRACE_CATEGORIES else 'other'


def _action_category(value):
    if type(value) is not str:
        return 'other'
    if value.startswith('artifact.'):
        return 'artifact'
    if value.startswith('workspace.family_recovery.'):
        return 'recovery'
    if value.startswith('workspace.'):
        return 'workspace'
    if value.startswith('codex.worker.'):
        return 'worker'
    if value.startswith(('protocol.', 'thread/', 'turn/', 'item/')):
        return 'protocol'
    return 'other'


def _safe_status(value):
    if value is None:
        return 'missing'
    if type(value) is not str:
        return 'invalid'
    return value if value in _DIAGNOSTIC_STATUSES else 'unrecognized'


def _sanitize_readback_diagnostic(value, boundary):
    """Fixed labels and bounded numbers only; never copy caller data or IDs."""
    if (type(value) is not dict or type(value.get('predicate')) is not str
            or value['predicate'] not in _READBACK_PREDICATES[boundary]):
        return None
    safe = {'schema_version': f'memoir-{boundary}-readback-diagnostic/1',
            'boundary': boundary, 'predicate': value['predicate']}
    collection = value.get('collection')
    if type(collection) is str and collection in {'tasks', 'trace', 'steps', 'task_statuses', 'sources', 'milestones', 'handles'}:
        safe['collection'] = collection
    index = value.get('index')
    if type(index) is int and 0 <= index <= 2**31 - 1:
        safe['index'] = index
    count = value.get('count')
    if type(count) is int and 0 <= count <= 2**31 - 1:
        safe['count'] = count
    if 'status' in value:
        safe['status'] = _safe_status(value['status'])
    for key, allowed in (('trace_category', _TRACE_CATEGORIES), ('action_category', _ACTION_CATEGORIES)):
        category = value.get(key)
        if type(category) is str and category in allowed:
            safe[key] = category
    action_status = value.get('action_status')
    if type(action_status) is str and action_status in _FAILED_STATUSES:
        safe['action_status'] = action_status
    limits = value.get('trajectory_limits')
    if type(limits) is dict:
        projected = {key: limits[key] for key in ('max_steps', 'observed_steps', 'dropped_steps')
                     if type(limits.get(key)) is int and 0 <= limits[key] <= 2**31 - 1}
        if type(limits.get('overflowed')) is bool:
            projected['overflowed'] = limits['overflowed']
        if projected:
            safe['trajectory_limits'] = projected
    return safe


def _readback_require(condition, reason, boundary, predicate, **details):
    if not condition:
        error = SubscriptionRunnerError(reason)
        error.readback_diagnostic = _sanitize_readback_diagnostic({'predicate': predicate, **details}, boundary)
        raise error


def _readback_call(record, boundary, function, *args):
    """Save a detached safe diagnostic even when the readback must reject."""
    try:
        return function(*args)
    except Exception as error:
        try:
            diagnostic = _sanitize_readback_diagnostic(getattr(error, 'readback_diagnostic', None), boundary)
        except Exception:
            diagnostic = None
        record[f'{boundary}_readback_diagnostic'] = diagnostic or {
            'schema_version': f'memoir-{boundary}-readback-diagnostic/1',
            'boundary': boundary, 'predicate': 'helper_exception'}
        raise


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


def _runtime_failure_summary(value, correlation):
    """Retain only a small, same-round parser location before strict rejection."""
    if type(value) is not dict:
        return None
    trajectory = value.get('trajectory')
    if (type(trajectory) is not dict or type(trajectory.get('correlation')) is not dict
            or not all(trajectory['correlation'].get(key) == expected
                       for key, expected in correlation.items())):
        return None
    # The recorder can exhaust its step budget before workspace.failed. Its
    # bounded final state is independent of that budget, but remains untrusted
    # evidence that must be projected again under this exact round correlation.
    outputs = []
    final = trajectory.get('final')
    state = final.get('state') if type(final) is dict else None
    terminal = state.get('workspace_failure') if type(state) is dict else None
    if type(terminal) is dict and terminal.get('action') == 'workspace.failed':
        outputs.append(terminal)
    steps = trajectory.get('steps')
    if type(steps) is list:
        outputs.extend(step.get('output') for step in reversed(steps[-512:])
                       if type(step) is dict and step.get('action') == 'workspace.failed')
    for output in outputs:
        details = sanitize_json_failure_details(output)
        if not details:
            continue
        summary = {'action': 'workspace.failed', **details}
        if type(output.get('retryable')) is bool:
            summary['retryable'] = output['retryable']
        if _uuid(value.get('accepted_source_id')):
            summary['accepted_source_id'] = value['accepted_source_id']
        return summary
    return None


def _runtime_readback(value, correlation):
    trajectory, correlation_verified = None, False
    def check(condition, predicate, **details):
        reason = ('correlation_mismatch' if predicate in {'trajectory_shape', 'correlation_shape', 'correlation_mismatch'}
                  else 'turn_incomplete' if predicate in {'result_shape', 'reply_type', 'reply_empty',
                    'accepted_source_type', 'accepted_source_empty', 'final_shape', 'final_status', 'final_error'}
                  else 'background_incomplete')
        if correlation_verified:
            details['trajectory_limits'] = trajectory.get('limits')
        _readback_require(condition, reason, 'runtime', predicate, **details)
    def entries(items, predicate):
        try:
            return enumerate(iter(items))
        except TypeError:
            check(False, predicate)
    def member(status, choices):
        try:
            return status in choices
        except TypeError:
            return False
    def nonfailure(status, shape_predicate, predicate, **details):
        try:
            failed = status in _FAILED_STATUSES
        except TypeError:
            check(False, shape_predicate, status=status, **details)
        check(not failed, predicate, status=status, **details)

    check(type(value) is dict, 'result_shape')
    check(type(value.get('reply')) is str, 'reply_type')
    check(value['reply'].strip(), 'reply_empty')
    check(type(value.get('accepted_source_id')) is str, 'accepted_source_type')
    check(value['accepted_source_id'], 'accepted_source_empty')
    trajectory = value.get('trajectory')
    check(type(trajectory) is dict, 'trajectory_shape')
    check(type(trajectory.get('correlation')) is dict, 'correlation_shape')
    check(all(trajectory['correlation'].get(key) == expected for key, expected in correlation.items()), 'correlation_mismatch')
    correlation_verified = True
    final = trajectory.get('final')
    check(type(final) is dict, 'final_shape')
    check(final.get('status') == 'completed', 'final_status', status=final.get('status'))
    check(not final.get('error'), 'final_error')
    check(not value.get('task_errors'), 'task_errors')
    for index, task in entries(value.get('tasks', []), 'tasks_shape'):
        details = {'collection': 'tasks', 'index': index}
        check(type(task) is dict, 'task_shape', **details)
        check(member(task.get('status'), _COMPLETED_STATUSES), 'task_status', status=task.get('status'), **details)
    # User-visible trace entries are the latest states, unlike protocol steps
    # which legitimately retain earlier running events from a completed call.
    for index, step in entries(value.get('trace', []), 'trace_shape'):
        details = {'collection': 'trace', 'index': index}
        check(type(step) is dict, 'trace_entry_shape', **details)
        details['trace_category'] = _trace_category(step.get('id'))
        check(member(step.get('status'), _COMPLETED_STATUSES), 'trace_status', status=step.get('status'), **details)
    for index, step in entries(trajectory.get('steps', []), 'steps_shape'):
        details = {'collection': 'steps', 'index': index}
        check(type(step) is dict, 'step_shape', **details)
        action = step.get('action', '')
        details['action_category'] = _action_category(action)
        output = step.get('output')
        check(not step.get('error'), 'step_error', **details)
        check(step.get('protocol_failed') is not True, 'step_protocol_failed', **details)
        nonfailure(step.get('status'), 'step_status_shape', 'step_status', **details)
        action_status = action.rsplit('.', 1)[-1] if type(action) is str else None
        check(not (type(action) is str and action_status in _FAILED_STATUSES),
              'step_action_status', action_status=action_status, **details)
        if type(output) is dict:
            check(not output.get('error'), 'step_output_error', **details)
            check(not output.get('retryable'), 'step_output_retryable', **details)
            check(not output.get('pending'), 'step_output_pending', **details)
            nonfailure(output.get('status'), 'step_output_status_shape', 'step_output_status', **details)
    limits = trajectory.get('limits', {})
    check(type(limits) is dict, 'limits_shape')
    check(not limits.get('overflowed'), 'trajectory_overflow')
    check(not limits.get('dropped_steps'), 'trajectory_dropped_steps')
    state = final.get('state', {})
    check(type(state) is dict, 'final_state_shape')
    check(not state.get('workspace_failure'), 'workspace_failure')
    check(not state.get('task_error_count'), 'task_error_count')
    for index, status in entries(state.get('task_statuses', []), 'task_statuses_shape'):
        check(member(status, _COMPLETED_STATUSES), 'final_task_status', status=status,
              collection='task_statuses', index=index)
    # The canonical bridge needs only correlation and final state. Never copy
    # arbitrary runtime metadata or hidden reasoning into the returned artifact.
    return {'reply': value['reply'], 'accepted_source_id': value['accepted_source_id'],
            'trajectory': {'correlation': deepcopy(correlation), 'final': {'status': 'completed'}}}


def _canonical_state(value, inputs, accepted):
    def check(condition, predicate, **details):
        _readback_require(condition, 'readback_incomplete', 'canonical', predicate, **details)
    ordinal = len(accepted)
    check(type(value) is dict, 'state_shape')
    check(value.get('project_id') == inputs['project_id'], 'project_mismatch')
    check(_exact_integer(value.get('completed_rounds'), ordinal), 'completed_rounds')
    processing = value.get('processing')
    check(type(processing) is dict, 'processing_shape')
    check(_exact_integer(processing.get('extracted_through'), ordinal), 'extracted_through')
    check(_exact_integer(processing.get('pending_inputs'), 0), 'pending_inputs')
    sources = value.get('sources')
    check(type(sources) is list, 'sources_shape')
    check(len(sources) == ordinal, 'source_count')
    check(len(set(accepted)) == ordinal, 'accepted_source_uniqueness')
    for index, source in enumerate(sources, 1):
        details = {'collection': 'sources', 'index': index - 1}
        check(type(source) is dict, 'source_shape', **details)
        check(source.get('id') == accepted[index - 1], 'source_id', **details)
        check(source.get('text') == inputs['rounds'][index - 1], 'source_text', **details)
        check(source.get('project_id') == inputs['project_id'], 'source_project', **details)
        check(source.get('language') == inputs['language'], 'source_language', **details)
        check(source.get('kind') == 'narrator_chat', 'source_kind', **details)
        check(source.get('status') == 'active', 'source_status', status=source.get('status'), **details)
        check(_exact_integer(source.get('version'), 1), 'source_version', **details)
        check(_exact_integer(source.get('sequence'), index), 'source_sequence', **details)


def _saved_checkpoint(draft, ordinal, language):
    # Stop immediately on a pending/failed saved milestone. Full references,
    # fingerprints and revision consistency are checked by the pure bridge.
    def check(condition, predicate, **details):
        _readback_require(condition, 'checkpoint_incomplete', 'checkpoint', predicate, **details)
    check(type(draft) is dict, 'draft_shape')
    check(draft.get('status') == 'ready', 'draft_status', status=draft.get('status'))
    check(draft.get('updating') is False, 'updating')
    check(draft.get('error') is None, 'error')
    check(draft.get('proposal_pending') is False, 'proposal_pending')
    check(_exact_integer(draft.get('covered_round'), ordinal), 'covered_round')
    check(_exact_integer(draft.get('milestone'), ordinal), 'milestone')
    check(type(draft.get('revision')) is int and draft['revision'] > 0, 'revision')
    progress = draft.get('progress')
    check(type(progress) is dict, 'progress_shape')
    extraction = progress.get('extraction')
    check(type(extraction) is dict, 'extraction_shape')
    check(_exact_integer(extraction.get('extracted_through'), ordinal), 'extracted_through')
    check(_exact_integer(extraction.get('pending_inputs'), 0), 'pending_inputs')
    preview = draft.get('preview')
    check(type(preview) is dict, 'preview_shape')
    check(preview.get('locale') == language, 'preview_locale')
    check(type(preview.get('text')) is str, 'preview_text_type')
    check(preview['text'].strip(), 'preview_text_empty')
    milestones = draft.get('milestones')
    check(type(milestones) is list, 'milestones_shape')
    check(len(milestones) == ordinal // 5, 'milestone_count')
    for index, (row, milestone) in enumerate(zip(milestones, range(5, ordinal + 1, 5))):
        details = {'collection': 'milestones', 'index': index}
        check(type(row) is dict, 'milestone_shape', **details)
        check(row.get('state') == 'completed', 'milestone_status', status=row.get('state'), **details)
        check(_exact_integer(row.get('milestone'), milestone), 'milestone_ordinal', **details)
        check(_exact_integer(row.get('covered_round'), milestone), 'milestone_covered_round', **details)
    check(type(draft.get('sections')) is list, 'sections_shape')
    check(draft['sections'], 'sections_empty')


def _lane_identifier(handle, index):
    _readback_require(type(handle.id) is str and handle.id, 'lane_incomplete', 'settlement',
                      'handle_id', collection='handles', index=index)
    return handle.id


def _lane_outcome(value, index):
    def check(condition, predicate, **details):
        _readback_require(condition, 'lane_incomplete', 'settlement', predicate,
                          collection='handles', index=index, **details)
    check(type(value) is dict, 'outcome_shape')
    check(value.get('status') == 'finished', 'outcome_status', status=value.get('status'))
    check(value.get('pending', False) is False, 'outcome_pending')
    check(not value.get('error'), 'outcome_error')
    check(not value.get('retryable'), 'outcome_retryable')
    check(_exact_integer(value.get('attempt', 1), 1), 'outcome_attempt')


def _pending_lanes(value):
    _readback_require(type(value) is list, 'background_incomplete', 'settlement', 'pending_shape')
    _readback_require(not value, 'background_incomplete', 'settlement', 'pending_lanes', count=len(value))


def _case_observation(bridge, partial):
    observation = bridge.observation(partial)
    if observation['output'] is None:
        partial['status'] = 'incomplete'
    _readback_require(observation['output'] is not None, 'readback_incomplete', 'case', 'observation_unavailable')
    return observation


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
            _readback_call(receipt, 'canonical', _canonical_state, initial, self._bridges[case].driver_inputs(), [])
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
                    try:
                        if browser is not None and browser.turns_enabled:
                            record['turn_delivery'] = 'browser_form'
                            value = await browser.turn(case, ordinal, text)
                        else:
                            record['turn_delivery'] = 'direct_api'
                            value = await session.runtime.turn(storage, text, project_id=inputs['project_id'],
                                language=inputs['language'], client_turn_id=str(uuid4()), include_trajectory=True,
                                evaluation=deepcopy(correlation), conversation_text=text, source_kind='narrator_chat')
                        receipt['execution_stage'] = 'runtime_readback'
                        failure_summary = _runtime_failure_summary(value, correlation)
                        if failure_summary is not None:
                            record['failure_summary'] = failure_summary
                        record.update(_readback_call(record, 'runtime', _runtime_readback, value, correlation), status='delivered')
                        accepted.append(record['accepted_source_id'])
                        receipt['execution_stage'] = 'background_dispatch'
                        handles = await dispatch_memoir_lanes_once(session.temporal_client, session.broker,
                                                                 session.task_queue, single_attempt=True)
                        receipt['execution_stage'] = 'background_settlement'
                        for handle_index, handle in enumerate(handles):
                            handle_id = _readback_call(record, 'settlement', _lane_identifier, handle, handle_index)
                            if handle_id not in partial['workflow_ids']:
                                partial['workflow_ids'].append(handle_id)
                            outcome = await handle.result()
                            _readback_call(record, 'settlement', _lane_outcome, outcome, handle_index)
                        receipt['execution_stage'] = 'canonical_readback'
                        view = await _storage_read(storage.memory_events, inputs['project_id'])
                        _readback_call(record, 'canonical', _canonical_state, view, inputs, accepted)
                        record['canonical_state'] = deepcopy(view)
                        draft = None
                        if ordinal in self._profile.checkpoints:
                            receipt['execution_stage'] = 'checkpoint_readback'
                            draft = await _storage_read(storage.saved_memoir_draft, inputs['project_id'], inputs['language'])
                            _readback_call(record, 'checkpoint', _saved_checkpoint, draft, ordinal, inputs['language'])
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
                        _readback_call(record, 'settlement', _pending_lanes, pending)
                        session.finish_round()
                        record.update(background_settled=True, status='completed')
                        receipt['execution_stage'] = 'progress_receipt'
                        await self._emit(receipt)
                    except BaseException:
                        try:
                            readback = getattr(session, 'worker_failure_for', None)
                            cause = readback(correlation) if callable(readback) else None
                            if cause is not None:
                                record['worker_failure'] = deepcopy(cause)
                                receipt['worker_failure'] = deepcopy(cause)
                        except Exception:
                            pass
                        raise
            partial['status'] = 'completed'
            partial['workflow_ids'].sort()
            receipt['execution_stage'] = 'case_observation'
            observation = _readback_call(record, 'case', _case_observation, bridge, partial)
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
