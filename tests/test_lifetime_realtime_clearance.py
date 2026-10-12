"""Synthetic-only global realtime drain / canonical admission boundary."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_agent_commit_postgres import OWNER, OTHER, as_user
from test_shared_memory_events_postgres import rpc, literal


def test_new_adoption_requires_explicit_realtime_clearance(gate):
    sql=gate
    # This test deliberately uses the migration-default stage, unlike the
    # explicitly cleared ordinary canonical test fixtures.
    if sql("select to_regclass('public.lifetime_realtime_clearance');").stdout.strip():
        sql('truncate public.lifetime_realtime_clearance; insert into public.lifetime_realtime_clearance default values;')
    blocked=rpc(sql,'resolve_lifetime_conversation','null',check=False)
    assert blocked.returncode!=0 and 'LIFETIME_REALTIME_CLEARANCE_REQUIRED' in blocked.stderr
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip()=='0'


def test_direct_realtime_requires_transactional_authority_even_legacy_only(monkeypatch):
    from apps.api.lifetime_memory_activation import RealtimePublication
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    monkeypatch.setenv('MEMOIR_LEGACY_ONLY_DEPLOYMENT','true')
    with pytest.raises(PublicationUnavailable):RealtimePublication(None,authenticated_owner=UUID(int=4))


def publisher_case(kind, **options):
    if kind == 'collector':
        from apps.api.lifetime_memory_publication import ProviderPublication
        from test_lifetime_memory_engine import FENCE
        return ProviderPublication('synthetic-only', authenticated_owner=FENCE.identity.owner_id, **options), FENCE
    if kind == 'lane':
        from apps.api.lifetime_memory_lane_engine import LanePublication
        from test_lifetime_memory_lane_engine import transport
        fence = transport().fence
        return LanePublication('synthetic-only', authenticated_owner=fence.user_id, **options), fence
    from apps.api.lifetime_memory_job_engine import JobPublication
    from test_lifetime_memory_job_engine import transport
    fence = transport().fence
    return JobPublication('synthetic-only', authenticated_owner=fence.user_id, **options), fence


@pytest.mark.parametrize('kind', ['collector', 'lane', 'job'])
@pytest.mark.parametrize('closed', [False, True])
def test_every_provider_admission_requires_clearance_after_authority(monkeypatch, kind, closed):
    import psycopg
    from apps.api.lifetime_memory_activation import CanonicalActivationUnavailable
    calls = []; released = []
    class Database:
        @staticmethod
        async def connect(*args, **kwargs): return Database()
        async def execute(self, statement, args=None):
            calls.append(statement)
            if 'provider_activation' in statement and closed:
                raise psycopg.errors.ObjectNotInPrerequisiteState('private attestation must not escape')
            async def fetchone(): return (10,)
            return SimpleNamespace(fetchone=fetchone)
        async def close(self): released.append(True)
    monkeypatch.setattr(psycopg, 'AsyncConnection', Database)
    publisher, fence = publisher_case(kind)
    async def run():
        async with publisher.guard(fence):
            assert not closed and not released
    if closed:
        with pytest.raises(CanonicalActivationUnavailable) as error: asyncio.run(run())
        assert 'private' not in str(error.value)
    else: asyncio.run(run())
    assert calls[-1] == 'select public.lock_lifetime_provider_activation()'
    assert 'publication' in calls[-2]
    assert released == [True]


@pytest.mark.parametrize('kind', ['collector', 'lane', 'job'])
def test_activation_wait_cannot_spend_previously_measured_lease(monkeypatch, kind):
    import psycopg
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    released = []
    class Database:
        @staticmethod
        async def connect(*args, **kwargs): return Database()
        async def execute(self, statement, args=None):
            if 'provider_activation' in statement: await asyncio.sleep(.03)
            async def fetchone(): return (.11,)
            return SimpleNamespace(fetchone=fetchone)
        async def close(self): released.append(True)
    monkeypatch.setattr(psycopg, 'AsyncConnection', Database)
    publisher, fence = publisher_case(kind)
    async def run():
        with pytest.raises(PublicationUnavailable):
            async with publisher.guard(fence): pytest.fail('Expired lease admitted bytes')
    asyncio.run(run())
    assert released == [True]


def test_saved_publication_does_not_require_new_generation_clearance(monkeypatch):
    import psycopg
    from apps.api.lifetime_memory_publication import TransactionalPublication
    from test_lifetime_memory_engine import FENCE
    class Database:
        @staticmethod
        async def connect(*args, **kwargs): return Database()
        async def execute(self, statement, args=None):
            assert 'provider_activation' not in statement
            async def fetchone(): return (10,)
            return SimpleNamespace(fetchone=fetchone)
        async def close(self): pass
    monkeypatch.setattr(psycopg, 'AsyncConnection', Database)
    async def run():
        async with TransactionalPublication('synthetic-only', authenticated_owner=FENCE.identity.owner_id).guard(FENCE): pass
    asyncio.run(run())


def test_clearance_acquisition_timeout_is_fixed_but_send_cancellation_is_preserved(monkeypatch):
    import psycopg
    from apps.api.lifetime_memory_activation import ActivationPublication, CanonicalActivationUnavailable
    closed=[]
    class Database:
        block = True
        @staticmethod
        async def connect(*args, **kwargs): return Database()
        async def execute(self, statement, args=None):
            if 'provider_activation' in statement and self.block: await asyncio.Event().wait()
        async def close(self): closed.append(True)
    monkeypatch.setattr(psycopg, 'AsyncConnection', Database)
    async def run():
        publisher = ActivationPublication('synthetic-only', authenticated_owner=OWNER, lock_timeout=.01, send_timeout=.01)
        with pytest.raises(CanonicalActivationUnavailable):
            async with publisher.guard(): pytest.fail('Timed-out activation admitted')
        Database.block = False
        with pytest.raises(TimeoutError):
            async with publisher.guard(): await asyncio.Event().wait()
        entered = asyncio.Event()
        async def sending():
            async with publisher.guard():
                entered.set(); await asyncio.Event().wait()
        task=asyncio.create_task(sending())
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(run());assert len(closed)==3


@pytest.mark.parametrize('stream', [False, True])
@pytest.mark.parametrize('kind', ['collector', 'lane', 'job'])
def test_worker_missing_clearance_authority_rejects_before_stream_starts(monkeypatch, stream, kind):
    from fastapi.testclient import TestClient
    from apps.api import codex_worker_service as worker
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'synthetic')
    monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL', raising=False)
    if kind == 'collector':
        from test_lifetime_memory_engine import fixture
        packet, context = fixture()
        payload={'user_id':str(packet.fence.identity.owner_id),'project_id':packet.fence.identity.project_id,
            'agent_role':'collector','model':packet.budget.model,'governed':packet.model_dump(mode='json'),'interview_context':context}
    else:
        if kind == 'lane':
            from test_lifetime_memory_lane_engine import transport
        else:
            from test_lifetime_memory_job_engine import transport
        packet=transport()
        payload={'user_id':str(packet.fence.user_id),'project_id':packet.fence.project_id,
            'agent_role':'author_timeline' if kind=='lane' else 'organiser','model':packet.budget.model,
            'bounded_'+kind:packet.model_dump(mode='json')}
    async def forbidden(*args, **kwargs): pytest.fail('No provider work before readiness')
    monkeypatch.setattr(worker.worker, 'turn', forbidden)
    headers={'X-Codex-Worker-Secret':'synthetic'}
    if stream: headers['Accept']='application/x-ndjson'
    with TestClient(worker.app) as client:
        result=client.post('/internal/codex/turn',json=payload,headers=headers)
    assert result.status_code==503,result.text
    assert result.headers['X-Error-Code']=='LIFETIME_REALTIME_CLEARANCE_REQUIRED'
    assert 'started' not in result.text


def reset_stage(sql):
    sql('truncate public.lifetime_realtime_clearance; insert into public.lifetime_realtime_clearance default values;')


def ready(sql):
    sql("select public.begin_lifetime_realtime_drain(0); select public.attest_lifetime_realtime_clearance(1,'synthetic-isolated-fixture-no-live-calls');")


@pytest.fixture
def gate(sql):
    reset_stage(sql)
    try: yield sql
    finally:
        reset_stage(sql); ready(sql)


def dsn_for(sql):
    command=sql.command
    return f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"


async def wait_blocked(observer, pid):
    async with asyncio.timeout(2):
        while True:
            row=await (await observer.execute('select cardinality(pg_blocking_pids(%s))',(pid,))).fetchone()
            if row[0]: return


@pytest.mark.parametrize('role',['anon','authenticated','service_role'])
def test_only_database_owner_can_attest_clearance(gate,role):
    for statement in ["select public.begin_lifetime_realtime_drain(0)",
            "select public.attest_lifetime_realtime_clearance(1,'forged-clearance')",
            "update public.lifetime_realtime_clearance set stage='canonical_ready',revision=2,termination_attestation_reference='forged'",
            "select * from public.lifetime_realtime_clearance"]:
        blocked=gate(f'set role {role}; {statement};',check=False)
        assert blocked.returncode!=0 and 'permission denied' in blocked.stderr
    assert gate('select stage from public.lifetime_realtime_clearance;').stdout.strip()=='legacy_only'


def test_operator_transitions_require_cas_attestation_and_never_reopen(gate):
    assert gate("select public.attest_lifetime_realtime_clearance(0,'premature');",check=False).returncode!=0
    assert gate('select public.begin_lifetime_realtime_drain(1);',check=False).returncode!=0
    gate('select public.begin_lifetime_realtime_drain(0);')
    for value in ('null',"''","'private human prose is forbidden'","repeat('x',257)"):
        assert gate(f'select public.attest_lifetime_realtime_clearance(1,{value});',check=False).returncode!=0
    gate("select public.attest_lifetime_realtime_clearance(1,'synthetic-verified-all-connected-and-inflight-calls');")
    assert gate("update public.lifetime_realtime_clearance set stage='legacy_only',revision=3,termination_attestation_reference=null;",check=False).returncode!=0
    assert gate('select public.begin_lifetime_realtime_drain(2);',check=False).returncode!=0
    assert gate('select stage from public.lifetime_realtime_clearance;').stdout.strip()=='canonical_ready'


def test_identity_insert_gate_and_existing_identity_recovery_are_distinct(gate):
    gate(f"insert into public.user_memoir_project(user_id,project_id) values('{OWNER}','fixture-project');")
    blocked=gate(f"insert into public.user_lifetime_conversation(user_id,project_id) values('{OWNER}','fixture-project');",check=False)
    assert blocked.returncode!=0 and 'LIFETIME_REALTIME_CLEARANCE_REQUIRED' in blocked.stderr
    ready(gate)
    gate(f"insert into public.user_lifetime_conversation(user_id,project_id) values('{OWNER}','fixture-project');")
    identity=rpc(gate,'resolve_lifetime_conversation','null')
    reset_stage(gate);gate('select public.begin_lifetime_realtime_drain(0);')
    assert rpc(gate,'resolve_lifetime_conversation','null')==identity
    assert rpc(gate,'read_lifetime_project_identity',"'fixture-project'")['conversation_id']==identity['conversation_id']
    gate('truncate public.lifetime_realtime_clearance;')
    assert rpc(gate,'resolve_lifetime_conversation','null')==identity
    denied=rpc(gate,'resolve_lifetime_conversation','null',owner=OTHER,check=False)
    assert denied.returncode!=0 and 'LIFETIME_REALTIME_CLEARANCE_REQUIRED' in denied.stderr


def test_actual_realtime_body_admission_serializes_drain_but_not_provider_response(gate,monkeypatch):
    import psycopg
    import httpx
    from apps.api import realtime_routes
    from apps.api.lifetime_memory_activation import RealtimePublication,CanonicalActivationUnavailable
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-unpaid-key')
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
    dsn=dsn_for(gate)
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();generation=asyncio.Event();finish=asyncio.Event();sent=[]
        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self,request):
                async for chunk in request.stream:
                    entered.set();await release.wait();sent.append(chunk)
                generation.set();await finish.wait()
                return httpx.Response(201,text='v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n')
        original=httpx.AsyncClient
        monkeypatch.setattr(realtime_routes.httpx,'AsyncClient',lambda **options:original(transport=Transport(),**options))
        publisher=RealtimePublication(dsn,authenticated_owner=OWNER)
        calling=asyncio.create_task(realtime_routes.exchange_offer('v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n',{},OWNER,publisher=publisher))
        operator=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        try:
            async with asyncio.timeout(2): await entered.wait()
            draining=asyncio.create_task(operator.execute('select public.begin_lifetime_realtime_drain(0)'))
            await wait_blocked(observer,operator.info.backend_pid)
            assert not draining.done()
            release.set();await draining
            async with asyncio.timeout(2): await generation.wait()
            assert not calling.done() and len(sent)==1
            with pytest.raises(CanonicalActivationUnavailable):
                async with publisher.guard():pytest.fail('Draining admitted another direct call')
            finish.set();assert (await calling).startswith('v=0')
        finally:
            release.set();finish.set();await asyncio.gather(calling,return_exceptions=True)
            await operator.close();await observer.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('commit',[False,True])
def test_provider_waits_for_operator_ready_commit_and_rollback_is_closed(gate,commit):
    import psycopg
    from apps.api.lifetime_memory_activation import ActivationPublication,CanonicalActivationUnavailable
    gate('select public.begin_lifetime_realtime_drain(0);')
    async def scenario():
        operator=await psycopg.AsyncConnection.connect(dsn_for(gate))
        await operator.execute("select public.attest_lifetime_realtime_clearance(1,'synthetic-clearance')")
        entered=asyncio.Event()
        async def admit():
            async with ActivationPublication(dsn_for(gate),authenticated_owner=OWNER).guard():entered.set()
        task=asyncio.create_task(admit())
        observer=await psycopg.AsyncConnection.connect(dsn_for(gate),autocommit=True)
        try:
            async with asyncio.timeout(2):
                while True:
                    row=await (await observer.execute('select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))',(operator.info.backend_pid,))).fetchone()
                    if row[0]:break
            assert not entered.is_set()
            if commit:await operator.commit();await task;assert entered.is_set()
            else:
                await operator.rollback()
                with pytest.raises(CanonicalActivationUnavailable):await task
                assert not entered.is_set()
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await operator.close();await observer.close()
    asyncio.run(scenario())


def test_queued_exclusive_transition_has_no_owner_rollout_lock_cycle(gate):
    import psycopg
    from apps.api.lifetime_memory_activation import RealtimePublication,CanonicalActivationUnavailable
    async def scenario():
        dsn=dsn_for(gate)
        reader=await psycopg.AsyncConnection.connect(dsn)
        owner=await psycopg.AsyncConnection.connect(dsn)
        operator=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        tasks=[]
        try:
            await reader.execute('select stage from public.lifetime_realtime_clearance for share')
            await owner.execute('select 1 from auth.users where id=%s for update',(OWNER,))
            async def direct():
                with pytest.raises(CanonicalActivationUnavailable):
                    async with RealtimePublication(dsn,authenticated_owner=OWNER).guard():pytest.fail('Drain admitted direct call')
            calling=asyncio.create_task(direct());tasks.append(calling)
            async with asyncio.timeout(2):
                while True:
                    row=await (await observer.execute('select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))',(owner.info.backend_pid,))).fetchone()
                    if row[0]:break
            draining=asyncio.create_task(operator.execute('select public.begin_lifetime_realtime_drain(0)'));tasks.append(draining)
            await wait_blocked(observer,operator.info.backend_pid)
            # Drain is queued behind a rollout reader while direct admission is
            # queued behind the adopting owner. Releasing that reader must let
            # drain finish WITHOUT requiring the owner transaction to release.
            # A rollout-first direct reader would keep drain blocked here.
            await reader.rollback()
            async with asyncio.timeout(1):
                await draining
                with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                    await owner.execute('select public.require_lifetime_canonical_clearance()')
                await owner.rollback();await calling
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            for connection in (reader,owner,operator,observer):await connection.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('kind',['collector','lane','job'])
def test_actual_provider_activation_timeout_is_typed_and_releases_guard(monkeypatch,kind):
    import psycopg
    from apps.api.lifetime_memory_activation import CanonicalActivationUnavailable
    closed=[]
    class Database:
        @staticmethod
        async def connect(*args,**kwargs):return Database()
        async def execute(self,statement,args=None):
            if 'provider_activation' in statement:await asyncio.Event().wait()
            async def fetchone():return (10,)
            return SimpleNamespace(fetchone=fetchone)
        async def close(self):closed.append(True)
    monkeypatch.setattr(psycopg,'AsyncConnection',Database)
    publisher,fence=publisher_case(kind,lock_timeout=.01)
    async def run():
        with pytest.raises(CanonicalActivationUnavailable):
            async with publisher.guard(fence):pytest.fail('Clearance timeout admitted request')
    asyncio.run(run());assert closed==[True]


@pytest.mark.parametrize('stream',[False,True])
def test_late_worker_clearance_failure_keeps_fixed_safe_code(monkeypatch,stream):
    import json
    from fastapi.testclient import TestClient
    from apps.api import codex_worker_service as worker
    from apps.api.lifetime_memory_activation import CanonicalActivationUnavailable
    from test_lifetime_memory_engine import fixture
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    class PreflightReady:
        def __init__(self,*args,**kwargs):pass
        @asynccontextmanager
        async def guard(self):yield
    async def denied(*args,**kwargs):raise CanonicalActivationUnavailable()
    monkeypatch.setattr(worker,'ActivationPublication',PreflightReady)
    monkeypatch.setattr(worker.worker,'turn',denied)
    packet,context=fixture()
    payload={'user_id':str(packet.fence.identity.owner_id),'project_id':packet.fence.identity.project_id,
        'agent_role':'collector','model':packet.budget.model,'governed':packet.model_dump(mode='json'),'interview_context':context}
    headers={'X-Codex-Worker-Secret':'synthetic'}
    if stream:headers['Accept']='application/x-ndjson'
    with TestClient(worker.app) as client:result=client.post('/internal/codex/turn',json=payload,headers=headers)
    if stream:
        assert result.status_code==200
        events=[json.loads(line) for line in result.text.splitlines()]
        assert events[0]['type']=='started'
        assert events[-1]=={'type':'error','code':CanonicalActivationUnavailable.code,
            'message':'The response could not be completed or saved. Please try again.'}
    else:
        assert result.status_code==503
        assert result.headers['X-Error-Code']==CanonicalActivationUnavailable.code
    assert 'attestation' not in result.text
