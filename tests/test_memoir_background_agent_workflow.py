"""Accepted conversation → background Codex tools → real canonical domain commits."""
import asyncio
import json
from pathlib import Path
import subprocess
import threading

import pytest

from fastapi import FastAPI
import httpx

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.memory_event_worker import MemoryEventWorker
from controlled_skill_harness import ControlledSkillConnection, empty_document, install_document_provider
from test_background_profile_workflow import database, Broker
from test_conversation_attribution import Conversation, empty
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_memoir_background_agent_postgres import service
from test_agent_commit_postgres import OWNER


@pytest.mark.parametrize('text,preference,locale',[
    ('我于1983年4月出生在承德。',None,'zh-CN'),
    ('我于1983年4月出生在承德。','en-AU','en-AU'),
    ('I was born in Chengde in April 1983.','zh-CN','zh-CN'),
    ('I was born in Chengde in April 1983.',None,'en-AU'),
])
def test_resolved_language_reaches_background_skills_and_map_cards(sql,tmp_path,monkeypatch,text,preference,locale):
    from test_conversation_attribution import episode
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    phases=[]
    title='1983年4月出生在承德' if locale=='zh-CN' else 'Born in Chengde in April 1983'
    class LocalizedConnection(ControlledSkillConnection):
        async def turn(self,thread_id,prompt,**options):
            task=json.loads(prompt)['task']
            assert task['lane']=='B' and task['locale']==locale, 'Resolve context before selecting any source skills.'
            return await super().turn(thread_id,prompt,**options)
    def respond(body):
        task=json.loads(body['input'])
        phase='profile' if 'profile_patch' in body['text']['format']['schema']['properties'] else 'extract'
        phases.append(phase)
        assert task['lane_context']['preferences']['language']==locale
        language='Simplified Chinese' if locale=='zh-CN' else 'Australian English'
        assert f'Write in {language}; preserve original quoted source language.' in body['instructions']
        output=empty_document(body)
        if phase=='extract':
            packet=task['payload']
            output['events']=[episode(packet,packet['sources'][0]['text'],title=title)]
        return output
    install_document_provider(monkeypatch, respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',LocalizedConnection)
    conversation=Conversation(sql,tmp_path / 'conversation',monkeypatch,empty)
    native=CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
        worker_transport=httpx.ASGITransport(app=app))
    with conversation.client:
        conversation.say(text,**({'language':preference} if preference else {}))
        conversation.deliver_receipts()
        run,=service(sql,'pending_memoir_background_agents')
        result=asyncio.run(worker.execute_background_agent(run))
        assert result['status']=='finished',result
        assert phases==['profile','extract']
        profile=conversation.client.get('/v1/agent/profile').json()
        assert profile['preferred_language']==locale
        response=conversation.client.get('/v1/story/map-events',params={'project_id':conversation.project})
        assert response.status_code==200,response.text
        assert [event['title'] for event in response.json()['events']]==[title]
        replay=subprocess.run(['node',str(Path(__file__).parent/'js/helpers/replay-background-locale.mjs')],
            input=json.dumps(dict(project_id=conversation.project,feed=response.json(),profile=profile,locale=locale,title=title)),
            text=True,capture_output=True,timeout=10)
        assert replay.returncode==0,replay.stdout+replay.stderr


