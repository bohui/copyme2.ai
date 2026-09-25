import asyncio

import pytest

from apps.api.agent_lock import AgentTurnBusyError, AgentTurnLease


class FakeLeaseStorage:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.calls = []

    def acquire_agent_turn_lease(self, token, seconds):
        self.calls.append(("acquire", token, seconds))
        return self.acquired

    def renew_agent_turn_lease(self, token, seconds):
        self.calls.append(("renew", token, seconds))
        return True

    def release_agent_turn_lease(self, token):
        self.calls.append(("release", token))
        return True


def test_lease_releases_after_a_successful_turn():
    storage = FakeLeaseStorage()

    async def run():
        async with AgentTurnLease(storage, lease_seconds=30) as lease:
            lease.assert_held()

    asyncio.run(run())

    assert [call[0] for call in storage.calls] == ["acquire", "release"]


def test_lease_refuses_a_second_holder():
    storage = FakeLeaseStorage(acquired=False)

    async def run():
        with pytest.raises(AgentTurnBusyError):
            async with AgentTurnLease(storage):
                pass

    asyncio.run(run())
    assert [call[0] for call in storage.calls] == ["acquire"]
