"""Checkpoint bytes, restore authority and failure behavior; no live services."""
import asyncio
import hashlib
from io import BytesIO
import json
import os
import shutil
import stat
from zipfile import ZipFile, ZipInfo

import httpx
import pytest

from apps.api.codex_home_store import BUCKET, CodexHomeStore, HomeCheckpointUnavailable, _pack, _unpack
from apps.api.conversation_reply_session import InterviewSession, open_interview
from apps.api.conversation_reply import reply_packet, reply_schema
from test_interview_native_session import Native, options, packets


@pytest.fixture
def remote(monkeypatch):
    objects, requests = {}, []
    def handle(request):
        requests.append(request)
        path = request.url.path.replace('/object/authenticated/', '/object/')
        if request.method == 'POST':
            objects[path] = request.content
            return httpx.Response(200, json={'Key': path})
        return httpx.Response(200, content=objects[path]) if path in objects else httpx.Response(404)
    store = CodexHomeStore('https://storage.invalid', 'synthetic-server-key', transport=httpx.MockTransport(handle))
    monkeypatch.setattr(CodexHomeStore, 'configured', classmethod(lambda cls: store))
    return store, objects, requests


def session(root, packet, context):
    return InterviewSession(root, packet, reply_packet(packet), reply_schema(context),
        packet.model, 'low', 'http://provider.invalid/v1', [])


def saved_home(root):
    first, second, context, reply = packets()
    source = session(root, first, context)
    source.thread_id = 'native-thread'
    source.sources = {'source:1': [1, {'char_start': 0, 'char_end': 5}]}
    source.accept(reply)
    (source.home / 'sessions').mkdir()
    (source.home / 'sessions' / 'rollout.jsonl').write_bytes(b'private interview\n')
    (source.home / 'memories').mkdir()
    (source.home / 'memories' / 'memory_summary.md').write_bytes(b'private memory')
    (source.home / 'state_5.sqlite').write_bytes(b'sqlite database')
    (source.home / 'state_5.sqlite-wal').write_bytes(b'sqlite WAL')
    for name in ('auth.json', 'config.toml', 'logs_1.sqlite', '.identity.json'):
        (source.home / name).write_bytes(b'credential or unrelated private state')
    state = json.loads(source.path.read_bytes())
    return source, state, second, context


def committed_packet(packet, checkpoint):
    execution = {key: checkpoint[key] for key in ('thread_id', 'sequence', 'source_id', 'reply_sha256')}
    execution['home_checkpoint'] = checkpoint
    return packet.model_copy(update={'interview_context': {**packet.interview_context, 'execution': execution}})


def descriptor(store, source, state, wire):
    digest = hashlib.sha256(wire).hexdigest()
    return dict(path=store._path(source, state['sequence'], digest), scope=source.scope,
        archive_sha256=digest, byte_size=len(wire), **{key:state[key] for key in (
            'thread_id', 'sequence', 'source_id', 'source_version', 'reply_sha256')})


def test_checkpoint_round_trip_recovers_state_and_memories_without_credentials(tmp_path, remote):
    store, objects, requests = remote
    source, state, second, context = saved_home(tmp_path)
    async def run():
        checkpoint = await store.save(source, state)
        shutil.rmtree(tmp_path)
        restored = session(tmp_path, committed_packet(second, checkpoint), context)
        assert checkpoint['path'] not in json.dumps(reply_packet(restored.packet))
        assert await store.restore(restored, uid=os.getuid(), apply_owner=False)
        assert restored.compatible()
        assert restored.state == state
        assert (restored.home / 'sessions' / 'rollout.jsonl').read_bytes() == b'private interview\n'
        assert (restored.home / 'memories' / 'memory_summary.md').read_bytes() == b'private memory'
        assert (restored.home / 'state_5.sqlite-wal').read_bytes() == b'sqlite WAL'
        for name in ('auth.json', 'config.toml', 'logs_1.sqlite', '.identity.json'):
            assert not (restored.home / name).exists()
        assert stat.S_IMODE(restored.home.stat().st_mode) == 0o700
        assert stat.S_IMODE((restored.home / 'state_5.sqlite').stat().st_mode) == 0o600
    asyncio.run(run())
    assert len(objects) == 1
    assert str(source.packet.identity.owner_id) in next(iter(objects))
    assert '/sandbox/' in next(iter(objects))
    assert requests[0].headers['x-upsert'] == 'false'
    assert all(request.headers['authorization'] == 'Bearer synthetic-server-key' for request in requests)


