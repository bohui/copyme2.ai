"""Offline prerequisite for a guard INSIDE the actual gateway send boundary.

This module does not install a hook, authenticate a consumer, or grant live
access. A send-entry count is not verified upstream accounting until a reviewed
gateway binding proves every HTTP/WS generation and replay uses this instance.
No credential, source text, response body or reasoning is written to its journal.
"""
import asyncio
from contextlib import aclosing
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import time
from uuid import UUID


class CanaryStopped(RuntimeError):
    """Content-free, terminal stop reason."""


SAFE_STOPS = frozenset({'wire_protocol_invalid', 'wire_event_too_large',
    'upstream_failed_or_incomplete', 'duplicate_completion', 'completion_unavailable',
    'completion_invalid', 'served_model_mismatch', 'usage_missing_or_invalid',
    'response_id_invalid', 'closed', 'gateway_dispatch_forbidden',
    'gateway_session_unavailable', 'gateway_target_forbidden',
    'gateway_auth_mismatch', 'gateway_payload_forbidden',
    'gateway_account_mismatch', 'gateway_replay_forbidden',
    'gateway_request_id_unavailable', 'gateway_source_mismatch',
    'gateway_boundary_unobserved', 'correlation_forbidden'})


class CanarySendGuard:
    def __init__(self, *, reservation, run_id, source_revision, account_binding,
                 model, maximum_requests=80, request_seconds=60, wall_seconds=900):
        if type(maximum_requests) is not int or not 0 <= maximum_requests <= 80:
            raise ValueError('Request cap must be an integer from zero to eighty')
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= limit
                for v, limit in ((request_seconds, 60), (wall_seconds, 900))):
            raise ValueError('Finite bounded request and wall deadlines are required')
        if (str(UUID(run_id)) != run_id or not re.fullmatch('[a-f0-9]{40}', source_revision)
                or not re.fullmatch('[a-f0-9]{64}', account_binding)
                or model != 'gpt-5.6-luna'):
            raise ValueError('Explicit pinned canary identity and model are required')
        self.run_id = run_id
        self.source_revision = source_revision
        self.account_binding = account_binding
        self.model = model
        self.maximum_requests = maximum_requests
        self.request_seconds = request_seconds
        self.deadline = time.monotonic() + wall_seconds
        self.entries = []
        self.stop_reason = None
        self.closed = False
        self.active_finished = True
        self._active_task = None
        self._streams = set()
        self._lock = asyncio.Lock()
        self._fd = os.open(Path(reservation), os.O_WRONLY | os.O_CREAT |
            os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            self._write({'event': 'reserved', 'run_id': run_id,
                'source_revision': source_revision, 'account_binding': account_binding,
                'model': model, 'maximum_requests': maximum_requests,
                'boundary_verified': False, 'restart_allowed': False})
        except BaseException:
            os.close(self._fd)
            self.closed = True
            raise

    def _write(self, event):
        raw = (json.dumps(event, ensure_ascii=True) + '\n').encode()
        offset = 0
        while offset < len(raw):
            offset += os.write(self._fd, raw[offset:])
        os.fsync(self._fd)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.aclose()

    async def aclose(self):
        if not self.closed:
            self.stop_reason = self.stop_reason or 'closed'
            task = self._active_task
            if task is not None and task is not asyncio.current_task() and not task.done():
                task.cancel()
                done, _ = await asyncio.wait({task}, timeout=5)
                self.active_finished = bool(done)
            for stream in tuple(self._streams):
                try:
                    await asyncio.wait_for(stream.aclose(), 5)
                except (RuntimeError, TimeoutError):
                    self.active_finished = False
            self._streams.clear()
            try:
                self._write({'event': 'closed', 'run_id': self.run_id,
                    'active_finished': self.active_finished})
            finally:
                os.close(self._fd)
                self.closed = True

    def stop(self, reason):
        """Permanently revoke future sends after a binding validation failure."""
        if reason not in SAFE_STOPS:
            raise ValueError('A content-free registered stop reason is required')
        if not self.closed and not self.stop_reason:
            self.stop_reason = reason
            self._write({'event': 'stopped', 'reason': reason})

    def stream(self, send, *, payload, transport, account_binding, correlation=None):
        """Wrap ONE lowest-level generation send and its entire response.

        The trusted native binding supplies the account fingerprint from the
        actual auth/header context. Caller-supplied metadata is not that proof.
        `send` is an external wire adapter returning SSE blocks for HTTP/WS.
        """
        stream = self._stream(send, payload=payload, transport=transport,
            account_binding=account_binding, correlation=correlation)
        self._streams.add(stream)
        return stream

    async def _stream(self, send, *, payload, transport, account_binding, correlation):
        async with self._lock:
            if self.closed or self.stop_reason:
                raise CanaryStopped(self.stop_reason or 'closed')
            if time.monotonic() >= self.deadline:
                self.stop_reason = 'wall_deadline'
                raise CanaryStopped(self.stop_reason)
            if len(self.entries) >= self.maximum_requests:
                self.stop_reason = 'request_limit'
                raise CanaryStopped(self.stop_reason)
            reason = None
            if account_binding != self.account_binding:
                reason = 'account_mismatch'
            elif not isinstance(payload, dict) or payload.get('model') != self.model:
                reason = 'model_mismatch'
            elif transport not in {'http', 'websocket'}:
                reason = 'transport_forbidden'
            elif transport == 'websocket' and payload.get('type') != 'response.create':
                reason = 'websocket_operation_forbidden'
            allowed = {'run_id', 'case_id', 'round_id', 'trace_id', 'observation_id',
                'job_id', 'checkpoint_id', 'request_id', 'role', 'phase'}
            if correlation is not None and (not isinstance(correlation, dict) or
                    any(k not in allowed or not isinstance(v, str) or
                        not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', v)
                        for k, v in correlation.items())):
                reason = 'correlation_forbidden'
            if reason:
                self.stop_reason = reason
                self._write({'event': 'stopped', 'reason': reason})
                raise CanaryStopped(reason)
            entry = {'ordinal': len(self.entries) + 1, 'transport': transport,
                'started_at_utc': datetime.now(timezone.utc).isoformat(),
                'correlation': dict(correlation or {}), 'status': 'started'}
            self._write({'event': 'send_reserved', **entry})
            self.entries.append(entry)
            buffer, terminal = '', None
            self._active_task = asyncio.current_task()
            try:
                async with asyncio.timeout(min(self.request_seconds,
                        self.deadline - time.monotonic())):
                    async with aclosing(send(deepcopy(payload))) as stream:
                        async for block in stream:
                            if not isinstance(block, str):
                                raise CanaryStopped('wire_protocol_invalid')
                            buffer += block
                            if len(buffer) > 2 * 1024 * 1024:
                                raise CanaryStopped('wire_event_too_large')
                            buffer = buffer.replace('\r\n', '\n')
                            while '\n\n' in buffer:
                                event_block, buffer = buffer.split('\n\n', 1)
                                event_names = [line[6:].strip() for line in
                                    event_block.splitlines() if line.startswith('event:')]
                                if any(name in {'error', 'response.failed', 'response.incomplete'}
                                        for name in event_names):
                                    raise CanaryStopped('upstream_failed_or_incomplete')
                                data = '\n'.join(line[5:].lstrip() for line in
                                    event_block.splitlines() if line.startswith('data:'))
                                if not data or data == '[DONE]':
                                    continue
                                event = json.loads(data)
                                if not isinstance(event, dict):
                                    raise CanaryStopped('wire_protocol_invalid')
                                if any(name not in {'', 'message', event.get('type')}
                                        for name in event_names):
                                    raise CanaryStopped('wire_protocol_invalid')
                                if (event.get('type') in {'response.failed', 'response.incomplete', 'error'}
                                        or event.get('error') is not None):
                                    raise CanaryStopped('upstream_failed_or_incomplete')
                                if event.get('type') == 'response.completed':
                                    if terminal is not None:
                                        raise CanaryStopped('duplicate_completion')
                                    terminal = self._completion(event.get('response'))
                            yield block
                if terminal is None or buffer.strip():
                    raise CanaryStopped('completion_unavailable')
                entry.update(status='completed', **terminal)
            except BaseException as error:
                self.stop_reason = (str(error) if isinstance(error, CanaryStopped) and
                    str(error) in SAFE_STOPS else 'send_interrupted_or_failed')
                entry['status'] = 'unavailable'
                if not self.closed:
                    self._write({'event': 'send_unavailable', 'reason': self.stop_reason, **entry})
                if isinstance(error, (asyncio.CancelledError, GeneratorExit)):
                    raise
                raise CanaryStopped(self.stop_reason) from None
            finally:
                self._active_task = None
            self._write({'event': 'send_settled', **entry})

    def _completion(self, response):
        if not isinstance(response, dict):
            raise CanaryStopped('completion_invalid')
        if (response.get('status', 'completed') != 'completed'
                or response.get('error') is not None
                or response.get('incomplete_details') is not None):
            raise CanaryStopped('upstream_failed_or_incomplete')
        model = response.get('model')
        if model is not None and model != self.model:
            raise CanaryStopped('served_model_mismatch')
        usage = response.get('usage')
        if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                for k in ('input_tokens', 'output_tokens')):
            raise CanaryStopped('usage_missing_or_invalid')
        response_id = response.get('id')
        if response_id is not None and (not isinstance(response_id, str) or
                not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,120}', response_id)):
            raise CanaryStopped('response_id_invalid')
        return {'response_id': response_id, 'served_model': model,
            'usage': {k: usage[k] for k in ('input_tokens', 'output_tokens')}}

    def receipt(self):
        done = [entry for entry in self.entries if entry['status'] == 'completed']
        return {'run_id': self.run_id, 'source_revision': self.source_revision,
            'boundary_verified': False, 'guarded_send_entries': len(self.entries),
            'completed': len(done), 'attempts': deepcopy(self.entries),
            'input_tokens_reported': sum(e['usage']['input_tokens'] for e in done),
            'output_tokens_reported': sum(e['usage']['output_tokens'] for e in done),
            'stop_reason': self.stop_reason, 'restart_allowed': False,
            'token_limits_enforced': False, 'upstream_cancellation': 'unverified',
            'cleanup': {'closed': self.closed, 'active_finished': self.active_finished}}
