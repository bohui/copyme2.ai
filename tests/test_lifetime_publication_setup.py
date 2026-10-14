"""Remote database setup has several round trips before the guarded send."""
import asyncio
from types import SimpleNamespace

import psycopg
import pytest

from apps.api.lifetime_memory_publication import TransactionalPublication, send_governed
from test_lifetime_memory_transport import FENCE


@pytest.mark.parametrize('stale', [False, True])
def test_brief_database_setup_delay_keeps_the_fence_and_send_boundary(monkeypatch, stale):
    class Connection:
        closed = False

        async def execute(self, statement, parameters=None):
            # Four remote round trips can exceed two seconds without any lock
            # contention. The lease is still checked after that setup.
            await asyncio.sleep(.55)
            if 'lock_lifetime_publication' in statement and stale:
                raise psycopg.errors.SerializationFailure('stale lifetime fence')
            async def fetchone():
                return (60,)
            return SimpleNamespace(fetchone=fetchone)

        async def close(self):
            self.closed = True

    connection = Connection()

    async def connect(*args, **kwargs):
        return connection
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)

    async def scenario():
        publisher = TransactionalPublication('synthetic', authenticated_owner=FENCE['identity']['owner_id'])
        sent = []

        async def send(message):
            assert not connection.closed
            sent.append(message)

        operation = send_governed(send, {'body': b'private'}, publisher=publisher, fence=FENCE)
        if stale:
            with pytest.raises(psycopg.errors.SerializationFailure):
                await operation
            assert not sent
        else:
            await operation
            assert sent == [{'body': b'private'}]
        assert connection.closed
        assert publisher.send_timeout == 2

    asyncio.run(scenario())
