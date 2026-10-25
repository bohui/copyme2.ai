"""Only the exact authoritative pending-policy sentinel changes error handling."""
import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import httpx
import psycopg
import pytest

from apps.api.lifetime_memory_policy import PolicyUnavailable, is_policy_pending


class DatabaseError(psycopg.Error):
    def __init__(self, code='55000', primary='LIFETIME_POLICY_PENDING'):
        super().__init__('Private statement text must never classify or escape')
        self.sqlstate=code
        self.primary=primary
    @property
    def diag(self):return SimpleNamespace(message_primary=self.primary)


@pytest.mark.parametrize('code,message,expected',[
    ('55000','LIFETIME_POLICY_PENDING',True),
    ('42501','LIFETIME_POLICY_PENDING',False),
    ('40001','LIFETIME_POLICY_PENDING',False),
    ('55000','LIFETIME_POLICY_PENDING extra private details',False),
    ('55000','stale lifetime fence',False),
    ('55000','Publication owner mismatch',False),
    ('55000',' LIFETIME_POLICY_PENDING',False),
])
def test_sql_pending_classifier_requires_exact_primary_diagnostic(code,message,expected):
    assert is_policy_pending(DatabaseError(code,message)) is expected


@pytest.mark.parametrize('body,expected',[
    ({'code':'55000','message':'LIFETIME_POLICY_PENDING'},True),
    ({'code':'40001','message':'LIFETIME_POLICY_PENDING'},False),
    ({'code':'55000','message':'LIFETIME_POLICY_PENDING private'},False),
    ({'code':'55000','message':'foreign owner'},False),
    ({'code':55000,'message':'LIFETIME_POLICY_PENDING'},False),
    (None,False),([],False),('LIFETIME_POLICY_PENDING',False),
])
def test_postgrest_pending_classifier_requires_exact_json(body,expected):
    response=httpx.Response(400,content=json.dumps(body).encode(),request=httpx.Request('POST','http://database.invalid/rpc'))
    error=httpx.HTTPStatusError('Private request',request=response.request,response=response)
    assert is_policy_pending(error) is expected


@pytest.mark.parametrize('error',[
    RuntimeError('LIFETIME_POLICY_PENDING'), TimeoutError('LIFETIME_POLICY_PENDING'),
    SimpleNamespace(sqlstate='55000',diag=SimpleNamespace(message_primary='LIFETIME_POLICY_PENDING')),
])
def test_generic_errors_are_never_blessed_as_policy_pending(error):
    assert not is_policy_pending(error)


@pytest.mark.parametrize('body',[b'',b'not json',b'{'])
def test_unparseable_provider_503_is_not_policy_pending(body):
    response=httpx.Response(503,content=body,request=httpx.Request('POST','http://provider.invalid'))
    assert not is_policy_pending(httpx.HTTPStatusError('LIFETIME_POLICY_PENDING',request=response.request,response=response))


@pytest.mark.parametrize('kind',['collector','lane','job','saved','read'])
@pytest.mark.parametrize('pending',[False,True])
def test_actual_publication_guards_preserve_only_authoritative_policy_pending(monkeypatch,kind,pending):
    from test_lifetime_realtime_clearance import publisher_case
    closed=[];calls=[]
    class Database:
        @staticmethod
        async def connect(*args,**kwargs):return Database()
        async def execute(self,statement,args=None):
            calls.append(statement)
            if 'publication(' in statement:raise DatabaseError('55000' if pending else '40001')
        async def close(self):closed.append(True)
    monkeypatch.setattr(psycopg,'AsyncConnection',Database)
    if kind=='saved':
        from apps.api.lifetime_memory_publication import TransactionalPublication
        from test_lifetime_memory_engine import FENCE as fence
        publisher=TransactionalPublication('synthetic-only',authenticated_owner=fence.identity.owner_id)
    elif kind=='read':
        from apps.api.lifetime_memory_reads import ReadPublication
        from test_lifetime_memory_reads import FENCE as fence, OWNER
        publisher=ReadPublication('synthetic-only',authenticated_owner=OWNER)
    else:
        publisher,fence=publisher_case(kind)
    async def run():
        with pytest.raises(Exception) as caught:
            async with publisher.guard(fence):pytest.fail('Pending policy admitted content')
        assert isinstance(caught.value,PolicyUnavailable) is pending
        if pending:assert 'Private' not in str(caught.value)
    asyncio.run(run())
    assert closed==[True]
    assert not any('provider_activation' in statement for statement in calls)


def test_already_verified_policy_exception_is_safe_and_idempotent():
    assert is_policy_pending(PolicyUnavailable())
    assert PolicyUnavailable.code == "LIFETIME_POLICY_PENDING"


@pytest.mark.parametrize('stream',[False,True])
def test_worker_policy_error_uses_fixed_code_without_untrusted_fields(monkeypatch,stream):
    from fastapi.testclient import TestClient
    from apps.api import codex_worker_service as worker
    from test_lifetime_memory_engine import fixture
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    class Ready:
        def __init__(self,*args,**kwargs):pass
        @asynccontextmanager
        async def guard(self):yield
    async def denied(*args,**kwargs):
        error=PolicyUnavailable()
        error.trajectory={'private':'Accepted original source'}
        raise error
    monkeypatch.setattr(worker,'ActivationPublication',Ready)
    monkeypatch.setattr(worker.worker,'turn',denied)
    packet,context=fixture()
    payload={'user_id':str(packet.fence.identity.owner_id),'project_id':packet.fence.identity.project_id,
        'agent_role':'collector','model':packet.budget.model,'governed':packet.model_dump(mode='json'),'interview_context':context}
    headers={'X-Codex-Worker-Secret':'synthetic'}
    if stream:headers['Accept']='application/x-ndjson'
    with TestClient(worker.app) as client:response=client.post('/internal/codex/turn',json=payload,headers=headers)
    if stream:
        events=[json.loads(line) for line in response.text.splitlines()]
        assert events[-1]=={'type':'error','code':PolicyUnavailable.code,
            'message':'The response could not be completed or saved. Please try again.'}
    else:
        assert response.status_code==503
        assert response.headers['X-Error-Code']==PolicyUnavailable.code
        assert response.headers['Retry-After']=='60'
    assert 'Accepted original source' not in response.text


