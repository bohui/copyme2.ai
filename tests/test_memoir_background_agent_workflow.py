"""Accepted conversation → background Codex tools → real canonical domain commits."""
import asyncio
import json
from pathlib import Path
import subprocess

import pytest

from fastapi import FastAPI
import httpx

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.memory_event_worker import MemoryEventWorker
from controlled_skill_harness import ControlledSkillConnection
from test_background_profile_workflow import database, Broker
from test_conversation_attribution import Conversation, empty
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_memoir_background_agent_postgres import service
from test_agent_commit_postgres import OWNER


@pytest.mark.parametrize('profile_first',[False,True])
def test_foreground_keeps_replying_while_background_finishes_then_batches_queued_narrations(sql,tmp_path,monkeypatch,profile_first):
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
            if task.get('lane') == 'B':
                batches.append(task['source_work']['sources'])
                if profile_first and len(batches)==1:
                    self.source_choices=('memoir-memory-context','memoir-author-timeline')
            else:
                is_profile='profile_patch' in options['output_schema']['properties']
                source=task['payload']['source'] if is_profile else task['payload']['sources'][0]
                if not is_profile:
                    originals.append(source)
                if not entered.is_set():
                    entered.set()
                    await release.wait()
                if is_profile:
                    output=json.loads(await super().turn(thread_id,prompt,**options))
                    output['profile_patch']=[{'field':'birth_place','value':'Hobart','source_refs':[{
                        'source_id':source['id'],'version':source['version'],'quote':source['text'],
                        'char_start':0,'char_end':len(source['text'])}]}]
                    return json.dumps(output)
            return await super().turn(thread_id,prompt,**options)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',SlowConnection)
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
        async def turn(self,thread_id,prompt,**options):
            value = json.loads(prompt)
            result = await super().turn(thread_id,prompt,**options)
            if value['task'].get('lane') != 'B':
                fields = options['output_schema']['properties']
                phase = 'profile_patch' if 'profile_patch' in fields else 'events'
                nested.append(phase)
                nested_metadata.append(options['responsesapi_client_metadata'])
                output = json.loads(result)
                if phase == 'profile_patch':
                    source = value['task']['payload']['source']
                    named = 'memoir-place-journey' in choices
                    quote = 'My name is Avery.' if named else source['text']
                    output['profile_patch'] = [{'field':'name' if named else 'birth_year','value':'Avery' if named else 1960,'source_refs':[{
                        'source_id':source['id'],'version':source['version'],'quote':quote,
                        'char_start':0,'char_end':len(quote)}]}]
                elif 'memoir-place-journey' in choices:
                    output['place_journeys'] = [{'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],
                        'granularity':'city','latitude':None,'longitude':None}]
                return json.dumps(output)
            return result
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
        assert all(meta['trace_name']=='memoir-background-agent' for meta in nested_metadata)
        assert [meta['generation_name'] for meta in nested_metadata]==[
            'memoir-memory-context' if phase=='profile_patch' else
            'memoir-author-timeline' if 'memoir-author-timeline' in choices else 'memoir-place-journey'
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
