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


def test_worker_can_opt_out_of_linux_privdrop_only_when_explicitly_requested(tmp_path, monkeypatch):
    worker = CodexWorker(home_root=tmp_path, command=["codex", "app-server"])
    assert worker._run_command(20001)[0] == "/usr/bin/setpriv"
    monkeypatch.setenv("MEMORY_SPARK_DISABLE_PRIVDROP", "1")
    assert worker._run_command(20001) == ["codex", "app-server"]


def test_worker_reads_bounded_timeout_from_environment_for_isolated_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMORY_SPARK_CODEX_WORKER_TIMEOUT", "180")
    worker = CodexWorker(home_root=tmp_path)
    assert worker.timeout == 180
    monkeypatch.setenv("MEMORY_SPARK_CODEX_WORKER_TIMEOUT", "999")
    assert CodexWorker(home_root=tmp_path / "capped").timeout == 240


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


def test_workspace_focus_pass_uses_the_requested_domain_contract(tmp_path, monkeypatch):
    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, params):
            assert method == 'thread/start'
            assert 'Focused author-timeline recovery pass' in params['baseInstructions']
            return {'thread': {'id': 'focused'}}

        async def turn(self, thread_id, prompt, **kwargs):
            assert prompt == 'Storyteller message:\nI was born in Hobart.'
            return '[[MEMORY_SPARK_AUTHOR_TIMELINE]]{"timeline":[]}[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'

    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *args: tmp_path)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    result = asyncio.run(worker.turn(WorkerTurnInput(
        user_id='11111111-1111-4111-8111-111111111111',
        text='I was born in Hobart.', agent_role='workspace',
        extraction_focus='author_timeline', family_enabled=True,
    )))
    assert result['reply'].startswith('[[MEMORY_SPARK_AUTHOR_TIMELINE]]')


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
            assert 'on_delta' in kwargs, 'private workspace deltas must reach the API preview parser'
            await kwargs['on_delta']('Hello')
            return 'Hello'

    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *args: tmp_path)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    async def delta(text): pass
    asyncio.run(worker.turn(WorkerTurnInput(
        user_id='11111111-1111-4111-8111-111111111111',
        text='I grew up in Sydney.', agent_role=role,
    ), on_delta=delta))


def test_collector_thread_refresh_boundary_is_bounded_and_role_specific():
    from apps.api.codex_worker_service import WorkerTurnInput

    base = dict(
        user_id='11111111-1111-4111-8111-111111111111',
        thread_id='old-thread', text='A synthetic turn.',
        conversation_rounds_completed=40,
    )
    assert CodexWorker._refresh_collector_thread(WorkerTurnInput(**base)) is True
    assert CodexWorker._refresh_collector_thread(WorkerTurnInput(**{**base, 'conversation_rounds_completed': 39})) is False
    assert CodexWorker._refresh_collector_thread(WorkerTurnInput(**{**base, 'agent_role': 'workspace'})) is False


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


def test_workspace_can_finish_after_the_collector_execution_budget(tmp_path, monkeypatch):
    worker = CodexWorker(home_root=tmp_path, timeout=0.01)

    async def extraction(payload):
        await asyncio.sleep(0.02)
        return {'reply': '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'}

    monkeypatch.setattr(worker, '_turn', extraction)
    payload = WorkerTurnInput(user_id=UUID(int=1), text='memory', agent_role='workspace')
    assert asyncio.run(worker.turn(payload))['reply']
    with pytest.raises(TimeoutError):
        asyncio.run(worker.turn(payload.model_copy(update={'agent_role': 'collector'})))


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


@pytest.mark.parametrize('phase,timeout_name', [('index', 'COMPOSER_TIMEOUT'), ('draft', 'COMPOSER_DRAFT_TIMEOUT')])
def test_composer_has_its_own_budget_and_structured_output(tmp_path, monkeypatch, phase, timeout_name):
    from apps.api import memoir_preview
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'composer-test-low')
    seen = []
    class Connection:
        def __init__(self, *args, **kwargs):
            seen.append(kwargs['timeout'])
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def request(self, method, params):
            assert params['ephemeral'] is True
            assert params['model'] == 'composer-test-low'
            return {'thread': {'id': 'composer'}}
        async def turn(self, thread_id, prompt, **kwargs):
            assert ('periods' if phase == 'index' else 'schema_version') in kwargs['output_schema']['required']
            return '{"periods":[],"events":[]}'
    worker = CodexWorker(home_root=tmp_path, timeout=1)
    async def reachable(): pass
    monkeypatch.setattr(worker, '_ensure_composer_provider', reachable)
    monkeypatch.setattr(worker, '_home', lambda *args: tmp_path)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    asyncio.run(worker.turn(WorkerTurnInput(user_id='11111111-1111-4111-8111-111111111111',
                                          text='test', agent_role='composer', composer_phase=phase)))
    assert seen == [getattr(memoir_preview, timeout_name)]


def test_only_composer_accepts_larger_structured_packets():
    from pydantic import ValidationError
    options = {'user_id': '11111111-1111-4111-8111-111111111111', 'text': 'x' * 120001}
    with pytest.raises(ValidationError):
        WorkerTurnInput(**options)
    assert WorkerTurnInput(**options, agent_role='composer').agent_role == 'composer'


def test_composer_offline_provider_fails_before_model_start(tmp_path, monkeypatch):
    from apps.api.codex_worker_service import ComposerProviderUnavailable
    async def refused(*args):
        raise ConnectionRefusedError('private endpoint details must not escape')
    monkeypatch.setattr(asyncio, 'open_connection', refused)
    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_turn', lambda *args: pytest.fail('Offline provider must not start model work'))
    with pytest.raises(ComposerProviderUnavailable, match='^The model provider is unavailable$'):
        asyncio.run(worker.turn(WorkerTurnInput(user_id=UUID(int=1), text='synthetic', agent_role='composer')))


def test_composer_offline_endpoint_has_safe_terminal_code(monkeypatch):
    from apps.api import codex_worker_service as service
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'test-secret')
    async def offline(payload):
        raise service.ComposerProviderUnavailable('private diagnostic')
    monkeypatch.setattr(service.worker, 'turn', offline)
    response = TestClient(app).post('/internal/codex/turn', headers={'X-Codex-Worker-Secret':'test-secret'},
        json={'user_id':str(UUID(int=1)), 'text':'synthetic', 'agent_role':'composer'})
    assert response.status_code == 503
    assert response.headers['X-Error-Code'] == 'COMPOSER_PROVIDER_UNAVAILABLE'
    assert 'private' not in response.text
