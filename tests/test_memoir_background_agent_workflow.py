"""Accepted conversation → background Codex tools → real canonical domain commits."""
import asyncio
import json

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
    class ChoosingConnection(ControlledSkillConnection):
        source_choices = ()
        async def turn(self,thread_id,prompt,**options):
            value = json.loads(prompt)
            result = await super().turn(thread_id,prompt,**options)
            if value['task'].get('lane') != 'B':
                fields = options['output_schema']['properties']
                phase = 'profile_patch' if 'profile_patch' in fields else 'events'
                nested.append(phase)
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
