"""Explicit legacy-only compatibility, fenced against concurrent adoption.

An absent rollout flag never establishes that an owner is unmapped. A configured
server DSN always wins over the operator-only legacy deployment assertion. The
SQL helper holds auth.users FOR SHARE, conflicting with canonical adoption, only
through actual pipe/HTTP body admission. Generation never holds this lock.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, nullcontext
from dataclasses import dataclass
from math import ceil
import os
from uuid import UUID

from starlette.responses import JSONResponse, StreamingResponse

from .lifetime_memory_publication import PublicationUnavailable
from .lifetime_memory_reads import _settle


class LegacyMappingConflict(PublicationUnavailable):
    code = 'LIFETIME_GOVERNED_REQUEST_REQUIRED'


class LegacyAuthorityUnavailable(PublicationUnavailable):
    code = 'LIFETIME_WORKER_AUTHORITY_UNAVAILABLE'


@dataclass(frozen=True, init=False, repr=False)
class LegacyPublication:
    _dsn: str | None
    _owner: UUID
    send_timeout: float
    lock_timeout: float

    def __init__(self, dsn, *, authenticated_owner, send_timeout=2.0, lock_timeout=5.0):
        if not 0 < send_timeout <= 5 or not 0 < lock_timeout <= 5:
            raise ValueError('Legacy publication timeouts must be positive and at most five seconds')
        object.__setattr__(self, '_dsn', dsn)
        object.__setattr__(self, '_owner', UUID(str(authenticated_owner)))
        object.__setattr__(self, 'send_timeout', send_timeout)
        object.__setattr__(self, 'lock_timeout', lock_timeout)

    @property
    def owner(self):
        return self._owner

    @asynccontextmanager
    async def guard(self):
        async with self.session() as session:
            async with session.guard():
                yield

    @asynccontextmanager
    async def session(self):
        """Reuse a response connection, never its transaction or admission result."""
        session = _LegacySession(self)
        try:
            yield session
        finally:
            if session.connection is not None:
                await _settle(asyncio.create_task(session.connection.close()))


class _LegacySession:
    def __init__(self, publisher):
        self.publisher = publisher
        self.connection = None

    @asynccontextmanager
    async def guard(self):
        publisher = self.publisher
        if not publisher._dsn:
            from .lifetime_memory_runtime import lifetime_enabled
            legacy_only = os.getenv('MEMOIR_LEGACY_ONLY_DEPLOYMENT', '').lower() in {'1','true','yes'}
            if not legacy_only or lifetime_enabled():
                raise LegacyAuthorityUnavailable('Legacy execution requires authoritative cohort verification')
            # Only a separately asserted pre-migration-only deployment may use
            # this branch. It must never be configured for a canonical cohort.
            async with asyncio.timeout(publisher.send_timeout):
                yield
            return
        from psycopg import AsyncConnection, Error
        try:
            try:
                async with asyncio.timeout(publisher.lock_timeout):
                    if self.connection is None:
                        self.connection = await AsyncConnection.connect(publisher._dsn, connect_timeout=max(2, ceil(publisher.lock_timeout)))
                    connection = self.connection
                    await connection.execute('set local role authenticated')
                    await connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(publisher._owner),))
                    await connection.execute("select set_config('lock_timeout',%s,true)", (f'{int(publisher.lock_timeout*1000)}ms',))
                    result = await connection.execute('select public.lock_lifetime_legacy_worker_admission()')
                    admitted = (await result.fetchone())[0]
            except (Error, TimeoutError) as error:
                raise LegacyAuthorityUnavailable('Legacy identity authority is unavailable') from error
            if admitted is False:
                raise LegacyMappingConflict('This owner requires governed execution')
            if admitted is not True:
                raise LegacyAuthorityUnavailable('Invalid legacy identity authority response')
            async with asyncio.timeout(publisher.send_timeout):
                yield
        finally:
            if self.connection is not None:
                # End this body's transaction before requesting another chunk.
                # The session keeps only the socket; adoption is checked again.
                async def release():
                    async with asyncio.timeout(publisher.lock_timeout):
                        await self.connection.rollback()
                await _settle(asyncio.create_task(release()))


class _LegacyResponse:
    def __init__(self, content, *, publisher, **kwargs):
        if not callable(getattr(publisher, 'guard', None)):
            raise TypeError('Legacy response requires an authoritative publication guard')
        self.publisher = publisher
        super().__init__(content, **kwargs)

    async def __call__(self, scope, receive, send):
        session = getattr(self.publisher, 'session', None)
        connection_scope = session() if callable(session) else nullcontext(self.publisher)
        async with connection_scope as publisher:
            async def guarded_send(message):
                if message['type'] == 'http.response.body':
                    async with publisher.guard():
                        await send(message)
                else:
                    await send(message)
            await super().__call__(scope, receive, guarded_send)


class LegacyJSONResponse(_LegacyResponse, JSONResponse):
    """Freeze JSON now; gate its actual ASGI body send against adoption."""


class LegacyStreamingResponse(_LegacyResponse, StreamingResponse):
    """Gate each dequeued stream body through actual ASGI send completion."""


class LegacyRequestBody:
    """Freeze one legacy request; hold authority through transport body write.

    The next iteration resumes only after the transport has consumed the current
    chunk. Close explicitly on transport failure to release the adoption lock.
    """
    def __init__(self, content, *, publisher):
        self._content = bytes(content)
        self._publisher = publisher
        self._iterator = None

    async def _chunks(self):
        async with self._publisher.guard():
            yield self._content

    def __aiter__(self):
        if self._iterator is not None:
            raise RuntimeError('Legacy request bodies cannot be replayed')
        self._iterator = self._chunks()
        return self._iterator

    async def aclose(self):
        if self._iterator is not None:
            await _settle(asyncio.create_task(self._iterator.aclose()))
