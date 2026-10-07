"""Incremental turn transport; cancellation retains ownership of the turn task."""
import asyncio
import json
import logging
import anyio

from .diagnostics import (configure_diagnostic_logger, failure_class,
                          log_diagnostic, new_request_id)


diagnostic_logger = configure_diagnostic_logger(logging.getLogger('memoir.turn_stream'))


class VisibleText:
    """Hold split marker prefixes and suppress the appended machine-only suffix."""
    prefixes = ('[[MEMORY_SPARK_', '<!-- profile:')

    def __init__(self):
        self.pending = ''
        self.hidden = False

    def feed(self, text, *, final=False):
        if self.hidden:
            return ''
        self.pending += text
        lowered = self.pending.casefold()
        matches = [lowered.find(prefix.casefold()) for prefix in self.prefixes]
        matches = [index for index in matches if index >= 0]
        if matches:
            index = min(matches)
            visible = self.pending[:index]
            self.pending = ''
            self.hidden = True
            return visible
        keep = 0
        for prefix in self.prefixes:
            for size in range(1, len(prefix)):
                if lowered.endswith(prefix.casefold()[:size]):
                    keep = max(keep, size)
        # Drop incomplete machine marker prefixes at EOF too.
        visible = self.pending[:-keep] if keep else self.pending
        self.pending = '' if final else (self.pending[-keep:] if keep else '')
        return visible


async def turn_events(run, cleanup=None):
    queue = asyncio.Queue(maxsize=64)
    request_id = new_request_id()
    stage = 'acceptance'
    saved_boundary = False

    async def emit_text(text):
        if text:
            await queue.put({'type': 'text_delta', 'text': text})

    async def emit_event(event):
        nonlocal request_id, stage, saved_boundary
        if not isinstance(event, dict) or not event.get('type'):
            raise ValueError('Invalid turn stream event')
        if event.get('turn_id'):
            request_id = new_request_id(event['turn_id'])
        if event['type'] == 'progress':
            candidate = (event.get('data') or {}).get('id')
            if candidate in {'context', 'language', 'reply', 'save', 'workspace'}:
                stage = candidate
        if event['type'] == 'conversation_saved':
            saved_boundary = True
        await queue.put(event)

    class Emitter:
        async def __call__(self, text):
            await emit_text(text)

        async def event(self, event):
            await emit_event(event)

    async def produce():
        try:
            result = await run(Emitter())
            await queue.put({'type': 'result', 'data': result})
        except Exception as error:
            status_code = getattr(getattr(error, 'response', None), 'status_code',
                                  getattr(error, 'status_code', None))
            log_diagnostic(
                diagnostic_logger, 'turn_stream_failed', request_id,
                component='memoir.turn_stream', status='failed', call_type=stage,
                failure_class=failure_class(error, status_code=status_code),
                error_code=type(error).__name__, http_status=status_code,
                terminal_event='conversation_saved' if saved_boundary else None,
            )
            # Never expose provider credentials, private artifacts or raw exceptions.
            event = {'type': 'error', 'message': 'The response could not be completed or saved. Please try again.'}
            partial_trajectory = getattr(error, 'trajectory', None)
            if isinstance(partial_trajectory, dict):
                # Worker-side trajectories are already recorder-redacted. Keep
                # the partial evidence while never serializing the exception.
                event['trajectory'] = partial_trajectory
            await queue.put(event)

    task = asyncio.create_task(produce())
    conversation_saved = False
    try:
        yield json.dumps({'type': 'started'}) + '\n'
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except asyncio.TimeoutError:
                if task.done():
                    yield json.dumps({'type': 'error', 'message': 'The response was interrupted before it could be saved.'}) + '\n'
                    break
                yield json.dumps({'type': 'heartbeat'}) + '\n'
                continue
            if event.get('type') == 'conversation_saved':
                conversation_saved = True
            yield json.dumps(event, ensure_ascii=False) + '\n'
            if event['type'] in {'result', 'error'}:
                break
    finally:
        # Starlette cancels its AnyIO scope on disconnect; settlement must
        # survive that cancellation before releasing storage and turn leases.
        # Once the conversation boundary has been emitted, let the optional
        # workspace phase settle instead of cancelling it with the HTTP stream.
        with anyio.CancelScope(shield=True):
            if not conversation_saved:
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if cleanup:
                await cleanup()


STREAM_HEADERS = {'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'}
