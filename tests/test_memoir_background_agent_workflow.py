"""Accepted conversation → background Codex tools → real canonical domain commits."""
import asyncio

from fastapi import FastAPI
import httpx

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.memory_event_worker import MemoryEventWorker
from controlled_skill_harness import ControlledSkillConnection
from test_background_profile_workflow import database, Broker
from test_conversation_attribution import Conversation, empty
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_memoir_background_agent_postgres import service


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
        assert 'memoir-interview-guidance' in ControlledSkillConnection.selected
        assert sql('select bool_and(processing_status=\'succeeded\') from public.user_narrator_source;').stdout.strip()=='t'
        assert sql('select token is null from public.user_memoir_background_agent;').stdout.strip()=='t'
        assert conversation.admissions==[], 'The old fixed worker request path must not execute the B work.'
        next_reply=conversation.say('What happens to my memories?')
        assert next_reply['conversation_saved']
