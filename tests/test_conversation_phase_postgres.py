"""Real restricted-role phase state, CAS, replay and ownership acceptance."""
import pytest
from test_interview_photos_postgres import database, attachment_database, private_database, event_database, sql, rpc, literal, accept, as_user, OWNER, OTHER, OLD, TURN
from test_interview_work_plan_postgres import plan, save


def read(sql,owner=OWNER):
    return rpc(sql,'read_user_conversation_phase',"'project'",owner=owner)


def control(sql, action, revision):
    return rpc(sql,'change_user_conversation_phase',f"'project',{literal(action)},{revision}")


def test_new_state_is_idempotent_and_control_does_not_spend_rounds(sql):
    accept(sql,'My name is Joan')
    initial=read(sql)
    assert initial['phase']=='comfort' and initial['revision']==0
    assert read(sql)==initial
    explicit=control(sql,'shape',0)
    assert explicit['preferred_phase']=='shape' and explicit['revision']==1
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
    assert read(sql)==explicit


def test_stale_control_and_cross_owner_access_fail(sql):
    accept(sql)
    control(sql,'pause',0)
    assert rpc(sql,'change_user_conversation_phase',"'project','resume',0",check=False).returncode!=0
    assert rpc(sql,'read_user_conversation_phase',"'project'",owner=OTHER,check=False).returncode!=0
    assert sql(as_user('select count(*) from public.user_conversation_phase;',OTHER)).stdout.strip()=='0'
    assert sql('set role anon; select * from public.user_conversation_phase;',check=False).returncode!=0


def test_phase_is_atomic_with_reply_and_replay_preserves_newer_control(sql):
    accept(sql,'My name is Joan')
    value=plan(name='Joan'); value['phase_update']={'expected_revision':0,'phase':'comfort'}
    result=save(sql,value)
    assert result['conversation_phase']['revision']==0
    changed=control(sql,'explore',0)
    result=save(sql,value)
    assert result['conversation_phase']==changed
    assert 'phase_update' not in result['plan']


def test_late_automatic_save_cannot_overwrite_pause_or_lose_narration(sql):
    accept(sql,'I remember the garden.')
    control(sql,'pause',0)
    value=plan('extract',None); value['phase_update']={'expected_revision':0,'phase':'explore'}
    assert save(sql,value,check=False).returncode!=0
    assert read(sql)['paused']
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert rpc(sql,'read_user_interview_turn',f"'project','{TURN}'")['reply'] is None


@pytest.mark.parametrize('text,action',[('Shape my story','shape'),('帮我整理故事','shape'),('pause','pause'),('请暂停一下','pause')])
def test_current_narrator_control_is_grounded_independently_in_sql(sql,text,action):
    accept(sql,text)
    value=plan('reply_only',None)
    if action=='pause': value.update(candidates=[],chosen_id=None)
    value['phase_update']={'expected_revision':0,'phase':None}
    result=save(sql,value)
    state=result['conversation_phase']
    assert state['paused'] if action=='pause' else state['preferred_phase']=='shape'


def test_omitted_phase_update_cannot_bypass_newer_choice(sql):
    accept(sql,'Shape my story')
    control(sql,'pause',0)
    value=plan('reply_only',None); value.update(candidates=[],chosen_id=None)
    assert save(sql,value)['conversation_phase']['paused']
    assert read(sql)['preferred_phase'] is None
    assert read(sql)['paused']


def test_automatic_and_repeated_controls_align_with_policy(sql):
    accept(sql,'My name is Joan')
    explicit=control(sql,'shape',0)
    assert control(sql,'shape',1)==explicit
    automatic=control(sql,'automatic',1)
    assert automatic['phase']=='comfort' and automatic['preferred_phase'] is None
    assert automatic['selection']=='automatic'


def test_additive_migration_can_be_replayed_without_rewrapping(sql):
    from pathlib import Path
    accept(sql)
    state=control(sql,'shape',0)
    migration=Path(__file__).resolve().parents[1]/'supabase/migrations/202610120002_conversation_phase.sql'
    sql(migration.read_text())
    assert read(sql)==state
    assert rpc(sql,'read_user_interview_context',"'project'")['conversation_phase']==state


