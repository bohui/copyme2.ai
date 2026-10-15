"""Actual API and worker ASGI with real SQL; only app-server model I/O is synthetic."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from apps.api import agent_routes,codex_worker_service as worker_module,lifetime_memory_engine as engine_module
from apps.api.codex_runtime import CodexRuntime
from apps.api.codex_agent import CodexConnection
from apps.api.main import create_app
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER
from test_name_only_opening import proposal


@pytest.mark.parametrize('execution', ['worker', 'inprocess'])
def test_first_visible_ack_precedes_proposal_completion_and_durable_save(sql, tmp_path, monkeypatch, execution):
    command = sql.command
    dsn = sql.publication_dsn or f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', dsn)
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET', 'synthetic-worker-secret')
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.delenv('MEMORY_SPARK_CODEX_WORKER_URL', raising=False)
    calls = []

    async def scenario():
        from psycopg import AsyncConnection
        finish, visible = asyncio.Event(), asyncio.Event()
        async def completed_rounds():
            async with await AsyncConnection.connect(dsn, autocommit=True) as connection:
                return (await (await connection.execute('select count(*) from public.user_completed_round')).fetchone())[0]
        expected = proposal(name='Joan', question='What would you like to share?')
        expected['acknowledgement'] = 'It is good to meet you, Joan.'
        expected['plan']['conversation_phase'] = 'comfort'
        expected['continuity_updates'] = []
        expected['place_journeys'] = []
        expected['plan']['candidates'][0]['context']['historical_clue_id'] = None
        raw = json.dumps(expected)

        class ControlledAppServer(CodexConnection):
            def __init__(self, command, home, **options):
                super().__init__(command, home, **options)
                self.options = options
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def request(self, method, params):
                async with self.options['request_admission'](): pass
                if method == 'thread/start':
                    return {'thread': {'id': 'synthetic-streaming-thread'}}
                thread, turn = params['threadId'], 'synthetic-turn'
                calls.append(thread)
                # Stream the final JSON through its acknowledgement, then
                # withhold all private planning bytes behind the barrier.
                split = raw.index(', "plan"')
                early = raw[:split]
                from jsonschema import validate
                validate(json.loads(raw), params['outputSchema'])
                self.early = [{'method': 'item/agentMessage/delta', 'params': {
                    'threadId': thread, 'turnId': turn, 'itemId': 'early', 'delta': char}} for char in early]
                self.final = [
                    {'method': 'item/agentMessage/delta', 'params': {'threadId': thread,
                        'turnId': turn, 'itemId': 'early', 'delta': raw[split:]}},
                    {'method': 'item/completed', 'params': {'threadId': thread, 'turnId': turn,
                        'item': {'id': 'early', 'type': 'agentMessage', 'phase': 'final_answer', 'text': raw}}},
                    {'method': 'turn/completed', 'params': {'threadId': thread,
                        'turn': {'id': turn, 'status': 'completed'}}},
                ]
                return {'turn': {'id': turn}}
            async def receive(self):
                if self.early: return self.early.pop(0)
                await finish.wait()
                return self.final.pop(0)

        # HTTPX's standard ASGI transport buffers the whole response. This
        # bridge preserves real worker ASGI sends and transport backpressure.
        class WorkerTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                content = await request.aread()
                queue, started = asyncio.Queue(maxsize=1), asyncio.get_running_loop().create_future()
                consumed = False
                async def receive():
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {'type': 'http.request', 'body': content, 'more_body': False}
                    await asyncio.Event().wait()
                async def send(message):
                    if message['type'] == 'http.response.start':
                        started.set_result((message['status'], message['headers']))
                    else:
                        if message.get('body'): await queue.put(message['body'])
                        if not message.get('more_body', False): await queue.put(None)
                scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
                    'http_version': '1.1', 'method': request.method, 'scheme': 'http',
                    'path': request.url.path, 'raw_path': request.url.raw_path,
                    'query_string': b'', 'headers': [(key.lower(), value) for key, value in request.headers.raw],
                    'client': ('127.0.0.1', 1), 'server': ('worker.invalid', 80)}
                task = asyncio.create_task(worker_module.app(scope, receive, send))
                status, headers = await started
                class Body(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        while (chunk := await queue.get()) is not None: yield chunk
                        await task
                    async def aclose(self):
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                return httpx.Response(status, headers=headers, stream=Body())

        monkeypatch.setattr(worker_module, 'CodexConnection', ControlledAppServer)
        monkeypatch.setattr(engine_module, 'CodexConnection', ControlledAppServer)
        monkeypatch.setattr(worker_module, 'worker', worker_module.CodexWorker(
            home_root=tmp_path/'worker', api_key='synthetic', model='gpt-5.6-luna-pooled'))
        monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
        runtime = CodexRuntime(home_root=tmp_path/'api', worker_url='http://worker.invalid' if execution == 'worker' else None,
            worker_secret='synthetic-worker-secret', worker_transport=WorkerTransport() if execution == 'worker' else None)
        runtime.api_key = 'synthetic'
        monkeypatch.setattr(agent_routes, 'runtime', runtime)
        app, events = create_app(MemoryStore()), []
        payload = {'text': 'My name is Joan', 'client_turn_id': str(uuid4()), 'language': 'en-AU'}
        content = json.dumps(payload).encode()
        async def receive(): return {'type': 'http.request', 'body': content, 'more_body': False}
        async def send(message):
            for line in message.get('body', b'').splitlines():
                event = json.loads(line)
                events.append(event)
                if event['type'] == 'text_delta' and event.get('text'): visible.set()
        scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
            'http_version': '1.1', 'method': 'POST', 'scheme': 'http',
            'path': '/api/v1/memoir/agent/turn', 'raw_path': b'/api/v1/memoir/agent/turn',
            'query_string': b'', 'headers': [(b'content-type', b'application/json'), (b'accept', b'application/x-ndjson')],
            'client': ('127.0.0.1', 1), 'server': ('test', 80)}
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(visible.wait(), 10)
            assert not finish.is_set() and not task.done()
            assert ''.join(e['text'] for e in events if e['type'] == 'text_delta') == expected['acknowledgement']
            assert not any(e['type'] in {'conversation_saved', 'result'} for e in events)
            assert await completed_rounds() == 0
            finish.set()
            await asyncio.wait_for(task, 10)
            assert not any(e['type'] == 'error' for e in events)
            saved = next(e['data'] for e in events if e['type'] == 'conversation_saved')
            assert saved['reply'] == ''.join(e['text'] for e in events if e['type'] == 'text_delta')
            assert saved['reply'].count(expected['acknowledgement']) == 1
            assert saved['reply'].endswith('What would you like to share?')
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                replay = (await client.post('/api/v1/memoir/agent/turn', json={**payload, 'project_id': saved['project_id']})).json()
            assert replay['cached'] and replay['reply'] == saved['reply'] and len(calls) == 1
            assert await completed_rounds() == 1
        finally:
            finish.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


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
