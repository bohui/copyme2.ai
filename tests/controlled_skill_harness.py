"""Scripted model choices at the Codex boundary, never live model evidence."""
import json
from uuid import uuid4


class ControlledSkillConnection:
    instances = []
    selected = []
    execute_optional = False
    only_optional = False

    def __init__(self, command, home, **options):
        self.options = options
        self.home = home
        self.thread_id = 'controlled-' + uuid4().hex
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def request(self, method, params):
        assert method == 'thread/start' and params['ephemeral']
        self.start = params
        async with self.options['request_admission']():
            return {'thread': {'id': self.thread_id}}

    async def tool(self, tool, **arguments):
        result = await self.options['tool_handler']({'threadId':self.thread_id,
            'turnId':'controlled-turn','tool':tool,'arguments':arguments})
        assert result['success'], result
        return json.loads(result['contentItems'][0]['text'])

    async def turn(self, thread_id, prompt, **options):
        async with self.options['request_admission']():
            pass
        value = json.loads(prompt)
        task = value['task']
        if task.get('lane') == 'B':
            work = task['work']
            tried = set()
            for _ in range(10):
                available = [item for item in work if (item['required'] or self.execute_optional)
                    and (not self.only_optional or not item['required']) and item['skill'] not in tried]
                if not available:
                    break
                selected = next((item for item in available if not item.get('depends_on')), available[0])['skill']
                self.selected.append(selected)
                await self.tool('memoir_read_skill', skill=selected)
                result = await self.tool('memoir_execute_skill', skill=selected)
                if result['status'] in {'deferred','unavailable','stale','retry_required'}:
                    tried.add(selected)
                work = (await self.tool('memoir_pending_work'))['work']
            return json.dumps({'status':'finished'})
        selected = value['available_skills'][0]['name']
        self.selected.append(selected)
        await self.tool('memoir_read_skill', skill=selected)
        fields = options['output_schema']['properties']
        if 'profile_patch' in fields:
            return json.dumps({'profile_patch':[]})
        if 'signals' in fields:
            return json.dumps({'signals':[],'prepared_questions':[],
                'acknowledgement_guidance':None,'strategy_proposal':None})
        return json.dumps({key:[] for key in ('events','place_journeys','continuity_updates',
            'event_places','passage_dispositions') if key in fields})


def run_optional_background(sql, project, tmp_path, monkeypatch, news_engine):
    """Run the real agent/worker/DB path with a scripted optional-news choice."""
    import asyncio
    from fastapi import FastAPI
    import httpx
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.memory_event_worker import MemoryEventWorker
    from test_background_profile_workflow import Broker
    from test_shared_memory_events_postgres import rpc, literal
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',ControlledSkillConnection)
    monkeypatch.setattr(ControlledSkillConnection,'execute_optional',True)
    monkeypatch.setattr(ControlledSkillConnection,'only_optional',True)
    monkeypatch.setattr(ControlledSkillConnection,'selected',[])
    run_id=rpc(sql,'queue_user_memoir_background_agent',literal(project))
    native=CodexWorker(home_root=tmp_path / 'optional-agent',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    native._news_engine=news_engine
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    async def scenario():
        worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
            worker_transport=httpx.ASGITransport(app=app))
        return await worker.execute_background_agent(run_id)
    result=asyncio.run(scenario())
    assert result['status'] in {'finished','pending'},result
    assert 'memoir-historical-news-research' in ControlledSkillConnection.selected
    return result
