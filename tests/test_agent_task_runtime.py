import asyncio
import threading
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from apps.api.codex_runtime import CodexRuntime
from apps.api.task_queue import configured_queue


@pytest.mark.parametrize('publisher_down', [False, True])
def test_collector_publishes_only_after_commit_and_invalidates_confirmation(monkeypatch, tmp_path, publisher_down):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    storage = Mock()
    storage.user_id = '11111111-1111-4111-8111-111111111111'
    storage.acquire_agent_turn_lease.return_value = True
    storage.renew_agent_turn_lease.return_value = True
    storage.release_agent_turn_lease.return_value = True
    storage.agent_session.return_value = None
    storage.memories.return_value = [{'id': 'school', 'kind': 'agent',
        'content': 'Storyteller: I went to school.\nMemory Spark: Which school?'}]
    storage.profile.return_value = {'preferred_language': 'en-AU'}
    storage.place_journey.return_value = None
    storage.story_entitlement.return_value = None
    storage.recall_rounds_completed.return_value = 0
    storage.commit_agent_turn.return_value = {'id': 'new-turn'}
    queue = configured_queue()
    queue.update_collection(storage.user_id, 'project', expected_revision=0, periods={}, ready=True)
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test-key')
    runtime._worker_turn = AsyncMock(return_value={'thread_id': 'collector-thread', 'reply':
        'I can prepare that. [[MEMORY_SPARK_TASKS]][{"kind":"BuildSourceExport","memory_ids":["school"]}][[/MEMORY_SPARK_TASKS]]'})

    async def publish(owner, project, task):
        storage.commit_agent_turn.assert_called_once()
        assert queue.collection(owner, project)['ready'] is False
        assert task.sources[0].content == 'I went to school.'
        if publisher_down:
            raise httpx.ConnectError('publisher unavailable')
        return queue.submit(owner, project, task)

    runtime.publish_task = AsyncMock(side_effect=publish)
    result = asyncio.run(runtime.turn(storage, 'Export my memories', project_id='project'))
    assert result['reply'] == 'I can prepare that.'
    assert 'MEMORY_SPARK_TASKS' not in storage.commit_agent_turn.call_args.args[2]
    runtime.publish_task.assert_awaited_once()
    assert queue.collection(storage.user_id, 'project')['revision'] == 2
    if publisher_down:
        assert not result['tasks']
        assert result['task_errors'] == [{'kind': 'BuildSourceExport', 'code': 'TASK_NOT_QUEUED'}]
    else:
        assert result['tasks'][0]['status'] == 'QUEUED'
        assert not result['task_errors']


def test_next_turn_can_generate_while_workspace_phase_is_pending(monkeypatch):
    class Storage:
        user_id = '11111111-1111-4111-8111-111111111111'

        def acquire_agent_turn_lease(self, *args):
            return True

        def renew_agent_turn_lease(self, *args):
            return True

        def release_agent_turn_lease(self, *args):
            return True

        def agent_session(self):
            return None

        def memories(self):
            return []

        def profile(self):
            return getattr(self, 'saved_profile', {'preferred_language': 'en-AU'})

        def save_profile(self, profile):
            self.saved_profile = dict(profile)

        def place_journey(self):
            return None

        def story_entitlement(self):
            return None

        def commit_agent_turn(self, *args):
            return {'id': 'saved'}

    storage = Storage()
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test-key')
    workspace_started = asyncio.Event()
    release_workspace = asyncio.Event()
    worker_started = []

    async def worker(**kwargs):
        worker_started.append(kwargs['text'])
        return {'thread_id': f"thread-{len(worker_started)}", 'reply': f"Reply {len(worker_started)}"}

    async def workspace(**kwargs):
        workspace_started.set()
        await release_workspace.wait()
        return {
            'place_journey': None,
            'place_journey_change': None,
            'profile_updates': None,
            'family_context': None,
            'family_context_update': None,
            'tasks': [],
            'task_errors': [],
        }

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    monkeypatch.setattr(runtime, '_persist_workspace', workspace)

    async def run():
        first = asyncio.create_task(runtime.turn(storage, 'first'))
        await asyncio.wait_for(workspace_started.wait(), 1)
        second = asyncio.create_task(runtime.turn(storage, 'second'))
        for _ in range(100):
            if len(worker_started) == 2:
                break
            await asyncio.sleep(0.01)
        assert worker_started == ['first', 'second']
        release_workspace.set()
        await asyncio.gather(first, second)

    asyncio.run(run())