@pytest.mark.parametrize('profile_first',[False,True])
def test_foreground_keeps_replying_while_background_finishes_then_batches_queued_narrations(sql,tmp_path,monkeypatch,profile_first):
    from test_conversation_reply import proposal
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    entered, release = asyncio.Event(), asyncio.Event()
    batches, originals = [], []
    class SlowConnection(ControlledSkillConnection):
        source_choices = ('memoir-author-timeline',)
        async def turn(self,thread_id,prompt,**options):
            task = json.loads(prompt)['task']
            assert task['lane']=='B'
            batches.append(task['source_work']['sources'])
            if profile_first and len(batches)==1:
                self.source_choices=('memoir-memory-context','memoir-author-timeline')
            return await super().turn(thread_id,prompt,**options)
    async def respond(body):
        task=json.loads(body['input'])
        is_profile='profile_patch' in body['text']['format']['schema']['properties']
        source=task['payload']['source'] if is_profile else task['payload']['sources'][0]
        if not is_profile:
            originals.append(source)
        if not entered.is_set():
            entered.set()
            await release.wait()
        output=empty_document(body)
        if is_profile:
            output['profile_patch']=[{'field':'birth_place','value':'Hobart','source_refs':[{
                'source_id':source['id'],'version':source['version'],'quote':source['text'],
                'char_start':0,'char_end':len(source['text'])}]}]
        return output
    install_document_provider(monkeypatch, respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',SlowConnection)
    def reply(context):
        return {**proposal(), 'quote':context['source']['text'],
            'question':'What else do you remember about ' + context['source']['text']}
    conversation=Conversation(sql,tmp_path / 'conversation',monkeypatch,empty,reply=reply)
    native=CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
        worker_transport=httpx.ASGITransport(app=app))
    with conversation.client:
        first=conversation.say('I was born in Hobart.')
        conversation.deliver_receipts()
        run,=service(sql,'pending_memoir_background_agents')
        async def scenario():
            running=asyncio.create_task(worker.execute_background_agent(run))
            try:
                async with asyncio.timeout(20):
                    await entered.wait()
                later=[]
                for text in ['We played in the school housing.','Our favourite game was hide-and-seek.']:
                    async with asyncio.timeout(20):
                        reply=await asyncio.to_thread(conversation.say,text)
                    assert reply['conversation_saved'] and reply['reply']
                    later.append(reply)
                    await asyncio.to_thread(conversation.deliver_receipts)
                assert not running.done(), 'Both foreground replies must finish while the first B model is held.'
                assert service(sql,'pending_memoir_background_agents')==[]
                assert len(batches)==1 and len(originals)==(0 if profile_first else 1)
            finally:
                release.set()
                result=await running
            assert result['pending']
            assert sql("select count(*) from public.user_narrator_source where processing_status='succeeded';").stdout.strip()=='1'
            sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
            assert (await worker.execute_background_agent(run))['status']=='finished'
            return later
        later=asyncio.run(scenario())
        assert [[s['text'] for s in group] for group in batches]==[
            ['I was born in Hobart.'],['We played in the school housing.','Our favourite game was hide-and-seek.']]
        assert [s['id'] for s in originals]==[first['accepted_source_id'],*[r['accepted_source_id'] for r in later]]
        last_turn=sql('select client_turn_id from public.user_narrator_source where sequence=3;').stdout.strip()
        from apps.api.background_skills import group_places
        grouping=asyncio.run(group_places(OWNER,conversation.project,[],client_turn_id=last_turn))
        assert grouping['skill_progress']['started_at'] and grouping['skill_progress']['finished_at']
        response=conversation.client.get('/v1/story/readiness',params={'project_id':conversation.project})
        progress=response.json()['skill_progress']['items']
        steps=[s for s in progress if s['phase']=='extract' and s['status']=='saved']
        grouped=[s for s in steps if s['coverage_start']==2 and s['coverage_end']==3]
        assert len(grouped)==2 and len({s['batch_id'] for s in grouped})==1
        assert all(s['client_turn_id']==last_turn and s['started_at']<=s['finished_at'] for s in grouped)
        assert not any(s['skill']=='memoir-memory-context' and s.get('source_id') in {r['accepted_source_id'] for r in later} for s in progress)
        turns=json.loads(sql('select jsonb_agg(client_turn_id order by sequence) from public.user_narrator_source;').stdout)
        replay=subprocess.run(['node',str(Path(__file__).parent/'js/helpers/replay-background-batch.mjs')],
            input=json.dumps({'progress':response.json()['skill_progress'],'turns':turns}),
            text=True,capture_output=True,timeout=20)
        assert replay.returncode==0,replay.stderr


