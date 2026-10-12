import json
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
from apps.api import agent_routes,supabase_routes
from apps.api.codex_runtime import CodexRuntime
from apps.api.main import create_app
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER
from test_shared_memory_events_postgres import rpc,literal
from test_name_only_opening import proposal


def configure(sql,monkeypatch,tmp_path,provider):
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    def storage(_):
        result=PostgresRest(sql,OWNER).storage()
        result.all_memories=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Mapped accounts cannot load legacy user-wide memory'))
        return result
    monkeypatch.setattr(agent_routes,'authenticated_storage',storage)
    monkeypatch.setattr(supabase_routes,'storage',storage)
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))


def test_direct_mapping_when_flag_false_cannot_open_legacy_generation_or_cache(sql,monkeypatch,tmp_path):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
    configure(sql,monkeypatch,tmp_path,lambda _:(_ for _ in ()).throw(AssertionError('Generation disabled')))
    with TestClient(create_app(MemoryStore()),raise_server_exceptions=False) as client:
        response=client.post('/v1/agent/turn',json={'project_id':identity['project_id'],'text':'A new memory','client_turn_id':str(uuid4())})
        assert response.status_code==503,response.text
        assert response.headers['X-Error-Code']=='LIFETIME_GENERATION_PAUSED'
        history=client.get(f"/v1/user/projects/{identity['project_id']}/history")
        assert history.status_code==200,history.text
        legacy=client.get('/v1/user/memories')
        assert legacy.status_code==409,legacy.text
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'


def test_flag_rollback_preserves_saved_receipts_and_current_withdrawal_fence(sql,monkeypatch,tmp_path):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    calls=[]
    def provider(request):
        calls.append(json.loads(request.content))
        result=proposal(name='Joan',question='Where would you like to begin?');result['plan']['conversation_phase']='comfort'
        return httpx.Response(200,json={'reply':json.dumps(result),'thread_id':'saved-before-rollback','artifacts':[]})
    configure(sql,monkeypatch,tmp_path,provider)
    turn=str(uuid4())
    with TestClient(create_app(MemoryStore()),raise_server_exceptions=False) as client:
        saved=client.post('/v1/agent/turn',json={'text':'My name is Joan','client_turn_id':turn})
        assert saved.status_code==200,saved.text
        project=saved.json()['project_id']
        monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
        replay=client.post('/v1/agent/turn',json={'project_id':project,'text':'My name is Joan','client_turn_id':turn})
        assert replay.status_code==200 and replay.json()['cached'],replay.text
        rpc(sql,'change_user_narrator_source',f"{literal(project)},'{saved.json()['accepted_source_id']}',1,'withdraw',null")
        receipt=client.get('/v1/agent/turns/'+turn,params={'project_id':project})
        assert receipt.status_code==200 and receipt.json()['reply'] is None,receipt.text
        profile=client.get('/v1/agent/profile')
        assert profile.status_code==200 and profile.json()['name'] is None,profile.text
    assert len(calls)==1
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'


def test_direct_legacy_commit_is_rejected_after_canonical_adoption(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    from test_agent_commit_postgres import OLD,as_user
    rpc(sql,'acquire_user_agent_turn_lease',f"'{OLD}'")
    blocked=rpc(sql,'commit_user_agent_turn',f"'{OLD}','old-thread','Old reply',array[]::text[],null,{literal(identity['project_id'])},'{uuid4()}',false,'unplaced'",check=False)
    assert blocked.returncode!=0 and 'governed atomic commit required' in blocked.stderr
    denied=sql(as_user(f"select public.commit_user_agent_turn_before_lifetime_adoption('{OLD}','old-thread','Old reply');"),check=False)
    assert denied.returncode!=0 and 'permission denied' in denied.stderr
    assert sql('select count(*) from public.user_memory;').stdout.strip()=='0'


def test_legacy_outer_send_serializes_adoption_and_drops_queued_old_body(sql):
    import asyncio
    import psycopg
    from apps.api.lifetime_memory_legacy import LegacyPublication,LegacyStreamingResponse,LegacyMappingConflict
    command=sql.command
    dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();adopted=asyncio.Event();sent=[]
        async def chunks():
            yield b'first legacy output'
            await adopted.wait()
            yield b'stale private queued output'
        app=create_app(MemoryStore())
        @app.get('/legacy-adoption-boundary')
        async def route():return LegacyStreamingResponse(chunks(),publisher=LegacyPublication(dsn,authenticated_owner=OWNER))
        async def send(message):
            if message['type']=='http.response.body' and message.get('body')==b'first legacy output':
                entered.set();await release.wait()
            sent.append(message)
        async def receive():await asyncio.Event().wait()
        scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1','method':'GET','scheme':'http',
          'path':'/legacy-adoption-boundary','raw_path':b'/legacy-adoption-boundary','query_string':b'','headers':[],
          'client':('127.0.0.1',1234),'server':('test',80)}
        sending=asyncio.create_task(app(scope,receive,send))
        connection=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        try:
            async with asyncio.timeout(3):await entered.wait()
            await connection.execute('set role authenticated')
            await connection.execute("select set_config('request.jwt.claim.sub',%s,false)",(OWNER,))
            adopting=asyncio.create_task(connection.execute('select public.resolve_lifetime_conversation(null)'))
            async with asyncio.timeout(1):
                while True:
                    blocked=await (await observer.execute('select cardinality(pg_blocking_pids(%s))',(connection.info.backend_pid,))).fetchone()
                    if blocked[0]:break
                    assert not adopting.done()
            release.set();await adopting;adopted.set()
            try:await sending
            except LegacyMappingConflict:pass
            else:raise AssertionError('Old queued output must be rejected after adoption')
            assert not any(b'stale private' in message.get('body',b'') for message in sent)
        finally:
            release.set();adopted.set();sending.cancel()
            await asyncio.gather(sending,return_exceptions=True)
            await connection.close();await observer.close()
    asyncio.run(scenario())


# The same isolated SQL authority must fence both production dispatch modes.
import pytest


@pytest.mark.parametrize('mode',['in_process','worker'])
def test_legacy_runtime_actual_admission_rejects_intervening_adoption(sql,monkeypatch,tmp_path,mode):
    import asyncio
    from types import SimpleNamespace
    import apps.api.codex_runtime as module
    from apps.api.codex_agent import CodexConnection
    from apps.api.lifetime_memory_legacy import LegacyMappingConflict
    command=sql.command
    dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',dsn)
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
    writes=[]
    async def adopt():
        identity=await asyncio.to_thread(rpc,sql,'resolve_lifetime_conversation','null')
        assert identity['outcome']=='resolved'
    class Connection(CodexConnection):
        async def __aenter__(self):
            await adopt()
            async def drain():pass
            self.process=SimpleNamespace(stdin=SimpleNamespace(write=writes.append,drain=drain))
            return self
        async def __aexit__(self,*args):pass
        async def request(self,method,params):
            await self.send({'method':method,'params':params})
            raise AssertionError('Adopted legacy request reached the application-server pipe')
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self,request):
            await adopt()
            writes.append(await request.aread())
            raise AssertionError('Adopted legacy request body reached worker transport')
    monkeypatch.setattr(module,'CodexConnection',Connection)
    runtime=module.CodexRuntime(home_root=tmp_path/'homes',
        worker_url='http://controlled.invalid' if mode=='worker' else None,
        worker_secret='synthetic',worker_transport=Transport())
    with pytest.raises(LegacyMappingConflict):
        asyncio.run(runtime._resolve_language(OWNER,'Synthetic original','en-AU'))
    assert writes==[]
