"""Barrier-driven send/correction tests against an isolated real PostgreSQL."""
import asyncio
from copy import deepcopy

import pytest
from apps.api.lifetime_memory_publication import TransactionalPublication, PublicationUnavailable
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_agent_commit_postgres import database as postgres_database
from test_agent_commit_postgres import OWNER, OTHER, OLD, as_user
from test_shared_memory_events_postgres import rpc, literal


@pytest.fixture(scope='module')
def database():
    yield from postgres_database.__wrapped__(publication_tcp=True)


def setup(sql):
    identity = rpc(sql,'resolve_lifetime_conversation','null')
    sql(as_user("insert into public.user_profile(user_id,profile) values(auth.uid(),'{}') on conflict(user_id) do update set profile='{}';"))
    source = rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])}, '00000000-0000-4000-8000-000000000001', 'Private original memory'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence = rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}', '{OLD}'")
    dsn = sql.publication_dsn
    return identity,source,fence,dsn


def test_send_completes_before_correction_fence_and_later_output_is_blocked(sql):
    import psycopg
    identity,source,fence,dsn = setup(sql)
    async def scenario():
        publisher = TransactionalPublication(dsn,authenticated_owner=OWNER)
        correction = await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        await correction.execute('set role authenticated')
        await correction.execute("select set_config('request.jwt.claim.sub',%s,false)",(OWNER,))
        pid = correction.info.backend_pid
        async with publisher.guard(fence):
            edit = asyncio.create_task(correction.execute('select public.change_user_narrator_source(%s,%s,1,\'withdraw\',null)',(identity['project_id'],source['id'])))
            observer = await psycopg.AsyncConnection.connect(dsn,autocommit=True)
            try:
                # The database lock wait is the barrier, not elapsed sleeping.
                async with asyncio.timeout(2):
                    while True:
                        row = await (await observer.execute('select cardinality(pg_blocking_pids(%s))',(pid,))).fetchone()
                        if row[0]:
                            break
                assert not edit.done()
            finally:
                await observer.close()
            # Simulated ASGI send completes here while the correction is blocked.
        await edit
        await correction.close()
        with pytest.raises(psycopg.DatabaseError) as rejected:
            async with publisher.guard(fence):
                pytest.fail('stale queued output must never be sent')
        assert rejected.value.sqlstate == 'PT409'
    asyncio.run(scenario())
    assert rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}', '{OLD}'")['execution_generation'] == fence['execution_generation']+1


def test_disconnect_and_send_timeout_release_locks_for_withdrawal(sql):
    identity,source,fence,dsn = setup(sql)
    async def scenario():
        publisher = TransactionalPublication(dsn,authenticated_owner=OWNER,send_timeout=.05)
        with pytest.raises(TimeoutError):
            async with publisher.guard(fence):
                await asyncio.Event().wait()
        entered = asyncio.Event()
        async def blocked_send():
            async with publisher.guard(fence):
                entered.set()
                await asyncio.Event().wait()
        sending = asyncio.create_task(blocked_send())
        await entered.wait()
        sending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sending
    asyncio.run(scenario())
    assert rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])}, '{source['id']}', 1, 'withdraw', null")


def test_owner_and_snapshot_are_not_supplied_by_the_client(sql):
    identity,source,fence,dsn = setup(sql)
    async def scenario():
        publisher = TransactionalPublication('invalid connection',authenticated_owner=OTHER)
        with pytest.raises(PublicationUnavailable):
            async with publisher.guard(fence):
                pass
        publisher = TransactionalPublication(dsn,authenticated_owner=OWNER)
        for key in ['source_revision','phase_revision','preference_revision','execution_generation','policy_epoch']:
            stale=deepcopy(fence); stale[key]+=1
            with pytest.raises(Exception,match='stale lifetime fence'):
                async with publisher.guard(stale):
                    pytest.fail('changed fence must be rejected')
    asyncio.run(scenario())