@pytest.mark.parametrize('change', ['scope', 'owner', 'uncommitted'])
def test_checkpoint_cannot_authorize_wrong_identity_or_uncommitted_history(tmp_path, change):
    source, state, second, context = saved_home(tmp_path)
    wire = _pack(source, state)
    shutil.rmtree(tmp_path)
    if change == 'uncommitted':
        second = second.model_copy(update={'tail': []})
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=wire)
    store = CodexHomeStore('https://storage.invalid', 'synthetic', transport=httpx.MockTransport(handle))
    if change != 'uncommitted':
        second = committed_packet(second, descriptor(store, source, state, wire))
    target = session(tmp_path, second, context)
    if change == 'scope':
        target.scope = 'f' * 64
    elif change == 'owner':
        target.packet = target.packet.model_copy(update={'identity': target.packet.identity.model_copy(
            update={'owner_id': '22222222-2222-4222-8222-222222222222'})})
    assert not asyncio.run(store.restore(target, uid=os.getuid(), apply_owner=False))
    assert requests == []
    assert not list(target.home.iterdir())


@pytest.mark.parametrize('path', ['home/../../escape', 'home/sessions/../escape', 'home/auth.json',
    'home/sessions/./escape', 'home/sessions/link', '/escape'])
def test_archive_rejects_unsafe_paths_and_symlinks_before_writing(tmp_path, path):
    source, state, _, _ = saved_home(tmp_path)
    buffer = BytesIO(_pack(source, state))
    with ZipFile(buffer, 'a') as archive:
        entry = ZipInfo(path)
        if path.endswith('/link'):
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(entry, b'outside')
    with pytest.raises(ValueError):
        _unpack(buffer.getvalue(), source)
    assert not (tmp_path / 'escape').exists()


def test_snapshot_rejects_linked_files_and_size_overflow(tmp_path, monkeypatch):
    source, state, _, _ = saved_home(tmp_path)
    (source.home / 'sessions' / 'link').symlink_to(source.home / 'auth.json')
    with pytest.raises(ValueError, match='regular file'):
        _pack(source, state)
    (source.home / 'sessions' / 'link').unlink()
    monkeypatch.setattr('apps.api.codex_home_store.MAX_BYTES', 1)
    with pytest.raises(ValueError, match='limit exceeded'):
        _pack(source, state)


def test_existing_home_is_never_overwritten_by_remote_checkpoint(tmp_path, remote):
    store, _, requests = remote
    source, _, _, _ = saved_home(tmp_path)
    assert not asyncio.run(store.restore(source, uid=os.getuid(), apply_owner=False))
    assert requests == []


@pytest.mark.parametrize('code', ['NoSuchKey', 'NoSuchBucket', 'AccessDenied'])
def test_supabase_missing_key_is_a_cold_start_but_other_errors_are_visible(tmp_path, code):
    source, state, second, context = saved_home(tmp_path)
    wire = _pack(source, state)
    store = CodexHomeStore('https://storage.invalid', 'synthetic', transport=httpx.MockTransport(
        lambda request: httpx.Response(400, json={'statusCode':'404', 'code':code})))
    checkpoint = descriptor(store, source, state, wire)
    shutil.rmtree(tmp_path)
    current = session(tmp_path, committed_packet(second, checkpoint), context)
    if code == 'NoSuchKey':
        assert not asyncio.run(store.restore(current, uid=os.getuid(), apply_owner=False))
    else:
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(store.restore(current, uid=os.getuid(), apply_owner=False))


