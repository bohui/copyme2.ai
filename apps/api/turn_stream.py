"""Incremental turn transport; cancellation retains ownership of the turn task."""
import asyncio
import json
import anyio


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

    async def emit_text(text):
        if text:
            await queue.put({'type': 'text_delta', 'text': text})

    async def emit_event(event):
        if not isinstance(event, dict) or not event.get('type'):
            raise ValueError('Invalid turn stream event')
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
        except Exception:
            # Never expose provider credentials, private artifacts or raw exceptions.
            await queue.put({'type': 'error', 'message': 'The response could not be completed or saved. Please try again.'})

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
