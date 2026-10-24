"""Project game URLs with owner, public and email-bound invited-player access."""
import asyncio
import re
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from .agent_routes_support import authenticated_storage
from .conversation_recovery import PROJECT_ID_PATTERN
from .formal_memoir_routes import _rpc_error
from .story_game_routes import StoryGameResponse

router = APIRouter(prefix='/v1/story-games', tags=['Story game pages'])


class Revision(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_revision: int = Field(ge=1, strict=True)


class Visibility(Revision):
    visibility: Literal['private', 'friends', 'public']


class Invitation(Revision):
    email: str = Field(max_length=254, pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class AcceptInvitation(BaseModel):
    model_config = {'extra': 'forbid'}
    token: str = Field(pattern=r'^[a-f0-9]{64}$')


def valid_project(project_id):
    if not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise HTTPException(422, 'Invalid project')


async def owner_rpc(project_id, authorization, name, **parameters):
    valid_project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        response = await asyncio.to_thread(storage.request, 'POST', '/rest/v1/rpc/' + name,
            json={'p_project_id': project_id, **parameters})
        return JSONResponse(response.json(), headers={'Cache-Control': 'private, no-store'})
    except httpx.HTTPStatusError as error:
        try:
            code = error.response.json().get('code')
        except (ValueError, AttributeError):
            code = None
        if code == 'PT404':
            raise HTTPException(404, 'Game or invitation unavailable.') from None
        raise _rpc_error(error) from None
    except httpx.RequestError:
        raise HTTPException(503, 'Game controls are temporarily unavailable.') from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.get('/{project_id}')
async def game_page(project_id: str, authorization: str | None = Header(default=None)):
    valid_project(project_id)
    viewer = None
    if authorization:
        storage = await asyncio.to_thread(authenticated_storage, authorization)
        try:
            viewer = storage.user_id
        finally:
            await asyncio.to_thread(storage.client.close)
    return StoryGameResponse(viewer, project_id)


@router.put('/{project_id}/visibility')
async def visibility(project_id: str, payload: Visibility, authorization: str | None = Header(default=None)):
    return await owner_rpc(project_id, authorization, 'set_story_game_visibility',
        p_visibility=payload.visibility, p_expected_revision=payload.expected_revision)


@router.post('/{project_id}/invitations')
async def invite(project_id: str, payload: Invitation, authorization: str | None = Header(default=None)):
    return await owner_rpc(project_id, authorization, 'invite_story_game_viewer',
        p_email=payload.email, p_expected_revision=payload.expected_revision)


@router.post('/{project_id}/invitations/accept')
async def accept(project_id: str, payload: AcceptInvitation, authorization: str | None = Header(default=None)):
    return await owner_rpc(project_id, authorization, 'accept_story_game_invitation', p_token=payload.token)


@router.post('/{project_id}/invitations/{invitation_id}/revoke')
async def revoke(project_id: str, invitation_id: UUID, payload: Revision, authorization: str | None = Header(default=None)):
    return await owner_rpc(project_id, authorization, 'revoke_story_game_invitation',
        p_invitation_id=str(invitation_id), p_expected_revision=payload.expected_revision)
