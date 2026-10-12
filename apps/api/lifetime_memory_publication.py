"""Opt-in transaction held through actual transport send, never queue insertion.

Requires a server-configured transactional PostgreSQL connection. PostgREST RPC
alone cannot implement this boundary. No connection is opened on import.
"""
import asyncio
from contextlib import asynccontextmanager
from uuid import UUID

from .lifetime_memory_contracts import ExecutionFence


class PublicationUnavailable(RuntimeError):
    pass


class TransactionalPublication:
    def __init__(self, dsn, *, authenticated_owner, send_timeout=2.0, lock_timeout=2.0):
        if not dsn:
            raise PublicationUnavailable('Governed publication requires a transactional database connection')
        if not 0 < send_timeout <= 5 or not 0 < lock_timeout <= 5:
            raise ValueError('publication timeouts must be positive and at most five seconds')
        self._dsn = dsn
        self.owner = UUID(str(authenticated_owner))
        self.send_timeout = send_timeout
        self.lock_timeout = lock_timeout

    @asynccontextmanager
    async def guard(self, fence):
        from psycopg import AsyncConnection
        from psycopg.types.json import Jsonb

        # Validate/copy before any connection. The verified authentication result,
        # not a browser field or queued event, supplies self.owner.
        snapshot = ExecutionFence.model_validate(fence).model_dump(mode='json')
        if snapshot['identity']['owner_id'] != str(self.owner):
            raise PublicationUnavailable('Publication owner mismatch')
        connection = None
        try:
            async with asyncio.timeout(self.lock_timeout):
                connection = await AsyncConnection.connect(self._dsn, connect_timeout=2)
                await connection.execute('set local role authenticated')
                await connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(self.owner),))
                await connection.execute("select set_config('lock_timeout',%s,true)", (f'{int(self.lock_timeout*1000)}ms',))
                result = await connection.execute('select public.lock_lifetime_publication(%s)', (Jsonb(snapshot),))
                remaining = float((await result.fetchone())[0])
            allowance = min(self.send_timeout, remaining - 0.1)
            if allowance <= 0:
                raise PublicationUnavailable('Publication lease expires too soon')
            # The caller awaits ASGI send (or yields from the response body)
            # inside this scope. Do not await producer work or another DB RPC.
            async with asyncio.timeout(allowance):
                yield
        finally:
            if connection is not None:
                # Closing rolls back the read-only publication transaction and
                # releases locks even if ASGI disconnect cancellation repeats.
                closing = asyncio.create_task(connection.close())
                while not closing.done():
                    try:
                        await asyncio.shield(closing)
                    except asyncio.CancelledError:
                        continue
                closing.result()


async def send_governed(send, message, *, publisher, fence):
    """Guard actual ASGI send completion. Snapshot belongs to this exact body.

    Use for non-streamed JSON and dequeued stream bodies, not their producers.
    Already-delivered or network-buffered text cannot be recalled on withdrawal.
    """
    snapshot = ExecutionFence.model_validate(fence).model_dump(mode='json')
    async with publisher.guard(snapshot):
        await send(message)
