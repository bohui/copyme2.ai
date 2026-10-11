"""Independent context reads overlap without releasing live storage operations."""
import asyncio
import json
import threading
from uuid import uuid4

import pytest

from apps.api.turn_stream import turn_events
from test_name_only_opening import Storage, harness, proposal


def test_saved_context_reads_overlap_before_model_dispatch(monkeypatch, tmp_path):
    storage = Storage({'preferred_language': 'zh-CN'})
    runtime, calls = harness(monkeypatch, tmp_path, storage, proposal(), 'local')
    entered, lock, all_entered = set(), threading.Lock(), threading.Event()
    def read(name, value):
        with lock:
            entered.add(name)
            if len(entered) == 3: all_entered.set()
        if not all_entered.wait(0.5):
            raise RuntimeError('Independent reads were serialized')
        return value
    storage.agent_session = lambda: read('session', None)
    storage.memories = lambda: read('memories', [])
    profile = storage.profile()
    storage.profile = lambda: read('profile', profile)

    async def run():
        async def turn(emit):
            return await runtime.turn(storage, '我叫韩凤江', project_id='project',
                client_turn_id=str(uuid4()), on_delta=emit, on_event=emit.event)
        packets = [json.loads(line) async for line in turn_events(turn)]
        assert packets[-1]['type'] == 'result'
        assert packets[-1]['data']['conversation_saved'] is True
        assert all_entered.is_set() and len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('termination', ['error', 'cancel'])
def test_failed_preparation_settles_all_reads_before_lease_and_client_close(monkeypatch, tmp_path, termination):
    storage = Storage({'preferred_language': 'zh-CN'})
    runtime, calls = harness(monkeypatch, tmp_path, storage, proposal(), 'local')
    entered, finished, lock = set(), set(), threading.Lock()
    all_entered, release, failing = threading.Event(), threading.Event(), threading.Event()
    released, closed = [], []
    def read(name, value):
        with lock:
            entered.add(name)
            if len(entered) == 3: all_entered.set()
        assert all_entered.wait(2)
        if name == 'profile' and termination == 'error':
            failing.set()
            raise RuntimeError('Controlled profile read failure')
        assert release.wait(3)
        with lock: finished.add(name)
        return value
    storage.agent_session = lambda: read('session', None)
    storage.memories = lambda: read('memories', [])
    storage.profile = lambda: read('profile', {'preferred_language': 'zh-CN'})
    storage.release_agent_turn_lease = lambda *a: released.append(set(finished)) or True

    async def run():
        async def turn(emit):
            return await runtime.turn(storage, '我叫韩凤江', project_id='project',
                client_turn_id=str(uuid4()), on_delta=emit, on_event=emit.event)
        async def cleanup(): closed.append(set(finished))
        stream = turn_events(turn, cleanup=cleanup)
        assert json.loads(await anext(stream))['type'] == 'started'
        async def consume(): return [json.loads(line) async for line in stream]
        task = asyncio.create_task(consume())
        try:
            assert await asyncio.to_thread(all_entered.wait, 2)
            if termination == 'cancel': task.cancel()
            else: assert await asyncio.to_thread(failing.wait, 2)
            # Give the producer a chance to fail/cancel; the blocked storage
            # reads must still own the lease and the caller's client.
            await asyncio.sleep(0.01)
            assert not released and not closed
        finally:
            release.set()
        if termination == 'cancel':
            with pytest.raises(asyncio.CancelledError): await task
        else:
            packets = await task
            assert packets[-1]['type'] == 'error'
        expected = {'session', 'memories'} if termination == 'error' else {'session', 'memories', 'profile'}
        assert released == [expected] and closed == [expected]
        assert calls == []
    asyncio.run(run())
