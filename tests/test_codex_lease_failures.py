import asyncio
import base64
import threading

import pytest

from apps.api.agent_lock import AgentTurnLease
from apps.api.codex_runtime import CodexRuntime


class Storage:
    user_id = '11111111-1111-4111-8111-111111111111'

    def __init__(self):
        self.events = []

    def acquire_agent_turn_lease(self, *args):
        return True

    def renew_agent_turn_lease(self, *args):
        return False

    def release_agent_turn_lease(self, *args):
        self.events.append('release')
        return True

    def agent_session(self):
        return None

    def memories(self):
        return []

    def put_agent_turn_file(self, *args):
        self.events.append('upload')

    def commit_agent_turn(self, *args):
        self.events.append('commit')


def test_lost_lease_does_not_upload_or_commit(monkeypatch):
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://unused')
    async def worker(**kwargs):
        return {'thread_id': 'thread', 'reply': 'reply', 'artifacts': [
            {'path': 'sessions/thread.json', 'content': base64.b64encode(b'state').decode()}
        ]}
    monkeypatch.setattr(runtime, '_worker_turn', worker)
    with pytest.raises(RuntimeError, match='lease was lost'):
        asyncio.run(runtime.turn(storage, 'hello'))
    assert storage.events == ['release']


@pytest.mark.parametrize('outage', [False, True])
def test_heartbeat_loss_cancels_running_turn(monkeypatch, outage):
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://unused')
    real_sleep = asyncio.sleep
    started = threading.Event()
    def renew(*args):
        assert started.wait(5)
        if outage:
            raise RuntimeError('database unavailable')
        return False
    monkeypatch.setattr(storage, 'renew_agent_turn_lease', renew)
    async def immediate_sleep(seconds):
        await real_sleep(0)
    monkeypatch.setattr(asyncio, 'sleep', immediate_sleep)
    async def worker(**kwargs):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            storage.events.append('worker_stopped')
    monkeypatch.setattr(runtime, '_worker_turn', worker)
    with pytest.raises(RuntimeError, match='lease was lost'):
        asyncio.run(runtime.turn(storage, 'hello'))
    assert 'upload' not in storage.events and 'commit' not in storage.events
    assert storage.events == ['worker_stopped', 'release']


def test_cancelled_io_finishes_before_release():
    storage = Storage()
    entered = threading.Event()
    finish = threading.Event()
    def upload():
        entered.set()
        assert finish.wait(5)
        storage.events.append('upload_finished')
    async def run():
        async def turn():
            async with AgentTurnLease(storage) as lease:
                await lease.io(upload)
        task = asyncio.create_task(turn())
        await asyncio.to_thread(entered.wait)
        task.cancel()
        await asyncio.sleep(0)
        assert 'release' not in storage.events
        task.cancel()
        await asyncio.sleep(0)
        assert 'release' not in storage.events
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert storage.events == ['upload_finished', 'release']


def test_cancellation_during_acquisition_releases_its_token(monkeypatch):
    storage = Storage()
    entered, finish = threading.Event(), threading.Event()
    def acquire(*args):
        entered.set()
        assert finish.wait(5)
        storage.events.append('acquired')
        return True
    monkeypatch.setattr(storage, 'acquire_agent_turn_lease', acquire)
    async def run():
        async def turn():
            async with AgentTurnLease(storage):
                pytest.fail('cancelled turn should not start')
        task = asyncio.create_task(turn())
        await asyncio.to_thread(entered.wait)
        task.cancel()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert storage.events == ['acquired', 'release']
