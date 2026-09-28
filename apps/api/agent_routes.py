"""Supabase-authenticated Codex conversation endpoints."""
import asyncio
from datetime import date
import os
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from .turn_stream import STREAM_HEADERS, turn_events

from .agent_lock import AgentTurnBusyError, AgentTurnLease
from .agent_routes_support import authenticated_storage
from .codex_runtime import CodexRuntime
from .family_context import family_features_enabled, valid_family_project_id
from .place_journey import normalize_persisted_place_journey

router = APIRouter(prefix='/v1/agent', tags=['Codex agent'])
runtime = CodexRuntime()


class TurnInput(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    # The UI locale is not the interview language.  Omit this when the
    # storyteller has not explicitly chosen a conversation language so the
    # runtime can infer it from the conversation without changing the UI.
    language: Literal['en-AU', 'zh-CN'] | None = None


class ProfileSettingsInput(BaseModel):
    preferred_language: Literal['en-AU', 'zh-CN'] | None = None
    name: str | None = Field(default=None, max_length=120)
    birth_year: int | None = Field(default=None, ge=1800, le=date.today().year)
    birth_place: str | None = Field(default=None, max_length=160)
    childhood_place: str | None = Field(default=None, max_length=160)


@router.get('/profile')
async def read_profile_settings(authorization: str | None = Header(default=None)):
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        profile = await asyncio.to_thread(storage.profile)
        return {key: profile.get(key) for key in ProfileSettingsInput.model_fields}
    finally:
        await asyncio.to_thread(storage.client.close)


@router.patch('/profile')
async def update_profile_settings(payload: ProfileSettingsInput, authorization: str | None = Header(default=None)):
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        async with AgentTurnLease(storage) as lease:
            profile = await lease.io(storage.profile)
            for key, value in payload.model_dump(exclude_unset=True).items():
                if isinstance(value, str):
                    value = value.strip() or None
                if value is None:
                    profile.pop(key, None)
                else:
                    profile[key] = value
            await lease.check()
            await lease.io(storage.save_profile, profile)
            return {key: profile.get(key) for key in ProfileSettingsInput.model_fields}
    except AgentTurnBusyError:
        raise HTTPException(409, 'Please wait for the current reply to finish before saving your profile.') from None
    finally:
        await asyncio.to_thread(storage.client.close)


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
async def turn(payload: TurnInput, authorization: str | None = Header(default=None),
               accept: str = Header(default='application/json')):
    if payload.project_id is not None and valid_family_project_id(payload.project_id) is None:
        raise HTTPException(422, 'Invalid Family project id')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    if 'application/x-ndjson' in accept:
        return StreamingResponse(
            turn_events(lambda emit: runtime.turn(storage, payload.text, project_id=payload.project_id,
                                                 language=payload.language, on_delta=emit,
                                                 on_event=emit.event),
                        cleanup=lambda: asyncio.to_thread(storage.client.close)),
            media_type='application/x-ndjson', headers=STREAM_HEADERS,
        )
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
