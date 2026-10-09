"""Provider-free artifact route tests; real PG tests require explicit opt-in."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import threading
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

import memoir_postgres_workflow as fixture
from apps.api.codex_runtime import CodexRuntime


OWNER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
TOKEN = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
RELATIVE = f'sessions/turns/{TOKEN}/synthetic.jsonl'
NAME = f'{OWNER}/agent/{RELATIVE}'
JSONL = '{"synthetic":"first\u2028record"}\n{"synthetic":"second"}\n'.encode()


def result(value, *, returncode=0, stderr=''):
    return SimpleNamespace(returncode=returncode, stdout=json.dumps(value) + '\n', stderr=stderr)


class SqlStub:
    """Records statements only; never claims to prove PostgreSQL or RLS."""
    _memoir_artifact_storage_initialized = True

    def __init__(self, value=None):
        self.calls, self.value = [], value

    def __call__(self, query, **kwargs):
        self.calls.append(query)
        return result(self.value)


def upload(rest, *, name=NAME, content=JSONL, headers=None):
    return rest.handle(httpx.Request('POST', 'http://synthetic.invalid/storage/v1/object/memory-spark/' + name,
        content=content, headers=headers or {'content-type': 'application/octet-stream', 'x-upsert': 'false'}))


def test_runtime_path_transmits_raw_jsonl_and_upload_sql_is_atomic_owner_scoped():
    sql = SqlStub({'status': 'stored', 'bytes': len(JSONL)})
    storage = fixture.PostgresRest(sql, OWNER).storage()
    try:
        lease = SimpleNamespace(lease_token=TOKEN, assert_held=lambda: None)
        paths = CodexRuntime._save_worker_artifacts(storage,
            [{'path': 'sessions/synthetic.jsonl', 'content': base64.b64encode(JSONL).decode()}], lease)
        assert paths == [RELATIVE]
        assert len(sql.calls) == 1
        query = sql.calls[0]
        assert 'begin isolation level read committed;' in query.lower() and 'commit;' in query.lower()
        assert 'set local role authenticated;' in query
        assert "set local request.jwt.claim.sub='" + OWNER + "'" in query
        assert query.index('pg_advisory_xact_lock') < query.index('insert into storage.objects')
        assert query.index('pg_advisory_xact_lock') < query.index('sum(')
        assert "decode('" + JSONL.hex() + "','hex')" in query
        assert 'on conflict' in query.lower()
        assert str(fixture.ARTIFACT_MAX_OBJECTS_PER_OWNER) in query
        assert str(fixture.ARTIFACT_MAX_BYTES_PER_OWNER) in query
    finally:
        storage.client.close()


@pytest.mark.parametrize('content', [b'', b'\x00\xff\xfe', b'# Synthetic\n', JSONL])
def test_fresh_facade_get_decodes_exact_persisted_bytes(content):
    sql = SqlStub({'content_hex': content.hex(), 'bytes': len(content)})
    storage = fixture.PostgresRest(sql, OWNER).storage()
    try:
        assert storage.get_agent_file(RELATIVE) == content
        assert len(sql.calls) == 1
        assert 'set role authenticated;' in sql.calls[0]
        assert "name='" + NAME + "'" in sql.calls[0]
        assert 'fixture_content' in sql.calls[0]
    finally:
        storage.client.close()


@pytest.mark.parametrize('name', [
    NAME.replace(OWNER, OTHER), NAME.replace('/agent/', '/attachment/'),
    NAME.replace('/sessions/', '/photos/'), NAME.replace('/turns/', '/other/'),
    NAME.replace(TOKEN, 'not-a-uuid'), NAME.replace('/synthetic.jsonl', '/.hidden'),
    NAME.replace('/synthetic.jsonl', '/a%2f..%2fb'),
    NAME.replace('/synthetic.jsonl', '/a%5cb'), NAME + '?unexpected=true',
])
def test_invalid_owner_or_path_has_no_sql_or_storage_side_effect(name):
    sql = SqlStub()
    response = upload(fixture.PostgresRest(sql, OWNER), name=name)
    assert response.status_code in {400, 403, 405}
    assert sql.calls == []


@pytest.mark.parametrize('headers', [
    {'content-type': 'application/json', 'x-upsert': 'false'},
    {'content-type': 'application/octet-stream', 'x-upsert': 'true'},
    {'content-type': 'application/octet-stream'},
    {'content-type': 'application/octet-stream', 'x-upsert': 'false', 'content-encoding': 'gzip'},
])
def test_only_explicit_raw_immutable_uploads_are_admitted(headers):
    sql = SqlStub()
    assert upload(fixture.PostgresRest(sql, OWNER), headers=headers).status_code == 400
    assert sql.calls == []


@pytest.mark.parametrize('path,method', [
    ('/storage/v1/object/sign/memory-spark/' + NAME, 'POST'),
    ('/storage/v1/object/list/memory-spark', 'POST'),
    ('/storage/v1/object/memoir-interview-photos/' + NAME, 'POST'),
    ('/storage/v1/object/memory-spark/' + NAME, 'DELETE'),
    ('/storage/v1/object/memory-spark/' + NAME, 'PUT'),
])
def test_other_storage_routes_and_service_identity_fail_closed(path, method):
    sql = SqlStub()
    rest = fixture.PostgresRest(sql, OWNER)
    assert rest.handle(httpx.Request(method, 'http://synthetic.invalid' + path,
        content=b'not JSON')).status_code in {400, 403, 405}
    assert upload(fixture.PostgresRest(sql, OWNER, service=True)).status_code == 403
    assert sql.calls == []


def test_uninitialized_storage_and_oversize_payload_fail_before_sql(monkeypatch):
    sql = SqlStub()
    sql._memoir_artifact_storage_initialized = False
    assert upload(fixture.PostgresRest(sql, OWNER)).status_code == 503
    sql._memoir_artifact_storage_initialized = True
    monkeypatch.setattr(fixture, 'ARTIFACT_MAX_BYTES', 2)
    assert upload(fixture.PostgresRest(sql, OWNER), content=b'123').status_code == 413
    assert sql.calls == []


@pytest.mark.parametrize('value,status', [
    ({'status': 'conflict'}, 409), ({'status': 'quota_exceeded'}, 413),
    ({'status': 'stored', 'bytes': -1}, 500), (None, 500),
])
def test_upload_requires_confirmed_persistence_and_never_retries(value, status):
    sql = SqlStub(value)
    assert upload(fixture.PostgresRest(sql, OWNER)).status_code == status
    assert len(sql.calls) == 1


def test_sql_failure_is_content_free_and_not_success():
    sql = SqlStub()
    def fail(query, **kwargs):
        sql.calls.append(query)
        return result(None, returncode=1, stderr='ERROR: 42501: PRIVATE_SQL_AND_BYTES')
    fail._memoir_artifact_storage_initialized = True
    response = upload(fixture.PostgresRest(fail, OWNER))
    assert response.status_code == 403
    assert 'PRIVATE' not in response.text
    assert len(sql.calls) == 1


def test_initializer_has_no_production_policy_or_lease_access_changes():
    sql = SqlStub()
    sql._memoir_artifact_storage_initialized = False
    limits = fixture.initialize_artifact_storage(sql)
    ddl = sql.calls[0].lower()
    assert 'fixture_content bytea' in ddl
    assert 'unique' in ddl and 'bucket_id' in ddl and 'name' in ddl
    assert 'enable row level security' in ddl
    assert 'grant select,insert' in ddl
    assert 'create policy' not in ddl and 'security definer' not in ddl
    assert 'user_agent_turn_lease' not in ddl
    assert sql._memoir_artifact_storage_initialized is True
    assert limits == {'max_artifact_bytes': 25 * 1024 * 1024,
        'max_objects_per_owner': 512, 'max_bytes_per_owner': 512 * 1024 * 1024}


class ReadinessSql(SqlStub):
    """Offline orchestration stub; actual persistence is tested only below."""
    def __init__(self, *, fail_read=False, hold_read=False, existing=False):
        super().__init__()
        self.objects, self.owner = {}, None
        self.fail_read, self.hold_read, self.existing = fail_read, hold_read, existing
        self.read_started, self.read_release = threading.Event(), threading.Event()
        self.read_settled = False

    def __call__(self, query, **kwargs):
        self.calls.append(query)
        if query.startswith('insert into auth.users'):
            if self.existing:
                raise RuntimeError('Synthetic owner already exists')
            self.owner = re.search(r"values\('([^']+)'", query)[1]
            return result(None)
        if 'delete from auth.users' in query:
            if self.hold_read:
                assert self.read_settled
            self.objects.clear()
            self.owner = None
            return result(None)
        if "jsonb_build_object('owners'" in query:
            return result({'owners': int(self.owner is not None), 'objects': len(self.objects)})
        if '_user_agent_turn_lease(' in query:
            return result(True)
        if 'insert into storage.objects' in query:
            match = re.search(r"select 'memory-spark','([^']+)',decode\('([0-9a-f]*)','hex'\)", query)
            name, encoded = match.groups()
            self.objects[name] = bytes.fromhex(encoded)
            return result({'status': 'stored', 'bytes': len(self.objects[name])})
        if "'content_hex'" in query:
            if self.hold_read:
                self.read_started.set()
                assert self.read_release.wait(5)
                self.read_settled = True
            if self.fail_read:
                return result({'content_hex': '00', 'bytes': 1})
            name = re.search(r"and name='([^']+)'", query)[1]
            value = self.objects[name]
            return result({'content_hex': value.hex(), 'bytes': len(value)})
        raise AssertionError('Unexpected synthetic SQL')


def test_provider_free_readiness_uses_actual_runtime_storage_lease_and_fresh_reader(monkeypatch):
    sql = ReadinessSql()
    opened = []
    original = fixture.PostgresRest.storage
    def storage(self):
        value = original(self)
        opened.append(value)
        return value
    monkeypatch.setattr(fixture.PostgresRest, 'storage', storage)
    receipt = asyncio.run(fixture.verify_artifact_storage(sql, probe_owner=str(uuid4())))
    assert receipt['status'] == 'verified' and receipt['byte_readback_verified'] is True
    assert receipt['probe_cleaned'] is True and receipt['model_calls'] == 0
    assert receipt['real_storage_writes'] is False and receipt['artifacts'] == 2
    assert len(receipt['sha256']) == 2 and all(len(digest) == 64 for digest in receipt['sha256'])
    assert len(opened) == 2 and opened[0] is not opened[1]
    assert all(item.client.is_closed for item in opened)
    assert sql.owner is None and sql.objects == {}
    assert any('acquire_user_agent_turn_lease' in query for query in sql.calls)
    assert any('renew_user_agent_turn_lease' in query for query in sql.calls)
    assert any('release_user_agent_turn_lease' in query for query in sql.calls)


def test_readiness_rejects_bad_readback_and_cleans_only_its_new_owner():
    sql = ReadinessSql(fail_read=True)
    with pytest.raises(RuntimeError, match='readback differs'):
        asyncio.run(fixture.verify_artifact_storage(sql, probe_owner=str(uuid4())))
    assert sql.owner is None and sql.objects == {}
    existing = ReadinessSql(existing=True)
    with pytest.raises(RuntimeError, match='already exists'):
        asyncio.run(fixture.verify_artifact_storage(existing, probe_owner=str(uuid4())))
    assert len(existing.calls) == 1 and not any('delete' in query for query in existing.calls)


def test_readiness_cancellation_joins_read_io_before_cleaning_probe():
    sql = ReadinessSql(hold_read=True)
    async def check():
        task = asyncio.create_task(fixture.verify_artifact_storage(sql, probe_owner=str(uuid4())))
        assert await asyncio.to_thread(sql.read_started.wait, 5)
        task.cancel()
        sql.read_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(check())
    assert sql.read_settled and sql.owner is None and sql.objects == {}


@pytest.fixture(scope='module')
def artifact_database():
    if os.environ.get('MEMOIR_TEST_ARTIFACT_POSTGRES') != '1':
        pytest.skip('Actual disposable PostgreSQL artifact tests require explicit opt-in')
    from test_agent_commit_postgres import database
    from test_guest_conversation_transfer import attachment_database
    from test_private_rounds_postgres import private_database
    from test_shared_memory_events_postgres import event_database
    setup = database.__wrapped__()
    sql = next(setup)
    try:
        sql = event_database.__wrapped__(private_database.__wrapped__(attachment_database.__wrapped__(sql)))
        fixture.initialize_artifact_storage(sql)
        yield sql
    finally:
        setup.close()


@pytest.fixture
def artifact_sql(artifact_database):
    artifact_database('truncate storage.objects;')
    return artifact_database


def test_postgres_actual_runtime_readiness_and_probe_cleanup(artifact_sql):
    probe = str(uuid4())
    receipt = asyncio.run(fixture.verify_artifact_storage(artifact_sql, probe_owner=probe))
    assert receipt['status'] == 'verified' and receipt['byte_readback_verified'] is True
    assert receipt['probe_cleaned'] is True and receipt['model_calls'] == 0
    assert receipt['artifacts'] == 2 and receipt['bytes'] > 0
    assert artifact_sql('select count(*) from storage.objects;').stdout.strip() == '0'
    assert artifact_sql(f"select count(*) from auth.users where id='{probe}';").stdout.strip() == '0'


def test_postgres_immutable_owner_storage_and_existing_lease_fencing(artifact_sql):
    from test_agent_commit_postgres import OWNER as db_owner, OTHER as db_other, as_user, OLD, NEW, commit
    first = fixture.PostgresRest(artifact_sql, db_owner).storage()
    second = fixture.PostgresRest(artifact_sql, db_owner).storage()
    try:
        assert first.acquire_agent_turn_lease(OLD)
        path = first.put_agent_turn_file(OLD, 'sessions/probe.jsonl', JSONL)
        assert second.get_agent_file(path) == JSONL
        with pytest.raises(httpx.HTTPStatusError) as duplicate:
            first.put_agent_turn_file(OLD, 'sessions/probe.jsonl', b'overwrite')
        assert duplicate.value.response.status_code == 409
        assert second.get_agent_file(path) == JSONL
        assert artifact_sql(as_user('select count(*) from storage.objects;', db_other)).stdout.strip() == '0'
        foreign = f"insert into storage.objects(bucket_id,name,fixture_content) values('memory-spark','{db_owner}/agent/{path}',decode('61','hex'));"
        assert artifact_sql(as_user(foreign, db_other), check=False).returncode != 0
        assert artifact_sql(as_user(commit(paths=f"array['sessions/turns/{NEW}/wrong']")), check=False).returncode != 0
        first.commit_agent_turn(OLD, 'synthetic', 'synthetic', [path])
        assert first.release_agent_turn_lease(OLD)
        with pytest.raises(httpx.HTTPStatusError):
            first.commit_agent_turn(OLD, 'synthetic', 'synthetic', [path])
    finally:
        first.client.close()
        second.client.close()


def test_postgres_quota_serializes_concurrent_uploads_without_partial_writes(artifact_sql, monkeypatch):
    from test_agent_commit_postgres import OWNER as db_owner
    monkeypatch.setattr(fixture, 'ARTIFACT_MAX_BYTES_PER_OWNER', 8)
    monkeypatch.setattr(fixture, 'ARTIFACT_MAX_OBJECTS_PER_OWNER', 2)
    def send(index):
        rest = fixture.PostgresRest(artifact_sql, db_owner)
        name = f'{db_owner}/agent/sessions/turns/{TOKEN}/{index}.jsonl'
        return upload(rest, name=name, content=b'12345').status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(send, [1, 2]))
    assert sorted(statuses) == [200, 413]
    assert artifact_sql('select count(*) from storage.objects;').stdout.strip() == '1'
    assert artifact_sql('select sum(octet_length(fixture_content)) from storage.objects;').stdout.strip() == '5'


def test_postgres_object_quota_is_independent_of_byte_quota(artifact_sql, monkeypatch):
    from test_agent_commit_postgres import OWNER as db_owner
    monkeypatch.setattr(fixture, 'ARTIFACT_MAX_OBJECTS_PER_OWNER', 2)
    rest = fixture.PostgresRest(artifact_sql, db_owner)
    statuses = [upload(rest, name=f'{db_owner}/agent/sessions/turns/{TOKEN}/{i}', content=b'').status_code
        for i in range(3)]
    assert statuses == [200, 200, 413]
    assert artifact_sql('select count(*) from storage.objects;').stdout.strip() == '2'
