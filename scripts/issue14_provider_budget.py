"""Durable, shared pre-send accounting for the inactive issue #14 adapter.

Only the controlled protocol uses this ledger. XTS rates and byte tokens are
test fixtures, never prices, tokenization evidence, or authority for live use.
One process owns a run; every transport/role in that run shares this instance.
An existing run journal is never reopened, resumed, cleared, or refunded.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import threading
import json
from uuid import UUID


class BudgetStopped(RuntimeError):
    """Content-free failure. Never attach provider bodies or exception text."""


_MAX = 2**53 - 1
ROLES = frozenset({'collector', 'workspace', 'classification',
    'composer_preparation', 'composer_draft', 'composer_review', 'tool_loop', 'retry'})
STOP_REASONS = frozenset({'protocol_invalid', 'identity_mismatch', 'role_forbidden',
    'target_forbidden', 'usage_invalid', 'request_replay', 'response_replay',
    'ticket_invalid', 'send_interrupted_or_failed', 'journal_unavailable', 'closed'})


def _integer(value):
    return type(value) is int and 0 <= value <= _MAX


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


@dataclass(frozen=True)
class Limits:
    requests: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    output_tokens_per_request: int
    currency_micros: int

    def __post_init__(self):
        if (not all(_integer(v) for v in asdict(self).values())
                or self.output_tokens_per_request == 0):
            raise ValueError('Explicit bounded integer fixture limits are required')


@dataclass(frozen=True)
class _Ticket:
    ordinal: int


class ProviderBudget:
    """Write-ahead reservations, strict settlement, retained uncertainty.

    A reservation is fsynced before the transport is called. Settlement is
    fsynced before releasing any unused tokens or currency. Reasoning is a
    subset of output: it has its own cap but is charged only once. Until a
    response is verified, all possible output is reserved as reasoning too.

    Restart policy is deliberately terminal. The exclusively created durable
    run filename fences restarts, including incomplete/partially written logs.
    Changing run IDs/registry roots is a new run, not a supported budget reset.
    """

    def __init__(self):
        raise TypeError('Use create; this ledger has no live mode')

    @classmethod
    def create(cls, *, reservation_root, run_id, source_revision, limits):
        if (not _uuid(run_id) or type(source_revision) is not str
                or not re.fullmatch('[a-f0-9]{40}', source_revision)
                or type(limits) is not Limits):
            raise ValueError('Explicit fixture run, source and limits are required')
        root = Path(reservation_root)
        if root.is_symlink() or not root.is_dir():
            raise ValueError('An existing ordinary reservation directory is required')
        self = object.__new__(cls)
        self._run_id, self._source_revision, self._limits = run_id, source_revision, limits
        self._pid = os.getpid()
        self._lock = threading.RLock()
        self._entries, self._tickets = [], {}
        self._request_ids, self._response_ids = set(), set()
        self._accounted = dict.fromkeys(('input_tokens', 'output_tokens',
            'reasoning_tokens', 'currency_micros'), 0)
        self._reported = dict(self._accounted)
        self._stop_reason = None
        self._journal_durable = True
        self._closed = False
        self._fd = None
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            try:
                self._fd = os.open(run_id + '.jsonl', os.O_WRONLY | os.O_CREAT |
                    os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
            except FileExistsError:
                raise BudgetStopped('reservation_exists') from None
            self._write('created', schema='issue14-controlled-budget/1', run_id=run_id,
                source_revision=source_revision, limits=asdict(limits),
                protocol='synthetic-responses-byte-v1', currency='XTS',
                input_micros_per_token=2, output_micros_per_token=5,
                reasoning_included_in_output=True, live_ready=False, restart_allowed=False)
            # Persist the filename, not just its contents, before any send.
            os.fsync(directory)
        except BaseException as error:
            if self._fd is not None:
                os.close(self._fd)
            self._closed = True
            if isinstance(error, Exception) and not isinstance(error, BudgetStopped):
                raise BudgetStopped('journal_unavailable') from None
            raise
        finally:
            os.close(directory)
        return self

    @property
    def run_id(self):
        return self._run_id

    @property
    def source_revision(self):
        return self._source_revision

    @property
    def limits(self):
        return self._limits

    def _owner(self):
        if os.getpid() != self._pid:
            raise BudgetStopped('process_ownership_mismatch')

    def _write(self, event, **fields):
        try:
            raw = (json.dumps({'event': event, **fields}, allow_nan=False,
                sort_keys=True, separators=(',', ':')) + '\n').encode()
            offset = 0
            while offset < len(raw):
                written = os.write(self._fd, raw[offset:])
                if written <= 0:
                    raise OSError('write unavailable')
                offset += written
            os.fsync(self._fd)
        except BaseException as error:
            self._journal_durable = False
            self._stop_reason = 'journal_unavailable'
            if isinstance(error, Exception):
                raise BudgetStopped('journal_unavailable') from None
            raise

    def _admit(self):
        if self._closed or self._stop_reason:
            raise BudgetStopped(self._stop_reason or 'closed')

    def stop(self, reason):
        self._owner()
        if reason not in STOP_REASONS:
            raise ValueError('A registered content-free reason is required')
        with self._lock:
            if not self._stop_reason:
                self._stop_reason = reason
                if not self._closed:
                    self._write('stopped', reason=reason)

    def _reject(self, reason):
        self.stop(reason)
        raise BudgetStopped(reason)

    def reserve(self, *, request_id, role, payload_bytes):
        """Called only after final byte serialization at the owned HTTP seam."""
        self._owner()
        with self._lock:
            self._admit()
            if not _uuid(request_id) or role not in ROLES or not _integer(payload_bytes):
                self._reject('protocol_invalid')
            if request_id in self._request_ids:
                self._reject('request_replay')
            output = self.limits.output_tokens_per_request
            reserved = {'input_tokens': payload_bytes, 'output_tokens': output,
                'reasoning_tokens': output, 'currency_micros': payload_bytes * 2 + output * 5}
            if len(self._entries) >= self.limits.requests:
                raise BudgetStopped('requests_limit')
            for key, amount in reserved.items():
                if self._accounted[key] + amount > getattr(self.limits, key):
                    raise BudgetStopped(key + '_limit')
            entry = {'ordinal': len(self._entries) + 1, 'request_id': request_id,
                'role': role, 'status': 'reserved', 'payload_bytes': payload_bytes,
                'reserved': reserved}
            # Even an uncertain partial write is retained in memory and fences
            # this process. The pre-existing filename fences every restart.
            self._entries.append(entry)
            self._request_ids.add(request_id)
            for key, amount in reserved.items():
                self._accounted[key] += amount
            self._write('send_reserved', **entry)
            ticket = _Ticket(entry['ordinal'])
            self._tickets[id(ticket)] = (ticket, entry)
            return ticket

    def _entry(self, ticket):
        record = self._tickets.get(id(ticket))
        if record is None or record[0] is not ticket or record[1]['status'] != 'reserved':
            self._reject('ticket_invalid')
        return record[1]

    def settle(self, ticket, *, response_id, input_tokens, output_tokens, reasoning_tokens):
        self._owner()
        with self._lock:
            if self._closed or not self._journal_durable:
                raise BudgetStopped(self._stop_reason or 'closed')
            entry = self._entry(ticket)
            if (not _uuid(response_id)
                    or not all(_integer(v) for v in (input_tokens, output_tokens, reasoning_tokens))
                    or input_tokens > entry['reserved']['input_tokens']
                    or output_tokens > entry['reserved']['output_tokens']
                    or reasoning_tokens > output_tokens):
                self._reject('usage_invalid')
            if response_id in self._response_ids:
                self._reject('response_replay')
            actual = {'input_tokens': input_tokens, 'output_tokens': output_tokens,
                'reasoning_tokens': reasoning_tokens,
                'currency_micros': input_tokens * 2 + output_tokens * 5}
            # Do not publish success or release anything until durable.
            self._write('send_settled', ordinal=entry['ordinal'], response_id=response_id, actual=actual)
            entry.update(status='settled', response_id=response_id, actual=actual)
            self._response_ids.add(response_id)
            for key, amount in actual.items():
                self._accounted[key] -= entry['reserved'][key] - amount
                self._reported[key] += amount

    def close(self):
        self._owner()
        with self._lock:
            if self._closed:
                return
            try:
                self.stop('closed')
            finally:
                self._closed = True
                os.close(self._fd)
                self._fd = None

    def receipt(self):
        self._owner()
        with self._lock:
            settled = sum(e['status'] == 'settled' for e in self._entries)
            return {'schema': 'issue14-controlled-budget/1', 'run_id': self.run_id,
                'source_revision': self.source_revision, 'evidence_mode': 'controlled_loopback',
                'currency': 'XTS', 'limits': asdict(self.limits),
                'accounted': dict(self._accounted), 'reported': dict(self._reported),
                'reserved_requests': len(self._entries), 'settled_requests': settled,
                'unresolved_requests': len(self._entries) - settled,
                'attempts': deepcopy(self._entries), 'stop_reason': self._stop_reason,
                'journal_durable': self._journal_durable, 'closed': self._closed,
                'live_ready': False, 'actual_provider_requests': None,
                'real_provider_token_or_cost_limits_verified': False,
                'upstream_cancellation_verified': False, 'restart_allowed': False}