def test_direct_preference_write_and_project_first_acceptance_do_not_deadlock(sql):
    import psycopg
    identity,source,fence,dsn = setup(sql)
    async def scenario():
        plan = await psycopg.AsyncConnection.connect(dsn)
        preference = await psycopg.AsyncConnection.connect(dsn)
        try:
            # Hold the existing project-first acceptance transaction at its seam.
            # Fixture-only barrier emulates the security-definer RPC's lock.
            await plan.execute('select 1 from public.user_memoir_project where user_id=%s and project_id=%s for update',(OWNER,identity['project_id']))
            await plan.execute('set local role authenticated')
            await plan.execute("select set_config('request.jwt.claim.sub',%s,true)",(OWNER,))
            await preference.execute('set local role authenticated')
            await preference.execute("select set_config('request.jwt.claim.sub',%s,true)",(OWNER,))
            async with asyncio.timeout(2):
                # This must complete even while plan owns the project lock.
                await preference.execute('update public.user_profile set profile=%s where user_id=%s',('{"preferred_language":"zh-CN"}',OWNER))
                await preference.commit()
                await plan.execute("select public.accept_user_interview_turn(%s,'00000000-0000-4000-8000-000000000002','Another memory')",(identity['project_id'],))
                await plan.commit()
        finally:
            await preference.close(); await plan.close()
    asyncio.run(scenario())
    current=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}', '{OLD}'")
    assert current['preference_revision'] == fence['preference_revision']+1


def test_actual_asgi_send_await_is_inside_the_guard_and_preference_changes_revoke(sql):
    from apps.api.lifetime_memory_publication import send_governed
    import psycopg
    identity,source,fence,dsn=setup(sql)
    sent=[]
    async def send(message):
        sent.append(message)
    async def scenario():
        publisher=TransactionalPublication(dsn,authenticated_owner=OWNER)
        await send_governed(send,{'type':'http.response.body','body':b'authorized'},publisher=publisher,fence=fence)
        sql(as_user("update public.user_profile set profile='{" + '"preferred_language":"zh-CN"' + "}';"))
        with pytest.raises(psycopg.DatabaseError) as rejected:
            await send_governed(send,{'type':'http.response.body','body':b'stale'},publisher=publisher,fence=fence)
        assert rejected.value.sqlstate == 'PT409'
    asyncio.run(scenario())
    assert len(sent)==1 and sent[0]['body']==b'authorized'


def test_brief_background_project_lock_does_not_abort_valid_stream(sql):
    from apps.api.lifetime_memory_publication import send_governed
    import psycopg
    identity,source,fence,dsn=setup(sql)
    sent=[]

    async def scenario():
        blocker=await psycopg.AsyncConnection.connect(dsn)
        observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        sending=None
        try:
            await blocker.execute('select 1 from public.user_memoir_project where user_id=%s and project_id=%s for update',
                (OWNER,identity['project_id']))
            publisher=TransactionalPublication(dsn+' application_name=publication-delay-regression',authenticated_owner=OWNER)
            async def send(message):
                sent.append(message)
            sending=asyncio.create_task(send_governed(send,{'body':b'authorized'},publisher=publisher,fence=fence))
            async with asyncio.timeout(2):
                while True:
                    row=await (await observer.execute("select exists(select 1 from pg_stat_activity where application_name='publication-delay-regression' and cardinality(pg_blocking_pids(pid))>0)")).fetchone()
                    if row[0]:
                        break
                    await asyncio.sleep(.01)
            # Release a transient background lock after the old two-second
            # setup limit, but inside the bounded five-second guard allowance.
            await asyncio.sleep(2.2)
            await blocker.commit()
            await sending
        finally:
            await blocker.close()
            await observer.close()
            if sending and not sending.done():
                sending.cancel()
                await asyncio.gather(sending,return_exceptions=True)
    asyncio.run(scenario())
    assert sent==[{'body':b'authorized'}]
