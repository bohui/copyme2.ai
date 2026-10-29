"""A durable Lane B run exposes only current, owner-scoped Memoir work to Codex."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
import re
from typing import Literal
from uuid import UUID

import httpx
from pydantic import Field

from .lifetime_memory_contracts import Contract
from .lifetime_memory_publication import PublicationUnavailable
from .prompt_artifact import load_prompt_artifact, prompt_path

LANE_SKILLS = {'timeline': 'memoir-author-timeline', 'composer': 'memoir-composer',
    'guidance': 'memoir-interview-guidance'}


class BackgroundAgentInput(Contract):
    id: UUID
    token: UUID
    user_id: UUID
    project_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    source_high_water: int = Field(ge=0, strict=True)
    policy_epoch: int = Field(ge=1, strict=True)
    preference_revision: int = Field(ge=0, strict=True)
    locale: Literal['en-AU', 'zh-CN'] = 'en-AU'
    selection: dict[str, str] | None = None


class BackgroundAgentPublication:
    def __init__(self, dsn, fence):
        if not dsn:
            raise PublicationUnavailable('Background agent requires canonical publication')
        self.dsn = dsn
        self.fence = BackgroundAgentInput.model_validate(fence).model_dump(mode='json')

    @asynccontextmanager
    async def connection(self):
        from psycopg import AsyncConnection, Error
        from psycopg.types.json import Jsonb
        connection = None
        try:
            async with asyncio.timeout(5):
                connection = await AsyncConnection.connect(self.dsn, connect_timeout=2)
                await connection.execute('set local role service_role')
                await connection.execute("select set_config('request.jwt.claim.sub',%s,true),"
                    "set_config('request.jwt.claim.role','service_role',true),set_config('lock_timeout','2s',true)",
                    (self.fence['user_id'],))
                remaining = await connection.execute('select public.lock_memoir_background_agent(%s)',
                    (Jsonb(self.fence),))
                if float((await remaining.fetchone())[0]) <= .1:
                    raise PublicationUnavailable('Background agent lease expires too soon')
            yield connection
            await connection.commit()
        except Error as error:
            raise PublicationUnavailable('Background agent is unavailable or stale') from error
        finally:
            if connection is not None:
                await asyncio.shield(connection.close())

    @asynccontextmanager
    async def guard(self, fence):
        if BackgroundAgentInput.model_validate(fence).model_dump(mode='json') != self.fence:
            raise PublicationUnavailable('Background agent scope changed')
        async with self.connection():
            async with asyncio.timeout(2):
                yield


class AgentBroker:
    """Host code uses domain RPCs; the model never supplies SQL or RPC names."""
    def __init__(self, publication):
        self.publication = publication

    async def rpc(self, name, **arguments):
        from psycopg.types.json import Jsonb
        if not all(re.fullmatch('[a-z][a-z0-9_]*', item) for item in (name, *arguments)):
            raise ValueError('Invalid background operation')
        values = [Jsonb(value) if isinstance(value, (dict, list)) else value for value in arguments.values()]
        parameters = ','.join(key + '=>%s' for key in arguments)
        async with self.publication.connection() as connection:
            result = await connection.execute('select public.' + name + '(' + parameters + ')', values)
            return (await result.fetchone())[0]


class LocalSkillTransport(httpx.AsyncBaseTransport):
    """Nested skill execution uses the background slot already held by its agent."""
    def __init__(self, worker, fence):
        self.worker, self.fence = worker, fence

    async def handle_async_request(self, request):
        from .codex_worker_service import WorkerTurnInput
        body = b''.join([chunk async for chunk in request.stream])
        if len(body) > 2_000_000 or request.url.path != '/internal/codex/turn':
            raise ValueError('Unavailable nested skill operation')
        payload = WorkerTurnInput.model_validate_json(body)
        if (payload.bounded_lane is None or str(payload.user_id) != self.fence['user_id']
                or payload.project_id != self.fence['project_id']):
            raise ValueError('Nested skill belongs to another background run')
        # This is a host-created call, after a scoped domain claim, never a public
        # worker endpoint or a second acquisition of the foreground capacity pool.
        result = await self.worker._turn(payload)
        return httpx.Response(200, json=result)


class BackgroundSkills:
    def __init__(self, fence, broker, event_worker, *, news_engine=None):
        self.fence, self.broker, self.event_worker = fence, broker, event_worker
        self.news_attempted = False
        self.news_engine = news_engine

    async def news_basis(self):
        if self.news_attempted or os.getenv('MEMORY_SPARK_HISTORICAL_NEWS', '').lower() not in {'1','true','yes'}:
            return None
        state = await self.broker.rpc('read_user_historical_news', p_project_id=self.fence['project_id'])
        if not state.get('enabled'):
            return None
        view = await self.broker.rpc('read_user_historical_news_basis', p_project_id=self.fence['project_id'])
        if not view:
            return None
        places = await self.broker.rpc('read_lifetime_place_journeys', p_project_id=self.fence['project_id'])
        if places:
            view['places'] = places
        from .historical_news import accepted_hypothesis
        hypothesis = accepted_hypothesis(view, selection=self.fence.get('selection'))
        return (view, hypothesis) if hypothesis else None

    async def work(self):
        current = await self.broker.rpc('read_memoir_background_work', p_fence=self.fence)
        work = [{'skill': LANE_SKILLS[row['skill']], 'required': True} for row in current['lanes']]
        if any(row['skill'] == 'timeline' for row in current['lanes']):
            for item in work:
                if item['skill'] != 'memoir-author-timeline':
                    item['depends_on'] = ['memoir-author-timeline']
        news = await self.news_basis()
        if news:
            work.append({'skill': 'memoir-historical-news-research', 'required': False,
                'public_context': {key: news[1][key] for key in ('place','start','end')}})
        return {'work': work}

    async def execute(self, name):
        current = await self.broker.rpc('read_memoir_background_work', p_fence=self.fence)
        lane = next((row for row in current['lanes'] if LANE_SKILLS[row['skill']] == name), None)
        if lane:
            result = await self.event_worker.execute_lane(lane['id'])
            return {'status': result['status']}
        if name != 'memoir-historical-news-research':
            return {'status': 'unavailable'}
        basis = await self.news_basis()
        if not basis:
            return {'status': 'unavailable'}
        self.news_attempted = True
        view, hypothesis = basis
        job = await self.broker.rpc('begin_user_historical_news', p_project_id=self.fence['project_id'],
            p_hypothesis=hypothesis, p_snapshot=view['news_snapshot'])
        if not job:
            return {'status': 'deferred_or_already_processed'}
        from .historical_news import HistoricalResearch
        from .historical_news_provider import GatewayHistoricalProvider
        from .background_skills import ServiceWork
        work = ServiceWork(name, 'place_selection', self.fence['user_id'], self.fence['project_id'],
            job['id'], research_job_id=job['id'])
        await work.update('running')
        if self.news_engine is None:
            self.news_engine = HistoricalResearch(GatewayHistoricalProvider())
        try:
            result = await self.news_engine.run(hypothesis)
        except asyncio.CancelledError:
            await work.update('failed')
            raise
        except Exception:
            result = {'status':'unavailable','clues':[],'failures':['research_unavailable']}
        saved = await self.broker.rpc('finish_user_historical_news', p_project_id=self.fence['project_id'],
            p_job_id=job['id'], p_result=result)
        cached = result.get('accounting',{}).get('cache') == 'hit'
        await work.update('failed' if not saved or result['status']=='unavailable' else 'cached' if cached else 'saved', cached=cached)
        return {'status': 'saved' if saved else 'stale', 'clues': len(result.get('clues', []))}


async def run_background_agent(worker, payload, *, publisher=None, broker=None, connection_factory=None):
    from .memory_event_worker import MemoryEventWorker
    from .memoir_skill_agent import run_skill_agent
    from .model_configuration import background_model, background_effort
    fence = payload.background_agent.model_dump(mode='json')
    publisher = publisher or BackgroundAgentPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'), fence)
    broker = broker or AgentBroker(publisher)
    executor = MemoryEventWorker(broker, worker_url='http://memoir-local-worker', worker_secret='local-capability',
        worker_transport=LocalSkillTransport(worker, fence))
    if os.getenv('MEMORY_SPARK_HISTORICAL_NEWS','').lower() in {'1','true','yes'} and not getattr(worker,'_news_engine',None):
        from .historical_news import HistoricalResearch
        from .historical_news_provider import GatewayHistoricalProvider
        worker._news_engine = HistoricalResearch(GatewayHistoricalProvider())
    skills = BackgroundSkills(fence, broker, executor, news_engine=getattr(worker,'_news_engine',None))
    names = list(LANE_SKILLS.values())
    if os.getenv('MEMORY_SPARK_HISTORICAL_NEWS','').lower() in {'1','true','yes'}:
        names.append('memoir-historical-news-research')
    work = await skills.work()
    if not work['work']:
        return {'reply':'{"status":"finished"}','thread_id':None,'artifacts':[],
            'pending':False,'model_invoked':False}
    instructions = load_prompt_artifact(prompt_path('memoir/shared/background-agent'))
    timeout = worker._execution_timeout('background_agent')
    result = await run_skill_agent(command=worker._run_command(worker._uid_for(fence['user_id'])),
        home_root=worker.home_root, base_url=worker.base_url, api_key=worker.api_key,
        model=background_model(), effort=background_effort(), instructions=instructions,
        packet={'lane': 'B', **work, 'locale': fence['locale'],
            'budget': {'max_tool_calls':32, 'seconds':timeout}}, skills=names,
        execute=skills.execute, work=skills.work, publisher=publisher, fence=fence,
        schema={'type':'object','additionalProperties':False,'properties':{'status':{'type':'string','const':'finished'}},'required':['status']},
        timeout=timeout, connection_factory=connection_factory,
        trace_name='memoir-background-agent',
        issue14_admission=worker._issue14_admission, uid=worker._uid_for(fence['user_id']),
        apply_owner=os.getenv('MEMORY_SPARK_DISABLE_PRIVDROP') != '1')
    # A model's final message never marks pending domain obligations complete.
    remaining = await skills.work()
    result['pending'] = any(item['required'] for item in remaining['work'])
    return result
