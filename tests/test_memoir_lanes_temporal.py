"""Real Temporal/PostgreSQL/private-worker integration; provider is controlled."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from test_shared_memory_events_postgres import (
    database, attachment_database, private_database, event_database, sql,
    rpc, OWNER, TURN, ROOT,
)
from memoir_postgres_workflow import PostgresRest
import pytest


@pytest.mark.parametrize('skill',['timeline','composer'])
def test_real_worker_and_temporal_coalesce_busy_lane_to_latest_available_inputs(sql,tmp_path,monkeypatch,skill):
    from test_shared_memory_events_postgres import five_rounds,add_rounds,extract,service_rpc,literal,as_user
    from test_agent_commit_postgres import OLD
    from apps.api.codex_worker_service import CodexWorker,WorkerTurnInput
    from apps.api.memory_event_worker import MemoirLaneBroker,MemoryEventWorker
    from apps.api.temporal_workflows import MemoirSkillLane
    from scripts.task_runtime import dispatch_memoir_lanes_once
    if skill=='composer':
        sources,lanes=five_rounds(sql)
        lane=lanes['composer_lane_id']
    else:
        sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
        source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','First original.'")
        sources=[source]
        lane=None
    gate=tmp_path/'hold-provider'
    gate.touch()
    calls=tmp_path/'calls.jsonl'
    control=tmp_path/'provider.json'
    control.write_text(json.dumps({'mode':skill,'reply':{'events':[]},'calls':str(calls),
        'hold_phase':'draft' if skill=='composer' else 'timeline','gate':str(gate)}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    provider=CodexWorker(home_root=tmp_path/'worker-homes',command=[sys.executable,str(ROOT/'tests/fixtures/issue6_controlled_app_server.py'),str(control)])
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput): return await provider.turn(payload)
    async def scenario():
        async def readiness_connection(reader,writer):
            writer.close()
            await writer.wait_closed()
        readiness=await asyncio.start_server(readiness_connection,'127.0.0.1',0)
        provider.base_url=f'http://127.0.0.1:{readiness.sockets[0].getsockname()[1]}/v1'
        options={'download_dest_dir':'/tmp/memoir-issue6-temporal','dev_server_database_filename':str(tmp_path/'temporal.sqlite'),'ip':'127.0.0.1','ui':False}
        async with await WorkflowEnvironment.start_local(**options) as env:
            async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql,OWNER,service=True).handle)) as client:
                broker=MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic-service',client=client)
                worker=MemoryEventWorker(broker,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.ASGITransport(app=app))
                outcomes=[]
                @activity.defn(name='memoir.execute_lane')
                async def execute(lane_id:str):
                    result=await worker.execute_lane(lane_id)
                    state=await broker.rpc('read_memoir_lane_state',p_lane_id=lane_id)
                    outcomes.append((lane_id,result['status'],state['covered_round'],state['successful_source']))
                    return {'status':result['status'],'pending':state['pending']}
                async with Worker(env.client,task_queue='issue6-coalesce',workflows=[MemoirSkillLane],activities=[execute]):
                    handles=await dispatch_memoir_lanes_once(env.client,broker,'issue6-coalesce')
                    selected=next(h for h in handles if lane is None or h.id=='memoir-lane:'+lane)
                    lane_id=selected.id.removeprefix('memoir-lane:')
                    async def held():
                        while not calls.exists() or not any(json.loads(l)['phase'].endswith('_held') for l in calls.read_text().splitlines()):
                            await asyncio.sleep(.05)
                    await asyncio.wait_for(held(),15)
                    for start,end in ([(2,10),(11,15),(16,20)] if skill=='timeline' else [(6,10),(11,15),(16,20)]):
                        added=add_rounds(sql,start,end)
                        if skill=='composer': extract(sql,added,[])
                        await dispatch_memoir_lanes_once(env.client,broker,'issue6-coalesce')
                    extra=add_rounds(sql,21,21,'An additional input before the next checkpoint.')
                    if skill=='composer': extract(sql,extra,[])
                    await dispatch_memoir_lanes_once(env.client,broker,'issue6-coalesce')
                    log=[json.loads(l) for l in calls.read_text().splitlines()]
                    assert sum(c['phase']==('draft' if skill=='composer' else 'timeline') for c in log)==1
                    assert not any(o[0]==lane_id for o in outcomes)
                    gate.unlink()
                    await asyncio.wait_for(selected.result(),25)
                    saved=[o for o in outcomes if o[0]==lane_id and o[1]=='saved']
                    assert len(saved)==2
                    view=rpc(sql,'read_user_memory_events',"'project'")
                    assert view['processing']['extracted_through']==21
                    if skill=='timeline':
                        packets=[c for c in [json.loads(l) for l in calls.read_text().splitlines()] if c['phase']=='timeline']
                        assert len(packets)==2 and len(packets[0]['source_ids'])==1 and len(packets[1]['source_ids'])==20
                    else:
                        draft=rpc(sql,'read_user_memoir_draft',"'project'")
                        assert draft['covered_round']==21 and draft['milestone']==20 and draft['revision']==1
                    history=await selected.fetch_history()
                    assert b'additional input' not in b''.join(e.SerializeToString() for e in history.events)
        readiness.close()
        await readiness.wait_closed()
    asyncio.run(scenario())


def test_real_temporal_dispatch_commits_evidence_without_story_text_in_history(sql, tmp_path, monkeypatch):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.memory_event_worker import MemoirLaneBroker, MemoryEventWorker
    from apps.api.temporal_workflows import MemoirSkillLane
    from scripts.task_runtime import dispatch_memoir_lanes_once
    secret = 'Private synthetic memory retained outside workflow history.'
    rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', '{secret}'")
    control = tmp_path / 'provider.json'
    control.write_text(json.dumps({'reply': {'events': []}}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    provider_worker = CodexWorker(home_root=tmp_path / 'worker-homes',
        command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
    app = FastAPI()
    @app.post('/internal/codex/turn')
    async def worker_turn(payload: WorkerTurnInput):
        return await provider_worker.turn(payload)
    async def scenario():
        options = {'download_dest_dir': '/tmp/memoir-issue6-temporal',
                   'dev_server_database_filename': str(tmp_path / 'temporal.sqlite'), 'ip': '127.0.0.1', 'ui': False}
        async with await WorkflowEnvironment.start_local(**options) as env:
            transport = httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)
            async with httpx.AsyncClient(transport=transport) as client:
                broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=client)
                event_worker = MemoryEventWorker(broker, worker_url='http://controlled-worker.invalid',
                    worker_secret='synthetic-worker-secret', worker_transport=httpx.ASGITransport(app=app))
                @activity.defn(name='memoir.execute_lane')
                async def execute_lane(lane_id: str):
                    result = await event_worker.execute_lane(lane_id)
                    return {'status': result['status']}
                async with Worker(env.client, task_queue='issue6-synthetic', workflows=[MemoirSkillLane], activities=[execute_lane]):
                    handles = await dispatch_memoir_lanes_once(env.client, broker, 'issue6-synthetic')
                    assert len(handles) == 1
                    await asyncio.wait_for(handles[0].result(), 20)
                    assert rpc(sql, 'read_user_memory_events', "'project'")['processing']['extracted_through'] == 1
                    history = await handles[0].fetch_history()
                    assert secret.encode() not in b''.join(event.SerializeToString() for event in history.events)
    asyncio.run(scenario())


@pytest.mark.parametrize('skill',['timeline','composer'])
def test_real_temporal_worker_interruption_recovers_failed_range_without_new_turn(sql,tmp_path,monkeypatch,skill):
    from test_shared_memory_events_postgres import five_rounds,add_rounds,extract,deliver_latest,service_rpc,literal,run_controlled_composer
    from apps.api.codex_worker_service import CodexWorker,WorkerTurnInput
    from apps.api.memory_event_worker import MemoirLaneBroker,MemoryEventWorker
    from apps.api.temporal_workflows import MemoirSkillLane
    from scripts.task_runtime import dispatch_memoir_lanes_once
    sources,lanes=five_rounds(sql)
    if skill=='composer':
        assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    added=add_rounds(sql,6,10)
    if skill=='composer':
        event=rpc(sql,'read_user_memory_events',"'project'")['events'][0]
        extract(sql,added,[{'existing_id':event['id'],'expected_revision':1,'kind':'event','title':'Started school',
            'source_refs':[{'source_id':added[0]['id'],'version':1,'quote':added[0]['text']}]}])
    deliver_latest(sql)
    lane=lanes[skill+'_lane_id']
    gate=tmp_path/'held'
    gate.touch()
    calls=tmp_path/'recovery-calls.jsonl'
    control=tmp_path/'recovery-provider.json'
    control.write_text(json.dumps({'mode':skill,'reply':{'events':[]},'calls':str(calls),
        'hold_phase':'draft' if skill=='composer' else 'timeline','gate':str(gate)}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    async def scenario():
        async def ready(reader,writer):
            writer.close()
            await writer.wait_closed()
        readiness=await asyncio.start_server(ready,'127.0.0.1',0)
        app=FastAPI()
        provider=CodexWorker(home_root=tmp_path/'first-worker',base_url=f'http://127.0.0.1:{readiness.sockets[0].getsockname()[1]}/v1',
            command=[sys.executable,str(ROOT/'tests/fixtures/issue6_controlled_app_server.py'),str(control)])
        @app.post('/internal/codex/turn')
        async def turn(payload:WorkerTurnInput):
            # This provider speaks one role's protocol and logs that role's
            # packets. Unrelated dispatched lanes must not enter its call log.
            expected_role = 'author_timeline' if skill == 'timeline' else 'composer'
            if payload.agent_role != expected_role:
                from fastapi.responses import JSONResponse
                return JSONResponse(status_code=503, content={'detail': 'Unrelated controlled provider unavailable'})
            return await provider.turn(payload)
        options={'download_dest_dir':'/tmp/memoir-issue6-temporal','dev_server_database_filename':str(tmp_path/'recovery-temporal.sqlite'),'ip':'127.0.0.1','ui':False}
        async with await WorkflowEnvironment.start_local(**options) as env:
            async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql,OWNER,service=True).handle)) as client:
                broker=MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic',client=client)
                application=MemoryEventWorker(broker,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.ASGITransport(app=app))
                @activity.defn(name='memoir.execute_lane')
                async def execute(lane_id:str):
                    result=await application.execute_lane(lane_id)
                    state=await broker.rpc('read_memoir_lane_state',p_lane_id=lane_id)
                    return {'status':result['status'],'pending':state['pending']}
                first=Worker(env.client,task_queue='issue6-recovery',workflows=[MemoirSkillLane],activities=[execute],graceful_shutdown_timeout=__import__('datetime').timedelta(seconds=0))
                async with first:
                    handles=await dispatch_memoir_lanes_once(env.client,broker,'issue6-recovery')
                    selected=next(h for h in handles if h.id=='memoir-lane:'+lane)
                    async def wait_held():
                        while not calls.exists() or not any(json.loads(l)['phase'].endswith('_held') for l in calls.read_text().splitlines()): await asyncio.sleep(.05)
                    await asyncio.wait_for(wait_held(),15)
                    held=json.loads(sql(f"select to_jsonb(l) from public.user_memoir_lane l where id='{lane}';").stdout.strip())
                    later=add_rounds(sql,11,20)
                    if skill=='composer': extract(sql,later,[])
                    await dispatch_memoir_lanes_once(env.client,broker,'issue6-recovery')
                    assert rpc(sql,'read_user_memory_events',"'project'")['processing']['extracted_through']==(5 if skill=='timeline' else 20)
                    await first.shutdown()
                # Controlled clock boundary in synthetic PG; no new narrator turn.
                sql(f"update public.user_memoir_lane set lease_until=clock_timestamp()-interval '1 second',run_deadline=clock_timestamp()-interval '1 second' where id='{lane}';")
                gate.unlink()
                provider.home_root=tmp_path/'replacement-worker'
                provider.home_root.mkdir(mode=0o700)
                async with Worker(env.client,task_queue='issue6-recovery',workflows=[MemoirSkillLane],activities=[execute]):
                    await dispatch_memoir_lanes_once(env.client,broker,'issue6-recovery')
                    await asyncio.wait_for(selected.result(),30)
                view=rpc(sql,'read_user_memory_events',"'project'")
                assert view['completed_rounds']==20 and view['processing']['extracted_through']==20
                before=rpc(sql,'read_user_memoir_draft',"'project'") if skill=='composer' else view
                if skill=='composer':
                    assert before['covered_round']==20 and before['revision']==2
                    late=service_rpc(sql,'finish_memoir_composer',f"'{lane}','{held['token']}',1,'{{}}'::jsonb")
                else:
                    packets=[json.loads(l) for l in calls.read_text().splitlines() if json.loads(l)['phase']=='timeline']
                    assert len(packets)==2 and len(packets[0]['source_ids'])==5 and len(packets[1]['source_ids'])==15
                    late=service_rpc(sql,'finish_memoir_timeline',f"'{lane}','{held['token']}','[]'::jsonb")
                assert late['status']=='stale'
                assert (rpc(sql,'read_user_memoir_draft',"'project'") if skill=='composer' else rpc(sql,'read_user_memory_events',"'project'"))==before
        readiness.close()
        await readiness.wait_closed()
    asyncio.run(scenario())


def test_configured_deadline_stops_hung_provider_and_exposes_bounded_retry(sql,tmp_path,monkeypatch):
    from test_shared_memory_events_postgres import story_client
    from apps.api.codex_worker_service import CodexWorker,WorkerTurnInput
    from apps.api.memory_event_worker import MemoirLaneBroker,MemoryEventWorker
    from apps.api.temporal_workflows import MemoirSkillLane
    from scripts.task_runtime import dispatch_memoir_lanes_once
    rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','An original retained through timeout.'")
    gate=tmp_path/'hold'
    gate.touch()
    control=tmp_path/'provider.json'
    control.write_text(json.dumps({'mode':'timeline','reply':{'events':[]},'calls':str(tmp_path/'calls.jsonl'),'hold_phase':'timeline','gate':str(gate)}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_RUN_SECONDS','1')
    provider=CodexWorker(home_root=tmp_path/'worker',command=[sys.executable,str(ROOT/'tests/fixtures/issue6_controlled_app_server.py'),str(control)])
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput): return await provider.turn(payload)
    async def scenario():
        options={'download_dest_dir':'/tmp/memoir-issue6-temporal','dev_server_database_filename':str(tmp_path/'temporal.sqlite'),'ip':'127.0.0.1','ui':False}
        async with await WorkflowEnvironment.start_local(**options) as env:
            async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql,OWNER,service=True).handle)) as client:
                broker=MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic',client=client)
                worker=MemoryEventWorker(broker,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.ASGITransport(app=app))
                @activity.defn(name='memoir.execute_lane')
                async def execute(lane_id:str):
                    result=await worker.execute_lane(lane_id)
                    state=await broker.rpc('read_memoir_lane_state',p_lane_id=lane_id)
                    return {'status':result['status'],'pending':state['pending']}
                async with Worker(env.client,task_queue='issue6-deadline',workflows=[MemoirSkillLane],activities=[execute]):
                    handle=(await dispatch_memoir_lanes_once(env.client,broker,'issue6-deadline'))[0]
                    assert (await asyncio.wait_for(handle.result(),30))['status']=='retry_required'
                    view=rpc(sql,'read_user_memory_events',"'project'")
                    assert view['sources'][0]['text']=='An original retained through timeout.'
                    assert view['processing']['extracted_through']==0 and view['completed_rounds']==0
                    saved=story_client(sql).get('/v1/story/private-draft?project_id=project',headers={'Authorization':'Bearer synthetic-author'}).json()
                    assert saved['progress']['extraction']['state']=='retry_required' and saved['error']
                    assert not saved['updating']
                    retry=story_client(sql).post('/v1/story/private-draft/retry',headers={'Authorization':'Bearer synthetic-author'},json={'project_id':'project'}).json()
                    assert retry['progress']['extraction']['state']=='pending'
    asyncio.run(scenario())
