import json
from uuid import uuid4
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api import agent_routes
from apps.api.codex_runtime import CodexRuntime
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER
from test_shared_memory_events_postgres import rpc,literal
from test_name_only_opening import proposal


@pytest.mark.parametrize('streaming',[True,False])
def test_real_governed_http_save_cold_replay_preserves_identity_and_lease(sql,tmp_path,monkeypatch,streaming):
    command=sql.command
    dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true');monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',dsn)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS','1')
    calls=[]
    output=proposal(name='Joan',question='What would you like to share?');output['plan']['conversation_phase']='comfort'
    def provider(request):
        body=json.loads(request.content);calls.append(body)
        assert body['governed']['fence']['identity']['owner_id']==OWNER
        assert body['memories']==[] and body['profile']=={} and body['text']=='' and body['thread_id'] is None
        raw=json.dumps(output)
        if request.headers.get('accept')!='application/x-ndjson':
            return httpx.Response(200,json={'reply':raw,'thread_id':'synthetic-governed','artifacts':[]})
        return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},content='\n'.join(json.dumps(x) for x in [
            {'type':'text_delta','text':raw},{'type':'result','data':{'reply':raw,'thread_id':'synthetic-governed','artifacts':[]}}])+'\n')
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    from apps.api.main import create_app
    app=create_app(MemoryStore())
    headers={'Accept':'application/x-ndjson' if streaming else 'application/json'}
    turn=str(uuid4());payload={'client_turn_id':turn,'text':'My name is Joan','language':'en-AU'}
    with TestClient(app) as client:
        first=client.post('/v1/agent/turn',headers=headers,json=payload)
        assert first.status_code==200,first.text
        if streaming:
            events=[json.loads(line) for line in first.text.splitlines()]
            assert not [e for e in events if e['type']=='error'],events
            result=next(e['data'] for e in events if e['type']=='result')
        else:result=first.json()
        assert result['conversation_saved'] and result['accepted_source_id']
        assert result['reply'].endswith('What would you like to share?')
        payload['project_id']=result['project_id']
        monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
        retry=client.post('/v1/agent/turn',headers=headers,json=payload)
        if streaming:replayed=next(json.loads(line)['data'] for line in retry.text.splitlines() if json.loads(line)['type']=='result')
        else:replayed=retry.json()
        assert replayed['cached'] and replayed['reply']==result['reply']
        conflict=client.post('/v1/agent/turn',headers=headers,json={**payload,'text':'Different narrator input'})
        if streaming:assert any(json.loads(line)['type']=='error' for line in conflict.text.splitlines())
        else:assert conflict.status_code>=400
        monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS','999')
        paused=client.post('/v1/agent/turn',json={**payload,'client_turn_id':str(uuid4())})
        assert paused.status_code==503 and paused.headers['X-Error-Code']=='LIFETIME_GENERATION_PAUSED'
    assert len(calls)==1
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip()=='0'


