from uuid import UUID
import asyncio
import os

import pytest

from fastapi.testclient import TestClient

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput, app
from apps.api.codex_artifacts import iter_artifacts


@pytest.fixture
def own_uid(monkeypatch):
    # macOS UID and primary GID differ. These portable tests exercise safe
    # file handling; Linux integration tests exercise actual tenant UID drops.
    fchown, chown = os.fchown, os.chown
    monkeypatch.setattr(os, 'fchown', lambda fd, uid, gid: fchown(fd, uid, os.getgid()))
    monkeypatch.setattr(os, 'chown', lambda path, uid, gid: chown(path, uid, os.getgid()))
    return os.getuid()


def test_worker_allocates_stable_distinct_os_identities(tmp_path):
    worker = CodexWorker(home_root=tmp_path)
    first = worker._uid_for(str(UUID("11111111-1111-4111-8111-111111111111")))
    second = worker._uid_for(str(UUID("22222222-2222-4222-8222-222222222222")))

    assert first == worker._uid_for("11111111-1111-4111-8111-111111111111")
    assert first != second
    assert 20000 <= first < 60000
    assert 20000 <= second < 60000


def test_memory_context_pass_is_ephemeral_and_never_streams_or_exports_artifacts(tmp_path, monkeypatch):
    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, params):
            assert method == 'thread/start'
            assert params['ephemeral'] is True
            assert 'memoir-memory-context' in params['baseInstructions']
            assert 'Reply to the storyteller in English' not in params['baseInstructions']
            return {'thread': {'id': 'intake'}}

        async def turn(self, thread_id, prompt, **kwargs):
            assert 'on_delta' not in kwargs
            assert kwargs['output_schema']['required'] == ['preferred_language']
            assert '我叫慧博' in prompt
            return '{"preferred_language":"zh-CN"}'

    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *args: tmp_path)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)

    def no_artifacts(*args):
        pytest.fail('Intake must not enumerate conversation artifacts')

    monkeypatch.setattr('apps.api.codex_worker_service.iter_artifacts', no_artifacts)
    result = asyncio.run(worker.turn(WorkerTurnInput(
        user_id='11111111-1111-4111-8111-111111111111',
        text='我叫慧博', agent_role='memory_context', thread_id='existing-conversation',
    ), on_delta=lambda text: pytest.fail('Intake must not stream')))
    assert result['reply'] == '{"preferred_language":"zh-CN"}'
    assert result['artifacts'] == []


@pytest.mark.parametrize('role', ['collector', 'workspace'])
def test_worker_sends_instructions_once_instead_of_repeating_them_in_user_input(tmp_path, monkeypatch, role):
    class Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def __init__(self, *args, **kwargs):
            pass

        async def request(self, method, params):
            self.instructions = params['baseInstructions']
            return {'thread': {'id': 'test'}}

        async def turn(self, thread_id, prompt, **kwargs):
            assert self.instructions not in prompt, 'system instructions were sent twice'
            assert prompt == 'Storyteller message:\nI grew up in Sydney.'
            return 'Hello'

    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *args: tmp_path)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    asyncio.run(worker.turn(WorkerTurnInput(
        user_id='11111111-1111-4111-8111-111111111111',
        text='I grew up in Sydney.', agent_role=role,
    )))


def test_worker_home_permissions_separate_sibling_homes(monkeypatch, tmp_path):
    monkeypatch.setattr(os, 'fchown', lambda fd, uid, gid: None)
    tmp_path.chmod(0o711)
    worker = CodexWorker(home_root=tmp_path)

    home = worker._home("11111111-1111-4111-8111-111111111111", 20000)

    assert tmp_path.stat().st_mode & 0o777 == 0o711
    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / "config.toml").stat().st_mode & 0o777 == 0o600


def test_worker_endpoint_requires_private_secret(monkeypatch):
    monkeypatch.setenv("MEMORY_SPARK_CODEX_WORKER_SECRET", "test-secret")
    client = TestClient(app)

    response = client.post(
        "/internal/codex/turn",
        json={
            "user_id": "11111111-1111-4111-8111-111111111111",
            "text": "hello",
        },
    )

    assert response.status_code == 401


@pytest.mark.parametrize('link', ['symlink', 'hardlink'])
def test_config_replacement_never_modifies_link_target(tmp_path, link, own_uid):
    root = tmp_path / 'worker'
    worker = CodexWorker(home_root=root)
    user = '11111111-1111-4111-8111-111111111111'
    home = root / user
    home.mkdir()
    victim = tmp_path / 'victim'
    victim.write_text('private memory')
    original = victim.stat()
    if link == 'symlink':
        (home / 'config.toml').symlink_to(victim)
    else:
        os.link(victim, home / 'config.toml')
    worker._home(user, own_uid)
    assert victim.read_text() == 'private memory'
    assert victim.stat().st_mode == original.st_mode
    assert victim.stat().st_uid == original.st_uid
    assert not (home / 'config.toml').is_symlink()
    assert (home / 'config.toml').stat().st_ino != victim.stat().st_ino


