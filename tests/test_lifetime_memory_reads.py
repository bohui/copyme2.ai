"""Read snapshots never borrow or interfere with the generation writer lease."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from apps.api.lifetime_memory_publication import PublicationUnavailable
from apps.api.lifetime_memory_reads import (
    ReadFence, ReadJSONResponse, ReadPublication, ReadSnapshot, snapshot_lifetime_read,
)

OWNER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
CONVERSATION = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
FENCE = dict(identity=dict(owner_id=OWNER, conversation_id=CONVERSATION,
    project_id='read-project'), policy_epoch=1, source_revision=1,
    execution_generation=1, phase_revision=0, preference_revision=0,
    captured_at_ms=1791763200000)
SCOPE = {'type': 'http', 'asgi': {'spec_version': '2.4'}}


class Publisher:
    def __init__(self, timeout=1):
        self.current = ReadFence.model_validate(FENCE)
        self.lock = asyncio.Lock()
        self.active = False
        self.send_timeout = timeout
        self.writer_active = True

    @asynccontextmanager
    async def guard(self, fence):
        async with self.lock:
            if ReadFence.model_validate(fence) != self.current:
                raise PublicationUnavailable('stale read fence')
            self.active = True
            try:
                async with asyncio.timeout(self.send_timeout):
                    yield
            finally:
                self.active = False

    async def correct(self, field='policy_epoch'):
        async with self.lock:
            current = self.current.model_dump(mode='json')
            current[field] += 1
            self.current = ReadFence.model_validate(current)


def execute(coroutine):
    async def bounded():
        async with asyncio.timeout(3):
            return await coroutine
    return asyncio.run(bounded())


async def receive():
    await asyncio.Event().wait()


@pytest.mark.parametrize('override', [dict(lease_token=CONVERSATION),
    dict(policy_epoch=True), dict(source_revision='1'), dict(captured_at_ms=None),
    dict(captured_at_ms=True), dict(preference_revision=-1), dict(unexpected=True)])
def test_read_fence_has_strict_types_and_rejects_writer_lease(override):
    with pytest.raises(ValidationError):
        ReadFence.model_validate({**FENCE, **override})


def test_capture_precedes_reads_and_pins_identity_without_resolving_or_leasing():
    calls = []
    publisher = Publisher()
    payload = {'reply': 'original'}
    original = deepcopy(FENCE)
    def rpc(name, **kwargs):
        calls.append(name)
        if name == 'read_lifetime_project_identity':
            return original['identity']
        assert name == 'capture_lifetime_read_fence'
        assert kwargs == {'p_project_id': 'read-project'}
        return original
    service = SimpleNamespace(user_id=OWNER, lifetime_rpc=rpc)
    def reader(fence):
        assert calls == ['read_lifetime_project_identity', 'capture_lifetime_read_fence']
        assert service.lifetime_read_identity == fence.identity.model_dump(mode='json')
        calls.append('read')
        return payload
    response = snapshot_lifetime_read(service, 'read-project', reader, publisher=publisher)
    payload['reply'] = 'changed'
    original['identity']['project_id'] = 'other'
    assert response.snapshot.body == b'{"reply":"original"}'
    assert response.snapshot.fence.identity.project_id == 'read-project'
    assert not hasattr(service, 'lifetime_read_identity')
    assert calls == ['read_lifetime_project_identity', 'capture_lifetime_read_fence', 'read']


@pytest.mark.parametrize('change', [dict(user_id=OTHER), dict(project='other')])
def test_capture_rejects_owner_or_project_mismatch_before_read(change):
    service = SimpleNamespace(user_id=change.get('user_id', OWNER),
        lifetime_rpc=lambda *a, **kw: deepcopy(FENCE['identity']))
    def forbidden(_):
        pytest.fail('mismatched scope reached data reader')
    with pytest.raises(PublicationUnavailable):
        snapshot_lifetime_read(service, change.get('project', 'read-project'), forbidden,
            publisher=Publisher())


@pytest.mark.parametrize('field', ['policy_epoch', 'source_revision', 'execution_generation',
                                  'phase_revision', 'preference_revision'])
def test_change_committed_after_read_prevents_any_old_json_bytes(field):
    async def scenario():
        publisher = Publisher()
        original = deepcopy(FENCE)
        snapshot = ReadSnapshot({'reply': 'old body'}, original)
        await publisher.correct(field)
        # Capturing again cannot relabel the old immutable snapshot.
        original.update(publisher.current.model_dump(mode='json'))
        messages = []
        async def send(message): messages.append(message)
        with pytest.raises(PublicationUnavailable):
            await ReadJSONResponse(snapshot, publisher=publisher)(SCOPE, receive, send)
        assert not messages
    execute(scenario())


def test_correction_cannot_commit_before_actual_send_finishes_and_writer_can_run():
    async def scenario():
        publisher = Publisher()
        entered, release, attempted = asyncio.Event(), asyncio.Event(), asyncio.Event()
        messages = []
        async def send(message):
            assert publisher.active
            assert publisher.writer_active
            if message['type'] == 'http.response.body':
                entered.set()
                await release.wait()
                messages.append(message)
        async def correct():
            attempted.set()
            await publisher.correct()
        response = asyncio.create_task(ReadJSONResponse(ReadSnapshot({'reply': 'valid'}, FENCE),
            publisher=publisher)(SCOPE, receive, send))
        await entered.wait()
        correction = asyncio.create_task(correct())
        await attempted.wait()
        assert not correction.done()
        release.set()
        await response
        await correction
        assert len(messages) == 1 and not publisher.active
    execute(scenario())


@pytest.mark.parametrize('mode', ['cancel', 'disconnect', 'timeout'])
def test_failure_or_disconnect_releases_send_guard(mode):
    async def scenario():
        publisher = Publisher(timeout=.02 if mode == 'timeout' else 1)
        entered = asyncio.Event()
        async def send(message):
            if message['type'] == 'http.response.body':
                entered.set()
                if mode == 'disconnect': raise OSError('disconnected')
                await asyncio.Event().wait()
        task = asyncio.create_task(ReadJSONResponse(ReadSnapshot({'reply': 'private'}, FENCE),
            publisher=publisher)(SCOPE, receive, send))
        await entered.wait()
        if mode == 'cancel': task.cancel()
        with pytest.raises({'cancel': asyncio.CancelledError, 'disconnect': OSError,
                            'timeout': TimeoutError}[mode]):
            await task
        assert not publisher.active
        await publisher.correct()
    execute(scenario())


def test_publication_rejects_owner_before_opening_database():
    async def scenario():
        publisher = ReadPublication('not-a-real-dsn', authenticated_owner=OTHER)
        with pytest.raises(PublicationUnavailable, match='owner'):
            async with publisher.guard(FENCE):
                pytest.fail('other owner published')
    execute(scenario())


def test_legacy_asgi_disconnect_cancels_body_and_releases_guard():
    async def scenario():
        publisher = Publisher()
        entered = asyncio.Event()
        async def send(message):
            if message['type'] == 'http.response.body':
                entered.set()
                await asyncio.Event().wait()
        async def disconnected():
            await entered.wait()
            return {'type': 'http.disconnect'}
        await ReadJSONResponse(ReadSnapshot({'reply': 'private'}, FENCE), publisher=publisher)(
            {'type': 'http', 'asgi': {'spec_version': '2.3'}}, disconnected, send)
        assert not publisher.active
        await publisher.correct()
    execute(scenario())


# Reuse the ordinary route fixture to prove the gated adapter leaves pagination
# and original-source response contracts intact, with no model or live requests.
from test_conversation_recovery_api import recovery, BASE, SOURCE, TURN, source, memory


@pytest.mark.parametrize('kind', ['history', 'source', 'receipt'])
def test_governed_routes_capture_before_read_and_use_final_send_guard(recovery, monkeypatch, kind):
    from apps.api import lifetime_memory_reads
    from apps.api.agent_storage import UserStorage
    client, rows, calls, _ = recovery
    rows['user_narrator_source'].append(source())
    rows['user_memory'].append(memory())
    fence = deepcopy(FENCE)
    fence['identity']['project_id'] = 'project-a'
    publisher = Publisher()
    publisher.current = ReadFence.model_validate(fence)
    published = []
    original_guard = publisher.guard
    @asynccontextmanager
    async def guard(snapshot):
        published.append(snapshot)
        async with original_guard(snapshot): yield
    publisher.guard = guard
    monkeypatch.setattr(lifetime_memory_reads, 'ReadPublication', lambda *a, **kw: publisher)
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    rpc_calls = []
    def rpc(self, name, **kwargs):
        rpc_calls.append(name)
        if name == 'read_lifetime_project_identity':
            return fence['identity']
        if name == 'capture_lifetime_read_fence':
            assert all(call.url.path == '/auth/v1/user' for call in calls)
            return fence
        assert name == 'read_lifetime_reply'
        assert self.lifetime_read_identity['conversation_id'] == CONVERSATION
        return {'reply': 'Current governed reply'}
    monkeypatch.setattr(UserStorage, 'lifetime_rpc', rpc)
    path = ('/agent/turns/' + TURN + '?project_id=project-a' if kind == 'receipt' else
        '/user/projects/project-a' + ('/history' if kind == 'history' else '/sources/' + SOURCE))
    response = client.get(BASE + path,
        headers={'Authorization': 'Bearer owner'})
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    assert rpc_calls[:2] == ['read_lifetime_project_identity', 'capture_lifetime_read_fence']
    assert len(published) == 1
    if kind == 'history':
        assert response.json()['items'][0]['reply'] == 'Current governed reply'
        assert response.json()['next_cursor'] is None
    elif kind == 'receipt':
        assert response.json()['reply'] == 'Current governed reply'
    else:
        assert response.json()['text'] == 'I lived near the river.'


from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_lifetime_memory_publication import database
from test_agent_commit_postgres import OLD, as_user
from test_shared_memory_events_postgres import rpc, literal


def setup_read(sql, *, profile=True):
    sql('truncate public.user_profile cascade;')
    identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
    if profile:
        sql(as_user("insert into public.user_profile(user_id,profile) values(auth.uid(),'{}');"))
    source = rpc(sql, 'accept_user_narrator_source',
        f"{literal(identity['project_id'])}, '00000000-0000-4000-8000-000000000001', 'Read original memory'")
    if not profile:
        # Atomic acceptance now creates the owner's policy/profile row. Restore
        # this test's missing-profile precondition only after that acceptance.
        sql(as_user('delete from public.user_profile where user_id=auth.uid();'))
    fence = rpc(sql, 'capture_lifetime_read_fence', literal(identity['project_id']))
    command = sql.command
    dsn = sql.publication_dsn or f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    return identity, source, fence, dsn


async def as_owner_connection(dsn):
    import psycopg
    connection = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    await connection.execute('set role authenticated')
    await connection.execute("select set_config('request.jwt.claim.sub',%s,false)", (OWNER,))
    return connection


async def wait_for_block(observer, connection):
    async with asyncio.timeout(2):
        while True:
            result = await observer.execute('select cardinality(pg_blocking_pids(%s))',
                (connection.info.backend_pid,))
            if (await result.fetchone())[0]: return


def test_postgres_capture_is_read_only_without_profile_or_writer_lease(sql):
    identity, source, fence, dsn = setup_read(sql, profile=False)
    assert 'lease_token' not in fence
    assert sql('select count(*) from public.user_profile;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_agent_turn_lease;').stdout.strip() == '0'
    async def scenario():
        async with ReadPublication(dsn, authenticated_owner=OWNER).guard(fence): pass
    execute(scenario())
    assert sql('select count(*) from public.user_profile;').stdout.strip() == '0'
    assert rpc(sql, 'capture_lifetime_read_fence', literal(identity['project_id']),
        owner=OTHER, check=False).returncode != 0
    assert sql("set role anon; select public.capture_lifetime_read_fence('unowned');",
        check=False).returncode != 0


@pytest.mark.parametrize('change', ['source', 'profile', 'profile_delete', 'phase'])
def test_postgres_correction_between_read_and_send_blocks_old_body(sql, change):
    identity, source, fence, dsn = setup_read(sql)
    snapshot = ReadSnapshot({'reply': 'previous private body'}, fence)
    if change == 'source':
        rpc(sql, 'change_user_narrator_source',
            f"{literal(identity['project_id'])}, '{source['id']}', 1, 'withdraw', null")
    elif change == 'profile':
        sql(as_user("update public.user_profile set profile='{\"preferred_language\":\"zh-CN\"}';"))
    elif change == 'profile_delete':
        sql(as_user('delete from public.user_profile where user_id=auth.uid();'))
    else:
        rpc(sql, 'change_user_conversation_phase', f"{literal(identity['project_id'])}, 'shape', 0")
    async def scenario():
        messages = []
        async def send(message): messages.append(message)
        with pytest.raises(PublicationUnavailable):
            await ReadJSONResponse(snapshot, publisher=ReadPublication(dsn,
                authenticated_owner=OWNER))(SCOPE, receive, send)
        assert messages == []
    execute(scenario())


@pytest.mark.parametrize('change', ['source', 'profile', 'first_profile'])
def test_postgres_actual_send_holds_authority_locks_until_completion(sql, change):
    import psycopg
    identity, source, fence, dsn = setup_read(sql, profile=change != 'first_profile')
    async def scenario():
        writer = await as_owner_connection(dsn)
        observer = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        entered, release = asyncio.Event(), asyncio.Event()
        delivered = []
        async def send(message):
            if message['type'] == 'http.response.body':
                entered.set()
                await release.wait()
                delivered.append(message)
        response = asyncio.create_task(ReadJSONResponse(ReadSnapshot({'reply': 'old'}, fence),
            publisher=ReadPublication(dsn, authenticated_owner=OWNER))(SCOPE, receive, send))
        edit = None
        try:
            await entered.wait()
            if change == 'source':
                edit = asyncio.create_task(writer.execute(
                    "select public.change_user_narrator_source(%s,%s,1,'withdraw',null)",
                    (identity['project_id'], source['id'])))
            elif change == 'profile':
                edit = asyncio.create_task(writer.execute(
                    "update public.user_profile set profile='{\"preferred_language\":\"zh-CN\"}' where user_id=auth.uid()"))
            else:
                edit = asyncio.create_task(writer.execute(
                    "insert into public.user_profile(user_id,profile) values(auth.uid(),'{\"preferred_language\":\"zh-CN\"}')"))
            await wait_for_block(observer, writer)
            assert not edit.done() and not delivered
            release.set()
            await response
            await edit
            assert len(delivered) == 1
            with pytest.raises(PublicationUnavailable):
                async with ReadPublication(dsn, authenticated_owner=OWNER).guard(fence): pass
        finally:
            release.set()
            await asyncio.gather(response, *([edit] if edit else []), return_exceptions=True)
            await writer.close()
            await observer.close()
    execute(scenario())


def test_postgres_receipt_read_does_not_acquire_or_block_current_writer_lease(sql):
    identity, source, fence, dsn = setup_read(sql)
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    lease_before = sql('select row_to_json(l) from public.user_agent_turn_lease l;').stdout
    async def scenario():
        import psycopg
        writer = await psycopg.AsyncConnection.connect(dsn)
        try:
            # Hold an exclusive writer-lease row lock, not merely an active token.
            await writer.execute('select 1 from public.user_agent_turn_lease for update')
            async with ReadPublication(dsn, authenticated_owner=OWNER, lock_timeout=.5).guard(fence):
                pass
        finally:
            await writer.close()
    execute(scenario())
    assert sql('select row_to_json(l) from public.user_agent_turn_lease l;').stdout == lease_before


@pytest.mark.parametrize('mode', ['cancel', 'disconnect', 'timeout'])
def test_postgres_failed_send_releases_locks_and_rolls_back(sql, mode):
    identity, source, fence, dsn = setup_read(sql)
    async def scenario():
        publisher = ReadPublication(dsn, authenticated_owner=OWNER,
            send_timeout=.04 if mode == 'timeout' else 1)
        entered = asyncio.Event()
        async def send(message):
            if message['type'] == 'http.response.body':
                entered.set()
                if mode == 'disconnect': raise OSError('disconnected')
                await asyncio.Event().wait()
        task = asyncio.create_task(ReadJSONResponse(ReadSnapshot({'reply': 'private'}, fence),
            publisher=publisher)(SCOPE, receive, send))
        await entered.wait()
        if mode == 'cancel': task.cancel()
        with pytest.raises({'cancel': asyncio.CancelledError, 'disconnect': OSError,
                            'timeout': TimeoutError}[mode]):
            await task
        writer = await as_owner_connection(dsn)
        try:
            await writer.execute("set lock_timeout='100ms'")
            await writer.execute("select public.change_user_narrator_source(%s,%s,1,'withdraw',null)",
                (identity['project_id'], source['id']))
        finally:
            await writer.close()
    execute(scenario())


@pytest.mark.parametrize('override', [dict(captured_at_ms=1), dict(captured_at_ms=999999999999999),
    dict(lease_token=CONVERSATION), dict(policy_epoch=None), dict(phase_revision='0'),
    dict(identity={**FENCE['identity'], 'owner_id': OTHER})])
def test_postgres_rejects_expired_future_malformed_and_cross_owner_fences(sql, override):
    identity, source, fence, dsn = setup_read(sql)
    fence.update(override)
    assert rpc(sql, 'lock_lifetime_read_publication', literal(fence) + '::jsonb',
        check=False).returncode != 0


def test_unmapped_legacy_read_is_explicit_and_never_falls_back_from_capture_failure():
    calls = []
    def rpc(name, **kwargs):
        calls.append(name)
        assert name == 'read_lifetime_project_identity'
        return None
    service = SimpleNamespace(user_id=OWNER, lifetime_rpc=rpc)
    def reader(fence):
        assert fence is None and service.lifetime_read_identity is None
        return {'reply': 'legacy owned-project reply'}
    assert snapshot_lifetime_read(service, 'legacy-project', reader) == {
        'reply': 'legacy owned-project reply'}
    assert calls == ['read_lifetime_project_identity']
    assert not hasattr(service, 'lifetime_read_identity')
    def broken(name, **kwargs):
        if name == 'read_lifetime_project_identity': return FENCE['identity']
        raise PublicationUnavailable('capture failed')
    service.lifetime_rpc = broken
    with pytest.raises(PublicationUnavailable):
        snapshot_lifetime_read(service, 'read-project', lambda _: pytest.fail('unsafe fallback'),
            publisher=Publisher())


def test_postgres_mapping_lookup_is_owner_project_scoped_and_never_creates_identity(sql):
    source = rpc(sql, 'accept_user_narrator_source', "'legacy-project','00000000-0000-4000-8000-000000000001','Original legacy source'")
    assert rpc(sql, 'read_lifetime_project_identity', "'legacy-project'") is None
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    assert sql('select id from public.user_narrator_source;').stdout.strip() == source['id']
    assert rpc(sql, 'read_lifetime_project_identity', "'legacy-project'", owner=OTHER) is None
    assert rpc(sql, 'read_lifetime_project_identity', "'nonexistent'") is None


def test_postgres_missing_profile_read_does_not_block_another_owner(sql):
    identity, source, fence, dsn = setup_read(sql, profile=False)
    async def scenario():
        writer = await as_owner_connection(dsn)
        try:
            await writer.execute("select set_config('request.jwt.claim.sub',%s,false)", (OTHER,))
            await writer.execute("set lock_timeout='100ms'")
            async with ReadPublication(dsn, authenticated_owner=OWNER).guard(fence):
                await writer.execute("insert into public.user_profile(user_id,profile) values(auth.uid(),'{}')")
        finally:
            await writer.close()
    execute(scenario())


def test_postgres_existing_profile_upsert_waits_for_send_without_lock_inversion(sql):
    import psycopg
    identity, source, fence, dsn = setup_read(sql)
    async def scenario():
        writer = await as_owner_connection(dsn)
        observer = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        edit = None
        try:
            async with ReadPublication(dsn, authenticated_owner=OWNER).guard(fence):
                edit = asyncio.create_task(writer.execute("insert into public.user_profile(user_id,profile) values(auth.uid(),'{\"preferred_language\":\"zh-CN\"}') on conflict(user_id) do update set profile=excluded.profile"))
                await wait_for_block(observer, writer)
                assert not edit.done()
            await edit
        finally:
            if edit: await asyncio.gather(edit, return_exceptions=True)
            await writer.close()
            await observer.close()
    execute(scenario())


@pytest.mark.parametrize('path', ['/user/projects/project-a/history',
    '/user/projects/project-a/sources/' + SOURCE, '/agent/turns/' + TURN + '?project_id=project-a'])
def test_flag_on_unmapped_legacy_gets_keep_original_owned_read_contract(recovery, monkeypatch, path):
    from apps.api import lifetime_memory_reads
    from apps.api.agent_storage import UserStorage
    client, rows, calls, _ = recovery
    rows['user_narrator_source'].append(source())
    rows['user_memory'].append(memory())
    mappings = []
    def rpc(self, name, **kwargs):
        assert name == 'read_lifetime_project_identity'
        assert kwargs == {'p_project_id': 'project-a'}
        mappings.append(name)
        return None
    monkeypatch.setattr(UserStorage, 'lifetime_rpc', rpc)
    expected = client.get(BASE + path, headers={'Authorization': 'Bearer owner'})
    assert expected.status_code == 200
    mappings.clear()
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setattr(lifetime_memory_reads, 'ReadPublication',
        lambda *a, **kw: pytest.fail('unmapped legacy read cannot invent a fence'))
    actual = client.get(BASE + path, headers={'Authorization': 'Bearer owner'})
    assert actual.status_code == 200
    assert actual.json() == expected.json()
    assert mappings == ['read_lifetime_project_identity']
    assert all(call.method == 'GET' for call in calls)


def test_repeated_cancellation_does_not_interrupt_database_close(monkeypatch):
    import psycopg
    async def scenario():
        entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Connection:
            closes = 0
            async def execute(self, *args): return self
            async def fetchone(self): return (20.0,)
            async def close(self):
                self.closes += 1
                closing.set()
                await release.wait()
        connection = Connection()
        async def connect(*args, **kwargs): return connection
        monkeypatch.setattr(psycopg.AsyncConnection, 'connect', connect)
        async def publish():
            async with ReadPublication('fixture', authenticated_owner=OWNER).guard(FENCE):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(publish())
        await entered.wait()
        task.cancel()
        await closing.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert connection.closes == 1
    execute(scenario())


@pytest.mark.parametrize('configured_dsn,legacy_only,allowed',[(True,True,False),(False,False,False),(False,True,True)])
def test_rest_schema_cache_miss_never_proves_unmapped_mixed_cohort(monkeypatch,configured_dsn,legacy_only,allowed):
    import httpx
    from types import SimpleNamespace
    from apps.api.lifetime_memory_reads import find_lifetime_read_identity
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
    monkeypatch.setenv('MEMOIR_LEGACY_ONLY_DEPLOYMENT','true' if legacy_only else 'false')
    if configured_dsn:monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL','synthetic-authority')
    else:monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL',raising=False)
    response=httpx.Response(404,request=httpx.Request('POST','https://synthetic.invalid/rpc'),
        json={'code':'PGRST202','message':'Could not find read_lifetime_project_identity in the schema cache'})
    def rpc(*args,**kwargs):response.raise_for_status()
    service=SimpleNamespace(user_id=OWNER,is_anonymous=False,lifetime_rpc=rpc)
    if allowed:assert find_lifetime_read_identity(service,None) is None
    else:
        with pytest.raises(httpx.HTTPStatusError):find_lifetime_read_identity(service,None)


@pytest.mark.parametrize('version',['2.3','2.4'])
def test_pending_policy_before_read_headers_sends_only_fixed_retry_metadata(version):
    from apps.api.lifetime_memory_policy import PolicyUnavailable
    released=[]
    class Pending:
        @asynccontextmanager
        async def guard(self,fence):
            try:
                error=PolicyUnavailable()
                error.trajectory={'source':'private original testimony'}
                raise error
                yield
            finally:released.append(True)
    async def scenario():
        messages=[]
        async def send(message):
            assert released==[True]
            messages.append(message)
        response=ReadJSONResponse(ReadSnapshot({'reply':'private original testimony','source_id':CONVERSATION},FENCE),
            publisher=Pending(),status_code=201,headers={'X-Private-Snapshot':CONVERSATION})
        await response({'type':'http','asgi':{'spec_version':version}},receive,send)
        assert [m['type'] for m in messages]==['http.response.start','http.response.body']
        assert messages[0]['status']==503
        headers=dict(messages[0]['headers'])
        assert headers[b'x-error-code']==b'LIFETIME_POLICY_PENDING'
        assert headers[b'retry-after']==b'60' and headers[b'cache-control']==b'no-store'
        assert b'x-private-snapshot' not in headers
        assert json.loads(messages[1]['body'])=={
            'detail':'Accepted conversation policy requires maintenance before private content can be used'}
        assert 'private original testimony' not in repr(messages)
        assert CONVERSATION not in repr(messages)
    execute(scenario())


@pytest.mark.parametrize('version',['2.3','2.4'])
@pytest.mark.parametrize('where',['start','body','guard_exit'])
def test_pending_policy_after_read_start_attempt_never_sends_second_headers(version,where):
    from apps.api.lifetime_memory_policy import PolicyUnavailable
    error=PolicyUnavailable()
    released=[]
    class Publisher:
        @asynccontextmanager
        async def guard(self,fence):
            try:
                yield
                if where=='guard_exit':raise error
            finally:released.append(True)
    async def scenario():
        messages=[]
        async def send(message):
            messages.append(message)
            if message['type']=='http.response.start' and where=='start':raise error
            if message['type']=='http.response.body' and where=='body':raise error
        response=ReadJSONResponse(ReadSnapshot({'reply':'original authorized body'},FENCE),publisher=Publisher())
        with pytest.raises(PolicyUnavailable) as caught:
            await response({'type':'http','asgi':{'spec_version':version}},receive,send)
        assert caught.value is error
        assert sum(m['type']=='http.response.start' for m in messages)==1
        assert messages[0]['status']==200
        assert len(messages)==(1 if where=='start' else 2)
        assert released==[True]
    execute(scenario())


@pytest.mark.parametrize('version',['2.3','2.4'])
@pytest.mark.parametrize('kind',['authority','cancel'])
def test_nonpolicy_read_admission_errors_keep_existing_no_response_behavior(version,kind):
    error=PublicationUnavailable('Foreign owner or stale fence') if kind=='authority' else asyncio.CancelledError()
    class Denied:
        @asynccontextmanager
        async def guard(self,fence):
            raise error
            yield
    async def scenario():
        messages=[]
        async def send(message):messages.append(message)
        with pytest.raises(type(error)) as caught:
            await ReadJSONResponse(ReadSnapshot({'reply':'private'},FENCE),publisher=Denied())(
                {'type':'http','asgi':{'spec_version':version}},receive,send)
        assert caught.value is error and messages==[]
    execute(scenario())
