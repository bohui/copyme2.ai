import asyncio

import psycopg
import pytest

from apps.api.lifetime_memory_activation import ActivationPublication, CanonicalActivationUnavailable
from test_lifetime_memory_transport import FENCE


@pytest.mark.parametrize('unavailable',[False,True])
def test_activation_setup_can_wait_briefly_but_still_rejects_unavailable_authority(monkeypatch,unavailable):
    class Connection:
        closed=False

        async def execute(self,statement,parameters=None):
            await asyncio.sleep(.55)
            if 'lock_lifetime_provider_activation' in statement and unavailable:
                raise psycopg.errors.SerializationFailure('activation unavailable')

        async def close(self):
            self.closed=True

    connection=Connection()
    async def connect(*args,**kwargs):
        return connection
    monkeypatch.setattr(psycopg.AsyncConnection,'connect',connect)

    async def scenario():
        publisher=ActivationPublication('synthetic',authenticated_owner=FENCE['identity']['owner_id'])
        entered=[]
        async def publish():
            async with publisher.guard():
                entered.append(True)
        if unavailable:
            with pytest.raises(CanonicalActivationUnavailable):
                await publish()
            assert not entered
        else:
            await publish()
            assert entered==[True]
        assert connection.closed and publisher.send_timeout==2
    asyncio.run(scenario())
