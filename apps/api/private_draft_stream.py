"""Local debug draft delivery, retaining each read's publication guard."""
import asyncio
import json
import logging
import os
from urllib.parse import urlsplit

from starlette.responses import StreamingResponse

from .lifetime_memory_reads import ReadJSONResponse, _settle
from .turn_stream import STREAM_HEADERS


logger = logging.getLogger(__name__)


def draft_updates_enabled():
    return os.getenv('MEMORY_SPARK_SHOW_DRAFT_UPDATES', '').strip().lower() in {'1', 'true', 'yes', 'on'}


def local_draft_updates(request):
    if not draft_updates_enabled():
        return False
    browser_url = request.headers.get('origin') or request.headers.get('referer')
    if not browser_url:
        browser_url = 'http://' + (request.headers.get('x-forwarded-host') or request.headers.get('host', ''))
    try:
        return urlsplit(browser_url).hostname in {'localhost', '127.0.0.1', '::1'}
    except ValueError:
        return False


class PrivateDraftStreamResponse(StreamingResponse):
    def __init__(self, first, read, cleanup, *, poll_interval=2, heartbeat_interval=10):
        self.first, self.read, self.cleanup = first, read, cleanup
        self.poll_interval, self.heartbeat_interval = poll_interval, heartbeat_interval
        self._reading = self._closing = None
        super().__init__((), media_type='application/x-ndjson',
                         headers={**STREAM_HEADERS, 'Cache-Control': 'no-store'})

    async def stream_response(self, send):
        await send({'type': 'http.response.start', 'status': self.status_code, 'headers': self.raw_headers})
        previous = None
        value = self.first
        last_sent = asyncio.get_running_loop().time()

        async def event(body):
            await send({'type': 'http.response.body', 'body': body, 'more_body': True})

        try:
            while True:
                body = value.snapshot.body if isinstance(value, ReadJSONResponse) else json.dumps(
                    value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
                if body != previous:
                    frame = b'{"type":"draft_update","data":' + body + b'}\n'
                    if isinstance(value, ReadJSONResponse):
                        # Hold the original snapshot's authority lock across the actual send.
                        async with value.publisher.guard(value.snapshot.fence.model_dump(mode='json')):
                            await event(frame)
                    else:
                        await event(frame)
                    previous = body
                    last_sent = asyncio.get_running_loop().time()
                elif asyncio.get_running_loop().time() - last_sent >= self.heartbeat_interval:
                    await event(b'{"type":"heartbeat"}\n')
                    last_sent = asyncio.get_running_loop().time()
                if not json.loads(body).get('updating'):
                    await event(b'{"type":"complete"}\n')
                    break
                await asyncio.sleep(self.poll_interval)
                self._reading = asyncio.create_task(asyncio.to_thread(self.read))
                value = await asyncio.shield(self._reading)
        except Exception as error:
            logger.warning('Private draft stream unavailable: %s', type(error).__name__)
            await event(b'{"type":"error","code":"PRIVATE_DRAFT_UNAVAILABLE"}\n')
        await send({'type': 'http.response.body', 'body': b'', 'more_body': False})

    async def aclose(self):
        async def finish():
            if self._reading is not None:
                await asyncio.gather(self._reading, return_exceptions=True)
            await asyncio.to_thread(self.cleanup)
        if self._closing is None:
            self._closing = asyncio.create_task(finish())
        await _settle(self._closing)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.aclose()