def test_oversized_input_rejected_before_source_acceptance(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_runtime import run_lifetime_turn,LifetimePublicationContext
    from apps.api.lifetime_memory_context import InputLimitExceeded
    import asyncio
    storage=PostgresRest(sql,OWNER).storage()
    with pytest.raises(InputLimitExceeded):
        asyncio.run(run_lifetime_turn(None,storage,'中'*6000,publication=LifetimePublicationContext()))
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'
    storage.client.close()


def test_real_http_literal_privacy_name_commitment_survive_checkpoint_cold_turn(sql,tmp_path,monkeypatch):
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true');monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    packets=[]
    def provider(request):
        body=json.loads(request.content);packet=json.loads(body['governed']['packet']);packets.append(packet)
        response=proposal(name='Joan' if len(packets)==1 else None,question='What can you tell me about the garden?')
        response['plan']['conversation_phase']='comfort' if len(packets)==1 else 'explore'
        if len(packets)>1:
            response['plan']['work']={'mode':'extract','name':None};response['acknowledgement']='We can return to the garden.'
        if len(packets)==2:
            assert any('school' in value.lower() for value in packet['pinned']['excluded_topics'])
        if len(packets)==3:
            assert packet['checkpoint']['coverage_end']>2
            assert packet['pinned']['chosen_name']=='Joan'
            assert any('school' in value.lower() for value in packet['pinned']['excluded_topics'])
            assert any('garden' in item['data']['text'] for item in packet['pinned']['known_continuity'] if item['kind']=='commitment')
        return httpx.Response(200,json={'thread_id':f'synthetic-{len(packets)}','reply':json.dumps(response),'artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    from apps.api.main import create_app
    app=create_app(MemoryStore())
    with TestClient(app) as client:
        first=client.post('/v1/agent/turn',json={'text':'My name is Joan','client_turn_id':str(uuid4())})
        assert first.status_code==200,first.text
        project=first.json()['project_id']
        second=client.post('/v1/agent/turn',json={'project_id':project,'text':"Don't discuss my school. I'll return to the garden later.",'client_turn_id':str(uuid4())})
        assert second.status_code==200,second.text
        sql(__import__('test_agent_commit_postgres').as_user(f"""do $do$ begin for n in 1..35 loop
          perform public.accept_user_narrator_source('{project}',gen_random_uuid(),repeat('A synthetic ordinary garden recollection. ',40));
        end loop;end $do$;"""))
        third=client.post('/v1/agent/turn',json={'project_id':project,'text':'Then what?','client_turn_id':str(uuid4())})
        assert third.status_code==200,third.text
    assert len(packets)==3
    assert sql('select count(*) from public.user_lifetime_continuity;').stdout.strip()=='2'


@pytest.mark.parametrize('streaming',[True,False])
def test_correction_after_provider_admission_blocks_old_text_and_commit(sql,tmp_path,monkeypatch,streaming):
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true');monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    output=proposal(name='Joan',question='What would you like to share?');output['acknowledgement']='Private old answer about Joan.'
    def provider(request):
        body=json.loads(request.content);packet=json.loads(body['governed']['packet'])
        source=packet['current']['narrator'];project=packet['identity']['project_id']
        rpc(sql,'change_user_narrator_source',f"'{project}','{source['source_id']}',1,'withdraw',null")
        raw=json.dumps(output)
        if not streaming:return httpx.Response(200,json={'reply':raw,'thread_id':'stale-thread','artifacts':[]})
        return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},content='\n'.join(json.dumps(x) for x in [
            {'type':'text_delta','text':raw},{'type':'result','data':{'reply':raw,'thread_id':'stale-thread','artifacts':[]}}])+'\n')
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    from apps.api.main import create_app
    app=create_app(MemoryStore())
    with TestClient(app) as client:
        response=client.post('/v1/agent/turn',headers={'Accept':'application/x-ndjson' if streaming else 'application/json'},json={'text':'My name is Joan','client_turn_id':str(uuid4())})
        assert 'Private old answer' not in response.text
        if streaming:assert '"type":"error"' in response.text
        else:assert response.status_code in {409,503}
    assert sql('select count(*) from public.user_memory;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_narrator_source where status=\'withdrawn\';').stdout.strip()=='1'


def test_active_privacy_byte_overflow_retains_source_without_provider_and_retry_recovers(sql,tmp_path,monkeypatch):
    from test_agent_commit_postgres import as_user
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true');monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    exclusions=['private forbidden subject '+str(n)+' '+('x'*100) for n in range(200)]
    sql(as_user(f"insert into public.user_profile(user_id,profile) values(auth.uid(),{literal({'memory_preferences':{'excluded_topics':exclusions}})}::jsonb) on conflict(user_id) do update set profile=excluded.profile;"))
    calls=[]
    def provider(request):
        calls.append(request)
        return httpx.Response(200,json={'thread_id':'recovered-policy','reply':json.dumps(proposal(name='Joan',question='What would you like to share?')),'artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    from apps.api.main import create_app
    app=create_app(MemoryStore())
    payload={'project_id':identity['project_id'],'client_turn_id':str(uuid4()),'text':'My name is Joan'}
    with TestClient(app) as client:
        pending=client.post('/v1/agent/turn',json=payload)
        assert pending.status_code==503 and pending.json()['detail']['state']=='source_accepted',pending.text
        assert pending.json()['detail']['accepted_source_id'] and calls==[]
        assert 'private forbidden subject' not in pending.text
        sql(as_user("update public.user_profile set profile=jsonb_set(profile,'{memory_preferences}','{}');"))
        recovered=client.post('/v1/agent/turn',json=payload)
        assert recovered.status_code==200 and recovered.json()['conversation_saved'],recovered.text
    assert len(calls)==1 and sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'


@pytest.mark.parametrize('text,kind',[
    ("I don't want to discuss my school",'excluded_topics'),
    ("Let's set aside my school for now",'paused_topics'),
    ('我们先不聊学校','paused_topics'),
    ('Don’t discuss my school','excluded_topics'),
    ('我不想再提学校','excluded_topics'),
])
def test_literal_privacy_variants_persist_before_http_provider(sql,tmp_path,monkeypatch,text,kind):
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true');monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    calls=[]
    def provider(request):
        packet=json.loads(json.loads(request.content)['governed']['packet']);calls.append(packet)
        assert text in packet['pinned'][kind]
        result=proposal(mode='extract',name=None,question='What would you like to share?')
        result['acknowledgement']='We can choose another memory.'
        return httpx.Response(200,json={'thread_id':'privacy-variant','reply':json.dumps(result),'artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    from apps.api.main import create_app
    app=create_app(MemoryStore())
    with TestClient(app) as client:
        response=client.post('/v1/agent/turn',json={'text':text,'client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
    assert len(calls)==1


@pytest.mark.parametrize('language',['en-AU','zh-CN'])
@pytest.mark.parametrize('streaming',[False,True])
def test_mapped_greeting_preserves_explicit_phase_without_acceptance_or_model(sql,tmp_path,monkeypatch,language,streaming):
    from test_agent_commit_postgres import as_user
    from apps.api.main import create_app
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    rpc(sql,'change_user_conversation_phase',f"'{identity['project_id']}','shape',0")
    sql(as_user(f"insert into public.user_profile(user_id,profile) values(auth.uid(),{literal({'preferred_language':language})}::jsonb) on conflict(user_id) do update set profile=excluded.profile;"))
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    def provider(request):raise AssertionError('Bounded greeting cannot call the provider')
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    with TestClient(create_app(MemoryStore())) as client:
        response=client.post('/v1/agent/greeting',headers={'Accept':'application/x-ndjson' if streaming else 'application/json'},json={'project_id':identity['project_id'],'action':'continue','language':language})
        assert response.status_code==200,response.text
        result=next(json.loads(line)['data'] for line in response.text.splitlines() if json.loads(line)['type']=='result') if streaming else response.json()
        assert result['conversation_phase']['phase']=='shape'
        assert result['conversation_phase']['selection']=='explicit'
        assert 'paused' not in result['conversation_phase']
        assert bool(result['reply'])
        assert not result['conversation_saved']
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_large_single_event_keeps_real_http_turn_bounded_and_resumable(sql,tmp_path,monkeypatch):
    from test_lifetime_event_context import seed_large_event
    from apps.api.main import create_app
    identity,_=seed_large_event(sql)
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    packets=[]
    def provider(request):
        body=json.loads(request.content)
        packet=json.loads(body['governed']['packet']);packets.append(packet)
        assert packet['input_tokens_upper_bound']<=body['governed']['budget']['input_budget']
        assert 'private private private' not in body['governed']['packet']
        response=proposal(name=None,question='What do you remember about school?')
        response['plan']['work']={'mode':'extract','name':None}
        response['plan']['conversation_phase']='explore'
        return httpx.Response(200,json={'reply':json.dumps(response),'thread_id':'bounded-large-event','artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    payload={'project_id':identity['project_id'],'client_turn_id':str(uuid4()),'text':'What happened at school?'}
    with TestClient(create_app(MemoryStore())) as client:
        for _ in range(12):
            result=client.post('/v1/agent/turn',json=payload)
            if result.status_code==200:break
            assert result.status_code==503,result.text
            assert result.headers['X-Error-Code']=='LIFETIME_MAINTENANCE_PENDING'
        assert result.status_code==200,result.text
        assert result.json()['conversation_saved']
    assert len(packets)==1
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1101'


def test_accepted_source_survives_provider_failure_then_exact_retry(sql,tmp_path,monkeypatch):
    from apps.api.main import create_app
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    calls=[]
    def provider(request):
        calls.append(json.loads(request.content))
        if len(calls)==1:return httpx.Response(503,json={'detail':'synthetic provider unavailable'})
        response=proposal(name='Joan',question='Where would you like to begin?')
        response['plan']['conversation_phase']='comfort'
        return httpx.Response(200,json={'reply':json.dumps(response),'thread_id':'recovered-provider','artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    payload={'project_id':identity['project_id'],'client_turn_id':str(uuid4()),'text':'My name is Joan'}
    with TestClient(create_app(MemoryStore()),raise_server_exceptions=False) as client:
        failed=client.post('/v1/agent/turn',json=payload)
        assert failed.status_code>=400
        receipt=client.get('/v1/agent/turns/'+payload['client_turn_id'],params={'project_id':identity['project_id']})
        assert receipt.status_code==200,receipt.text
        assert receipt.json()['state']=='source_accepted' and not receipt.json()['conversation_saved']
        retry=client.post('/v1/agent/turn',json=payload)
        assert retry.status_code==200,retry.text
        replay=client.post('/v1/agent/turn',json=payload)
        assert replay.status_code==200 and replay.json()['cached']
    assert len(calls)==2
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='1'
