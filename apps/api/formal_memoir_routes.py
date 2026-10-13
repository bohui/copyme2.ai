"""Authenticated, metadata-only formal composition and adaptation controls.

Database RPCs own all authority. No browser completion flags, source payloads or
generated manuscript/game content are accepted or delivered by these endpoints.
"""
import asyncio
import hmac
import os
import re
from uuid import UUID
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agent_routes_support import authenticated_storage
from .conversation_recovery import PROJECT_ID_PATTERN

router = APIRouter(tags=['Formal memoir'])


class BeginFormalMemoir(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_phase_revision: int = Field(ge=0, strict=True)
    expected_revision: int = Field(ge=0, strict=True)
    request_id: UUID


class StoryGameConsent(BaseModel):
    model_config = {'extra': 'forbid'}
    edition_id: UUID
    expected_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_revision: int = Field(ge=0, strict=True)
    action: Literal['grant', 'revoke']


def _rpc_error(error):
    try:
        failure = error.response.json()
        code, message = failure.get('code'), failure.get('message')
    except (ValueError, AttributeError):
        code, message = None, None
    gates = {
        'FORMAL_PRIVACY_REVIEW_REQUIRED': 'Review memoir privacy choices before composing.',
        'FORMAL_EXTRACTION_INCOMPLETE': 'Your memories are still being prepared.',
        'FORMAL_EVIDENCE_REQUIRED': 'Add supported memories before composing.',
        'FORMAL_SHAPE_REQUIRED': 'Choose Shape before composing.',
        'FORMAL_PLAN_CAPACITY_REQUIRED': 'This memoir needs a reviewed chapter plan.',
        'FORMAL_CHAPTER_CAPACITY_REQUIRED': 'This memoir needs a reviewed chapter plan.',
    }
    if isinstance(code, str) and isinstance(message, str) and code in {'40001', '55000'} and message in gates:
        return HTTPException(409, gates[message], headers={'X-Error-Code': message})
    if code == '40001' or error.response.status_code == 409:
        return HTTPException(409, 'Memoir authority changed; reload and retry.')
    if code == '42501' or error.response.status_code in (401, 403):
        return HTTPException(403, 'Memoir unavailable.')
    return HTTPException(503, 'Memoir controls are temporarily unavailable.')


async def _owned_rpc(project_id, authorization, name, parameters, *, status_code=200):
    if not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise HTTPException(422, 'Invalid project')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        response = await asyncio.to_thread(storage.request, 'POST', '/rest/v1/rpc/' + name,
                                         json={'p_project_id': project_id, **parameters})
        return JSONResponse(response.json(), status_code=status_code, headers={'Cache-Control': 'no-store'})
    except httpx.HTTPStatusError as error:
        raise _rpc_error(error) from None
    except httpx.RequestError:
        raise HTTPException(503, 'Memoir controls are temporarily unavailable.') from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.post('/projects/{project_id}/formal-memoir', status_code=202)
async def begin_formal_memoir(project_id: str, payload: BeginFormalMemoir,
                             authorization: str | None = Header(default=None)):
    return await _owned_rpc(project_id, authorization, 'begin_formal_memoir', {
        'p_expected_phase_revision': payload.expected_phase_revision,
        'p_expected_revision': payload.expected_revision, 'p_request_id': str(payload.request_id)}, status_code=202)


@router.get('/projects/{project_id}/formal-memoir')
async def read_formal_memoir_status(project_id: str, authorization: str | None = Header(default=None)):
    return await _owned_rpc(project_id, authorization, 'read_formal_memoir_status', {})


@router.put('/projects/{project_id}/story-game/consent')
async def set_story_game_consent(project_id: str, payload: StoryGameConsent,
                                 authorization: str | None = Header(default=None)):
    return await _owned_rpc(project_id, authorization, 'set_story_game_consent', {
        'p_edition_id': str(payload.edition_id), 'p_expected_digest': payload.expected_digest,
        'p_expected_revision': payload.expected_revision, 'p_action': payload.action})


@router.get('/projects/{project_id}/story-game/eligibility')
async def read_story_game_eligibility(project_id: str, authorization: str | None = Header(default=None)):
    # Metadata is a point-in-time indication, never a grant to dispatch or deliver.
    return await _owned_rpc(project_id, authorization, 'read_story_game_eligibility', {})


@router.post('/internal/formal-memoirs/{run_id}/advance', include_in_schema=False)
async def advance_formal_memoir_run(run_id: UUID, x_codex_worker_secret: str | None = Header(default=None)):
    expected = os.getenv('MEMORY_SPARK_CODEX_WORKER_SECRET', '')
    if not expected or not x_codex_worker_secret or not hmac.compare_digest(expected, x_codex_worker_secret):
        raise HTTPException(401, 'Invalid task publisher credentials')
    from .formal_memoir import advance_formal_memoir
    from .memory_event_worker import MemoirLaneBroker
    if not os.getenv('SUPABASE_URL') or not os.getenv('SUPABASE_SECRET_KEY'):
        raise HTTPException(503, 'Formal memoir worker is unavailable.')
    broker = MemoirLaneBroker()
    try:
        result = await advance_formal_memoir(broker, run_id)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except httpx.HTTPStatusError as error:
        raise _rpc_error(error) from None
    except (httpx.RequestError, ValueError, KeyError, TimeoutError):
        raise HTTPException(503, 'Formal memoir work was not completed; retry the same run.') from None
    finally:
        await broker.client.aclose()