def test_worker_rejects_symlink_home(tmp_path):
    worker = CodexWorker(home_root=tmp_path / 'worker')
    victim = tmp_path / 'victim'
    victim.mkdir()
    (worker.home_root / 'user').symlink_to(victim, target_is_directory=True)
    with pytest.raises(OSError):
        worker._home('user', os.getuid())
    assert not (victim / 'config.toml').exists()


def test_legacy_home_import_keeps_session_and_sqlite_state(tmp_path, own_uid):
    user = '11111111-1111-4111-8111-111111111111'
    legacy = tmp_path / 'legacy'
    original = legacy / user
    (original / 'sessions').mkdir(parents=True)
    (original / 'sessions' / 'thread-old.jsonl').write_text('saved rollout')
    (original / 'state.sqlite').write_bytes(b'database')
    (original / 'state.sqlite-wal').write_bytes(b'wal')
    worker = CodexWorker(home_root=tmp_path / 'worker', legacy_root=legacy)
    home = worker._home(user, own_uid)
    assert (home / 'sessions' / 'thread-old.jsonl').read_text() == 'saved rollout'
    assert (home / 'state.sqlite-wal').read_bytes() == b'wal'
    assert (original / 'state.sqlite').read_bytes() == b'database'
    (home / 'state.sqlite').write_bytes(b'new state')
    worker._home(user, own_uid)
    assert (home / 'state.sqlite').read_bytes() == b'new state'


def test_legacy_symlink_aborts_import_without_partial_home(tmp_path):
    legacy = tmp_path / 'legacy'
    (legacy / 'user').mkdir(parents=True)
    victim = tmp_path / 'victim'
    victim.write_text('private')
    (legacy / 'user' / 'linked').symlink_to(victim)
    worker = CodexWorker(home_root=tmp_path / 'worker', legacy_root=legacy)
    with pytest.raises(RuntimeError, match='symlink'):
        worker._home('user', os.getuid())
    assert not (worker.home_root / 'user').exists()
    assert victim.read_text() == 'private'


def test_artifacts_reject_links_and_hidden_files(tmp_path):
    (tmp_path / 'sessions').mkdir()
    (tmp_path / 'sessions' / 'valid').write_text('safe')
    (tmp_path / 'private').write_text('secret')
    (tmp_path / 'sessions' / 'linked').symlink_to(tmp_path / 'private')
    (tmp_path / 'sessions' / 'linked-dir').symlink_to(tmp_path, target_is_directory=True)
    os.link(tmp_path / 'private', tmp_path / 'sessions' / 'hardlinked')
    (tmp_path / 'sessions' / '.hidden').write_text('hidden')
    assert list(iter_artifacts(tmp_path)) == [('sessions/valid', b'safe')]


def test_worker_turn_timeout_cancels_execution(tmp_path, monkeypatch):
    worker = CodexWorker(home_root=tmp_path, timeout=0.01)
    cancelled = []
    async def blocked(payload):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    monkeypatch.setattr(worker, '_turn', blocked)
    payload = WorkerTurnInput(user_id=UUID(int=1), text='hello')
    with pytest.raises(TimeoutError):
        asyncio.run(worker.turn(payload))
    assert cancelled == [True]


def test_worker_instances_cannot_write_the_same_home(tmp_path, monkeypatch):
    from apps.api.agent_lock import AgentTurnBusyError
    first = CodexWorker(home_root=tmp_path)
    second = CodexWorker(home_root=tmp_path)
    payload = WorkerTurnInput(user_id=UUID(int=1), text='hello')
    async def run():
        entered = asyncio.Event()
        async def blocked(payload):
            entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(first, '_turn', blocked)
        task = asyncio.create_task(first.turn(payload))
        await entered.wait()
        try:
            with pytest.raises(AgentTurnBusyError):
                await second.turn(payload)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_disconnected_api_cancels_and_settles_worker(monkeypatch):
    from apps.api import codex_worker_service as service
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'test-secret')
    stopped = []
    async def run():
        started = asyncio.Event()
        async def blocked(payload):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(True)
        class Request:
            headers = {}
            async def is_disconnected(self):
                await started.wait()
                return True
        monkeypatch.setattr(service.worker, 'turn', blocked)
        with pytest.raises(asyncio.CancelledError):
            await service.turn(WorkerTurnInput(user_id=UUID(int=1), text='hello'),
                               Request(), 'test-secret')
    asyncio.run(run())
    assert stopped == [True]
