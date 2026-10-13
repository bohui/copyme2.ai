"""Canonical provider authority, cancellation and safe error transports."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from test_agent_commit_postgres import OWNER

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
def test_every_provider_admission_rechecks_authority_after_publication(monkeypatch, kind, closed):
    import psycopg
    from apps.api.lifetime_memory_activation import CanonicalActivationUnavailable
    calls = []; released = []
    class Database:
        @staticmethod
        async def connect(*args, **kwargs): return Database()
        async def execute(self, statement, args=None):
            calls.append(statement)
            if 'provider_activation' in statement and closed:
                raise psycopg.errors.ObjectNotInPrerequisiteState('private authority diagnostics must not escape')
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


def test_saved_publication_does_not_require_new_generation_authority(monkeypatch):
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


def test_authority_acquisition_timeout_is_fixed_but_send_cancellation_is_preserved(monkeypatch):
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
def test_worker_missing_provider_authority_rejects_before_stream_starts(monkeypatch, stream, kind):
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
    assert result.headers['X-Error-Code']=='LIFETIME_PROVIDER_AUTHORITY_UNAVAILABLE'
    assert 'started' not in result.text


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
            async with publisher.guard(fence):pytest.fail('Authority timeout admitted request')
    asyncio.run(run());assert closed==[True]


@pytest.mark.parametrize('stream',[False,True])
def test_late_worker_authority_failure_keeps_fixed_safe_code(monkeypatch,stream):
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
