"""Fail-closed ASGI transport for exact lifetime-memory publication snapshots.

Queueing is never publication. Only the response adapter consumes these envelopes,
awaiting each actual ASGI send under its own database publication guard. A caller
must transfer its turn-lease/storage cleanup to the response; the producer must
not release that lease when it returns. Cleanup runs after the final send or after
cancellation has settled the producer, outside every publication guard.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json

import anyio
from starlette.responses import JSONResponse, StreamingResponse

from .lifetime_memory_contracts import ExecutionFence
from .lifetime_memory_publication import PublicationDatabaseUnavailable, PublicationUnavailable, send_governed
from .turn_stream import STREAM_HEADERS


_ERROR = 'The response could not be completed or saved. Please try again.'
_PROGRESS_IDS = frozenset({'context', 'language', 'reply', 'save', 'workspace'})
_PROGRESS_STATUSES = frozenset({'pending', 'running', 'completed', 'failed', 'triggered'})


def _copy_fence(fence):
    if fence is None:
        raise PublicationUnavailable('Personal publication requires an execution fence')
    # Revalidate a detached copy, including nested identity; never retain a
    # caller-owned dict or let a later setter relabel previously queued output.
    return ExecutionFence.model_validate(
        ExecutionFence.model_validate(fence).model_dump(mode='json'))


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')


def _generic_event(event):
    """No free-form string, identifier or payload may hide in this exemption."""
    if event in ({'type': 'started'}, {'type': 'heartbeat'}):
        return True
    if set(event) != {'type', 'data'} or event['type'] != 'progress':
        return False
    data = event['data']
    return (isinstance(data, dict) and set(data) == {'id', 'status'}
            and isinstance(data['id'], str) and data['id'] in _PROGRESS_IDS
            and isinstance(data['status'], str) and data['status'] in _PROGRESS_STATUSES)


@dataclass(frozen=True)
class _Envelope:
    body: bytes
    fence: ExecutionFence | None
    terminal: bool = False


@dataclass(frozen=True, init=False)
class GovernedResult:
    """Freeze a result at its provenance boundary, before later plan mutations."""
    body: bytes
    fence: ExecutionFence

    def __init__(self, content, fence):
        snapshot = _copy_fence(fence)
        object.__setattr__(self, 'body', _json_bytes(content))
        object.__setattr__(self, 'fence', snapshot)

    def _envelope(self):
        return _Envelope(b'{"type":"result","data":' + self.body + b'}\n',
                         self.fence, terminal=True)


class GovernedEmitter:
    """Producer interface. A fence setter affects only subsequent snapshots."""
    def __init__(self, stream):
        self._stream = stream
        self._fence = None

    def set_fence(self, fence):
        self._fence = _copy_fence(fence)

    def snapshot_result(self, content, *, fence=None):
        return GovernedResult(content, self._fence if fence is None else fence)

    async def __call__(self, text):
        if not isinstance(text, str):
            raise ValueError('Invalid turn stream text')
        if text:
            await self.event({'type': 'text_delta', 'text': text})

    async def event(self, event):
        if not isinstance(event, dict) or not isinstance(event.get('type'), str) or not event['type']:
            raise ValueError('Invalid turn stream event')
        # Freeze both serialized payload and fence *before* any queue backpressure.
        fence = None if _generic_event(event) else _copy_fence(self._fence)
        envelope = _Envelope(_json_bytes(event) + b'\n', fence,
                             terminal=event['type'] in {'result', 'error'})
        await self._stream._queue.put(envelope)

    async def flush(self):
        """Wait for completed sends before the producer mutates plan/fence state.

        The consumer acknowledges only after send and guard exit, so this barrier
        never joins a producer from inside its publication transaction.
        """
        await self._stream._queue.join()


class GovernedTurnStream:
    """Single-use bounded envelope stream; use with GovernedStreamingResponse."""
    def __init__(self, run, cleanup=None, *, heartbeat_interval=10):
        if heartbeat_interval <= 0:
            raise ValueError('heartbeat_interval must be positive')
        self._run = run
        self._cleanup = cleanup
        self._heartbeat_interval = heartbeat_interval
        self._queue = asyncio.Queue(maxsize=64)
        self._task = None
        self._iterator = None
        self._closing = None
        self.emitter = GovernedEmitter(self)

    async def _produce(self):
        try:
            result = await self._run(self.emitter)
            # An explicit result retains its original fence even if the runtime
            # installed a newer fence before returning. Ordinary returns freeze
            # synchronously here before the next await/queue insertion.
            if not isinstance(result, GovernedResult):
                result = self.emitter.snapshot_result(result)
            await self._queue.put(result._envelope())
        except Exception:
            # Never expose raw errors, exception trajectories or arbitrary event
            # fields via the unfenced terminal-error escape hatch.
            await self._queue.put(_Envelope(
                _json_bytes({'type': 'error', 'message': _ERROR}) + b'\n',
                None, terminal=True))

    def __aiter__(self):
        if self._iterator is None:
            if self._closing is not None:
                raise RuntimeError('Governed stream is already closed')
            self._iterator = self._events()
        return self._iterator

    async def _events(self):
        self._task = asyncio.create_task(self._produce())
        yield _Envelope(b'{"type":"started"}\n', None)
        while True:
            try:
                envelope = await asyncio.wait_for(self._queue.get(), self._heartbeat_interval)
            except asyncio.TimeoutError:
                if self._task.done():
                    yield _Envelope(_json_bytes({'type': 'error', 'message': _ERROR}) + b'\n',
                                    None, terminal=True)
                    return
                yield _Envelope(b'{"type":"heartbeat"}\n', None)
                continue
            try:
                yield envelope
            finally:
                # The response resumes iteration only after its send guard has
                # exited. During failure it cancels the producer before aclose.
                self._queue.task_done()
            if envelope.terminal:
                return

    async def _settle(self):
        try:
            if self._task is not None:
                if not self._task.done():
                    self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            if self._iterator is not None:
                await self._iterator.aclose()
        finally:
            if self._cleanup is not None:
                await self._cleanup()

    async def aclose(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._settle())
        await _finish_cleanup(self._closing)


def governed_turn_events(run, cleanup=None, *, heartbeat_interval=10):
    return GovernedTurnStream(run, cleanup, heartbeat_interval=heartbeat_interval)


async def _finish_cleanup(task):
    """Settle exactly once, including under repeated ASGI cancellation."""
    cancelled = False
    with anyio.CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
    if cancelled:
        raise asyncio.CancelledError


async def _send_generic(send, message, publisher):
    # Unfenced static control frames must not hold a lease forever either.
    timeout = getattr(publisher, 'send_timeout', 2.0)
    async with asyncio.timeout(min(max(timeout, .001), 5.0)):
        await send(message)


class GovernedStreamingResponse(StreamingResponse):
    def __init__(self, content, *, publisher, status_code=200, headers=None,
                 media_type='application/x-ndjson', background=None):
        if not isinstance(content, GovernedTurnStream):
            raise TypeError('GovernedStreamingResponse requires governed_turn_events')
        self.publisher = publisher
        self.governed_stream = content
        super().__init__(content, status_code=status_code,
                         headers={**STREAM_HEADERS, **(headers or {})},
                         media_type=media_type, background=background)

    async def stream_response(self, send):
        try:
            await _send_generic(send, {'type': 'http.response.start',
                'status': self.status_code, 'headers': self.raw_headers}, self.publisher)
            async for envelope in self.body_iterator:
                message = {'type': 'http.response.body', 'body': envelope.body,
                           'more_body': True}
                if envelope.fence is None:
                    await _send_generic(send, message, self.publisher)
                else:
                    try:
                        await send_governed(send, message, publisher=self.publisher,
                                            fence=envelope.fence)
                    except Exception as error:
                        # A failed database guard drops this and all queued private
                        # bodies. Only a fixed, non-personal reconciliation notice
                        # is allowed after the failed publication attempt.
                        if not isinstance(error, PublicationDatabaseUnavailable) and getattr(error, 'sqlstate', None) not in {'40001', 'PT409'}:
                            raise
                        await _send_generic(send, {'type': 'http.response.body',
                            'body': (json.dumps({'type': 'error', 'message': _ERROR}, separators=(',', ':')) + '\n').encode('utf-8'),
                            'more_body': True}, self.publisher)
                        break
            await _send_generic(send, {'type': 'http.response.body', 'body': b'',
                                      'more_body': False}, self.publisher)
        finally:
            await self.governed_stream.aclose()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also owns cleanup when the legacy disconnect listener wins before
            # stream_response starts, or the HTTP response start itself fails.
            await self.governed_stream.aclose()


class GovernedJSONResponse(JSONResponse):
    """Freeze whole-body JSON and retain its lease until actual send completion."""
    def __init__(self, content, *, publisher, fence, cleanup=None, status_code=200,
                 headers=None, media_type=None, background=None):
        self.publisher = publisher
        self.fence = _copy_fence(fence)
        self._cleanup = cleanup
        self._closing = None
        super().__init__(content, status_code=status_code, headers=headers,
                         media_type=media_type, background=background)

    async def _settle(self):
        if self._cleanup is not None:
            await self._cleanup()

    async def aclose(self):
        if self._closing is None:
            self._closing = asyncio.create_task(self._settle())
        await _finish_cleanup(self._closing)

    async def __call__(self, scope, receive, send):
        async def guarded_send(message):
            if message['type'] == 'http.response.body':
                await send_governed(send, message, publisher=self.publisher, fence=self.fence)
            else:
                await _send_generic(send, message, self.publisher)
        try:
            await super().__call__(scope, receive, guarded_send)
        finally:
            await self.aclose()
