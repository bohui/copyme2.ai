"""Generated names lose authority with their source; explicit settings survive."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from apps.api import main, agent_routes
from apps.api.store import MemoryStore
from test_lifetime_home_recovery import home_auth, headers
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_lifetime_memory_commit import prepare, commit
from test_agent_commit_postgres import OWNER, OTHER, OLD, as_user
from test_shared_memory_events_postgres import rpc, literal


def pins(sql, identity):
    return rpc(sql, 'read_lifetime_pinned', f"'{identity['conversation_id']}'")


def change(sql, identity, accepted, action):
    return rpc(sql, 'change_user_narrator_source', f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,'{action}'," + ("'My name is Mary'" if action == 'edit' else 'null'))


def profile(sql):
    return json.loads(sql(f"select profile from public.user_profile where user_id='{OWNER}';").stdout)


@pytest.mark.parametrize('action', ['edit', 'withdraw'])
def test_generated_name_invalidates_exact_dependency_in_cold_pins_and_product_home(sql, home_auth, action):
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    assert pins(sql, identity)['chosen_name'] == 'Joan'
    with TestClient(main.create_app(MemoryStore())) as client:
        first = client.post('/v1/projects', headers=headers(), json={})
        assert first.status_code == 201 and first.json()['profile']['name'] == 'Joan'
        change(sql, identity, accepted, action)
        assert pins(sql, identity)['chosen_name'] is None
        assert profile(sql).get('name') is None
        warm = client.get('/v1/projects/' + identity['project_id'], headers=headers())
        assert warm.status_code == 200 and warm.json()['profile']['name'] is None
    with TestClient(main.create_app(MemoryStore())) as client:
        cold = client.post('/v1/projects', headers=headers('reauthenticated'), json={})
        assert cold.status_code == 201 and cold.json()['profile']['name'] is None
    assert json.loads(sql('select jsonb_build_object(\'authority\',authority,\'name\',chosen_name) from public.user_lifetime_chosen_name;').stdout) == {'authority': 'invalidated', 'name': None}


def test_generated_name_stores_exact_private_source_version_value(sql):
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    row = json.loads(sql('select row_to_json(n) from public.user_lifetime_chosen_name n;').stdout)
    assert row['source_id'] == accepted['source']['id'] and row['source_version'] == 1
    assert row['chosen_name'] == 'Joan' and row['project_id'] == identity['project_id']
    assert row['conversation_id'] == identity['conversation_id'] and row['user_id'] == OWNER
    assert sql(as_user('select * from public.user_lifetime_chosen_name;'), check=False).returncode != 0


@pytest.mark.parametrize('chosen', ['Joan', 'Independent name', None])
@pytest.mark.parametrize('action', ['edit', 'withdraw'])
def test_explicit_http_name_settings_survive_dependency_change_including_same_value(sql, home_auth, monkeypatch, chosen, action):
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    sql(f"update public.user_agent_turn_lease set expires_at=clock_timestamp() where user_id='{OWNER}';")
    monkeypatch.setattr(agent_routes, 'authenticated_storage', main.authenticated_storage)
    with TestClient(main.create_app(MemoryStore())) as client:
        saved = client.patch('/v1/agent/profile', headers=headers(), json={'name': chosen})
        assert saved.status_code == 200, saved.text
        assert saved.json()['name'] == chosen
        change(sql, identity, accepted, action)
        returned = client.get('/v1/agent/profile', headers=headers())
        assert returned.status_code == 200 and returned.json()['name'] == chosen
    assert profile(sql).get('name') == chosen
    assert pins(sql, identity)['chosen_name'] == chosen
    assert json.loads(sql('select jsonb_build_object(\'authority\',authority,\'name\',chosen_name,\'source\',source_id) from public.user_lifetime_chosen_name;').stdout) == {'authority': 'explicit', 'name': chosen, 'source': None}


def test_existing_independent_name_is_not_replaced_by_generated_name(sql):
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"name\":\"Independent\"}}') on conflict(user_id) do update set profile=excluded.profile;")
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    assert pins(sql, identity)['chosen_name'] == 'Independent'
    change(sql, identity, accepted, 'withdraw')
    assert profile(sql)['name'] == 'Independent'
    assert sql('select count(*) from public.user_lifetime_chosen_name;').stdout.strip() == '0'


def test_unrelated_settings_patch_preserves_provenance_until_source_withdrawal(sql):
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    saved = rpc(sql, 'set_lifetime_profile_settings', f"'{{\"birth_place\":\"Anshan\"}}','{OLD}'")
    assert saved['name'] == 'Joan' and saved['birth_place'] == 'Anshan'
    change(sql, identity, accepted, 'withdraw')
    assert profile(sql) == {'birth_place': 'Anshan'}


@pytest.mark.parametrize('locale', ['zh-CN', None])
def test_atomic_settings_locale_matches_existing_explicit_preference_semantics(sql, locale):
    from apps.api.conversation_locale import explicit_profile, record
    identity, turn, accepted, fence = prepare(sql)
    initial = {'name': 'Joan', 'preferred_language': 'en-AU', 'conversation_language': record('en-AU', source='first_reply', detected='en-AU', first_reply_id='first')}
    sql(as_user(f"update public.user_profile set profile={literal(initial)}::jsonb;"))
    saved = rpc(sql, 'set_lifetime_profile_settings', f"{literal({'preferred_language': locale})}::jsonb,'{OLD}'")
    assert saved == explicit_profile(initial, locale)
    for patch in ({'_provenance': {}}, {'name': 'x' * 121}, {'birth_year': '1950'}, {'preferred_language': 'fr'}):
        assert rpc(sql, 'set_lifetime_profile_settings', f"{literal(patch)}::jsonb,'{OLD}'", check=False).returncode != 0
    assert rpc(sql, 'set_lifetime_profile_settings', f"'{{\"name\":\"Other\"}}','{OLD}'", owner=OTHER, check=False).returncode != 0


@pytest.mark.parametrize('action', ['edit', 'withdraw'])
def test_profile_settings_and_name_invalidation_keep_project_profile_identity_lock_order(sql, action):
    import psycopg
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    command = sql.command
    dsn = f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    async def scenario():
        settings = await psycopg.AsyncConnection.connect(dsn)
        editor = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        observer = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        edit = None
        try:
            await settings.execute('set local role authenticated')
            await settings.execute("select set_config('request.jwt.claim.sub',%s,true)", (OWNER,))
            await settings.execute('select 1 from public.user_profile where user_id=auth.uid() for update')
            await editor.execute('set role authenticated')
            await editor.execute("select set_config('request.jwt.claim.sub',%s,false)", (OWNER,))
            edit = asyncio.create_task(editor.execute('select public.change_user_narrator_source(%s,%s,1,%s,%s)', (identity['project_id'], accepted['source']['id'], action, 'My name is Mary' if action == 'edit' else None)))
            async with asyncio.timeout(3):
                while not (await (await observer.execute('select cardinality(pg_blocking_pids(%s))', (editor.info.backend_pid,))).fetchone())[0]:
                    pass
                # The correction must wait before taking identity. The settings
                # profile→identity update can therefore finish without a cycle.
                await settings.execute("update public.user_profile set profile=profile||'{\"birth_place\":\"Independent\"}' where user_id=auth.uid()")
                await settings.commit()
                await edit
        finally:
            await settings.close()
            if edit is not None:
                await asyncio.gather(edit, return_exceptions=True)
            await editor.close()
            await observer.close()
    asyncio.run(scenario())
    assert pins(sql, identity)['chosen_name'] is None
    assert profile(sql)['birth_place'] == 'Independent'


def test_product_home_never_recaptures_new_fence_over_a_stale_name_body(sql, home_auth, monkeypatch):
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    store = MemoryStore()
    app = main.create_app(store)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.post('/v1/projects', headers=headers(), json={}).status_code == 201
        original = main._project_response
        changed = False
        def race(project, **kwargs):
            nonlocal changed
            body = original(project, **kwargs)
            if kwargs.get('authoritative_profile') is not None and not changed:
                changed = True
                change(sql, identity, accepted, 'withdraw')
            return body
        monkeypatch.setattr(main, '_project_response', race)
        response = client.get('/v1/projects/' + identity['project_id'], headers=headers())
        assert changed
        assert response.status_code >= 400
        assert 'Joan' not in response.text
    assert pins(sql, identity)['chosen_name'] is None


def test_actual_main_home_send_holds_source_authority_until_outer_asgi_delivery(sql, home_auth):
    import psycopg
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    app = main.create_app(MemoryStore())
    with TestClient(app) as client:
        assert client.post('/v1/projects', headers=headers(), json={}).status_code == 201
    command = sql.command
    dsn = f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        delivered = []
        editor = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        observer = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        await editor.execute('set role authenticated')
        await editor.execute("select set_config('request.jwt.claim.sub',%s,false)", (OWNER,))
        async def send(message):
            if message['type'] == 'http.response.body' and message.get('body'):
                assert b'Joan' in message['body']
                entered.set()
                await release.wait()
                delivered.append(message)
        async def receive():
            await asyncio.Event().wait()
        path = '/v1/projects/' + identity['project_id']
        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'}, 'http_version': '1.1',
            'method': 'GET', 'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': b'',
            'headers': [(b'authorization', b'Bearer owner')], 'client': ('test', 1), 'server': ('test', 80), 'root_path': ''}
        sending = asyncio.create_task(app(scope, receive, send))
        edit = None
        try:
            async with asyncio.timeout(3):
                await entered.wait()
                edit = asyncio.create_task(editor.execute("select public.change_user_narrator_source(%s,%s,1,'withdraw',null)", (identity['project_id'], accepted['source']['id'])))
                while not (await (await observer.execute('select cardinality(pg_blocking_pids(%s))', (editor.info.backend_pid,))).fetchone())[0]:
                    pass
                assert not edit.done() and not delivered
                release.set()
                await sending
                await edit
            assert len(delivered) == 1
        finally:
            release.set()
            await asyncio.gather(sending, *([edit] if edit else []), return_exceptions=True)
            await editor.close()
            await observer.close()
    asyncio.run(scenario())
    assert pins(sql, identity)['chosen_name'] is None


@pytest.mark.parametrize('action', ['edit', 'withdraw'])
@pytest.mark.parametrize('delete_profile', [False, True])
def test_stale_generic_profile_snapshot_cannot_resurrect_invalidated_generated_name(sql, action, delete_profile):
    from memoir_postgres_workflow import PostgresRest
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    storage = PostgresRest(sql, OWNER).storage()
    try:
        stale = storage.profile()
        assert stale['name'] == 'Joan'
        change(sql, identity, accepted, action)
        if delete_profile:
            sql(as_user('delete from public.user_profile where user_id=auth.uid();'))
        storage.save_profile({**stale, 'birth_place': 'Anshan', '_name_authority': 'explicit'})
        assert storage.profile().get('name') is None
        assert pins(sql, identity)['chosen_name'] is None
        assert profile(sql)['birth_place'] == 'Anshan'
        authority = sql('select row_to_json(n) from public.user_lifetime_chosen_name n;').stdout
        assert 'Joan' not in authority
        assert json.loads(authority)['authority'] == 'invalidated'
    finally:
        storage.client.close()


def test_generic_snapshot_cannot_replace_explicit_name_or_claim_private_provenance(sql):
    from memoir_postgres_workflow import PostgresRest
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    rpc(sql, 'set_lifetime_profile_settings', f"'{{\"name\":\"Independent\"}}','{OLD}'")
    storage = PostgresRest(sql, OWNER).storage()
    try:
        storage.save_profile({'name': 'Joan', '_name_authority': 'generated'})
        change(sql, identity, accepted, 'withdraw')
        assert storage.profile()['name'] == 'Independent'
    finally:
        storage.client.close()


@pytest.mark.parametrize('authenticated', [True, False])
def test_concurrent_profile_delete_and_stale_upsert_cannot_return_or_store_old_name(sql, authenticated):
    import psycopg
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    command = sql.command
    dsn = f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    async def scenario():
        deleting = await psycopg.AsyncConnection.connect(dsn)
        inserting = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        observer = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        write = None
        try:
            if authenticated:
                for connection, local in ((deleting, True), (inserting, False)):
                    await connection.execute('set ' + ('local ' if local else '') + 'role authenticated')
                    await connection.execute("select set_config('request.jwt.claim.sub',%s,%s)", (OWNER, local))
            # The unbound privileged variant models a service-side writer and
            # proves validation uses the affected owner, not auth.uid().
            await deleting.execute('delete from public.user_profile where user_id=%s', (OWNER,))
            write = asyncio.create_task(inserting.execute(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"name\":\"Joan\",\"birth_place\":\"Anshan\"}}') on conflict(user_id) do update set profile=excluded.profile returning profile"))
            async with asyncio.timeout(3):
                while not (await (await observer.execute('select cardinality(pg_blocking_pids(%s))', (inserting.info.backend_pid,))).fetchone())[0]:
                    pass
                assert not write.done()
                await deleting.commit()
                with pytest.raises(psycopg.errors.SerializationFailure):
                    await write
                retry = await inserting.execute(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"name\":\"Joan\",\"birth_place\":\"Anshan\"}}') on conflict(user_id) do update set profile=excluded.profile returning profile")
                returned = (await retry.fetchone())[0]
                assert returned.get('name') is None
                assert returned['birth_place'] == 'Anshan'
        finally:
            await deleting.close()
            if write is not None:
                await asyncio.gather(write, return_exceptions=True)
            await inserting.close()
            await observer.close()
    asyncio.run(scenario())
    assert profile(sql).get('name') is None
    assert pins(sql, identity)['chosen_name'] is None
