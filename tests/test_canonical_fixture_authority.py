"""Small real-SQL/worker smoke before the expensive Apple 250-turn fixture.

One disposable database, no Temporal and only the checked-in synthetic provider.
Apple execution requires the separately approved native resource/network window.
"""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from scripts.run_isolated_check import offline_environment
from scripts.canonical_native_fixture import verify_publication_instance
from test_agent_commit_postgres import database
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, rpc


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def authority_database():
    environment = offline_environment(ROOT)
    if (environment.get('MEMOIR_TEST_POSTGRES_BACKEND') == 'apple-container'
            and environment.get('MEMOIR_TEST_PUBLICATION_TCP') != '1'):
        pytest.skip('Requires explicit approval and MEMOIR_TEST_PUBLICATION_TCP=1 for the disposable guest SQL endpoint')
    environment.pop('MEMOIR_LEGACY_ONLY_DEPLOYMENT', None)
    endpoint = {}
    name = 'memoir-issue6-pg-' + uuid4().hex[:12]
    with pytest.MonkeyPatch.context() as patch:
        for key in list(os.environ): patch.delenv(key)
        for key, value in environment.items(): patch.setenv(key, value)
        patch.setenv('MEMOIR_TEST_POSTGRES_CONTAINER_NAME', name)
        generator = database.__wrapped__(deadline=time.monotonic() + 180,
            publication_tcp=True, publication_endpoint=endpoint)
        try:
            sql = next(generator)
            asyncio.run(verify_publication_instance(sql, time.monotonic() + 3))
            yield event_database.__wrapped__(private_database.__wrapped__(attachment_database.__wrapped__(sql)))
        finally:
            generator.close()
            if environment.get('MEMOIR_TEST_POSTGRES_BACKEND') == 'apple-container':
                stopped = subprocess.run(['container', 'inspect', name], capture_output=True, text=True, timeout=15)
                assert stopped.returncode != 0 and f'container not found: {name}' in stopped.stderr.lower()
                if endpoint:
                    with socket.socket() as probe:
                        probe.settimeout(1)
                        assert probe.connect_ex((endpoint['host'], endpoint['port'])) != 0


def new_owner(sql):
    owner = str(uuid4())
    sql(f"insert into auth.users(id,is_anonymous) values('{owner}',false);")
    return owner


def controlled_worker(tmp_path, monkeypatch, dsn):
    from apps.api.codex_worker_service import CodexWorker
    monkeypatch.delenv('MEMOIR_LEGACY_ONLY_DEPLOYMENT', raising=False)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', dsn)
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'synthetic-only')
    control = tmp_path / 'provider.json'
    control.write_text(json.dumps({'reply': 'Tell me more.'}))
    return CodexWorker(home_root=tmp_path / 'homes', base_url='http://127.0.0.1:1/v1',
        model='synthetic-protocol', timeout=5,
        command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])


def test_unmapped_native_worker_completes_one_turn_with_real_publication_authority(authority_database, tmp_path, monkeypatch):
    from apps.api.codex_worker_service import WorkerTurnInput
    owner = new_owner(authority_database)
    worker = controlled_worker(tmp_path, monkeypatch, authority_database.publication_dsn)
    result = asyncio.run(worker.turn(WorkerTurnInput(user_id=owner, text='An original synthetic memory.', language='en-AU')))
    assert result['reply'] == 'Tell me more.' and result['thread_id'] == 'synthetic-thread'


def test_mapped_native_worker_fails_before_creating_provider_home(authority_database, tmp_path, monkeypatch):
    from apps.api.codex_worker_service import WorkerTurnInput
    from apps.api.lifetime_memory_legacy import LegacyMappingConflict
    owner = new_owner(authority_database)
    assert rpc(authority_database, 'resolve_lifetime_conversation', 'null', owner=owner)['outcome'] == 'resolved'
    worker = controlled_worker(tmp_path, monkeypatch, authority_database.publication_dsn)
    with pytest.raises(LegacyMappingConflict):
        asyncio.run(worker.turn(WorkerTurnInput(user_id=owner, text='Do not dispatch.')))
    assert list((tmp_path / 'homes').iterdir()) == []


def test_native_worker_never_uses_missing_authority_as_legacy_only(authority_database, tmp_path, monkeypatch):
    from apps.api.codex_worker_service import WorkerTurnInput
    from apps.api.lifetime_memory_legacy import LegacyAuthorityUnavailable
    worker = controlled_worker(tmp_path, monkeypatch, '')
    with pytest.raises(LegacyAuthorityUnavailable):
        asyncio.run(worker.turn(WorkerTurnInput(user_id=new_owner(authority_database), text='Do not dispatch.')))
    assert list((tmp_path / 'homes').iterdir()) == []


@pytest.mark.parametrize('cancel', [False, True])
def test_native_pipe_drain_holds_adoption_lock_and_releases_on_completion_or_cancellation(
        authority_database, tmp_path, monkeypatch, cancel):
    import psycopg
    from apps.api.codex_agent import CodexConnection
    from apps.api.lifetime_memory_legacy import LegacyPublication, LegacyMappingConflict
    owner = new_owner(authority_database)
    worker = controlled_worker(tmp_path, monkeypatch, authority_database.publication_dsn)
    publisher = LegacyPublication(authority_database.publication_dsn, authenticated_owner=owner, send_timeout=5)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async with await psycopg.AsyncConnection.connect(authority_database.publication_dsn, autocommit=True) as adopter, \
                await psycopg.AsyncConnection.connect(authority_database.publication_dsn, autocommit=True) as observer:
            await adopter.execute('set role authenticated')
            await adopter.execute("select set_config('request.jwt.claim.sub',%s,false)", (owner,))
            async with CodexConnection(worker.command, tmp_path / 'pipe-home', request_admission=publisher.guard) as connection:
                writer = connection.process.stdin
                original_drain, original_write = writer.drain, writer.write
                writes = []
                def write(data):
                    writes.append(data)
                    original_write(data)
                async def drain():
                    await original_drain()
                    entered.set()
                    await release.wait()
                monkeypatch.setattr(writer, 'write', write)
                monkeypatch.setattr(writer, 'drain', drain)
                sending = asyncio.create_task(connection.send({'id': 99, 'method': 'thread/start', 'params': {}}))
                adopting = None
                try:
                    async with asyncio.timeout(3): await entered.wait()
                    adopting = asyncio.create_task(adopter.execute('select public.resolve_lifetime_conversation(null)'))
                    async with asyncio.timeout(2):
                        while True:
                            row = await (await observer.execute('select cardinality(pg_blocking_pids(%s))',
                                (adopter.info.backend_pid,))).fetchone()
                            if row[0]: break
                            assert not adopting.done(), 'Adoption passed while the provider pipe was draining'
                            await asyncio.sleep(.01)
                    if cancel:
                        sending.cancel()
                        with pytest.raises(asyncio.CancelledError): await sending
                    else:
                        release.set()
                        await sending
                    async with asyncio.timeout(2): await adopting
                    with pytest.raises(LegacyMappingConflict):
                        await connection.send({'id': 100, 'method': 'thread/start', 'params': {}})
                    assert len(writes) == 1, 'Post-adoption provider bytes must never reach the pipe'
                finally:
                    release.set()
                    sending.cancel()
                    if adopting is not None: adopting.cancel()
                    await asyncio.gather(sending, *([adopting] if adopting is not None else []), return_exceptions=True)
            assert connection.process.returncode is not None
    asyncio.run(scenario())
