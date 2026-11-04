"""Agent decisions use capability tools; model output cannot claim a saved result."""
import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api.codex_worker_service import WorkerTurnInput
from apps.api.memoir_background_agent import BackgroundAgentInput, BackgroundSkills, LocalSkillTransport


def fence():
    return BackgroundAgentInput(id=UUID(int=1),token=UUID(int=2),user_id=UUID(int=3),
        project_id='project',source_high_water=1,policy_epoch=1,preference_revision=0).model_dump(mode='json')


@pytest.mark.parametrize('patch', [
    {'user_id':str(UUID(int=999))}, {'project_id':'foreign'}, {'agent_role':'collector'},
    {'text':'private legacy context'}, {'profile':{'name':'invented'}},
    {'extra_instructions':'bypass'}, {'thread_id':'another-agent'},
])
def test_background_dispatch_requires_exact_owner_project_and_no_legacy_context(patch):
    current=fence()
    with pytest.raises(ValueError):
        WorkerTurnInput(**{**{'user_id':current['user_id'],'project_id':'project',
            'agent_role':'background_agent','background_agent':current},**patch})


def test_agent_executes_saved_work_without_offering_retired_interview_guidance(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    async def scenario():
        pending=[{'id':'composer-id','skill':'composer'},{'id':'timeline-id','skill':'timeline'},
            {'id':'retired-guidance','skill':'guidance'}]
        executed=[]
        class Broker:
            async def rpc(self,name,**arguments):
                assert name=='read_memoir_background_work'
                return {'lanes':list(pending),'selection':None}
        class Executor:
            async def execute_lane(self,lane_id,**options):
                executed.append(lane_id)
                if lane_id=='timeline-id':
                    assert options=={'source_work':{'source':None,'skills':[]}}
                pending[:]=[row for row in pending if row['id']!=lane_id]
                return {'status':'finished'}
        skills=BackgroundSkills(fence(),Broker(),Executor())
        assert [item['skill'] for item in (await skills.work())['work']]==['memoir-composer','memoir-author-timeline']
        assert await skills.execute('memoir-interview-guidance')=={'status':'unavailable'}
        assert executed==[]
        await skills.execute('memoir-author-timeline')
        assert executed==['timeline-id']
        assert [item['skill'] for item in (await skills.work())['work']]==['memoir-composer']
        assert await skills.execute('memoir-story-game')=={'status':'unavailable'}
        assert executed==['timeline-id']
    asyncio.run(scenario())


def test_nested_skill_cannot_cross_project_or_start_another_agent():
    import httpx
    async def scenario():
        current=fence()
        transport=LocalSkillTransport(SimpleNamespace(),current)
        request=httpx.Request('POST','http://local/internal/codex/turn',json={
            'user_id':current['user_id'],'project_id':'project','agent_role':'background_agent',
            'background_agent':current})
        with pytest.raises(ValueError,match='Nested skill'):
            await transport.handle_async_request(request)
    asyncio.run(scenario())


def test_source_choices_apply_only_to_the_original_window_returned_to_the_agent(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    async def scenario():
        source = {'id':'original','version':1,'text':'Hello.','char_start':0,'char_end':6}
        seen = []
        class Broker:
            async def rpc(self,name,**arguments):
                return {'lanes':[{'id':'lane','skill':'timeline'}],
                    'source_work':{'source':dict(source),'available_skills':['memoir-author-timeline']}}
        class Executor:
            async def execute_lane(self,lane_id,**arguments):
                seen.append(arguments)
                return {'status':'finished'}
        skills = BackgroundSkills(fence(),Broker(),Executor())
        await skills.work()
        assert await skills.execute('memoir-author-timeline') == {'status':'source_selection_required'}
        source['id'] = 'different-original'
        assert await skills.process_source([]) == {'status':'stale'}
        assert seen == []
        await skills.work()
        assert await skills.process_source([]) == {'status':'finished'}
        assert seen[0]['source_work']['source']['id'] == 'different-original'
        assert await skills.process_source([]) == {'status':'stale'}
    asyncio.run(scenario())


def test_failed_news_research_is_visible_even_when_its_unavailable_result_is_saved(monkeypatch):
    from unittest.mock import AsyncMock
    from apps.api import llm_tracing
    from test_llm_tracing import FakeLangfuse
    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS','1')
    monkeypatch.setattr('apps.api.background_skills.ServiceWork.update',AsyncMock())
    client=FakeLangfuse()
    monkeypatch.setattr(llm_tracing,'_client_cache',client)
    class Broker:
        async def rpc(self,name,**arguments):
            return {'lanes':[]} if name=='read_memoir_background_work' else {'id':'research-job'} if name=='begin_user_historical_news' else True
    skills=BackgroundSkills(fence(),Broker(),None,news_engine=SimpleNamespace(run=AsyncMock(return_value={
        'status':'unavailable','clues':[]})))
    skills.news_basis=AsyncMock(return_value=({'news_snapshot':{}},{'place':'Hobart','start':1960,'end':1970}))
    assert asyncio.run(skills.execute('memoir-historical-news-research'))['status']=='saved'
    attempt=next(o for o in client.observations if o.fields['metadata']['phase']=='research')
    assert attempt.fields['name']=='memoir-historical-news-research.research'
    assert attempt.updates[-1]['metadata']['status']=='failed'


@pytest.mark.parametrize('evaluation', [{}, {'case_id': 'trace-origin-test'}])
def test_worker_test_names_are_bound_to_the_dispatched_owner(tmp_path, monkeypatch, evaluation):
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.llm_tracing import gateway_metadata
    from test_lifetime_memory_engine import fixture, IDENTITY
    governed, context = fixture()
    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setenv('MEMORY_SPARK_TRACE_ORIGIN', 'test')
    monkeypatch.setenv('MEMORY_SPARK_TRACE_ORIGIN_OWNER_ID', str(IDENTITY.owner_id))
    async def observe(payload):
        return gateway_metadata('memoir-mira.reply', trace_name='memoir-mira')
    monkeypatch.setattr(worker, '_turn', observe)
    payload = WorkerTurnInput(user_id=IDENTITY.owner_id, project_id=IDENTITY.project_id,
        governed=governed, interview_context=context, evaluation=evaluation)
    result = asyncio.run(worker.turn(payload))
    session = result.pop('session_id')
    assert session.startswith('memoir-') and str(IDENTITY.owner_id) not in session
    prefix = 'evaluation/' if evaluation else 'test/'
    assert result == {'generation_name': prefix+'memoir-mira.reply', 'trace_name': prefix+'memoir-mira'}
    monkeypatch.setenv('MEMORY_SPARK_TRACE_ORIGIN_OWNER_ID', str(UUID(int=42)))
    result = asyncio.run(worker.turn(payload))
    assert result.pop('session_id') == session
    prefix = 'evaluation/' if evaluation else ''
    assert result == {'generation_name': prefix+'memoir-mira.reply', 'trace_name': prefix+'memoir-mira'}


def test_slow_background_agent_does_not_take_foreground_capacity(tmp_path,monkeypatch):
    from apps.api.codex_worker_service import CodexWorker
    from test_lifetime_memory_engine import fixture as collector_fixture, IDENTITY
    monkeypatch.setenv('MEMOIR_TWO_LANES','1')
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    async def scenario():
        worker=CodexWorker(home_root=tmp_path,model='synthetic-byte-bpe')
        entered, release = asyncio.Event(), asyncio.Event()
        async def execute(payload,**options):
            if payload.background_agent:
                entered.set()
                await release.wait()
                return {'reply':'background'}
            return {'reply':'foreground'}
        worker._turn=execute
        current={**fence(),'project_id':IDENTITY.project_id}
        background=WorkerTurnInput(user_id=current['user_id'],project_id=IDENTITY.project_id,
            agent_role='background_agent',background_agent=current)
        governed,context=collector_fixture()
        foreground=WorkerTurnInput(user_id=IDENTITY.owner_id,project_id=IDENTITY.project_id,
            governed=governed,interview_context=context,model='synthetic-byte-bpe')
        pending=asyncio.create_task(worker.turn(background))
        try:
            await asyncio.wait_for(entered.wait(),1)
            assert await asyncio.wait_for(worker.turn(foreground),1)=={'reply':'foreground'}
            assert not pending.done()
        finally:
            release.set()
            await pending
    asyncio.run(scenario())


@pytest.mark.parametrize('status,code,successful_yield',[
    (503,'LIFETIME_POLICY_PENDING',True),
    (503,'UNRELATED_UNAVAILABLE',False),
    (502,'LIFETIME_POLICY_PENDING',False),
])
def test_only_the_typed_policy_pause_preserves_background_failure_budget(status,code,successful_yield):
    import httpx
    from apps.api.memory_event_worker import MemoryEventWorker
    current=fence()
    finished=[]
    class Broker:
        async def rpc(self,name,**arguments):
            if name=='claim_memoir_background_agent':return current
            assert name=='finish_memoir_background_agent'
            finished.append(arguments)
            return {'status':'pending','pending':True}
    worker=MemoryEventWorker(Broker(),worker_url='http://synthetic.invalid',worker_secret='synthetic',
        worker_transport=httpx.MockTransport(lambda request:httpx.Response(status,
            headers={'X-Error-Code':code},json={'detail':'Unavailable'})))
    result=asyncio.run(worker.execute_background_agent(current['id']))
    assert result=={'status':'pending','pending':True}
    assert finished==[{'p_id':current['id'],'p_token':current['token'],'p_success':successful_yield}]
