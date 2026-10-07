"""Exclusive synthetic accounting for one proposed fifty-input campaign.

No method dispatches, loads authentication, verifies a native boundary, or grants
provider authority. Tickets reserve bookkeeping slots only. A future real
adapter requires separately reviewed admission, source/account verification and
an upstream send boundary; this module cannot supply any of them.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import threading
from time import monotonic
from uuid import UUID

from scripts.fifty_round_budget_contract import STAGES, _same_json_literal, _validate_proposal


class BudgetStopped(RuntimeError):
    """A content-free terminal reason; never include model or exception text."""


@dataclass(frozen=True)
class WorkerKey:
    stage: str
    round_number: int
    checkpoint_round: int | None = None
    preparation_id: str | None = None
    attempt: int = 1


@dataclass(frozen=True)
class _Ticket:
    ordinal: int
    kind: str
    deadline: float | None = None
    live_execution_authorized: bool = False


FAILURES = frozenset({'quota', 'provider_error', 'cancelled', 'usage_unknown',
    'protocol_error', 'operation_failed', 'closed'})
_SCOPE_KEYS = {'run_id', 'case_id', 'owner_id', 'project_id', 'source_revision',
    'source_tree', 'source_sha256', 'account_binding', 'roles'}
_CORRELATION_KEYS = {'trace_id', 'observation_id', 'request_id', 'job_id', 'checkpoint_id'}


def _safe_id(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', value) is not None


def _hex(value, length):
    return type(value) is str and re.fullmatch('[a-f0-9]{' + str(length) + '}', value) is not None


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _scope(scope, proposal):
    if type(scope) is not dict or set(scope) != _SCOPE_KEYS or any(type(k) is not str for k in scope):
        raise ValueError('Exact synthetic campaign scope is required')
    if (not _uuid(scope['run_id']) or not _uuid(scope['owner_id'])
            or not all(_safe_id(scope[k]) for k in ('case_id', 'project_id'))
            or not all(_hex(scope[k], 40) for k in ('source_revision', 'source_tree'))
            or not _hex(scope['account_binding'], 64)
            or scope['account_binding'] != proposal['routing']['account']['proposed_binding_sha256']):
        raise ValueError('Explicit fixed campaign identities are required')
    sources = scope['source_sha256']
    if (type(sources) is not dict or not sources or len(sources) > 512
            or any(type(k) is not str or not re.fullmatch(r'[A-Za-z0-9_./-]{1,256}', k)
                or k.startswith('/') or '..' in k.split('/') or not _hex(v, 64)
                for k, v in sources.items())):
        raise ValueError('Synthetic source pins must be bounded relative paths and SHA256 values')
    roles = scope['roles']
    if type(roles) is not dict or set(roles) != set(STAGES) or any(type(k) is not str for k in roles):
        raise ValueError('Every known role must have an explicit synthetic route')
    for stage, route in roles.items():
        expected = proposal['routing']['stages'][stage]
        if (type(route) is not dict or set(route) != {'model_alias', 'wire_model', 'reasoning'}
                or any(type(k) is not str for k in route) or not all(_safe_id(v) for v in route.values())
                or route['model_alias'] != expected['configuration_alias']
                or route['reasoning'] != expected['configuration_reasoning']):
            raise ValueError('Synthetic routes must preserve the proposed per-role policy')
    return deepcopy(scope)


def _key(key):
    if (type(key) is not WorkerKey or type(key.stage) is not str or key.stage not in STAGES
            or type(key.round_number) is not int or not 1 <= key.round_number <= 50
            or type(key.attempt) is not int):
        return False
    composer = key.stage in {'event_preparation', 'composer_draft', 'composer_review'}
    repair = key.stage in {'focused_family', 'composer_draft', 'composer_review'}
    if not 1 <= key.attempt <= (3 if repair else 1):
        return False
    if composer:
        if (type(key.checkpoint_round) is not int or key.checkpoint_round not in range(5, 51, 5)
                or key.round_number != key.checkpoint_round):
            return False
    elif key.checkpoint_round is not None:
        return False
    if key.stage == 'initial_locale' and key.round_number != 1:
        return False
    return _hex(key.preparation_id, 64) if key.stage == 'event_preparation' else key.preparation_id is None


class CampaignDispatchBudget:
    """Synthetic-only journal and state machine, owned by one process.

    All campaign users must share one fixed reservation registry root. A new
    directory is a different registry, never a supported way to resume/reset a
    run. Creation and all append operations are fail-closed. There is no restore
    or resume API, and a closed or crashed reservation remains consumed.
    """

    @classmethod
    def create(cls, *, reservation_root, proposal, scope):
        _validate_proposal(proposal)
        pinned = _scope(scope, proposal)
        root = Path(reservation_root)
        if root.is_symlink() or not root.is_dir():
            raise ValueError('An existing owned ordinary registry directory is required')
        self = object.__new__(cls)
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._scope = pinned
        self._proposal = deepcopy(proposal)
        self._workers, self._sends = [], []
        self._worker_tickets, self._send_tickets = {}, {}
        self._keys, self._preparations, self._response_ids = set(), set(), set()
        self._repair_attempts = {}
        self._counts = dict.fromkeys(STAGES, 0)
        self._active_worker = self._active_send = None
        self._stop_reason = None
        self._closed = False
        self._journal_durable = True
        self._active_finished = True
        now = monotonic()
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ValueError('A finite monotonic clock is required')
        self._last_time = now
        self._deadline = now + proposal['proposed_limits']['wall_seconds']
        self._fd = None
        path = root / (pinned['run_id'] + '.jsonl')
        try:
            self._fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        except FileExistsError:
            raise BudgetStopped('reservation_exists') from None
        try:
            self._write('created', scope=self._scope, proposed_limits=proposal['proposed_limits'],
                worker_stage_limits=proposal['worker_stage_limits'], evidence_mode='synthetic',
                actual_provider_requests=None, live_execution_authorized=False, restart_allowed=False)
        except BaseException:
            os.close(self._fd)
            self._fd = None
            self._closed = True
            raise
        return self

    def __init__(self):
        raise TypeError('Use create; no constructor grants dispatch authority')

    @property
    def deadline(self):
        """Monotonic campaign deadline for a synthetic adapter's bounded waits."""
        self._owner()
        return self._deadline

    def _owner(self):
        # Check before acquiring a possibly inherited lock after fork.
        if os.getpid() != self._pid:
            raise BudgetStopped('process_ownership_mismatch')

    def _write(self, event, **fields):
        try:
            raw = (json.dumps({'event': event, **fields}, allow_nan=False, sort_keys=True) + '\n').encode()
            offset = 0
            while offset < len(raw):
                written = os.write(self._fd, raw[offset:])
                if written <= 0:
                    raise OSError('Journal write unavailable')
                offset += written
            os.fsync(self._fd)
        except (OSError, TypeError, ValueError):
            self._journal_durable = False
            self._stop_reason = self._stop_reason or 'journal_unavailable'
            raise BudgetStopped('journal_unavailable') from None

    def _fence(self, reason):
        if not self._stop_reason:
            self._stop_reason = reason
            if not self._closed:
                self._write('stopped', reason=reason)

    def _reject(self, reason):
        self._fence(reason)
        raise BudgetStopped(reason)

    def _clock(self):
        now = monotonic()
        if type(now) not in (int, float) or not math.isfinite(now) or now < self._last_time:
            self._reject('clock_invalid')
        self._last_time = now
        if now >= self._deadline:
            self._reject('wall_deadline')
        if self._active_send is not None and now >= self._sends[self._active_send]['deadline']:
            self._sends[self._active_send]['status'] = 'unsettled'
            self._reject('request_deadline')
        return now

    def _admit_bookkeeping(self):
        if self._closed or self._stop_reason:
            raise BudgetStopped(self._stop_reason or 'closed')
        return self._clock()

    def _worker(self, ticket):
        entry = self._worker_tickets.get(id(ticket))
        if entry is None or entry[0] is not ticket:
            self._reject('foreign_worker_ticket')
        return entry[1]

    def _send(self, ticket):
        entry = self._send_tickets.get(id(ticket))
        if entry is None or entry[0] is not ticket:
            self._reject('foreign_send_ticket')
        return entry[1]

    def begin_worker(self, key, correlation=None):
        self._owner()
        with self._lock:
            self._admit_bookkeeping()
            if not _key(key):
                self._reject('worker_key_invalid')
            if (correlation is not None and (type(correlation) is not dict
                    or any(type(k) is not str or k not in _CORRELATION_KEYS or not _safe_id(v)
                        for k, v in correlation.items()))):
                self._reject('correlation_invalid')
            if key in self._keys:
                self._reject('worker_replay')
            if key.preparation_id is not None and key.preparation_id in self._preparations:
                self._reject('preparation_replay')
            if self._active_worker is not None:
                self._reject('worker_concurrency')
            base = (key.stage, key.round_number, key.checkpoint_round, key.preparation_id)
            if key.attempt != self._repair_attempts.get(base, 0) + 1:
                self._reject('repair_sequence_invalid')
            if self._counts[key.stage] >= self._proposal['worker_stage_limits'][key.stage]:
                self._reject('stage_limit')
            if len(self._workers) >= self._proposal['maximum_worker_requests']:
                self._reject('worker_limit')
            entry = {'ordinal': len(self._workers) + 1, 'key': asdict(key),
                'correlation': deepcopy(correlation or {}), 'status': 'active', 'send_count': 0}
            self._workers.append(entry)
            self._keys.add(key)
            self._repair_attempts[base] = key.attempt
            if key.preparation_id is not None:
                self._preparations.add(key.preparation_id)
            self._counts[key.stage] += 1
            self._active_worker = len(self._workers) - 1
            self._write('worker_reserved', **entry)
            ticket = _Ticket(entry['ordinal'], 'worker')
            self._worker_tickets[id(ticket)] = (ticket, self._active_worker)
            return ticket

    def declared_send_scope(self, worker_ticket):
        """Return synthetic declarations for fixtures; this is not observed proof."""
        self._owner()
        with self._lock:
            index = self._worker(worker_ticket)
            stage = self._workers[index]['key']['stage']
            return {**deepcopy({k: v for k, v in self._scope.items() if k != 'roles'}),
                'stage': stage, **deepcopy(self._scope['roles'][stage])}

    def reserve_send(self, worker_ticket, *, continuation_ordinal, observed_scope):
        self._owner()
        with self._lock:
            now = self._admit_bookkeeping()
            worker_index = self._worker(worker_ticket)
            worker = self._workers[worker_index]
            if worker_index != self._active_worker or worker['status'] != 'active':
                self._reject('worker_replay')
            if not _same_json_literal(observed_scope, self.declared_send_scope(worker_ticket)):
                self._reject('send_scope_mismatch')
            if self._active_send is not None:
                self._reject('send_concurrency')
            if type(continuation_ordinal) is not int or continuation_ordinal != worker['send_count'] + 1:
                self._reject('continuation_sequence_invalid')
            limits = self._proposal['proposed_limits']
            if len(self._sends) >= limits['maximum_actual_requests']:
                self._reject('send_limit')
            entry = {'ordinal': len(self._sends) + 1, 'worker_ordinal': worker['ordinal'],
                'continuation_ordinal': continuation_ordinal, 'status': 'reserved',
                'synthetic_started': False, 'deadline': min(self._deadline, now + limits['request_seconds']),
                'wire_model': observed_scope['wire_model']}
            self._sends.append(entry)
            worker['send_count'] += 1
            self._active_send = len(self._sends) - 1
            self._write('send_reserved', **entry)
            ticket = _Ticket(entry['ordinal'], 'send', entry['deadline'])
            self._send_tickets[id(ticket)] = (ticket, self._active_send)
            return ticket

    def mark_started(self, send_ticket):
        """Record a synthetic fixture contact, never a proven provider request."""
        self._owner()
        with self._lock:
            self._admit_bookkeeping()
            index = self._send(send_ticket)
            if index != self._active_send or self._sends[index]['status'] != 'reserved':
                self._reject('send_replay')
            self._sends[index].update(status='started', synthetic_started=True)
            self._write('synthetic_started', ordinal=index + 1)

    def settle(self, send_ticket, completion):
        self._owner()
        with self._lock:
            self._admit_bookkeeping()
            index = self._send(send_ticket)
            entry = self._sends[index]
            if index != self._active_send or entry['status'] != 'started':
                self._reject('send_replay')
            if (type(completion) is not dict
                    or set(completion) != {'response_id', 'wire_model', 'input_tokens', 'output_tokens'}
                    or any(type(k) is not str for k in completion)
                    or not _safe_id(completion['response_id'])
                    or type(completion['wire_model']) is not str or completion['wire_model'] != entry['wire_model']
                    or any(type(completion[k]) is not int or completion[k] < 0
                        for k in ('input_tokens', 'output_tokens'))):
                entry['status'] = 'unsettled'
                self._reject('completion_invalid_or_unknown')
            if completion['response_id'] in self._response_ids:
                entry['status'] = 'unsettled'
                self._reject('response_replay')
            self._response_ids.add(completion['response_id'])
            entry.update(status='completed', **deepcopy(completion))
            self._write('synthetic_settled', **entry)
            self._active_send = None

    def fail(self, send_ticket, reason):
        self._owner()
        with self._lock:
            if type(reason) is not str or reason not in FAILURES:
                self._reject('failure_reason_invalid')
            if self._closed:
                raise BudgetStopped(self._stop_reason or 'closed')
            index = self._send(send_ticket)
            if index != self._active_send or self._sends[index]['status'] not in {'reserved', 'started', 'unsettled'}:
                self._reject('send_replay')
            self._sends[index]['status'] = 'unsettled'
            self._fence(reason)
            self._write('send_unsettled', ordinal=index + 1, reason=reason)

    def finish_worker(self, worker_ticket):
        self._owner()
        with self._lock:
            self._admit_bookkeeping()
            index = self._worker(worker_ticket)
            if index != self._active_worker or self._workers[index]['status'] != 'active':
                self._reject('worker_replay')
            if self._active_send is not None:
                self._reject('worker_send_unsettled')
            self._workers[index]['status'] = 'completed'
            self._write('worker_finished', ordinal=index + 1)
            self._active_worker = None

    def stop(self, reason):
        self._owner()
        with self._lock:
            if type(reason) is not str or reason not in FAILURES:
                self._reject('failure_reason_invalid')
            self._fence(reason)

    def close(self):
        """Fence and close the journal immediately; never wait on transport tasks."""
        self._owner()
        with self._lock:
            if self._closed:
                return
            self._stop_reason = self._stop_reason or 'closed'
            self._active_finished = self._active_worker is None and self._active_send is None
            if self._active_send is not None:
                self._sends[self._active_send]['status'] = 'unsettled'
            try:
                self._write('closed', reason=self._stop_reason, active_finished=self._active_finished)
            finally:
                try:
                    os.close(self._fd)
                except OSError:
                    self._journal_durable = False
                    raise BudgetStopped('journal_unavailable') from None
                finally:
                    self._fd = None
                    self._closed = True

    def receipt(self):
        self._owner()
        with self._lock:
            completed = [entry for entry in self._sends if entry['status'] == 'completed']
            return {'schema_version': 'memoir-fifty-synthetic-dispatch/1', 'evidence_mode': 'synthetic',
                'live_execution_authorized': False, 'actual_provider_requests': None,
                'native_boundary_verified': False, 'restart_allowed': False,
                'scope': deepcopy(self._scope), 'worker_requests': len(self._workers),
                'worker_requests_by_stage': dict(self._counts), 'workers': deepcopy(self._workers),
                'send_reservations': len(self._sends), 'attempts': deepcopy(self._sends),
                'synthetic_contacts_started': sum(entry['synthetic_started'] for entry in self._sends),
                'completed_sends': len(completed),
                'unsettled_requests': len(self._sends) - len(completed),
                'remaining_send_reservations': self._proposal['proposed_limits']['maximum_actual_requests'] - len(self._sends),
                'synthetic_input_tokens_reported': sum(entry['input_tokens'] for entry in completed),
                'synthetic_output_tokens_reported': sum(entry['output_tokens'] for entry in completed),
                'hard_token_or_monetary_limit_enforced': False, 'stop_reason': self._stop_reason,
                'cleanup': {'closed': self._closed, 'journal_durable': self._journal_durable,
                    'active_finished': self._active_finished if self._closed
                        else self._active_worker is None and self._active_send is None}}
