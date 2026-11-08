"""Deliver saved workspace snapshots when Atlas commits a change."""

import asyncio
from collections import defaultdict
from contextlib import aclosing
from hashlib import sha256
import json
import logging

from fastapi import HTTPException
from starlette.responses import StreamingResponse

from .lifetime_memory_policy import PolicyUnavailable
from .lifetime_memory_reads import ReadAdmissionFailure, _settle
from .turn_progress import thinking_steps_enabled
from .turn_stream import STREAM_HEADERS


logger = logging.getLogger(__name__)
class AtlasUpdates:
    def __init__(self):
        self._subscribers = defaultdict(set)
        self._task = None
        self._connected = False

    @staticmethod
    def _signal(subscribers):
        for queue in subscribers:
            if queue.empty():
                queue.put_nowait(None)

    async def _listen(self, dsn):
        from psycopg import AsyncConnection, Error

        delay = 1
        while True:
            try:
                async with await AsyncConnection.connect(dsn, autocommit=True, connect_timeout=5) as connection:
                    await connection.execute('LISTEN memoir_atlas_updates')
                    self._connected = True
                    delay = 1
                    # Catch up once after LISTEN is installed, including after a disconnect.
                    for subscribers in self._subscribers.values():
                        self._signal(subscribers)
                    async for change in connection.notifies():
                        key, _, kind = change.payload.partition(':')
                        if kind == 'workspace' or (kind == 'progress' and thinking_steps_enabled()):
                            self._signal(self._subscribers.get(key, ()))
            except Error as error:
                logger.warning('Atlas notification connection interrupted: %s', type(error).__name__)
            finally:
                self._connected = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def events(self, dsn, owner, project_id, *, expires_in, heartbeat=15):
        key = sha256(f'{owner}:{project_id}'.encode()).hexdigest()
        queue = asyncio.Queue(maxsize=1)
        subscribers = self._subscribers[key]
        subscribers.add(queue)
        if self._task is None:
            self._task = asyncio.create_task(self._listen(dsn))
        if self._connected:
            self._signal((queue,))
        try:
            loop = asyncio.get_running_loop()
            expires = loop.time() + expires_in
            while (remaining := expires - loop.time()) > 0:
                try:
                    await asyncio.wait_for(queue.get(), timeout=min(heartbeat, remaining))
                except TimeoutError:
                    if loop.time() < expires:
                        yield False
                else:
                    yield True
        finally:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(key, None)

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None


class AtlasWorkspaceStream(StreamingResponse):
    def __init__(self, updates, read, read_more, cleanup):
        super().__init__((), media_type='text/event-stream',
                         headers={**STREAM_HEADERS, 'Cache-Control': 'no-store, no-transform'})
        self.updates, self.read, self.read_more, self.cleanup = updates, read, read_more, cleanup
        self.reading = None

    async def stream_response(self, send):
        await send({'type': 'http.response.start', 'status': self.status_code, 'headers': self.raw_headers})

        async def frame(body):
            await send({'type': 'http.response.body', 'body': body, 'more_body': True})

        async def publish(read, *args):
            self.reading = asyncio.create_task(asyncio.to_thread(read, *args))
            value = await asyncio.shield(self.reading)
            async with value.publisher.guard(value.snapshot.fence.model_dump(mode='json')):
                await frame(b'event: atlas-update\ndata: ' + value.snapshot.body + b'\n\n')
            return value.snapshot

        previous = None
        async with aclosing(self.updates) as updates:
            async for changed in updates:
                if not changed:
                    await frame(b': heartbeat\n\n')
                    continue
                # A writer can commit between capture and send. Retry one fresh read.
                for attempt in range(2):
                    try:
                        snapshot = await publish(self.read, previous)
                        if json.loads(snapshot.body).get('map_refresh'):
                            cursor = None
                            cursors = set()
                            while True:
                                continuation = await publish(self.read_more, snapshot.fence, cursor)
                                cursor = json.loads(continuation.body)['map_page'].get('next_cursor')
                                if not cursor:
                                    break
                                if cursor in cursors:
                                    raise HTTPException(503, 'Map pages did not advance')
                                cursors.add(cursor)
                        previous = snapshot.fence
                        break
                    except (ReadAdmissionFailure, PolicyUnavailable, HTTPException) as error:
                        status = getattr(error, 'status', getattr(error, 'status_code', 503))
                        previous = None
                        if status == 409 and attempt == 0:
                            continue
                        if status in {401, 403, 404}:
                            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
                            return
                        await frame(b'event: atlas-unavailable\ndata: {}\n\n')
                        break
        await send({'type': 'http.response.body', 'body': b'', 'more_body': False})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            async def close():
                if self.reading is not None:
                    await asyncio.gather(self.reading, return_exceptions=True)
                await asyncio.to_thread(self.cleanup)
            await _settle(asyncio.create_task(close()))
