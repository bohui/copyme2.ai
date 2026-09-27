"""Authenticated collection readiness, organising agent, and task results."""
import asyncio
import hashlib
import json
import os
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_lock import AgentTurnLease, AgentTurnBusyError
from .agent_routes_support import authenticated_storage
from .agent_tasks import BookStructure, TaskRequest, resolve_task
from .codex_runtime import CodexRuntime
from .memoir_tasks import MemoirTask, MemorySource
from .profile_intake import LIFE_STAGES
from .task_queue import configured_queue

router = APIRouter(prefix='/v1/agent', tags=['Memory collection'])


class PeriodCoverage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['recorded', 'skipped', 'not_applicable']
    memory_ids: list[str] = Field(default_factory=list, max_length=1000)
    note: str = Field(default='', max_length=500)

    @model_validator(mode='after')
    def validate_coverage(self):
        if self.status == 'recorded' and not self.memory_ids:
            raise ValueError('A recorded period requires saved memories')
        if self.status != 'recorded' and not self.note.strip():
            raise ValueError('Explain a skipped or inapplicable period')
        return self


class CollectionUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_revision: int = Field(ge=0)
    periods: dict[str, PeriodCoverage]
    confirm_ready: bool = False

    @model_validator(mode='after')
    def validate_periods(self):
        if not set(self.periods).issubset(LIFE_STAGES):
            raise ValueError('Unknown life stage')
        if self.confirm_ready and set(self.periods) != LIFE_STAGES:
            raise ValueError('Record or explicitly skip every life stage before confirming readiness')
        if self.confirm_ready and not any(p.status == 'recorded' for p in self.periods.values()):
            raise ValueError('At least one recorded period is required')
        return self


class OrganiseInput(BaseModel):
    expected_revision: int = Field(ge=1)
    language: Literal['en-AU', 'zh-CN'] = 'en-AU'


def _project(value):
    from .family_context import valid_family_project_id
    if valid_family_project_id(value) is None:
        raise HTTPException(422, 'Invalid project id')
    return value


def _queue():
    if not os.getenv('MEMORY_SPARK_TASK_DB'):
        raise HTTPException(503, 'Background tasks are not configured')
    return configured_queue()


def _sources(storage):
    reader = getattr(storage, 'all_memories', storage.memories)
    try:
        return CodexRuntime._task_sources(reader())
    except ValueError:
        raise HTTPException(422, 'Collection exceeds the supported memory limit') from None


def _source_fingerprint(sources):
    snapshot = [source.model_dump() for source in sorted(sources, key=lambda source: source.id)]
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


@router.get('/collection/{project_id}')
def collection(project_id: str, authorization: str | None = Header(default=None)):
    _project(project_id)
    storage = authenticated_storage(authorization)
    try:
        return {**_queue().collection(storage.user_id, project_id),
                'sources': [source.model_dump() for source in _sources(storage)],
                'tasks': _queue().list(storage.user_id, project_id)}
    finally:
        storage.client.close()


@router.put('/collection/{project_id}')
async def update_collection(project_id: str, payload: CollectionUpdate,
                      authorization: str | None = Header(default=None)):
    _project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        async with AgentTurnLease(storage) as lease:
            sources = await lease.io(_sources, storage)
            source_ids = {source.id for source in sources}
            requested = {key for period in payload.periods.values() for key in period.memory_ids}
            if not requested.issubset(source_ids):
                raise HTTPException(422, 'Collection references an unavailable memory')
            await lease.check()
            return await lease.io(_queue().update_collection, storage.user_id, project_id,
                periods={key: period.model_dump() for key, period in payload.periods.items()},
                ready=payload.confirm_ready, expected_revision=payload.expected_revision,
                source_fingerprint=_source_fingerprint(sources) if payload.confirm_ready else None)
    except (AgentTurnBusyError, ValueError) as error:
        raise HTTPException(409, str(error)) from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.post('/collection/{project_id}/tasks', status_code=202)