def test_next_turn_can_generate_while_workspace_lease_free_write_is_pending(monkeypatch):
    class Storage:
        user_id = '11111111-1111-4111-8111-111111111111'

        def __init__(self):
            self.lease_lock = threading.Lock()
            self.lease_held = False
            self.workspace_started = threading.Event()
            self.release_workspace = threading.Event()

        def acquire_agent_turn_lease(self, *args):
            with self.lease_lock:
                if self.lease_held:
                    return False
                self.lease_held = True
                return True

        def renew_agent_turn_lease(self, *args):
            with self.lease_lock:
                return self.lease_held

        def release_agent_turn_lease(self, *args):
            with self.lease_lock:
                self.lease_held = False
            return True

        def agent_session(self):
            return None

        def memories(self):
            return []

        def profile(self):
            return getattr(self, 'saved_profile', {'preferred_language': 'en-AU'})

        def save_profile(self, profile):
            self.saved_profile = dict(profile)

        def place_journey(self):
            return None

        def story_entitlement(self):
            return {
                'status': 'paid',
                'plan_key': 'family_memoir_v1',
                'family_tree': True,
                'timeline': True,
                'stripe_price_id': 'price_family_test',
            }

        def family_context(self, project_id):
            return None

        def upsert_family_context(self, project_id, document, expected_revision):
            self.workspace_started.set()
            assert self.release_workspace.wait(2)
            return {'changed': True, 'document': document, 'revision': 1}

        def commit_agent_turn(self, *args):
            return {'id': 'saved'}

    monkeypatch.setenv('STRIPE_PRICE_FAMILY', 'price_family_test')
    storage = Storage()
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test-key')
    worker_started = []

    async def worker(**kwargs):
        worker_started.append(kwargs['text'])
        if kwargs['text'] == 'first':
            return {
                'thread_id': 'thread-first',
                'reply': (
                    'Who was there? '
                    '[[MEMORY_SPARK_FAMILY_TREE]]'
                    '{"people":[{"id":"p-me","name":"Avery"}],"relationships":[]}'
                    '[[/MEMORY_SPARK_FAMILY_TREE]] '
                    '[[MEMORY_SPARK_AUTHOR_TIMELINE]]'
                    '{"timeline":[],"life_periods":[]}'
                    '[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'
                ),
                'artifacts': [],
            }
        return {'thread_id': 'thread-second', 'reply': 'And then? ', 'artifacts': []}

    monkeypatch.setattr(runtime, '_worker_turn', worker)

    async def run():
        first = asyncio.create_task(runtime.turn(storage, 'first', project_id='project-family'))
        await asyncio.to_thread(storage.workspace_started.wait, 2)
        second = asyncio.create_task(runtime.turn(storage, 'second', project_id='project-family'))
        await asyncio.wait_for(asyncio.sleep(0), 1)
        for _ in range(100):
            if len(worker_started) == 2:
                break
            await asyncio.sleep(0.01)
        assert worker_started == ['first', 'second']
        storage.release_workspace.set()
        await asyncio.gather(first, second)

    asyncio.run(run())


def test_cancelled_workspace_job_is_requeued(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    storage = Mock()
    storage.user_id = '11111111-1111-4111-8111-111111111111'
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='test-key')
    queue = configured_queue()
    entry = queue.submit_workspace(
        storage.user_id,
        'project',
        'turn-1',
        {
            'existing_family_context': None,
            'current_place_journey': None,
            'parsed_place_journey': None,
            'parsed_family_context': None,
            'family_skills': [],
            'profile': {},
            'profile_updates': None,
            'task_requests': [],
            'memories': [],
            'text': 'A memory',
            'language': 'en-AU',
            'turn_sequence': 1,
            'deferred_home': None,
            'memory': {'id': 'memory-1'},
            'legacy_markers': True,
        },
    )
    job = queue.claim_workspace(storage.user_id, job_id=entry['id'])
    started = asyncio.Event()

    async def blocked(**kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime, '_persist_workspace', blocked)

    async def run():
        task = asyncio.create_task(runtime._run_workspace_job(storage, job))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert queue.pending_workspace(storage.user_id)[0]['status'] == 'QUEUED'


def test_collector_role_applies_before_the_first_saved_memory():
    from apps.api.agent_tasks import collection_task_instructions
    assert 'memory-collection agent' in collection_task_instructions([])
