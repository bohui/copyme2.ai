"""Actual API and worker ASGI with real SQL; only app-server model I/O is synthetic."""
import json
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from apps.api import agent_routes,codex_worker_service as worker_module,lifetime_memory_engine as engine_module
from apps.api.codex_runtime import CodexRuntime
from apps.api.main import create_app
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER
from test_name_only_opening import proposal


@pytest.mark.parametrize('recovery',['volume_loss','corrupt','incompatible','restart'])
@pytest.mark.parametrize('execution,streaming',[('worker',False),('worker',True),('inprocess',True)])
def test_actual_engine_seams_cold_recover_and_replay_once(sql,tmp_path,monkeypatch,execution,streaming,recovery):
    command=sql.command
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres")
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic-worker-secret')
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    instances=[];packets=[];admissions=[]
    class ControlledAppServer:
        def __init__(self,command,home,**options):
            self.home=Path(home);self.options=options;instances.append(self)
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return None
        async def request(self,method,params):
            assert method=='thread/start' and params['ephemeral'] is True
            async with self.options['request_admission']():
                admissions.append(method)
                self.packet=json.loads(params['baseInstructions']);packets.append(self.packet)
            return {'thread':{'id':'synthetic-thread-'+str(len(instances))}}
        async def turn(self,thread,prompt,**options):
            async with self.options['request_admission']():admissions.append('turn/start')
            first=len(instances)==1
            result=proposal(mode='reply_only' if first else 'extract',name='Joan' if first else None,
                question='What would you like to share?')
            result['acknowledgement']='Thank you for telling me.'
            result['continuity_updates']=[]
            result['plan']['conversation_phase']='comfort' if first else 'explore'
            raw=json.dumps(result)
            if options.get('on_delta'):await options['on_delta'](raw)
            return raw
    monkeypatch.setattr(worker_module,'CodexConnection',ControlledAppServer)
    monkeypatch.setattr(engine_module,'CodexConnection',ControlledAppServer)
    monkeypatch.setattr(worker_module,'iter_artifacts',lambda *_:pytest.fail('Governed cold execution cannot enumerate old home artifacts'))
    monkeypatch.setattr(worker_module,'worker',worker_module.CodexWorker(home_root=tmp_path/'worker',api_key='synthetic-provider-value',model='gpt-5.6-luna-pooled'))
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    runtime=CodexRuntime(home_root=tmp_path/'api',
        worker_url='http://worker.invalid' if execution=='worker' else None,
        worker_secret='synthetic-worker-secret',worker_transport=httpx.ASGITransport(app=worker_module.app) if execution=='worker' else None)
    runtime.api_key='synthetic-provider-value'
    monkeypatch.setattr(agent_routes,'runtime',runtime)
    headers={'Accept':'application/x-ndjson' if streaming else 'application/json'}
    def result(response):
        assert response.status_code==200,response.text
        if not streaming:return response.json()
        events=[json.loads(line) for line in response.text.splitlines()]
        assert not [event for event in events if event['type']=='error'],events
        return next(event['data'] for event in events if event['type']=='result')
    with TestClient(create_app(MemoryStore())) as client:
        first=result(client.post('/v1/agent/turn',headers=headers,json={'text':'My name is Joan','client_turn_id':str(uuid4())}))
        assert first['conversation_saved']
        if recovery=='volume_loss':
            instances[0].home.rename(tmp_path/'lost-engine-volume')
        elif recovery in {'corrupt','incompatible'}:
            # Existing harness bytes are deliberately unusable and contain a marker
            # that must never enter a fresh canonical packet or model request.
            (instances[0].home/'resume-state.json').write_text('{corrupt private stale marker' if recovery=='corrupt' else '{"schema_version":999,"memory":"private stale marker"}')
        else:
            # A new runtime object simulates application process restart while
            # durable identity, accepted sources and optional old home remain.
            restarted=CodexRuntime(home_root=tmp_path/'api',worker_url=runtime.worker_url,
                worker_secret='synthetic-worker-secret',worker_transport=httpx.ASGITransport(app=worker_module.app) if execution=='worker' else None)
            restarted.api_key='synthetic-provider-value'
            monkeypatch.setattr(agent_routes,'runtime',restarted)
        payload={'project_id':first['project_id'],'text':'Then what?','client_turn_id':str(uuid4())}
        second=result(client.post('/v1/agent/turn',headers=headers,json=payload))
        replay=result(client.post('/v1/agent/turn',headers=headers,json=payload))
        assert replay['cached'] and replay['reply']==second['reply']
    assert len(instances)==2 and instances[0].home!=instances[1].home
    assert packets[0]['identity']==packets[1]['identity']
    assert 'private stale marker' not in json.dumps(packets)
    assert packets[1]['pinned']['chosen_name']=='Joan'
    assert admissions==['thread/start','turn/start','thread/start','turn/start']
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='2'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='2'
