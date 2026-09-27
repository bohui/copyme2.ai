"""Incremental turn transport; cancellation retains ownership of the turn task."""
import asyncio
import json
import anyio


class VisibleText:
    """Hold split marker prefixes and suppress the appended machine-only suffix."""
    prefix = '[[MEMORY_SPARK_'

    def __init__(self):
        self.pending = ''
        self.hidden = False

    def feed(self, text, *, final=False):
        if self.hidden:
            return ''
        self.pending += text
        index = self.pending.find(self.prefix)
        if index >= 0:
            visible = self.pending[:index]
            self.pending = ''
            self.hidden = True
            return visible
        keep = 0
        for size in range(1, len(self.prefix)):
            if self.pending.endswith(self.prefix[:size]):
                keep = size
        # Drop incomplete machine marker prefixes at EOF too.
        visible = self.pending[:-keep] if keep else self.pending
        self.pending = '' if final else (self.pending[-keep:] if keep else '')
        return visible


async def turn_events(run, cleanup=None):
    queue = asyncio.Queue(maxsize=64)

    async def emit(text):
        if text:
            await queue.put({'type': 'text_delta', 'text': text})

    async def produce():
        try:
            result = await run(emit)
            await queue.put({'type': 'result', 'data': result})
        except Exception:
            # Never expose provider credentials, private artifacts or raw exceptions.
            await queue.put({'type': 'error', 'message': 'The response could not be completed or saved. Please try again.'})

    task = asyncio.create_task(produce())
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
            yield json.dumps(event, ensure_ascii=False) + '\n'
            if event['type'] in {'result', 'error'}:
                break
    finally:
        # Starlette cancels its AnyIO scope on disconnect; settlement must
        # survive that cancellation before releasing storage and turn leases.
        with anyio.CancelScope(shield=True):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if cleanup:
                await cleanup()


STREAM_HEADERS = {'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no'}