def test_source_correction_reopens_exploration_and_preserves_explicit_shape(sql):
    turn=accept(sql,'I started school in 1960.')
    control(sql,'shape',0)
    rpc(sql,'change_user_narrator_source',f"'project','{turn['source']['id']}',1,'edit','I started school in 1961.'")
    state=read(sql)
    assert state['phase']=='explore' and state['preferred_phase']=='shape' and state['revision']==2


def test_legacy_saved_project_resumes_without_phase_state(sql):
    sql(f"insert into public.user_memoir_project(user_id,project_id) values ('{OWNER}','project');")
    sql(f"insert into public.user_memory(user_id,project_id,kind,content) values ('{OWNER}','project','agent',E'Storyteller: I remember the garden.\\nMemory Spark: Who was there?');")
    assert read(sql)['phase']=='explore'
    assert rpc(sql,'read_user_interview_context',"'project'")['has_accepted_narration']


@pytest.mark.parametrize('language,name,text,question',[
    ('en-AU','Joan','My name is Joan','What would you enjoy talking about?'),
    ('zh-CN','韩凤江','我叫韩凤江','您想先聊些什么？'),
])
@pytest.mark.parametrize('rich',[False,True])
def test_streamed_request_real_collector_validation_persistence_and_replay(sql,tmp_path,monkeypatch,language,name,text,question,rich):
    import json
    import time
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.store import MemoryStore
    from memoir_postgres_workflow import PostgresRest
    from test_name_only_opening import proposal
    outputs=[]; provider_calls=[]
    if rich:
        text=('My sister and I planted beans beside our old kitchen. She labelled every row. ' if language=='en-AU' else '小时候我和姐姐在老厨房旁种豆子，她给每一行都写了标签。')*40
        question='What do you remember about planting together?' if language=='en-AU' else '一起种豆子时，您还记得什么？'
    response=proposal(name=name,question=question)
    response['acknowledgement']=f'Good to meet you, {name}.' if language=='en-AU' else f'{name}，很高兴认识您。'
    response['plan']['conversation_phase']='explore' if rich else 'comfort'
    if rich:
        response['plan']['work']={'mode':'extract','name':None}
        response['acknowledgement']='You planted beans together.' if language=='en-AU' else '您和姐姐一起种豆子。'
    def provider(request):
        provider_calls.append(json.loads(request.content))
        data=json.loads(request.content)
        raw=json.dumps(response if data.get('agent_role','collector')=='collector' else {},ensure_ascii=False)
        packets=[{'type':'text_delta','text':raw}, {'type':'result','data':{
            'reply':raw,'thread_id':'synthetic-phase-thread','source_paths':[]}}]
        return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},content='\n'.join(json.dumps(p,ensure_ascii=False) for p in packets)+'\n')
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    app=FastAPI(); app.state.store=MemoryStore(); app.include_router(agent_routes.router)
    headers={'Authorization':'Bearer synthetic-author','Accept':'application/x-ndjson'}
    payload={'project_id':'project','client_turn_id':TURN,'text':text,'language':language}
    with TestClient(app) as client:
        start=time.monotonic()
        first=client.post('/v1/agent/turn',headers=headers,json=payload)
        packets=[json.loads(line) for line in first.text.splitlines()]
        assert not [p for p in packets if p['type']=='error'],packets
        saved=next(p['data'] for p in packets if p['type']=='conversation_saved')
        assert saved['conversation_phase']['phase']==('explore' if rich else 'comfort')
        assert question in saved['reply']
        readback=client.get(f'/v1/agent/turns/{TURN}?project_id=project').json()
        assert readback['conversation_phase']['phase']==saved['conversation_phase']['phase']
        assert readback['reply']==saved['reply']
        state=client.patch('/v1/agent/projects/project/conversation-phase',json={'action':'shape','expected_revision':saved['conversation_phase']['revision']}).json()['conversation_phase']
        assert state['preferred_phase']=='shape'
        retry=client.post('/v1/agent/turn',headers=headers,json=payload)
        replay=next(json.loads(line)['data'] for line in retry.text.splitlines() if json.loads(line)['type']=='result')
        assert replay['conversation_phase']==state and replay['reply']==saved['reply']
        assert len([p for p in provider_calls if p.get('agent_role','collector')=='collector'])==1
        if rich: assert any(p.get('agent_role')=='workspace' for p in provider_calls)
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
        assert rpc(sql,'read_user_memory_events',"'project'")['sources'][0]['text']==text


