"""Supabase-authenticated Codex conversation endpoints."""
import asyncio
import os
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .agent_lock import AgentTurnBusyError
from .agent_routes_support import authenticated_storage
from .codex_runtime import CodexRuntime
from .family_context import family_features_enabled, valid_family_project_id
from .place_journey import normalize_persisted_place_journey

router = APIRouter(prefix='/v1/agent', tags=['Codex agent'])
runtime = CodexRuntime()


class TurnInput(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    language: Literal['en-AU', 'zh-CN'] = 'en-AU'


class PlaceJourneyOutput(BaseModel):
    schema_version: Literal[1]
    status: Literal['active']
    revision: int = Field(ge=1)
    place: str
    hierarchy: list[str]
    granularity: Literal['country', 'region', 'city', 'suburb', 'landmark']
    latitude: float | None = None
    longitude: float | None = None
    duration_ms: int = Field(ge=2800, le=9000)
    updated_at: str


class PlaceJourneyResponse(BaseModel):
    place_journey: PlaceJourneyOutput | None


@router.get('/config')
def config():
    configured = bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_PUBLISHABLE_KEY'))
    show_thinking_steps = os.getenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    return {
        'enabled': configured,
        'auth_mode': 'supabase' if configured else ('test' if os.getenv('MEMORY_SPARK_TEST_MODE') == '1' else 'disabled'),
        'supabase_url': os.getenv('SUPABASE_URL'),
        'supabase_publishable_key': os.getenv('SUPABASE_PUBLISHABLE_KEY'),
        'show_thinking_steps': show_thinking_steps,
    }


@router.get('/place-journey', response_model=PlaceJourneyResponse)
async def place_journey(authorization: str | None = Header(default=None)):
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        record = await asyncio.to_thread(storage.place_journey)
        return {'place_journey': normalize_persisted_place_journey(record)}
    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        raise HTTPException(502, f'Supabase persistence failed: {error}') from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.post('/turn')
async def turn(payload: TurnInput, authorization: str | None = Header(default=None)):
    if payload.project_id is not None and valid_family_project_id(payload.project_id) is None:
        raise HTTPException(422, 'Invalid Family project id')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        return await runtime.turn(
            storage,
            payload.text,
            project_id=payload.project_id,
            language=payload.language,
        )
    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        raise HTTPException(502, f'Supabase persistence failed: {error}') from None
    except AgentTurnBusyError as error:
        raise HTTPException(409, str(error), headers={'X-Error-Code': 'AGENT_TURN_IN_PROGRESS'}) from None
    except RuntimeError as error:
        raise HTTPException(502, f'Codex agent failed: {error}') from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.get('/family-context')
async def family_context(project_id: str = Query(..., min_length=1, max_length=128),
                         authorization: str | None = Header(default=None)):
    if valid_family_project_id(project_id) is None:
        raise HTTPException(422, 'Invalid Family project id')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        entitlement = await asyncio.to_thread(storage.story_entitlement)
        enabled = family_features_enabled(entitlement)
        document = await asyncio.to_thread(storage.family_context, project_id) if enabled else None
        return {
            'project_id': project_id,
            'family_features_enabled': enabled,
            'family_context': document,
            'family_context_update': None,
        }
    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        raise HTTPException(502, f'Supabase persistence failed: {error}') from None
    finally:
        await asyncio.to_thread(storage.client.close)