@pytest.mark.parametrize('phase',['profile','extract'])
@pytest.mark.parametrize('restricted',[False,True])
def test_finished_background_output_waits_for_foreground_policy_without_another_model_call(
        sql,tmp_path,monkeypatch,fixed_policy_controls,phase,restricted):
    from apps.api import policy_review
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    entered,release,returned=asyncio.Event(),asyncio.Event(),asyncio.Event()
    reviewing,review_release=threading.Event(),threading.Event()
    calls=[]
    class Connection(ControlledSkillConnection):
        source_choices=('memoir-memory-context',) if phase=='profile' else ('memoir-author-timeline',)
    async def respond(body):
        task=json.loads(body['input'])['payload']
        calls.append(task)
        entered.set()
        await release.wait()
        output=empty_document(body)
        if phase=='profile':
            source=task['source']
            output['profile_patch']=[{'field':'birth_place','value':'Hobart','source_refs':[{
                'source_id':source['id'],'version':source['version'],'quote':source['text'],
                'char_start':0,'char_end':len(source['text'])}]}]
        returned.set()
        return output
    install_document_provider(monkeypatch,respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',Connection)
    complete=policy_review.complete_json
    async def review(name,payload,schema,**options):
        reviewing.set()
        assert await asyncio.to_thread(review_release.wait,10), 'Foreground policy review was not released.'
        return await complete(name,payload,schema,**options)
    conversation=Conversation(sql,tmp_path / 'conversation',monkeypatch,empty)
    native=CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
        worker_transport=httpx.ASGITransport(app=app))
    with conversation.client:
        first=conversation.say('I was born in Hobart.')
        conversation.deliver_receipts()
        run,=service(sql,'pending_memoir_background_agents')
        monkeypatch.setattr(policy_review,'complete_json',review)
        later_text='Please leave my birthplace out.' if restricted else 'We played in the garden.'
        if restricted:
            fixed_policy_controls.append(('excluded_topic',later_text))
        async def scenario():
            running=asyncio.create_task(worker.execute_background_agent(run))
            foreground=None
            try:
                async with asyncio.timeout(15):
                    await entered.wait()
                    foreground=asyncio.create_task(asyncio.to_thread(conversation.say,later_text))
                    assert await asyncio.to_thread(reviewing.wait,10)
                    release.set()
                    await returned.wait()
                    await asyncio.sleep(.5)
                    assert not running.done(), 'A pending foreground review must hold the result, not abort the batch.'
                    assert len(calls)==1
                    assert sql('select count(*) from public.user_lifetime_profile_receipt;').stdout.strip()=='0'
                    review_release.set()
                    assert (await foreground)['conversation_saved']
                    return await running
            finally:
                release.set()
                review_release.set()
                if foreground is not None:
                    await foreground
                await running
        result=asyncio.run(scenario())
        assert len(calls)==1, 'A reviewed result must not require another model call.'
        first_state=sql(f"select processing_status from public.user_narrator_source where id='{first['accepted_source_id']}';").stdout.strip()
        if restricted:
            assert first_state!='succeeded'
            assert conversation.client.get('/v1/agent/profile').json().get('birth_place') is None
        else:
            assert first_state=='succeeded',result
            if phase=='profile':
                assert conversation.client.get('/v1/agent/profile').json()['birth_place']=='Hobart'