@pytest.mark.parametrize('kind',['lane','job'])
@pytest.mark.parametrize('status,code,expected',[
    (503,'LIFETIME_POLICY_PENDING',True),(502,'LIFETIME_POLICY_PENDING',False),
    (503,'LIFETIME_POLICY_PENDING extra',False),(503,'PROVIDER_UNAVAILABLE',False),
])
def test_bounded_worker_policy_wire_is_exact(monkeypatch,kind,status,code,expected):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    from test_lifetime_memory_lane_engine import Publisher
    if kind=='lane':
        from test_lifetime_memory_lane_engine import transport
        from apps.api.lifetime_memory_lane_engine import send_bounded_lane_request as sender
    else:
        from test_lifetime_memory_job_engine import transport
        from apps.api.lifetime_memory_job_engine import send_bounded_job_request as sender
    async def response(request):return httpx.Response(status,headers={'X-Error-Code':code},text='Private untrusted error')
    with pytest.raises(Exception) as caught:
        asyncio.run(sender(worker_url='http://worker.invalid',worker_secret='synthetic',
            **{'bounded_'+kind:transport()},publisher=Publisher(),worker_transport=httpx.MockTransport(response)))
    assert isinstance(caught.value,PolicyUnavailable) is expected
    if not expected:assert isinstance(caught.value,httpx.HTTPStatusError)


def test_successful_postgrest_body_is_not_an_authority_error():
    response=httpx.Response(200,json={'code':'55000','message':PolicyUnavailable.code},
        request=httpx.Request('POST','http://database.invalid/rpc'))
    assert not is_policy_pending(httpx.HTTPStatusError('not an error status',request=response.request,response=response))


@pytest.mark.parametrize('stream',[False,True])
@pytest.mark.parametrize('code,expected',[(PolicyUnavailable.code,True),('LIFETIME_POLICY_PENDING private',False)])
def test_collector_worker_policy_transport_preserves_only_fixed_code(tmp_path,monkeypatch,stream,code,expected):
    from apps.api.codex_runtime import CodexRuntime
    from apps.api import lifetime_memory_publication as publication
    from test_lifetime_memory_engine import fixture, BUDGET, FakePublisher
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.delenv('MEMORY_SPARK_COLLECTOR_MODEL',raising=False)
    monkeypatch.setattr(publication,'ProviderPublication',lambda *args,**kwargs:FakePublisher())
    async def respond(request):
        if stream:
            return httpx.Response(200,content=json.dumps({'type':'error','code':code,
                'message':'Private untrusted error','trajectory':{'private':'original testimony'}})+'\n',
                headers={'Content-Type':'application/x-ndjson'})
        return httpx.Response(503,headers={'X-Error-Code':code},text='Private untrusted error')
    runtime=CodexRuntime(home_root=tmp_path,model=BUDGET.model,worker_url='http://worker.invalid',
        worker_secret='synthetic',worker_transport=httpx.MockTransport(respond))
    packet,context=fixture()
    async def delta(text):pytest.fail('No text may escape failed policy admission')
    with pytest.raises(Exception) as caught:
        asyncio.run(runtime._worker_turn(user_id=str(packet.fence.identity.owner_id),prior=None,
            memories=[],profile={},place_journey=None,family_enabled=False,family_context=None,
            project_id=packet.fence.identity.project_id,text='',language='en-AU',
            governed=packet.model_dump(mode='json'),interview_context=context,on_delta=delta if stream else None))
    assert isinstance(caught.value,PolicyUnavailable) is expected
    if expected:
        assert not hasattr(caught.value,'trajectory')
        assert 'Private' not in str(caught.value)


from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database as base_database


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True)


def test_real_sql_pending_policy_reaches_collector_saved_and_read_guards(sql):
    from test_agent_commit_postgres import OWNER, OLD, as_user
    from test_shared_memory_events_postgres import rpc, literal
    from apps.api.lifetime_memory_publication import ProviderPublication, TransactionalPublication
    from apps.api.lifetime_memory_reads import ReadPublication
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    rpc(sql,'accept_user_interview_turn',f"{literal(identity['project_id'])},'00000000-0000-4000-8000-000000000870','I remember the kitchen.'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    read_fence=rpc(sql,'capture_lifetime_read_fence',literal(identity['project_id']))
    # An explicit synthetic inventory blocker stands in for incomplete historic
    # policy review. Current authority remains valid; only policy readiness fails.
    sql(f"insert into public.user_lifetime_policy_inventory_pending values('{OWNER}',{literal(identity['project_id'])},'{identity['conversation_id']}','semantic-v1');")
    dsn=sql.publication_dsn
    async def run():
        for factory,snapshot in ((ProviderPublication,fence),(TransactionalPublication,fence),(ReadPublication,read_fence)):
            with pytest.raises(PolicyUnavailable) as caught:
                async with factory(dsn,authenticated_owner=OWNER).guard(snapshot):
                    pytest.fail('Incomplete policy admitted private bytes')
            assert is_policy_pending(caught.value)
    asyncio.run(run())