def test_two_tabs_cas_accepts_only_one_choice(sql):
    from concurrent.futures import ThreadPoolExecutor
    accept(sql)
    read(sql)
    def change(action):
        return rpc(sql,'change_user_conversation_phase',f"'project','{action}',0",check=False)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes=list(pool.map(change,['shape','pause']))
    assert sorted(result.returncode==0 for result in outcomes)==[False,True]
    assert read(sql)['revision']==1


@pytest.mark.parametrize('text,expected',[
    ('这段回忆让我难受，我想暂停一下。','pause'),
    ('This is upsetting, I want to pause.','pause'),
    ('他说，我想暂停一下。',None),('He said, I want to pause.',None),
    ('别暂停',None),("I don't want to pause",None),
])
def test_sql_current_intent_matches_application_without_reported_speech(sql,text,expected):
    # Helper is not callable by authenticated; exercise full public save RPC.
    accept(sql,text)
    value=plan('reply_only',None); value.update(candidates=[],chosen_id=None)
    value['phase_update']={'expected_revision':0,'phase':None}
    result=save(sql,value)
    assert result['conversation_phase']['paused']==(expected=='pause')


def test_guest_transfer_preserves_explicit_choice_and_retry(sql):
    from test_guest_conversation_transfer import TOKEN
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    accept(sql,'My name is Joan')
    original=control(sql,'shape',0)
    rpc(sql,'prepare_guest_conversation_transfer',f"'{TOKEN}','project','[]'::jsonb")
    result=rpc(sql,'attach_guest_conversation',f"'{TOKEN}'",owner=OTHER)
    assert result['attached']
    transferred=read(sql,OTHER)
    assert transferred==original
    changed=rpc(sql,'change_user_conversation_phase',"'project','pause',1",owner=OTHER)
    rpc(sql,'attach_guest_conversation',f"'{TOKEN}'",owner=OTHER)
    assert read(sql,OTHER)==changed


def test_admission_revision_never_refreshes_and_newer_pause_wins_retry(sql):
    admitted=accept(sql,'resume')
    assert admitted['phase_revision']==0
    paused=control(sql,'pause',0)
    assert accept(sql,'resume')['phase_revision']==0
    value=plan('reply_only',None); value.update(candidates=[],chosen_id=None)
    value['phase_update']={'expected_revision':0,'phase':None}
    assert save(sql,value,check=False).returncode!=0
    value['phase_update']['expected_revision']=1
    finished=save(sql,value)
    assert finished['conversation_phase']==paused
    assert read(sql)['paused'] and read(sql)['revision']==1
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert save(sql,value)['conversation_phase']==paused


@pytest.mark.parametrize('text',['She said:\nI want to pause.\nThose were her words.','她说：\n我想暂停一下。\n这是她的原话。'])
def test_multiline_report_does_not_persist_pause(sql,text):
    accept(sql,text)
    value=plan('reply_only',None); value['phase_update']={'expected_revision':0,'phase':None}
    assert not save(sql,value)['conversation_phase']['paused']