@pytest.mark.parametrize('retry_choices',[[],['memoir-place-journey']])
def test_failed_extraction_retry_preserves_the_saved_source_skills(sql,tmp_path,monkeypatch,retry_choices):
    from test_conversation_attribution import episode
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    attempts = []
    fail = True
    def extract(packet):
        attempts.append(packet)
        if fail:
            raise RuntimeError('Controlled extraction transport failure')
        return {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'])]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        conversation.say('I repaired bicycles in our garden.')
        conversation.deliver_receipts()
        lane = sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
        page = service(sql,'claim_memoir_lane',p_lane_id=lane,p_run_seconds=300)
        service(sql,'yield_lifetime_memoir_lane',p_lane_id=lane,p_token=page['token'])
        sql('update public.user_memoir_lane set available_at=clock_timestamp();')
        async def execute(choices):
            return await conversation.worker.execute_lane(lane,source_work={'source':page['source'],'skills':choices})
        first = asyncio.run(execute(['memoir-author-timeline']))
        assert first['status']=='retry'
        assert len(attempts)==1
        assert sql('select processing_status from public.user_narrator_source;').stdout.strip()!='succeeded'
        fail = False
        conversation.retry()
        sql('update public.user_memoir_lane set available_at=clock_timestamp();')
        second = asyncio.run(execute(retry_choices))
        saved = json.loads(sql('select source_decision from public.user_lifetime_lane_snapshot order by created_at desc limit 1;').stdout)
        assert saved['skills']==['memoir-author-timeline']
        assert second['status']=='saved'
        assert len(attempts)==2, 'Retry must execute the previously selected extraction.'
        assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='1'
        assert sql('select processing_status from public.user_narrator_source;').stdout.strip()=='succeeded'


@pytest.mark.parametrize('choices,text,phases',[
    ((), 'Hello.', []),
    (('memoir-author-timeline',), 'I repaired bicycles in our garden.', ['events']),
    (('memoir-place-journey',), 'I lived in Hobart.', ['events']),
    (('memoir-memory-context',), 'I was born in 1960.', ['profile_patch']),
    (('memoir-memory-context','memoir-place-journey'), 'My name is Avery. I lived in Hobart.', ['profile_patch','events']),
])
def test_lane_b_selects_each_source_skill_or_none_independently_of_lane_a_and_rounds(
        sql,tmp_path,monkeypatch,choices,text,phases):
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    nested = []
    nested_metadata = []
    class ChoosingConnection(ControlledSkillConnection):
        source_choices = ()
    def respond(body):
        task=json.loads(body['input'])
        fields=body['text']['format']['schema']['properties']
        phase='profile_patch' if 'profile_patch' in fields else 'events'
        nested.append(phase)
        nested_metadata.append(body['metadata'])
        output=empty_document(body)
        if phase=='profile_patch':
            source=task['payload']['source']
            named='memoir-place-journey' in choices
            quote='My name is Avery.' if named else source['text']
            output['profile_patch']=[{'field':'name' if named else 'birth_year','value':'Avery' if named else 1960,'source_refs':[{
                'source_id':source['id'],'version':source['version'],'quote':quote,
                'char_start':0,'char_end':len(quote)}]}]
        elif 'memoir-place-journey' in choices:
            output['place_journeys']=[{'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],
                'granularity':'city','latitude':None,'longitude':None}]
        return output
    install_document_provider(monkeypatch, respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',ChoosingConnection)
    conversation = Conversation(sql,tmp_path / 'conversation',monkeypatch,empty,work='reply_only')
    native = CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    app = FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    async def drain():
        worker = MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
            worker_transport=httpx.ASGITransport(app=app))
        for _ in range(4):
            sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
            pending = service(sql,'pending_memoir_background_agents')
            if not pending:
                return
            for run in pending:
                await worker.execute_background_agent(run)
        pytest.fail('Selected background source work did not settle')
    with conversation.client:
        conversation.say('Hello.')
        conversation.deliver_receipts()
        asyncio.run(drain())
        assert nested == [], 'Explicitly selecting no skills must not call extraction/profile models.'
        ChoosingConnection.source_choices = choices
        saved = conversation.say(text)
        conversation.deliver_receipts()
        asyncio.run(drain())
        assert nested == phases
        assert all(meta['trace_name']=='memoir-atlas' for meta in nested_metadata)
        assert [meta['generation_name'] for meta in nested_metadata]==[
            'memoir-memory-context.profile' if phase=='profile_patch' else
            'memoir-author-timeline.extract' if 'memoir-author-timeline' in choices else 'memoir-place-journey.extract'
            for phase in phases]
        assert sql('select bool_and(processing_status=\'succeeded\') from public.user_narrator_source;').stdout.strip() == 't'
        if choices == ('memoir-memory-context',):
            assert sql('select profile->>\'birth_year\' from public.user_profile;').stdout.strip() == '1960'
            assert sql('select max(ordinal) from public.user_completed_round;').stdout.strip() == '2'
        if 'memoir-place-journey' in choices:
            assert sql('select journeys->0->>\'place\' from public.user_lifetime_place_journey;').stdout.strip() == 'Hobart'
            assert sql("select distinct skill from public.user_background_skill_work where phase='extract' and model_invoked;").stdout.strip() == 'memoir-place-journey'
        if 'memoir-memory-context' in choices and 'memoir-place-journey' in choices:
            assert sql('select profile->>\'name\' from public.user_profile;').stdout.strip() == 'Avery'
        if choices == ('memoir-author-timeline',):
            assert sql("select distinct skill from public.user_background_skill_work where phase='extract' and model_invoked;").stdout.strip() == 'memoir-author-timeline'
        assert saved['conversation_saved']


def test_background_agent_selects_skills_and_persists_results_after_the_reply(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',ControlledSkillConnection)
    install_document_provider(monkeypatch)
    ControlledSkillConnection.instances=[]
    ControlledSkillConnection.selected=[]
    conversation=Conversation(sql,tmp_path / 'conversation',monkeypatch,empty)
    with conversation.client:
        delivered=conversation.say('I repaired bicycles in our garden.')
        assert delivered['conversation_saved']
        conversation.deliver_receipts()
        run_id,=service(sql,'pending_memoir_background_agents')
        native_worker=CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
            base_url='http://synthetic.invalid',api_key='synthetic')
        app=FastAPI()
        @app.post('/internal/codex/turn')
        async def turn(payload:WorkerTurnInput):
            return await native_worker.turn(payload)
        async def scenario():
            worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
                worker_transport=httpx.ASGITransport(app=app))
            result=await worker.execute_background_agent(run_id)
            assert result['status']=='finished',result
        asyncio.run(scenario())
        assert 'memoir-author-timeline' in ControlledSkillConnection.selected
        assert 'memoir-interview-guidance' not in ControlledSkillConnection.selected
        assert sql("select count(*) from public.user_memoir_lane where skill='guidance';").stdout.strip()=='0'
        assert sql('select bool_and(processing_status=\'succeeded\') from public.user_narrator_source;').stdout.strip()=='t'
        assert sql('select token is null from public.user_memoir_background_agent;').stdout.strip()=='t'
        assert conversation.admissions==[], 'The old fixed worker request path must not execute the B work.'
        next_reply=conversation.say('What happens to my memories?')
        assert next_reply['conversation_saved']
