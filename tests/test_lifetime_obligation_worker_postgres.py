import asyncio
import json
from test_lifetime_outbox_postgres import sql,event_database,private_database,attachment_database,database,setup,claim,save_reply
from test_agent_commit_postgres import OLD,OWNER,as_user
from test_shared_memory_events_postgres import rpc,literal
from apps.api.lifetime_memory_maintenance import drain_lifetime_obligations_once


def worker_rpc(sql,limit=4):
    result=sql(f"begin;set local role service_role;select set_config('request.jwt.claim.sub','',true);select public.drain_lifetime_memory_obligations({limit});commit;")
    rows=[line for line in result.stdout.splitlines() if line.startswith('{')]
    return json.loads(rows[-1])


def test_crashed_saved_turn_completes_without_user_token_or_new_visit(sql,monkeypatch):
    identity,source,fence=setup(sql)
    fence=save_reply(sql,source,fence)['fence']
    claimed=claim(sql,fence)
    assert claimed['status']=='running'
    # A process died after committing its receipt/claim. Only fixture clocks are
    # advanced; no authenticated user returns and no further turn is accepted.
    sql("update public.user_agent_turn_lease set expires_at=clock_timestamp()-interval '1 second';update public.user_lifetime_memory_obligation set claim_expires_at=clock_timestamp()-interval '1 second' where status='running';")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    class Broker:
        async def rpc(self,name,**params):
            assert name=='drain_lifetime_memory_obligations'
            return worker_rpc(sql,params['p_limit'])
    result=asyncio.run(drain_lifetime_obligations_once(Broker(),limit=4))
    assert result['processed']==2 and result['failed']==0
    assert sql("select count(*) from public.user_lifetime_memory_obligation where status='succeeded';").stdout.strip()=='2'
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip()=='0'


def test_worker_never_steals_foreground_lease_and_public_call_is_denied(sql):
    identity,source,fence=setup(sql)
    result=worker_rpc(sql)
    assert result['processed']==0 and result['busy']==1
    assert sql(f"select lease_token from public.user_agent_turn_lease where user_id='{OWNER}';").stdout.strip()==OLD
    denied=sql(as_user('select public.drain_lifetime_memory_obligations(4);'),check=False)
    assert denied.returncode!=0 and 'permission denied' in denied.stderr


def test_worker_failure_retains_bounded_retry_and_eventually_inspectable_exhaustion(sql):
    identity,source,fence=setup(sql)
    rpc(sql,'release_user_agent_turn_lease',f"'{OLD}'")
    sql("""create function public.fixture_projection_failure() returns trigger language plpgsql as $$begin
      if new.status='succeeded' then raise exception 'synthetic projection storage failure';end if;return new;end$$;
      create trigger fixture_projection_failure before update on public.user_lifetime_memory_obligation
      for each row execute function public.fixture_projection_failure();""")
    try:
        for n in range(5):
            result=worker_rpc(sql)
            assert result['failed']==1 and result['processed']==0
            assert int(sql('select attempts from public.user_lifetime_memory_obligation;').stdout.strip())==n+1
            sql("update public.user_lifetime_memory_obligation set next_attempt_at=clock_timestamp()-interval '1 second';")
        assert sql('select status from public.user_lifetime_memory_obligation;').stdout.strip()=='failed'
        assert sql('select error_code from public.user_lifetime_memory_obligation;').stdout.strip()=='projection_failed'
    finally:
        sql('drop trigger fixture_projection_failure on public.user_lifetime_memory_obligation;drop function public.fixture_projection_failure();')


def test_busy_owner_locks_release_before_worker_waits_on_another_tenant(sql):
    import psycopg
    from test_agent_commit_postgres import OTHER,NEW
    setup(sql)
    other=rpc(sql,'resolve_lifetime_conversation','null',owner=OTHER)
    rpc(sql,'accept_user_narrator_source',f"{literal(other['project_id'])},'{NEW}','Other synthetic source'",owner=OTHER)
    sql(f"insert into public.user_profile(user_id,profile) values('{OTHER}','{{}}') on conflict do nothing;insert into public.user_agent_turn_lease(user_id,lease_token,expires_at) values('{OTHER}','{NEW}',clock_timestamp()-interval '1 second');")
    command=sql.command
    dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    async def scenario():
        blocker=await psycopg.AsyncConnection.connect(dsn)
        worker=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        try:
            await blocker.execute('select 1 from public.user_agent_turn_lease where user_id=%s for update',(OTHER,))
            await worker.execute('set role service_role')
            running=asyncio.create_task(worker.execute('select public.drain_lifetime_memory_obligations(2)'))
            async with asyncio.timeout(1):
                while True:
                    blocked=await (await observer.execute('select cardinality(pg_blocking_pids(%s))',(worker.info.backend_pid,))).fetchone()
                    if blocked[0]:break
                    assert not running.done()
            # Owner one has an active foreground lease. Its earlier project and
            # preference locks must already have rolled back before tenant two.
            await observer.execute('begin')
            await observer.execute('select 1 from public.user_memoir_project where user_id=%s for update nowait',(OWNER,))
            await observer.execute('select 1 from public.user_profile where user_id=%s for update nowait',(OWNER,))
            await observer.execute('rollback')
            await blocker.rollback()
            await running
        finally:
            await blocker.close();await worker.close();await observer.close()
    asyncio.run(scenario())
