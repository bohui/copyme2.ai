"""Authenticated collection readiness, organising agent, and task results."""
import asyncio
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agent_lock import AgentTurnLease, AgentTurnBusyError
from .agent_routes_support import authenticated_storage
from .agent_tasks import TaskRequest
from .profile_intake import LIFE_STAGES
from .lifetime_memory_read_api import read_mapped, canonical_collection, mapped_identity
from .lifetime_memory_collection_jobs import update_selection, submit_selected_job, selected_job_result

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


def _require_canonical(storage, project_id):
    if mapped_identity(storage, project_id) is None:
        raise HTTPException(409, 'Open the saved canonical conversation first',
                            headers={'X-Error-Code': 'LIFETIME_IDENTITY_REQUIRED'})


@router.get('/collection/{project_id}')
def collection(project_id: str, cursor: UUID | None = None, task_cursor: UUID | None = None, limit: int = Query(default=8, ge=1, le=8),
               authorization: str | None = Header(default=None)):
    _project(project_id)
    storage = authenticated_storage(authorization)
    try:
        _require_canonical(storage, project_id)
        return read_mapped(storage, project_id,
            lambda fence: canonical_collection(storage, project_id, cursor=cursor, task_cursor=task_cursor, limit=limit))
    finally:
        storage.client.close()


@router.put('/collection/{project_id}')
async def update_collection(project_id: str, payload: CollectionUpdate,
                      authorization: str | None = Header(default=None)):
    _project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        async with AgentTurnLease(storage) as lease:
            await lease.io(_require_canonical, storage, project_id)
            return await lease.io(update_selection, storage, project_id, payload)
    except (AgentTurnBusyError, ValueError) as error:
        raise HTTPException(409, str(error)) from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.post('/collection/{project_id}/tasks', status_code=202)
async def publish_collection_task(project_id: str, payload: TaskRequest,
                                  authorization: str | None = Header(default=None)):
    _project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        await asyncio.to_thread(_require_canonical, storage, project_id)
        return await asyncio.to_thread(submit_selected_job, storage, project_id, payload)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except httpx.HTTPError:
        raise HTTPException(503, 'Task publisher unavailable; retry this request') from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.get('/tasks/{task_id}')
def task_result(task_id: str, cursor: UUID | None = None, limit: int = Query(default=8, ge=1, le=8),
                authorization: str | None = Header(default=None)):
    storage = authenticated_storage(authorization)
    try:
        governed = selected_job_result(storage, task_id, cursor=cursor, limit=limit)
        if governed is not None:
            return governed
        raise HTTPException(404, 'Task not found')
    finally:
        storage.client.close()


@router.post('/tasks/{task_id}/retry', status_code=202)
def retry_collection_task(task_id: UUID, authorization: str | None = Header(default=None)):
    storage = authenticated_storage(authorization)
    try:
        if mapped_identity(storage, None) is None:
            raise HTTPException(404, 'Task not found')
        from .lifetime_memory_collection_jobs import _owner_rpc
        value = _owner_rpc(storage, 'set_lifetime_collection_job_retry', p_job_id=str(task_id))
        return {key: value[key] for key in ('id', 'project_id', 'kind', 'status', 'attempts', 'error')}
    finally:
        storage.client.close()


@router.post('/collection/{project_id}/organise', status_code=202)
async def organise(project_id: str, payload: OrganiseInput,
                   authorization: str | None = Header(default=None)):
    _project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        async with AgentTurnLease(storage) as lease:
            await lease.io(_require_canonical, storage, project_id)
            entitlement = await lease.io(storage.story_entitlement)
            if getattr(storage, 'is_anonymous', False) or not entitlement or entitlement.get('status') != 'paid':
                raise HTTPException(402, 'A paid memoir entitlement is required for book organisation',
                                    headers={'X-Error-Code': 'PAYMENT_REQUIRED'})
            return await lease.io(submit_selected_job, storage, project_id, payload, organise=True)
    except AgentTurnBusyError:
        raise HTTPException(409, 'Another agent operation is in progress; retry shortly') from None
    except (ValueError, KeyError):
        raise HTTPException(502, 'Organising agent returned an invalid book structure') from None
    except httpx.HTTPError:
        raise HTTPException(503, 'Organising agent or persistence unavailable') from None
    finally:
        await asyncio.to_thread(storage.client.close)
