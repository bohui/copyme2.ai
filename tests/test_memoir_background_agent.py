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


def test_agent_can_choose_guidance_before_composer_and_refresh_current_work(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    async def scenario():
        pending=[{'id':'composer-id','skill':'composer'},{'id':'guidance-id','skill':'guidance'}]
        executed=[]
        class Broker:
            async def rpc(self,name,**arguments):
                assert name=='read_memoir_background_work'
                return {'lanes':list(pending),'selection':None}
        class Executor:
            async def execute_lane(self,lane_id):
                executed.append(lane_id)
                pending[:]=[row for row in pending if row['id']!=lane_id]
                return {'status':'finished'}
        skills=BackgroundSkills(fence(),Broker(),Executor())
        assert [item['skill'] for item in (await skills.work())['work']]==['memoir-composer','memoir-interview-guidance']
        await skills.execute('memoir-interview-guidance')
        assert executed==['guidance-id']
        assert [item['skill'] for item in (await skills.work())['work']]==['memoir-composer']
        assert await skills.execute('memoir-story-game')=={'status':'unavailable'}
        assert executed==['guidance-id']
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
