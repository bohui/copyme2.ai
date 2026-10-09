"""Opt-in task-owned client request boundary for the separate subscription mode.

This counts Codex HTTP attempts/continuations to the existing LiteLLM gateway.
It cannot count gateway-internal retries, enforce upstream token/dollar caps,
prove subscription headroom, or prove that disconnected upstream work stopped.
It does not activate a runner, load configuration/credentials, or alter any
historical strict-accounting contract. Numeric limits have no defaults.

Only ``controlled`` is exercised by this module's disposable-loopback tests.
``existing_route`` is an explicit source integration point requiring externally
authorized run scope and an explicitly supplied Authorization header. Merely
having this constructor is not approval to contact the existing route.
"""
import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID

import httpx


EXISTING_ENDPOINT = 'http://192.168.66.1:4000/v1/responses'
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
# The explicit campaign is the original ordered dataset, not an arbitrary
# grouping mechanism that can mint fresh per-case budgets.
MEMOIR_FIVE_CASE_IDS = ('harbour-copper-notebook', 'chengdu-tea-ledger',
    'perth-workshop-compass', 'kunming-garden-lanterns', 'sydney-platform-letters')
_SCHEMA = 'issue14-subscription-client-request-budget/1'
_BOUNDARY = 'client_to_existing_gateway_http_requests'
_STOP_REASONS = frozenset({'closed', 'requests_limit', 'elapsed_limit',
    'target_forbidden', 'identity_mismatch', 'protocol_invalid',
    'send_interrupted_or_failed', 'journal_unavailable', 'http_response_failed',
    'process_ownership_mismatch', 'event_loop_mismatch', 'route_binding_mismatch',
    'case_sequence_invalid', 'case_inactive', 'case_inflight',
    'case_requests_limit', 'case_elapsed_limit'})


class SubscriptionStopped(RuntimeError):
    """Content-free terminal error; never include request/provider error text."""


@dataclass(frozen=True)
class SubscriptionLimits:
    max_requests: int
    max_elapsed_seconds: float

    def __post_init__(self):
        if (type(self.max_requests) is not int or not 0 < self.max_requests < 2**53
                or type(self.max_elapsed_seconds) not in (int, float)
                or not math.isfinite(self.max_elapsed_seconds)
                or not 0 < self.max_elapsed_seconds < 2**53):
            raise ValueError('Explicit positive finite client request/time limits are required')


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