async def publish_collection_task(project_id: str, payload: TaskRequest,
                                  authorization: str | None = Header(default=None)):
    _project(project_id)
    _queue()
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        task = resolve_task(payload, await asyncio.to_thread(_sources, storage))
        return await CodexRuntime().publish_task(storage.user_id, project_id, task)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except httpx.HTTPError:
        raise HTTPException(503, 'Task publisher unavailable; retry this request') from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.get('/tasks/{task_id}')
def task_result(task_id: str, authorization: str | None = Header(default=None)):
    storage = authenticated_storage(authorization)
    try:
        task = _queue().get(storage.user_id, task_id)
        if task is None:
            raise HTTPException(404, 'Task not found')
        return task
    finally:
        storage.client.close()


@router.post('/collection/{project_id}/organise', status_code=202)
async def organise(project_id: str, payload: OrganiseInput,
                   authorization: str | None = Header(default=None)):
    _project(project_id)
    queue = _queue()
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        async with AgentTurnLease(storage) as lease:
            document = await asyncio.to_thread(queue.collection, storage.user_id, project_id)
            if not document['ready'] or document['revision'] != payload.expected_revision:
                raise HTTPException(409, 'Confirm the current timeline before organising the book')
            entitlement = await lease.io(storage.story_entitlement)
            if getattr(storage, 'is_anonymous', False) or not entitlement or entitlement.get('status') != 'paid':
                raise HTTPException(402, 'A paid memoir entitlement is required for book organisation',
                                    headers={'X-Error-Code': 'PAYMENT_REQUIRED'})
            sources = await lease.io(_sources, storage)
            if document.get('source_fingerprint') != _source_fingerprint(sources):
                raise HTTPException(409, 'Saved memories changed; review and confirm the collection again')
            chosen = {key for period in document['periods'].values() for key in period['memory_ids']}
            sources = [source for source in sources if source.id in chosen]
            if not sources or {source.id for source in sources} != chosen:
                raise HTTPException(409, 'Collection sources changed; review the timeline again')
            if sum(len(source.content) for source in sources) > 120000:
                raise HTTPException(422, 'This collection exceeds the current organising context limit')
            runtime = CodexRuntime()
            if not runtime.worker_url or not runtime.worker_secret:
                raise HTTPException(503, 'Organising agent unavailable')
            async with httpx.AsyncClient(timeout=runtime.timeout + 15) as client:
                response = await client.post(f'{runtime.worker_url}/internal/codex/turn',
                    headers={'X-Codex-Worker-Secret': runtime.worker_secret},
                    json={'user_id': storage.user_id, 'project_id': project_id,
                          'text': 'Propose the book structure for this confirmed collection.',
                          'agent_role': 'organiser', 'language': payload.language,
                          'task_sources': [source.model_dump() for source in sources]})
                response.raise_for_status()
                structure = BookStructure.model_validate_json(response.json()['reply'])
            await lease.check()
            current = await asyncio.to_thread(queue.collection, storage.user_id, project_id)
            if current != document:
                raise HTTPException(409, 'Collection changed during organisation; review it again')
            referenced = {key for section in structure.sections for key in section.memory_ids}
            if referenced != chosen:
                raise HTTPException(502, 'Organising agent omitted or invented a source reference')
            task = MemoirTask(kind='BuildOutline', title=structure.title,
                              sources=sources, sections=structure.sections)
            return await runtime.publish_task(storage.user_id, project_id, task)
    except AgentTurnBusyError:
        raise HTTPException(409, 'Another agent operation is in progress; retry shortly') from None
    except (ValueError, KeyError):
        raise HTTPException(502, 'Organising agent returned an invalid book structure') from None
    except httpx.HTTPError:
        raise HTTPException(503, 'Organising agent or persistence unavailable') from None
    finally:
        await asyncio.to_thread(storage.client.close)
