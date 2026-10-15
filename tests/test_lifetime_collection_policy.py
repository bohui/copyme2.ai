"""Policy completeness defers scheduling without changing selected evidence."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from apps.api.lifetime_memory_collection_jobs import CollectionJobWorker
from test_agent_commit_postgres import OWNER, OTHER, database
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_lifetime_collection_jobs import event_database, sql, create, source, claim, page, commit, service_rpc, confirm, paid, outline_result
from test_lifetime_memory_postgres import resolve
from test_shared_memory_events_postgres import rpc, literal


def pending_error(message='LIFETIME_POLICY_PENDING', code='55000'):
    response = httpx.Response(400, json={'code': code, 'message': message},
                              request=httpx.Request('POST', 'http://synthetic.invalid/rpc'))
    return httpx.HTTPStatusError('Synthetic RPC failure', request=response.request, response=response)


@pytest.mark.parametrize('stage', ['claim', 'page', 'commit', 'pause_release'])
def test_policy_pending_is_deferred_before_or_after_claim(monkeypatch, stage):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED', 'true' if stage == 'pause_release' else 'false')
    job_id, token = str(uuid4()), str(uuid4())
    calls = []

    class Broker:
        async def rpc(self, name, **kwargs):
            calls.append((name, kwargs))
            if name == 'claim_lifetime_collection_job':
                if stage == 'claim':
                    raise pending_error()
                return {'id': job_id, 'token': token, 'user_id': OWNER}
            if name == 'read_lifetime_collection_job_page':
                if stage == 'page':
                    raise pending_error()
                return {'complete': False, 'kind': 'BuildOutline' if stage == 'pause_release' else 'BuildSourceExport'}
            if name == 'commit_lifetime_collection_job_page' and stage == 'commit':
                raise pending_error()
            if name == 'release_lifetime_collection_job' and stage == 'pause_release':
                raise pending_error()
            if name == 'defer_lifetime_collection_job_policy':
                assert kwargs == {'p_job_id': job_id, 'p_token': token, 'p_user_id': OWNER}
                return True
            pytest.fail(name)

    assert asyncio.run(CollectionJobWorker(Broker()).execute(job_id)) == {'status': 'deferred', 'processed': 0}
    if stage == 'claim':
        assert len(calls) == 1
    else:
        assert calls[-1][0] == 'defer_lifetime_collection_job_policy'
    assert not any(kwargs.get('p_error') for _, kwargs in calls)


@pytest.mark.parametrize('code,message', [('55000', 'Other prerequisite failure'), ('42501', 'LIFETIME_POLICY_PENDING')])
def test_unrelated_rpc_errors_remain_failures(code, message):
    released = []

    class Broker:
        async def rpc(self, name, **kwargs):
            if name == 'claim_lifetime_collection_job':
                return {'id': kwargs['p_job_id'], 'token': str(uuid4()), 'user_id': OWNER}
            if name == 'read_lifetime_collection_job_page':
                raise pending_error(message, code)
            if name == 'release_lifetime_collection_job':
                released.append(kwargs['p_error'])
                return True
            pytest.fail(name)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(CollectionJobWorker(Broker()).execute(str(uuid4())))
    assert released == ['BOUNDED_JOB_RETRY']


def test_owner_read_reports_policy_maintenance_instead_of_generation_pause():
    from apps.api.lifetime_memory_collection_jobs import _owner_rpc
    from fastapi import HTTPException

    class Storage:
        def lifetime_rpc(self, name, **kwargs):
            raise pending_error()

    with pytest.raises(HTTPException) as caught:
        _owner_rpc(Storage(), 'read_lifetime_collection_job')
    assert caught.value.status_code == 503
    assert caught.value.headers == {'X-Error-Code': 'LIFETIME_POLICY_PENDING'}


def mark_pending(sql, identity, original, *, inventory=False):
    if inventory:
        sql(f"insert into public.user_lifetime_policy_inventory_pending values('{OWNER}',{literal(identity['project_id'])},'{identity['conversation_id']}','literal-v1');")
    else:
        sql(f"insert into public.user_lifetime_pending_policy values('{OWNER}',{literal(identity['project_id'])},'{identity['conversation_id']}',"
            f"'{original['id']}',1,'{original['client_turn_id']}','literal-v1');")


def dsn_for(sql):
    return sql.publication_dsn


class SQLBroker:
    def __init__(self, sql, after=None):
        self.dsn, self.after = dsn_for(sql), after

    async def rpc(self, name, **parameters):
        import psycopg
        from psycopg.sql import SQL, Identifier, Placeholder
        from psycopg.types.json import Jsonb
        arguments = SQL(',').join(SQL('{}=>{}').format(Identifier(key), Placeholder()) for key in parameters)
        values = [Jsonb(value) if isinstance(value, (dict, list)) else value for value in parameters.values()]
        async with await psycopg.AsyncConnection.connect(self.dsn) as connection:
            await connection.execute('set local role service_role')
            cursor = await connection.execute(SQL('select {}({})').format(Identifier('public', name), arguments), values)
            result = (await cursor.fetchone())[0]
        if self.after is not None:
            await self.after(name)
        return result


def checkpoint(sql, job):
    saved = sql(f"select to_jsonb(j)-array['state','token','lease_until','attempts','error'] "
                f"from public.user_lifetime_collection_job j where id='{job['id']}';").stdout
    for table, order in [('source', 'ordinal'), ('page', 'page_number'), ('node', 'ordinal')]:
        saved += sql(f"select jsonb_agg(to_jsonb(v) order by {order}) "
                     f"from public.user_lifetime_collection_job_{table} v where job_id='{job['id']}';").stdout
    return saved


@pytest.mark.parametrize('stage', ['claim', 'page', 'provider'])
def test_policy_wait_preserves_checkpoint_and_resumes_after_metadata_repair(sql, monkeypatch, stage):
    from apps.api.lifetime_memory_job_engine import JobPublication
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.delenv('MEMOIR_LIFETIME_GENERATION_PAUSED', raising=False)
    identity = resolve(sql)
    project = identity['project_id']
    originals = [source(sql, project, 'Original memory one.'), source(sql, project, 'Original memory two.')] if stage == 'provider' else [source(sql, project, 'x' * 5000)]
    if stage == 'provider':
        confirm(sql, project, originals)
        paid(sql)
    job = create(sql, project, [] if stage == 'provider' else [originals[0]['id']],
                 'BuildOutline' if stage == 'provider' else 'BuildSourceExport', 1 if stage == 'provider' else None)
    lease = claim(sql, job)
    frozen = page(sql, job, lease['token'])
    commit(sql, frozen, outline_result(frozen) if stage == 'provider' else None)
    service_rpc(sql, 'release_lifetime_collection_job', f"'{job['id']}','{lease['token']}',null")
    accepted = checkpoint(sql, job)
    inserted = False

    async def after(name):
        nonlocal inserted
        target = 'claim_lifetime_collection_job' if stage == 'page' else 'read_lifetime_collection_job_page'
        if not inserted and stage != 'claim' and name == target:
            await asyncio.to_thread(mark_pending, sql, identity, originals[0])
            inserted = True

    if stage == 'claim':
        mark_pending(sql, identity, originals[0])
    sent = []

    async def transport(request):
        fence = json.loads(await request.aread())['bounded_job']['fence']
        sent.append(fence['page_number'])
        return httpx.Response(200, json={'reply': json.dumps(outline_result(fence))})

    worker = CollectionJobWorker(SQLBroker(sql, after), worker_url='http://synthetic.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(transport), publisher=JobPublication(dsn_for(sql), authenticated_owner=OWNER))
    for _ in range(4):
        assert asyncio.run(worker.execute(job['id'])) == {'status': 'deferred', 'processed': 0}
        state = json.loads(sql(f"select jsonb_build_object('state',state,'attempts',attempts,'token',token) "
                               f"from public.user_lifetime_collection_job where id='{job['id']}';").stdout)
        assert state == {'state': 'QUEUED', 'attempts': 0, 'token': None}
        assert checkpoint(sql, job) == accepted
    assert sent == []
    # Synthetic owner-only maintenance establishes the same original's policy
    # receipt. No user completeness flag or historical preference is invented.
    sql(f"select public.apply_lifetime_literal_policy('{OWNER}',{literal(project)},'{originals[0]['id']}',1);")
    assert asyncio.run(worker.execute(job['id'])) == {'status': 'succeeded', 'processed': 2}
    assert sent == ([1, 2] if stage == 'provider' else [])
    assert rpc(sql, 'read_lifetime_collection_job', f"'{job['id']}',null,8")['status'] == 'SUCCEEDED'


@pytest.mark.parametrize('inventory', [False, True])
def test_policy_pending_owner_cannot_starve_another_tenants_export(sql, inventory):
    identity = resolve(sql)
    original = source(sql, identity['project_id'])
    old = [rpc(sql, 'create_lifetime_collection_job', f"{literal(identity['project_id'])},'BuildSourceExport','Export {n}',{literal([original['id']])}::jsonb") for n in range(4)]
    other = resolve(sql, owner=OTHER)
    theirs = source(sql, other['project_id'], owner=OTHER)
    later = rpc(sql, 'create_lifetime_collection_job', f"{literal(other['project_id'])},'BuildSourceExport','Other',{literal([theirs['id']])}::jsonb", owner=OTHER)
    assert service_rpc(sql, 'pending_lifetime_collection_jobs', '4,true') == [job['id'] for job in old]
    mark_pending(sql, identity, original, inventory=inventory)
    assert service_rpc(sql, 'pending_lifetime_collection_jobs', '4,true') == [later['id']]
    assert asyncio.run(CollectionJobWorker(SQLBroker(sql)).execute(later['id'])) == {'status': 'succeeded', 'processed': 1}
    assert service_rpc(sql, 'pending_lifetime_collection_jobs', '4,true') == []


def test_policy_metadata_defer_requires_exact_owner_live_token_and_worker_role(sql):
    identity = resolve(sql)
    original = source(sql, identity['project_id'], 'x' * 5000)
    job = create(sql, identity['project_id'], [original['id']])
    lease = claim(sql, job)
    accepted = checkpoint(sql, job)
    mark_pending(sql, identity, original)
    for owner, token in [(OTHER, lease['token']), (OWNER, str(uuid4()))]:
        assert service_rpc(sql, 'defer_lifetime_collection_job_policy', f"'{job['id']}','{token}','{owner}'", check=False).returncode != 0
    args = f"'{job['id']}','{lease['token']}','{OWNER}'"
    assert rpc(sql, 'defer_lifetime_collection_job_policy', args, check=False).returncode != 0
    assert sql(f'set role anon; select public.defer_lifetime_collection_job_policy({args});', check=False).returncode != 0
    assert service_rpc(sql, 'release_lifetime_collection_job', f"'{job['id']}','{lease['token']}',null", check=False).returncode != 0
    assert service_rpc(sql, 'defer_lifetime_collection_job_policy', args) is True
    assert checkpoint(sql, job) == accepted
    assert service_rpc(sql, 'defer_lifetime_collection_job_policy', args, check=False).returncode != 0
    sql(f"select public.apply_lifetime_literal_policy('{OWNER}',{literal(identity['project_id'])},'{original['id']}',1);")
    replacement = claim(sql, job)
    sql(f"update public.user_lifetime_collection_job set lease_until=clock_timestamp()-interval '1 second' where id='{job['id']}';")
    assert service_rpc(sql, 'defer_lifetime_collection_job_policy', f"'{job['id']}','{replacement['token']}','{OWNER}'", check=False).returncode != 0