class SubscriptionRun:
    """One process, one event loop, one route, one shared serial dispatch gate.

    Each attempt consumes a durable reservation before socket access; nothing
    refunds it. The exclusively created filename fences restart even after a
    failed/partial write. A different ID/root is a different run, not a resume.
    Journals intentionally contain no payload, headers, model, or remote IDs.
    Call ``close`` explicitly after all transports have closed.
    """

    def __init__(self):
        raise TypeError('Use create with explicit run identity and limits')

    @classmethod
    def create(cls, *, reservation_root, run_id, source_revision, limits,
               case_ids=None, case_limits=None):
        if (not _uuid(run_id) or type(source_revision) is not str
                or not re.fullmatch('[a-f0-9]{40}', source_revision)
                or type(limits) is not SubscriptionLimits):
            raise ValueError('Explicit run UUID, source revision and limits are required')
        if case_ids is not None or case_limits is not None:
            if (type(case_ids) is not tuple
                    or any(type(case_id) is not str for case_id in case_ids)
                    or case_ids != MEMOIR_FIVE_CASE_IDS
                    or type(case_limits) is not SubscriptionLimits
                    or case_limits.max_requests > 600
                    or case_limits.max_elapsed_seconds > 7200
                    or limits.max_requests > 3000
                    or limits.max_elapsed_seconds > 36000):
                raise ValueError('The explicit ordered five-case campaign and bounded limits are required')
        root = Path(reservation_root)
        if root.is_symlink() or not root.is_dir():
            raise ValueError('An existing ordinary reservation directory is required')
        self = object.__new__(cls)
        self._run_id, self._source_revision, self._limits = run_id, source_revision, limits
        self._started_at = time.monotonic()
        self._deadline = self._started_at + limits.max_elapsed_seconds
        self._pid = os.getpid()
        self._lock = threading.RLock()
        self._gate = asyncio.Lock()
        self._loop = None
        self._binding = None
        self._entries = []
        self._started_count = 0
        self._case_ids, self._case_limits = case_ids, case_limits
        self._cases = [{'case_id': case_id, 'status': 'pending', 'entries': [],
            'client_requests_started': 0, 'started_at_monotonic': None,
            'deadline_monotonic': None, 'finished_at_monotonic': None}
            for case_id in (case_ids or ())]
        self._active_case = None
        self._next_case_index = 0
        self._case_dispatches = 0
        self._stop_reason = None
        self._journal_durable = True
        self._closed = False
        self._fd = None
        directory = None
        try:
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                self._fd = os.open(run_id + '.jsonl', os.O_WRONLY | os.O_CREAT |
                    os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
            except FileExistsError:
                raise SubscriptionStopped('reservation_exists') from None
            campaign = ({} if case_ids is None else {
                'case_ids': list(case_ids), 'case_limits': asdict(case_limits),
                'started_at_monotonic': self._started_at,
                'global_deadline_monotonic': self._deadline})
            self._write('created', schema=_SCHEMA, run_id=run_id,
                source_revision=source_revision, limits=asdict(limits),
                counted_boundary=_BOUNDARY, concurrency=1, restart_allowed=False,
                hard_token_cap_verified=False, hard_dollar_cap_verified=False,
                upstream_cancellation_verified=False, **campaign)
            # The exclusive filename must survive a crash before any contact.
            os.fsync(directory)
        except BaseException as error:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            self._closed = True
            if isinstance(error, Exception) and not isinstance(error, SubscriptionStopped):
                raise SubscriptionStopped('journal_unavailable') from None
            raise
        finally:
            if directory is not None:
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

    @property
    def case_ids(self):
        return self._case_ids

    @property
    def case_limits(self):
        return self._case_limits

    @property
    def global_deadline(self):
        return self._deadline

    @property
    def deadline(self):
        case = self._active_case
        if case is not None:
            return min(self._deadline, case['deadline_monotonic'])
        return self._deadline

    def start_case(self, case_id):
        """Durably activate the next single-use case without resetting the run."""
        with self._lock:
            self._admit()
            if self.case_ids is None:
                raise ValueError('An explicit campaign is required')
            if (type(case_id) is not str or self._active_case is not None
                    or self._next_case_index >= len(self.case_ids)
                    or case_id != self.case_ids[self._next_case_index]):
                self._reject('case_sequence_invalid')
            if self._case_dispatches:
                self._reject('case_inflight')
            case = self._cases[self._next_case_index]
            started = time.monotonic()
            case.update(status='active', started_at_monotonic=started,
                deadline_monotonic=min(self.global_deadline,
                    started + self.case_limits.max_elapsed_seconds))
            # Retain activation even when its journal write is uncertain.
            self._active_case = case
            self._write('case_started', case_id=case_id,
                case_index=self._next_case_index + 1,
                started_at_monotonic=started,
                deadline_monotonic=case['deadline_monotonic'],
                global_deadline_monotonic=self.global_deadline)
            self._admit()

    def finish_case(self, case_id):
        """Finish only the active case; retain its budget, counters and deadline."""
        with self._lock:
            self._admit()
            if self.case_ids is None:
                raise ValueError('An explicit campaign is required')
            case = self._active_case
            if type(case_id) is not str or case is None or case_id != case['case_id']:
                self._reject('case_sequence_invalid')
            if self._case_dispatches:
                self._reject('case_inflight')
            finished = time.monotonic()
            summary = self._case_snapshot(case, finished)
            summary.update(status='completed', finished_at_monotonic=finished)
            self._write('case_finished', **summary,
                global_client_requests_reserved=len(self._entries),
                global_client_requests_started=self._started_count)
            self._admit()
            case.update(status='completed', finished_at_monotonic=finished)
            self._active_case = None
            self._next_case_index += 1

    def _owner(self):
        if os.getpid() != self._pid:
            raise SubscriptionStopped('process_ownership_mismatch')

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
                raise SubscriptionStopped('journal_unavailable') from None
            raise

    def stop(self, reason):
        self._owner()
        if reason not in _STOP_REASONS:
            raise ValueError('A registered content-free stop reason is required')
        with self._lock:
            if self._stop_reason is None:
                self._stop_reason = reason
                if not self._closed:
                    self._write('stopped', reason=reason)

    def _reject(self, reason):
        self.stop(reason)
        raise SubscriptionStopped(self._stop_reason or reason)

    def _admit(self):
        self._owner()
        if self._closed or self._stop_reason:
            raise SubscriptionStopped(self._stop_reason or 'closed')
        now = time.monotonic()
        if now >= self.global_deadline:
            self._reject('elapsed_limit')
        if self._active_case is not None and now >= self._active_case['deadline_monotonic']:
            self._reject('case_elapsed_limit')

    def remaining_seconds(self):
        """Remaining original run/active-case time; raises on terminal state."""
        with self._lock:
            self._admit()
            return max(0.0, self.deadline - time.monotonic())

    def _timeout_reason(self):
        if self._active_case is not None and self.deadline < self.global_deadline:
            return 'case_elapsed_limit'
        return 'elapsed_limit'

    def timeout_reason(self):
        """Content-free limiting deadline, retained even after terminal stop."""
        with self._lock:
            return self._timeout_reason()

    def _begin_dispatch(self):
        with self._lock:
            if self.case_ids is None:
                return False
            self._admit()
            if self._active_case is None:
                self._reject('case_inactive')
            # Include queued requests and body buffering, not only socket use.
            # Their case cannot change while they wait for the serial gate.
            self._case_dispatches += 1
            return True

    def _end_dispatch(self):
        with self._lock:
            self._case_dispatches -= 1

    def _bind_route(self, endpoint, mode):
        self._owner()
        with self._lock:
            binding = (endpoint, mode)
            if self._binding is not None and self._binding != binding:
                self._reject('route_binding_mismatch')
            self._binding = binding

    def _bind_loop(self):
        self._owner()
        with self._lock:
            loop = asyncio.get_running_loop()
            if self._loop is not None and self._loop is not loop:
                self._reject('event_loop_mismatch')
            self._loop = loop

    def _reserve(self, payload_bytes):
        with self._lock:
            self._capacity()
            entry = {'ordinal': len(self._entries) + 1, 'status': 'reserved',
                     'payload_bytes': payload_bytes, 'reserved_at_monotonic': time.monotonic()}
            if self._active_case is not None:
                entry.update(case_id=self._active_case['case_id'],
                    case_ordinal=len(self._active_case['entries']) + 1)
                self._active_case['entries'].append(entry)
            # Retain uncertainty even if only part of this write reaches disk.
            self._entries.append(entry)
            self._write('send_reserved', **entry)
            return entry

    def _capacity(self):
        self._admit()
        if self.case_ids is not None and self._active_case is None:
            self._reject('case_inactive')
        if len(self._entries) >= self.limits.max_requests:
            self._reject('requests_limit')
        if (self._active_case is not None
                and len(self._active_case['entries']) >= self.case_limits.max_requests):
            self._reject('case_requests_limit')

    def _starting(self, entry):
        with self._lock:
            # Serialization/fsync may have consumed the last remaining time.
            self._admit()
            self._started_count += 1
            if self._active_case is not None:
                self._active_case['client_requests_started'] += 1
            entry['started_at_monotonic'] = time.monotonic()
            self._write('send_started', ordinal=entry['ordinal'],
                started_at_monotonic=entry['started_at_monotonic'],
                **({key: entry[key] for key in ('case_id', 'case_ordinal')} if 'case_id' in entry else {}))
            # The extra diagnostic write cannot extend the existing deadline.
            self._admit()

    def _complete(self, entry, status_code, response_bytes):
        with self._lock:
            self._admit()
            case_fields = ({'case_id': entry['case_id'], 'case_ordinal': entry['case_ordinal']}
                if 'case_id' in entry else {})
            completed_at = time.monotonic()
            elapsed = max(0, round((completed_at - entry['started_at_monotonic']) * 1000))
            self._write('http_response_completed', ordinal=entry['ordinal'],
                status_code=status_code, response_bytes=response_bytes,
                completed_at_monotonic=completed_at, elapsed_ms=elapsed, **case_fields)
            # A blocking durable write is not a reason to extend the deadline.
            self._admit()
            entry.update(status='completed', status_code=status_code,
                         response_bytes=response_bytes, completed_at_monotonic=completed_at,
                         elapsed_ms=elapsed)

    def _case_snapshot(self, case, now):
        completed = sum(entry['status'] == 'completed' for entry in case['entries'])
        started, finished = case['started_at_monotonic'], case['finished_at_monotonic']
        status = case['status']
        if status == 'active' and (self._stop_reason is not None or self._closed):
            status = 'incomplete'
        return {'case_id': case['case_id'], 'status': status,
            'limits': asdict(self.case_limits),
            'max_client_requests': self.case_limits.max_requests,
            'client_requests_reserved': len(case['entries']),
            'client_requests_started': case['client_requests_started'],
            'completed_http_responses': completed,
            'unresolved_requests': len(case['entries']) - completed,
            'started_at_monotonic': started, 'deadline_monotonic': case['deadline_monotonic'],
            'finished_at_monotonic': finished,
            'elapsed_seconds': (0.0 if started is None else
                max(0.0, (now if finished is None else finished) - started))}

    def snapshot(self):
        self._owner()
        with self._lock:
            completed = sum(entry['status'] == 'completed' for entry in self._entries)
            receipt = {'schema': _SCHEMA, 'run_id': self.run_id,
                'source_revision': self.source_revision, 'limits': asdict(self.limits),
                'counted_boundary': _BOUNDARY, 'concurrency': 1,
                'max_client_requests': self.limits.max_requests,
                'client_requests_reserved': len(self._entries),
                'client_requests_started': self._started_count,
                'completed_http_responses': completed,
                'unresolved_requests': len(self._entries) - completed,
                'attempts': deepcopy(self._entries), 'stop_reason': self._stop_reason,
                'elapsed_seconds': max(0.0, time.monotonic() - self._started_at),
                'journal_durable': self._journal_durable, 'closed': self._closed,
                'actual_upstream_provider_requests': None,
                'hard_token_cap_verified': False, 'hard_dollar_cap_verified': False,
                'upstream_cancellation_verified': False, 'restart_allowed': False}
            if self.case_ids is not None:
                receipt.update(case_ids=list(self.case_ids), case_limits=asdict(self.case_limits),
                    active_case_id=(None if self._active_case is None or self._closed
                        or self._stop_reason is not None else self._active_case['case_id']),
                    started_at_monotonic=self._started_at,
                    global_deadline_monotonic=self.global_deadline,
                    effective_deadline_monotonic=self.deadline,
                    cases=[self._case_snapshot(case, time.monotonic()) for case in self._cases])
            return receipt

    def close(self):
        self._owner()
        with self._lock:
            if self._closed:
                return
            try:
                self.stop('closed')
            finally:
                self._closed = True
                if self._fd is not None:
                    os.close(self._fd)
                    self._fd = None


def _json_object(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    def invalid(value):
        raise ValueError('nonfinite JSON')
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite JSON')
        return result
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid,
                       parse_float=finite_float)
    if type(value) is not dict:
        raise ValueError('JSON object required')


class SubscriptionTransport(httpx.AsyncBaseTransport):
    """One private HTTPX send per reserved request, including continuations.

    Incoming mutable request objects/streams/extensions never reach the wire.
    Validated final bytes and headers are copied to a private request. Redirects
    are terminal, retries/proxies are disabled, and full responses are buffered
    within the original run deadline before any response reaches the caller.
    A complete 2xx HTTP response does not establish provider semantic success.
    """

    def __init__(self):
        raise TypeError('Use an explicit controlled or existing_route constructor')

    @classmethod
    def controlled(cls, *, run, endpoint):
        try:
            url = urlsplit(endpoint)
            valid = (type(endpoint) is str and url.scheme == 'http'
                and url.hostname == '127.0.0.1' and url.port is not None
                and 1024 <= url.port <= 65535
                and endpoint == f'http://127.0.0.1:{url.port}/v1/responses')
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise SubscriptionStopped('target_forbidden')
        return cls._create(run, endpoint, 'Bearer synthetic-token', 'controlled_loopback')

    @classmethod
    def existing_route(cls, *, run, authorization):
        """Source-only opt-in; caller must separately obtain live run authority."""
        return cls._create(run, EXISTING_ENDPOINT, authorization, 'existing_route')

    @classmethod
    def _create(cls, run, endpoint, authorization, mode):
        if type(run) is not SubscriptionRun:
            raise ValueError('An explicitly created shared SubscriptionRun is required')
        if (type(authorization) is not str or not authorization.startswith('Bearer ')
                or not authorization[7:] or not authorization.isascii()
                or any(ord(char) < 33 or ord(char) == 127 for char in authorization[7:])):
            raise SubscriptionStopped('identity_mismatch')
        run._bind_route(endpoint, mode)
        self = object.__new__(cls)
        self._run, self._endpoint = run, endpoint
        self._authorization = authorization
        self._closed = False
        self._wire = httpx.AsyncHTTPTransport(retries=0, trust_env=False,
            http1=True, http2=False, limits=httpx.Limits(max_connections=1,
                max_keepalive_connections=0))
        return self

    @property
    def endpoint(self):
        return self._endpoint

    @property
    def run(self):
        return self._run

    @property
    def run_id(self):
        return self._run.run_id

    def _headers(self, request):
        if request.method != 'POST' or str(request.url) != self.endpoint:
            self.run._reject('target_forbidden')
        # Snapshot before reading caller-owned streams. None of their later
        # method/URL/header mutations can affect the actual private request.
        pairs = list(request.headers.raw)
        headers = {}
        for key, value in pairs:
            if (type(key) is not bytes or type(value) is not bytes
                    or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key)
                    or any(char < 32 or char == 127 for char in value)):
                self.run._reject('protocol_invalid')
            name = key.lower()
            if name in headers:
                self.run._reject('protocol_invalid')
            headers[name] = value
        if (headers.get(b'authorization') != self._authorization.encode('ascii')
                or headers.get(b'host') != urlsplit(self.endpoint).netloc.encode('ascii')):
            self.run._reject('identity_mismatch')
        if (headers.get(b'content-type', b'').split(b';', 1)[0].strip().lower() != b'application/json'
                or headers.get(b'content-encoding', b'identity') != b'identity'
                or set(headers) & {b'transfer-encoding', b'proxy-authorization',
                    b'proxy-connection', b'upgrade', b'trailer', b'te', b'expect'}):
            self.run._reject('protocol_invalid')
        headers[b'accept-encoding'] = b'identity'
        headers[b'connection'] = b'close'
        return headers

    async def handle_async_request(self, request):
        response = None
        case_dispatch = False
        try:
            self.run._bind_loop()
            if self._closed:
                self.run._reject('closed')
            case_dispatch = self.run._begin_dispatch()
            async with asyncio.timeout(self.run.remaining_seconds()):
                async with self.run._gate:
                    # Fail without touching another caller-owned stream once
                    # the budget is consumed; repeat after buffering/fsync.
                    self.run._capacity()
                    if self._closed:
                        self.run._reject('closed')
                    headers = self._headers(request)
                    chunks, size = [], 0
                    async for block in request.stream:
                        # Reject mutable bytearray/memoryview chunks, not just
                        # their eventual serialized sizes.
                        if type(block) is not bytes:
                            self.run._reject('protocol_invalid')
                        size += len(block)
                        if size > MAX_REQUEST_BYTES:
                            self.run._reject('protocol_invalid')
                        chunks.append(block)
                    body = b''.join(chunks)
                    if headers.get(b'content-length') != str(len(body)).encode('ascii'):
                        self.run._reject('protocol_invalid')
                    try:
                        _json_object(body)
                    except (ValueError, TypeError, RecursionError, UnicodeError):
                        self.run._reject('protocol_invalid')
                    outgoing = httpx.Request('POST', self.endpoint,
                        headers=list(headers.items()), content=body,
                        extensions={'timeout': dict.fromkeys(('connect', 'read', 'write', 'pool'),
                            self.run.remaining_seconds())})
                    entry = self.run._reserve(len(body))
                    self.run._starting(entry)
                    response = await self._wire.handle_async_request(outgoing)
                    if (not 200 <= response.status_code < 300
                            or response.headers.get('content-encoding', 'identity') != 'identity'):
                        self.run._reject('http_response_failed')
                    chunks, size = [], 0
                    async for block in response.aiter_raw():
                        size += len(block)
                        if size > MAX_RESPONSE_BYTES:
                            self.run._reject('protocol_invalid')
                        chunks.append(block)
                    body = b''.join(chunks)
                    status = response.status_code
                    response_headers = [(key, value) for key, value in response.headers.raw
                        if key.lower() not in {b'connection', b'keep-alive', b'proxy-authenticate',
                            b'proxy-authorization', b'te', b'trailer', b'transfer-encoding',
                            b'upgrade', b'content-length'}]
                    await response.aclose()
                    response = None
                    self.run._complete(entry, status, len(body))
                    return httpx.Response(status, headers=response_headers, content=body)
        except BaseException as error:
            reason = (self.run.timeout_reason() if isinstance(error, TimeoutError) else
                str(error) if isinstance(error, SubscriptionStopped) and str(error) in _STOP_REASONS
                else 'send_interrupted_or_failed')
            try:
                self.run.stop(reason)
            finally:
                if not isinstance(error, Exception):
                    raise error
            raise SubscriptionStopped(self.run._stop_reason or reason) from None
        finally:
            if response is not None:
                try:
                    async with asyncio.timeout(1):
                        await response.aclose()
                except (Exception, asyncio.CancelledError):
                    pass
            if case_dispatch:
                self.run._end_dispatch()

    async def aclose(self):
        # Closing one client never resets the shared count/deadline/run gate.
        self._closed = True
        await self._wire.aclose()
