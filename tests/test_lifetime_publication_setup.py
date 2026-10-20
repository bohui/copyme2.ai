"""Remote database setup stays bounded without weakening the guarded send."""
import asyncio
from types import SimpleNamespace

import psycopg
import pytest

from apps.api.lifetime_memory_publication import TransactionalPublication, send_governed
from test_lifetime_memory_transport import FENCE


@pytest.mark.parametrize('stale', [False, True])
def test_publication_batches_session_setup_before_the_per_send_fence(monkeypatch, stale):
    calls = []

    class Connection:
        closed = False

        async def execute(self, statement, parameters=None):
            calls.append((statement, parameters))
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
            assert 'lock_lifetime_publication' in calls[-1][0]
            assert not connection.closed
            sent.append(message)

        if stale:
            with pytest.raises(psycopg.errors.SerializationFailure):
                await send_governed(send, {'body': b'private'}, publisher=publisher, fence=FENCE)
            assert not sent
        else:
            await send_governed(send, {'body': b'private'}, publisher=publisher, fence=FENCE)
            assert sent == [{'body': b'private'}]
        assert connection.closed
        assert len(calls) == 2, 'Setup must not add a round trip for each session setting'
        assert "set_config('role','authenticated',true)" in calls[0][0]
        assert calls[0][1] == (FENCE['identity']['owner_id'], '5000ms')

    asyncio.run(scenario())


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
