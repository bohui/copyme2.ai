"""Authenticated provider admission for the canonical conversation engine.

"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from .lifetime_memory_publication import PublicationUnavailable
from .lifetime_memory_reads import _settle


class CanonicalActivationUnavailable(PublicationUnavailable):
    code = 'LIFETIME_PROVIDER_AUTHORITY_UNAVAILABLE'

    def __init__(self):
        super().__init__('Conversation provider authority is unavailable')


async def require_provider_activation(connection):
    from psycopg import Error
    try:
        await connection.execute('select public.lock_lifetime_provider_activation()')
    except Error:
        raise CanonicalActivationUnavailable() from None


@dataclass(frozen=True, init=False, repr=False)
class ActivationPublication:
    _dsn: str
    _owner: UUID
    send_timeout: float
    lock_timeout: float

    def __init__(self, dsn, *, authenticated_owner, send_timeout=2.0, lock_timeout=2.0):
        if not dsn:
            raise CanonicalActivationUnavailable()
        if not 0 < send_timeout <= 5 or not 0 < lock_timeout <= 5:
            raise ValueError('Activation timeouts must be positive and at most five seconds')
        object.__setattr__(self,'_dsn',dsn)
        object.__setattr__(self,'_owner',UUID(str(authenticated_owner)))
        object.__setattr__(self,'send_timeout',send_timeout)
        object.__setattr__(self,'lock_timeout',lock_timeout)

    async def _lock(self, connection):
        await require_provider_activation(connection)

    @asynccontextmanager
    async def guard(self):
        from psycopg import AsyncConnection, Error
        connection=None
        try:
            try:
                async with asyncio.timeout(self.lock_timeout):
                    connection=await AsyncConnection.connect(self._dsn,connect_timeout=2)
                    await connection.execute('set local role authenticated')
                    await connection.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(self._owner),))
                    await connection.execute("select set_config('lock_timeout',%s,true)",(f'{int(self.lock_timeout*1000)}ms',))
                    await self._lock(connection)
            except (Error, TimeoutError):
                raise CanonicalActivationUnavailable() from None
            async with asyncio.timeout(self.send_timeout):yield
        finally:
            if connection is not None:await _settle(asyncio.create_task(connection.close()))