def test_interview_upload_runs_after_process_exit_and_failure_keeps_local_state(tmp_path, remote, monkeypatch, caplog):
    store, _, requests = remote
    first, _, context, reply = packets()
    closed = []
    class Process(Native):
        async def __aexit__(self, *args):
            closed.append(True)
    async def failed_save(session, state):
        assert closed == [True]
        raise ValueError('synthetic private details')
    monkeypatch.setattr(store, 'save', failed_save)
    async def run():
        settings = options(tmp_path, first, context)
        settings['connection_factory'] = Process
        with pytest.raises(HomeCheckpointUnavailable, match='not verified'):
            async with open_interview(**settings) as (current, _):
                current.accept(reply)
        assert current.checkpoint_status == 'save_failed'
        assert current.path.exists()
        assert json.loads(current.path.read_text())['reply_sha256']
    asyncio.run(run())
    assert requests == []  # An uncommitted object is never discovered by listing.
    assert 'synthetic private details' not in caplog.text


def test_queued_archive_retries_without_holding_the_next_local_interview(tmp_path, remote, monkeypatch):
    from apps.api import codex_home_store
    from apps.api.codex_worker_service import CodexWorker

    store, _, requests = remote
    first, second, context, reply = packets()
    worker = CodexWorker(home_root=tmp_path)
    staged, attempts = [], []
    upload = store.upload

    async def run():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def upload_when_released(content, receipt):
            attempts.append(content)
            if len(attempts) == 1:
                entered.set()
                await release.wait()
                raise httpx.ReadTimeout('synthetic transport timeout')
            return await upload(content, receipt)

        async def stage(publisher, fence, receipt, *, allow_committed):
            assert allow_committed and fence == first.fence
            staged.append(receipt)

        monkeypatch.setattr(store, 'upload', upload_when_released)
        monkeypatch.setattr(codex_home_store, 'stage_checkpoint', stage)

        def queue(store, archive):
            return worker._enqueue_checkpoint(
                lambda: codex_home_store.save_deferred_checkpoint(store, archive, None, first.fence))

        async with open_interview(**options(tmp_path, first, context), queue_checkpoint=queue) as (current, _):
            current.accept(reply)
        assert current.checkpoint_status == 'queued'
        await asyncio.wait_for(entered.wait(), timeout=2)
        try:
            async with open_interview(**options(tmp_path, second, context)) as (next_session, _):
                assert next_session.resumed
            assert staged == [] and requests == []
        finally:
            release.set()
            await worker.settle_checkpoints()
        assert len(attempts) == 2 and attempts[0] == attempts[1]
        assert [request.method for request in requests] == ['POST', 'GET']
        assert len(staged) == 1 and staged[0]['archive_sha256'] == hashlib.sha256(attempts[0]).hexdigest()

    asyncio.run(run())


def test_upload_is_not_reported_saved_without_exact_readback(tmp_path):
    source, state, _, _ = saved_home(tmp_path)
    store = CodexHomeStore('https://storage.invalid', 'synthetic', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b'wrong bytes')))
    with pytest.raises(ValueError, match='readback mismatch'):
        asyncio.run(store.save(source, state))


def test_new_upload_does_not_replace_the_previous_committed_archive(tmp_path, remote):
    store, objects, requests = remote
    source, state, second, context = saved_home(tmp_path)
    async def run():
        committed = await store.save(source, state)
        (source.home / 'memories' / 'memory_summary.md').write_bytes(b'uncommitted later work')
        pending = await store.save(source, state)
        assert committed['path'] != pending['path']
        assert len(objects) == 2
        shutil.rmtree(tmp_path)
        restored = session(tmp_path, committed_packet(second, committed), context)
        assert await store.restore(restored, uid=os.getuid(), apply_owner=False)
        assert (restored.home / 'memories' / 'memory_summary.md').read_bytes() == b'private memory'
        assert requests[-1].url.path.endswith(committed['path'])
    asyncio.run(run())


def test_restore_rejects_bytes_that_differ_from_the_committed_digest(tmp_path):
    source, state, second, context = saved_home(tmp_path)
    wire = _pack(source, state)
    store = CodexHomeStore('https://storage.invalid', 'synthetic', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=wire + b'changed')))
    checkpoint = descriptor(store, source, state, wire)
    shutil.rmtree(tmp_path)
    restored = session(tmp_path, committed_packet(second, checkpoint), context)
    with pytest.raises(ValueError, match='integrity mismatch'):
        asyncio.run(store.restore(restored, uid=os.getuid(), apply_owner=False))
    assert list(restored.home.iterdir()) == []
