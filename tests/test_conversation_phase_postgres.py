"""Real restricted-role phase state, CAS, replay and ownership acceptance."""
import pytest
from test_interview_photos_postgres import database, attachment_database, private_database, event_database, sql, rpc, literal, accept, as_user, OWNER, OTHER, OLD, TURN
from test_interview_work_plan_postgres import plan, save
from test_conversation_phase import CONTROL_ATTRIBUTION_CASES


def read(sql,owner=OWNER):
    return rpc(sql,'read_user_conversation_phase',"'project'",owner=owner)


@pytest.mark.parametrize('operation', ['context', 'receipt'])
def test_legacy_read_only_initializes_phase_without_admission_or_generation(sql, operation):
    import json
    accept(sql, 'My name is Joan')
    # Reproduce an owned pre-phase deployment with an already accepted turn.
    sql('delete from public.user_conversation_phase;')
    tables = sql("select tablename from pg_tables where schemaname='public' "
                 "and tablename<>'user_conversation_phase' order by tablename;").stdout.splitlines()
    def snapshot():
        queries = ' union all '.join(f"select '{table}' name, coalesce(jsonb_agg(to_jsonb(t) "
                                    f"order by to_jsonb(t)::text),'[]') value from public.\"{table}\" t"
                                    for table in tables)
        return json.loads(sql(f'select jsonb_object_agg(name,value) from ({queries}) tables;').stdout)
    arguments = "'project'" if operation == 'context' else f"'project','{TURN}'"
    name = 'read_user_interview_context' if operation == 'context' else 'read_user_interview_turn'
    before = snapshot()
    first = rpc(sql, name, arguments)
    assert first['conversation_phase']['phase'] == 'comfort'
    assert first['conversation_phase']['revision'] == 0
    assert sql('select count(*) from public.user_conversation_phase;').stdout.strip() == '1'
    assert rpc(sql, name, arguments) == first
    assert snapshot() == before, 'Read changed durable state beyond phase initialization'
    if operation == 'receipt':
        assert rpc(sql, name, arguments, owner=OTHER) is None
    else:
        assert rpc(sql, name, arguments, owner=OTHER, check=False).returncode != 0
    assert snapshot() == before
    # A read can take the documented owned-project lock. It cannot bypass a
    # concurrent writer, resolve/adopt a conversation, or admit another turn.
    import psycopg
    with psycopg.connect(sql.publication_dsn) as reader:
        reader.execute('set role authenticated')
        reader.execute("select set_config('request.jwt.claim.sub',%s,false)", (OWNER,))
        reader.execute(f'select public.{name}({arguments})')
        with psycopg.connect(sql.publication_dsn) as writer:
            writer.execute("set lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                writer.execute("select 1 from public.user_memoir_project where project_id='project' for update")


def test_anonymous_project_initialization_precedes_narration_and_preserves_ownership(sql):
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    rpc(sql, 'ensure_user_memoir_project', "'project'")
    rpc(sql, 'ensure_user_memoir_project', "'project'")
    assert read(sql)['phase'] == 'comfort'
    assert sql('select count(*) from public.user_memoir_project;').stdout.strip() == '1'
    for table in ('user_narrator_source', 'user_interview_turn', 'user_completed_round'):
        assert sql(f'select count(*) from public.{table};').stdout.strip() == '0'
    read_other = rpc(sql, 'read_user_conversation_phase', "'project'", owner=OTHER, check=False)
    assert read_other.returncode != 0
    assert sql("set role anon; select public.ensure_user_memoir_project('project');", check=False).returncode != 0
    assert rpc(sql, 'ensure_user_memoir_project', "'../invalid'", check=False).returncode != 0
    assert sql(as_user("insert into public.user_memoir_project(user_id,project_id) values(auth.uid(),'bypass');"), check=False).returncode != 0


def test_project_initialization_cannot_downgrade_a_canonical_owner(sql):
    identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
    assert rpc(sql, 'ensure_user_memoir_project', "'extra-legacy-project'", check=False).returncode != 0
    assert sql(f"select project_id from public.user_memoir_project where user_id='{OWNER}';").stdout.strip() == identity['project_id']


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
    control(sql,'shape',0)
    assert rpc(sql,'change_user_conversation_phase',"'project','comfort',0",check=False).returncode!=0
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


def test_late_automatic_save_cannot_overwrite_choice_or_lose_narration(sql):
    accept(sql,'I remember the garden.')
    changed=control(sql,'shape',0)
    value=plan('extract',None); value['phase_update']={'expected_revision':0,'phase':'explore'}
    assert save(sql,value,check=False).returncode!=0
    assert read(sql)==changed
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert rpc(sql,'read_user_interview_turn',f"'project','{TURN}'")['reply'] is None


@pytest.mark.parametrize('text,action',[('Shape my story','shape'),('帮我整理故事','shape'),('Explore a memory','explore'),('聊聊一段回忆','explore'),('继续聊聊','comfort')])
def test_current_narrator_control_is_grounded_independently_in_sql(sql,text,action):
    accept(sql,text)
    value=plan('reply_only',None)
    value['phase_update']={'expected_revision':0,'phase':None}
    result=save(sql,value)
    state=result['conversation_phase']
    assert state['preferred_phase']==action


def test_omitted_phase_update_cannot_bypass_newer_choice(sql):
    accept(sql,'Shape my story')
    changed=control(sql,'comfort',0)
    value=plan('reply_only',None)
    assert save(sql,value)['conversation_phase']==changed


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


def test_source_correction_preserves_conversation_mode(sql):
    turn=accept(sql,'I started school in 1960.')
    original=control(sql,'shape',0)
    rpc(sql,'change_user_narrator_source',f"'project','{turn['source']['id']}',1,'edit','I started school in 1961.'")
    state=read(sql)
    assert state==original


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
        outcomes=list(pool.map(change,['shape','comfort']))
    assert sorted(result.returncode==0 for result in outcomes)==[False,True]
    assert read(sql)['revision']==1


@pytest.mark.parametrize('text,expected', CONTROL_ATTRIBUTION_CASES + [
    ('这段回忆让我难受，我想整理我的故事。','shape'),
    ('This is important, I want to shape my story.','shape'),
    ('他说，整理我的故事。',None),('He said, shape my story.',None),
    ('pause',None),('resume',None),
])
def test_sql_current_intent_matches_application_without_reported_speech(sql,text,expected):
    # Helper is not callable by authenticated; exercise full public save RPC.
    accept(sql,text)
    value=plan('reply_only',None); value.update(candidates=[],chosen_id=None)
    value['phase_update']={'expected_revision':0,'phase':None}
    result=save(sql,value)
    assert result['conversation_phase']['preferred_phase']==expected
    assert 'paused' not in result['conversation_phase']


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
    changed=rpc(sql,'change_user_conversation_phase',"'project','comfort',1",owner=OTHER)
    rpc(sql,'attach_guest_conversation',f"'{TOKEN}'",owner=OTHER)
    assert read(sql,OTHER)==changed


def test_admission_revision_never_refreshes_and_newer_choice_wins_retry(sql):
    admitted=accept(sql,'Shape my story')
    assert admitted['phase_revision']==0
    changed=control(sql,'comfort',0)
    assert accept(sql,'Shape my story')['phase_revision']==0
    value=plan('reply_only',None)
    value['phase_update']={'expected_revision':0,'phase':None}
    assert save(sql,value,check=False).returncode!=0
    value['phase_update']['expected_revision']=1
    finished=save(sql,value)
    assert finished['conversation_phase']==changed
    assert read(sql)==changed
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert save(sql,value)['conversation_phase']==changed


@pytest.mark.parametrize('text',['She said:\nShape my story.\nThose were her words.','她说：\n整理我的故事。\n这是她的原话。'])
def test_multiline_report_does_not_change_mode(sql,text):
    accept(sql,text)
    value=plan('reply_only',None); value['phase_update']={'expected_revision':0,'phase':None}
    assert save(sql,value)['conversation_phase']['selection']=='automatic'


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


def test_explicit_event_correction_preserves_shape_and_later_choice(sql):
    from test_shared_memory_events_postgres import extract
    turn=accept(sql,'I started school.')
    source=turn['source']
    event=extract(sql,[source],[{'kind':'event','title':'Started school','source_refs':[
        {'source_id':source['id'],'version':1,'quote':source['text']}]}])['events'][0]
    original=control(sql,'shape',0)
    corrected=rpc(sql,'correct_user_memory_event',f"'project','{event['id']}',1,'{{\"life_stage\":\"childhood\"}}'::jsonb,'I was a child then.'")
    state=read(sql)
    assert corrected['life_stage']=='childhood' and state==original
    state=control(sql,'shape',state['revision'])
    correction=accept(sql,'Actually, I was an adolescent then.',turn='00000000-0000-4000-8000-000000000099')
    state=control(sql,'comfort',state['revision'])
    state=control(sql,'shape',state['revision'])
    current=rpc(sql,'read_user_memory_events',"'project'")['events'][0]
    rpc(sql,'correct_user_memory_event',f"'project','{event['id']}',{current['revision']},'{{\"life_stage\":\"adolescence\"}}'::jsonb,'Actually, I was an adolescent then.','chat','{correction['source']['id']}'")
    assert read(sql)==state


def test_current_chat_correction_and_failed_correction_keep_mode(sql):
    from test_shared_memory_events_postgres import extract
    source=accept(sql,'I started school.')['source']
    event=extract(sql,[source],[{'kind':'event','title':'Started school','source_refs':[
        {'source_id':source['id'],'version':1,'quote':source['text']}]}])['events'][0]
    state=control(sql,'shape',0)
    failure=rpc(sql,'correct_user_memory_event',f"'project','{event['id']}',999,'{{\"life_stage\":\"childhood\"}}'::jsonb,'Actually, I was a child then.'",check=False)
    assert failure.returncode != 0 and read(sql)==state
    correction=accept(sql,'Actually, I was a child then.',turn='00000000-0000-4000-8000-000000000098')
    rpc(sql,'correct_user_memory_event',f"'project','{event['id']}',1,'{{\"life_stage\":\"childhood\"}}'::jsonb,'Actually, I was a child then.','chat','{correction['source']['id']}'")
    assert read(sql)==state


@pytest.mark.parametrize('origin',['workspace','chat'])
@pytest.mark.parametrize('selection',['shape','automatic'])
def test_year_correction_changes_only_the_affected_event_without_restarting(sql,origin,selection):
    from test_shared_memory_events_postgres import extract
    source=accept(sql,'I started school in 1964. We moved in 1986.')['source']
    reference={'source_id':source['id'],'version':1,'quote':source['text']}
    events=extract(sql,[source],[
        {'kind':'event','title':'Started school','source_refs':[reference],
         'temporal':{'expression':'1964','precision':'year','year_start':1964,'year_end':1964,'basis':[reference]}},
        {'kind':'event','title':'Moved','source_refs':[reference],
         'temporal':{'expression':'1986','precision':'year','year_start':1986,'year_end':1986,'basis':[reference]}},
    ])['events']
    target=next(event for event in events if event['title']=='Started school')
    other=next(event for event in events if event['title']=='Moved')
    opening=plan('extract',None)
    opening['phase_update']={'expected_revision':0,'phase':'explore'}
    guidance=save(sql,opening)['conversation_phase']
    if selection=='shape': guidance=control(sql,'shape',guidance['revision'])
    statement='Actually, the school year was 1966.'
    source_id='null'
    if origin=='chat':
        correction=accept(sql,statement,turn='00000000-0000-4000-8000-000000000097')
        source_id=literal(correction['source']['id'])
        # Exercise the SQL backstop even if a worker bypasses Python filtering.
        # The collector saves before background event correction consumes its source.
        value=plan('extract',None)
        value['phase_update']={'expected_revision':guidance['revision'],'phase':'comfort'}
        sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
        saved=rpc(sql,'save_user_interview_plan',f"'project','{correction['client_turn_id']}',{literal(value)}::jsonb,'[]','{OLD}',{literal('The school year is 1966.')},'[]','real-collector-thread'")
        assert saved['conversation_phase']==guidance
    patch={'temporal':{'expression':'1966','precision':'year','year_start':1966,'year_end':1966}}
    corrected=rpc(sql,'correct_user_memory_event',f"'project',{literal(target['id'])},1,{literal(patch)}::jsonb,{literal(statement)},{literal(origin)},{source_id}")
    current=rpc(sql,'read_user_memory_events',"'project'")['events']
    assert corrected['temporal']['year_start']==1966 and corrected['revision']==2
    assert next(event for event in current if event['id']==other['id'])==other
    assert read(sql)==guidance


@pytest.mark.parametrize('action',['pause','resume'])
def test_removed_controls_cannot_create_a_durable_pause(sql,action):
    accept(sql)
    original=read(sql)
    assert rpc(sql,'change_user_conversation_phase',f"'project',{literal(action)},0",check=False).returncode!=0
    assert read(sql)==original and 'paused' not in original