def test_three_five_twenty_rounds_do_not_force_phase_or_change_allowance(sql,tmp_path,monkeypatch):
    import json
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.store import MemoryStore
    from memoir_postgres_workflow import PostgresRest
    from test_name_only_opening import proposal
    calls=[]
    response=proposal(name=None,question='What would you like to talk about?')
    response['acknowledgement']='We can take our time.'
    response['plan']['conversation_phase']='comfort'
    def provider(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},content=json.dumps({'type':'result','data':{
            'reply':json.dumps(response),'thread_id':'synthetic-phase-thread','source_paths':[]}})+'\n')
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    app=FastAPI(); app.state.store=MemoryStore(); app.include_router(agent_routes.router)
    with TestClient(app) as client:
        for number in range(1,21):
            response_http=client.post('/v1/agent/turn',headers={'Accept':'application/x-ndjson'},json={
                'text':'Hello again','project_id':'project','client_turn_id':f'00000000-0000-4000-8000-{number:012d}'})
            packets=[json.loads(line) for line in response_http.text.splitlines()]
            assert not [p for p in packets if p['type']=='error'],packets
            if number in (3,5,20):
                assert read(sql)['phase']=='comfort' and read(sql)['revision']==0
                assert sql('select count(*) from public.user_completed_round;').stdout.strip()==str(number)
                before=client.get('/v1/agent/projects/project/conversation-phase').json()
                assert before['conversation_phase']['phase']=='comfort'
        assert len(calls)==20
        state=client.patch('/v1/agent/projects/project/conversation-phase',json={'action':'shape','expected_revision':0}).json()['conversation_phase']
        assert state['phase']=='shape'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='20'
        denied=client.post('/v1/agent/turn',headers={'Accept':'application/x-ndjson'},json={
            'text':'Another reply','project_id':'project','client_turn_id':'00000000-0000-4000-8000-000000000021'})
        result=next(json.loads(line)['data'] for line in denied.text.splitlines() if json.loads(line)['type']=='result')
        assert result['recall_status']['payment_required'] and result['reply'] is None
        assert len(calls)==20 and sql('select count(*) from public.user_completed_round;').stdout.strip()=='20'


def test_rich_save_precedes_stalled_background_disconnect_and_replay(sql,tmp_path,monkeypatch):
    import asyncio
    import json
    import time
    import httpx
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    from test_name_only_opening import proposal
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB',raising=False)
    source='My sister and I planted beans beside the old kitchen. She labelled every row. '*40
    response=proposal('extract',None,'What do you remember about planting together?')
    response['acknowledgement']='You planted beans with your sister.'
    response['plan']['conversation_phase']='explore'
    async def scenario():
        saved=asyncio.Event(); background=asyncio.Event(); never=asyncio.Event(); calls=[]; marks={}; start=time.monotonic()
        async def provider(request):
            payload=json.loads(request.content); calls.append(payload)
            if payload.get('agent_role','collector')!='collector':
                background.set(); await never.wait()
            raw=json.dumps(response)
            return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},content='\n'.join(json.dumps(p) for p in [
                {'type':'text_delta','text':raw},{'type':'result','data':{'reply':raw,'thread_id':'synthetic-phase-thread','source_paths':[]}}])+'\n')
        async def delta(text):
            marks.setdefault('first_meaningful_text_ms',round((time.monotonic()-start)*1000,3))
            if '?' in text: marks.setdefault('validated_question_ms',round((time.monotonic()-start)*1000,3))
        async def event(packet):
            if packet['type']=='conversation_saved':
                marks['durable_save_ms']=round((time.monotonic()-start)*1000,3); saved.set()
        runtime=CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider))
        storage=PostgresRest(sql,OWNER).storage()
        task=asyncio.create_task(runtime.turn(storage,source,project_id='project',client_turn_id=TURN,on_delta=delta,on_event=event))
        try:
            await asyncio.wait_for(saved.wait(),5)
            await asyncio.wait_for(background.wait(),5)
            assert not task.done()
            assert marks['first_meaningful_text_ms']<=marks['validated_question_ms']<=marks['durable_save_ms']
            assert len([p for p in calls if p.get('agent_role','collector')=='collector'])==1
            assert read(sql)['phase']=='explore'
        finally:
            task.cancel(); await asyncio.gather(task,return_exceptions=True)
        replay=await runtime.turn(storage,source,project_id='project',client_turn_id=TURN)
        assert replay['cached'] and replay['conversation_saved']
        assert replay['conversation_phase']['phase']=='explore'
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
        assert len([p for p in calls if p.get('agent_role','collector')=='collector'])==1
        storage.client.close()
        return marks
    marks=asyncio.run(scenario())
    print('SYNTHETIC_PHASE_TIMINGS '+json.dumps(marks,sort_keys=True))
    (tmp_path/'phase-timings.json').write_text(json.dumps({'provider':'controlled_no_live_call',**marks}))
