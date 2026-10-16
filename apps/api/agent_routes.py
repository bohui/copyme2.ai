"""Supabase-authenticated Codex conversation endpoints."""
import asyncio
from datetime import date
import os
import re
from uuid import UUID, uuid4
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from .agent_lock import AgentTurnBusyError, AgentTurnLease
from .lifetime_memory_publication import PublicationUnavailable
from .agent_routes_support import authenticated_storage
from .codex_runtime import CodexRuntime
from .conversation_recovery import PROJECT_ID_PATTERN, TurnReceipt, turn_receipt
from .family_context import family_features_enabled, valid_family_project_id
from .family_photos import MAX_PHOTO_BYTES, family_person, portrait_bytes, save_person_photo, with_photo_urls
from .place_journey import normalize_persisted_place_journey
from .workspace_memory_actions import WorkspaceMemoryFocus
from .formal_memoir_routes import router as formal_memoir_router

router = APIRouter(prefix='/v1/agent', tags=['Codex agent'])
router.include_router(formal_memoir_router)
runtime = CodexRuntime()


class TurnInput(BaseModel):
    text: str = Field(default="", max_length=100000)
    client_turn_id: UUID | None = None
    conversation_text: str | None = Field(default=None, max_length=100000)
    source_kind: Literal['narrator_chat', 'narrator_transcript'] = 'narrator_chat'
    recording_ids: list[UUID] = Field(default_factory=list, max_length=20)
    uploaded_photo_ids: list[UUID] = Field(default_factory=list, max_length=5)
    photo_selection: dict | None = None
    workspace_focus: WorkspaceMemoryFocus | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    # The UI locale is not the interview language.  Omit this when the
    # storyteller has not explicitly chosen a conversation language so the
    # runtime can infer it from the conversation without changing the UI.
    language: Literal['en-AU', 'zh-CN'] | None = None
    # The browser sends this only for the first onboarding answer. It is a
    # compatibility hint. The server's durable first-reply state decides
    # whether detection is still eligible; this cannot override saved settings.
    first_reply_localization: bool = False


    @model_validator(mode='after')
    def require_narration_or_photo(self):
        original = self.conversation_text if self.conversation_text is not None else self.text
        if not original.strip() and not self.uploaded_photo_ids and not self.photo_selection:
            raise ValueError('Enter an answer or select a photo')
        if (self.uploaded_photo_ids or self.photo_selection) and not self.project_id:
            raise ValueError('Photo cues require an interview project')
        if len(self.recording_ids) != len(set(self.recording_ids)):
            raise ValueError('Duplicate recording reference')
        if self.recording_ids and (self.source_kind != 'narrator_transcript' or not original.strip()):
            raise ValueError('Recordings require a narrator transcript')
        if self.photo_selection is not None:
            if (set(self.photo_selection) != {'key', 'revision'}
                or not isinstance(self.photo_selection.get('key'), str)
                or self.photo_selection.get('revision') is not None and not isinstance(self.photo_selection.get('revision'), str)
                or not 1 <= len(self.photo_selection['key']) <= 4096
                or self.photo_selection.get('revision') is not None and not 1 <= len(self.photo_selection['revision']) <= 128):
                raise ValueError('Invalid photo selection receipt')
        return self


class GreetingInput(BaseModel):
    """A bounded assistant-only action; no caller-supplied prompt is accepted."""

    action: Literal['begin', 'continue']
    client_turn_id: UUID | None = None
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    language: Literal['en-AU', 'zh-CN'] | None = None
    first_reply_localization: bool = False


GREETING_PROMPTS = {
    'begin': (
        'The storyteller wants to begin exploring a memory. Invite them to share '
        'whatever comes to mind, without using a fixed onboarding question.'
    ),
    'continue': (
        'The storyteller wants to continue with another memory. Ask one open-ended '
        'question based on the conversation, without restarting onboarding.'
    ),
}


class ConversationPhaseControl(BaseModel):
    model_config = {'extra': 'forbid'}
    action: Literal['comfort', 'explore', 'shape', 'automatic', 'skip']
    expected_revision: int = Field(ge=0, strict=True)


def phase_http_error(error):
    status = error.response.status_code
    try:
        code = error.response.json().get('code')
    except (ValueError, AttributeError):
        code = None
    if code == '40001' or status == 409:
        return HTTPException(409, 'Your conversation choice changed. Please reload it.')
    if status in (401, 403) or code == '42501':
        return HTTPException(403, 'Conversation unavailable.')
    return HTTPException(503, 'Conversation controls are temporarily unavailable.')


@router.get('/projects/{project_id}/conversation-phase')
async def read_conversation_phase(project_id: str, authorization: str | None = Header(default=None)):
    if not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise HTTPException(422, 'Invalid project')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        from .conversation_phase import PhaseState
        state = await asyncio.to_thread(storage.conversation_phase, project_id)
        return {'conversation_phase': PhaseState.model_validate(state).model_dump(mode='json')}
    except httpx.HTTPStatusError as error:
        raise phase_http_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.patch('/projects/{project_id}/conversation-phase')
async def change_conversation_phase(project_id: str, payload: ConversationPhaseControl,
                                    authorization: str | None = Header(default=None)):
    if not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise HTTPException(422, 'Invalid project')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        from .conversation_phase import PhaseState
        # The RPC locks this owned project and compares preference revisions.
        state = await asyncio.to_thread(storage.change_conversation_phase,
            project_id, payload.action, payload.expected_revision)
        return {'conversation_phase': PhaseState.model_validate(state).model_dump(mode='json')}
    except httpx.HTTPStatusError as error:
        raise phase_http_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)


class ProfileSettingsInput(BaseModel):
    preferred_language: Literal['en-AU', 'zh-CN'] | None = None
    name: str | None = Field(default=None, max_length=120)
    birth_year: int | None = Field(default=None, ge=1800, le=date.today().year)
    birth_place: str | None = Field(default=None, max_length=160)
    childhood_place: str | None = Field(default=None, max_length=160)


def _profile_settings_response(profile):
    return {key: profile.get(key) for key in ProfileSettingsInput.model_fields}


@router.get('/profile')
async def read_profile_settings(authorization: str | None = Header(default=None)):
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        if callable(getattr(storage,'lifetime_rpc',None)):
            from .lifetime_memory_reads import find_lifetime_read_identity,snapshot_lifetime_read
            identity=await asyncio.to_thread(find_lifetime_read_identity,storage,None)
            if identity is not None:
                return await asyncio.to_thread(snapshot_lifetime_read,storage,identity.project_id,
                    lambda fence: _profile_settings_response(storage.profile()))
        profile = await asyncio.to_thread(storage.profile)
        from .conversation_locale import restore_from_history
        profile = await restore_from_history(storage, profile)
        return {key: profile.get(key) for key in ProfileSettingsInput.model_fields}
    finally:
        await asyncio.to_thread(storage.client.close)


@router.patch('/profile')
async def update_profile_settings(payload: ProfileSettingsInput, authorization: str | None = Header(default=None)):
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        async with AgentTurnLease(storage) as lease:
            if callable(getattr(storage,'lifetime_rpc',None)):
                from .lifetime_memory_reads import find_lifetime_read_identity,snapshot_lifetime_read
                identity=await lease.io(find_lifetime_read_identity,storage,None)
                if identity is not None:
                    patch={key:(value.strip() or None) if isinstance(value,str) else value
                        for key,value in payload.model_dump(exclude_unset=True).items()}
                    await lease.io(storage.lifetime_rpc,'set_lifetime_profile_settings',
                        p_patch=patch,p_lease_token=lease.lease_token)
                    # Capture before rereading, never attach a newer fence to
                    # the original RPC response after a concurrent correction.
                    def current_settings(fence):
                        current=storage.profile()
                        return {**_profile_settings_response(current),
                            'conversation_language':current.get('conversation_language')}
                    return await lease.io(snapshot_lifetime_read,storage,identity.project_id,current_settings)
            profile = await lease.io(storage.profile)
            for key, value in payload.model_dump(exclude_unset=True).items():
                if isinstance(value, str):
                    value = value.strip() or None
                if value is None:
                    profile.pop(key, None)
                else:
                    profile[key] = value
            if 'preferred_language' in payload.model_fields_set:
                from .conversation_locale import explicit_profile
                profile = explicit_profile(profile, payload.preferred_language)
            await lease.check()
            await lease.io(storage.save_profile, profile)
            return {**{key: profile.get(key) for key in ProfileSettingsInput.model_fields},
                    'conversation_language': profile.get('conversation_language')}
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
    from .recall import free_recall_rounds,private_draft_cadence
    from .private_draft_stream import draft_updates_enabled
    from .turn_progress import thinking_steps_enabled
    configured = bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_PUBLISHABLE_KEY'))
    show_thinking_steps = thinking_steps_enabled()
    return {
        'enabled': configured,
        'auth_mode': 'supabase' if configured else ('test' if os.getenv('MEMORY_SPARK_TEST_MODE') == '1' else 'disabled'),
        'supabase_url': os.getenv('SUPABASE_URL'),
        'supabase_publishable_key': os.getenv('SUPABASE_PUBLISHABLE_KEY'),
        # This is a browser-restricted key for Cesium's Google 2D Tiles only.
        # The server-side geocoding key is intentionally never returned here.
        'google_maps_browser_api_key': os.getenv('GOOGLE_MAPS_BROWSER_API_KEY'),
        'show_thinking_steps': show_thinking_steps,
        'show_draft_updates': draft_updates_enabled(),
        'free_recall_rounds':free_recall_rounds(),
        'private_draft_cadence':private_draft_cadence(),
    }


@router.get('/place-journey', response_model=PlaceJourneyResponse)
async def place_journey(authorization: str | None = Header(default=None)):
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        def read(fence):
            if fence is not None:
                places = storage.lifetime_rpc('read_lifetime_place_journeys', p_project_id=fence.identity.project_id)
                record = places[-1] if places else None
            else:
                record = storage.place_journey()
            return {'place_journey': normalize_persisted_place_journey(record)}
        if callable(getattr(storage, 'lifetime_rpc', None)):
            from .lifetime_memory_reads import snapshot_lifetime_read
            return await asyncio.to_thread(snapshot_lifetime_read, storage, None, read)
        return await asyncio.to_thread(read, None)
    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        raise HTTPException(502, f'Supabase persistence failed: {error}') from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.get('/places/{project_id}/photos')
async def project_place_photos(project_id: str, request: Request,
                              place: str = Query(min_length=1, max_length=120),
                              period: str = Query(default='', max_length=160),
                              cursor: str | None = Query(default=None, max_length=160),
                              refresh: bool = Query(default=False),
                              latitude: float | None = Query(default=None, ge=-90, le=90),
                              longitude: float | None = Query(default=None, ge=-180, le=180),
                              authorization: str | None = Header(default=None)):
    """Bearer-authenticated adapter over the existing shared photo pipeline."""
    if valid_family_project_id(project_id) is None:
        raise HTTPException(422, 'Invalid project id')
    if (latitude is None) != (longitude is None):
        raise HTTPException(422, 'Both photo search coordinates are required')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        project = await asyncio.to_thread(storage.memoir_project, project_id)
        if project is None:
            raise HTTPException(404, 'Project not found')
        # Project IDs are only unique inside an owner. Never scope a cursor by
        # project alone, even though public discovery jobs themselves are shared.
        owner = f'{storage.user_id}:{project_id}'
    except (httpx.HTTPStatusError, httpx.RequestError):
        raise HTTPException(503, 'Project verification temporarily unavailable',
                            headers={'X-Error-Code': 'PROJECT_HISTORY_UNAVAILABLE'}) from None
    finally:
        await asyncio.to_thread(storage.client.close)
    try:
        from .place_photo_transport import photo_response
        return await photo_response(request.app.state.memoir_photo_pages, owner, place, period, cursor,
            refresh=refresh, latitude=latitude, longitude=longitude,
            stream='application/x-ndjson' in request.headers.get('accept', ''))
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {'items': [], 'status': 'UNAVAILABLE'}


@router.get('/pending-turn')
def read_pending_turn(project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
                      authorization: str | None = Header(default=None)):
    storage = authenticated_storage(authorization)
    try:
        from .conversation_recovery import pending_turn_input
        from .lifetime_memory_reads import snapshot_lifetime_read
        def read(fence):
            pending = pending_turn_input(storage, project_id) if fence is not None else None
            return {'turn': TurnInput.model_validate(pending).model_dump(mode='json') if pending else None}
        return snapshot_lifetime_read(storage, project_id, read)
    except (httpx.HTTPError, PublicationUnavailable):
        raise HTTPException(503, 'Conversation recovery temporarily unavailable',
                            headers={'X-Error-Code': 'TURN_RECEIPT_UNAVAILABLE'}) from None
    finally:
        storage.client.close()


@router.get('/turns/{client_turn_id}', response_model=TurnReceipt)
def read_turn_receipt(client_turn_id: UUID,
                      project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
                      authorization: str | None = Header(default=None)):
    """Reconcile a lost response without admitting or generating another turn."""
    storage = authenticated_storage(authorization)
    try:
        if callable(getattr(storage,'lifetime_rpc',None)):
            from .lifetime_memory_reads import snapshot_lifetime_read
            return snapshot_lifetime_read(storage,project_id,lambda fence:turn_receipt(storage,project_id,str(client_turn_id)))
        return turn_receipt(storage, project_id, str(client_turn_id))
    except (httpx.HTTPStatusError, httpx.RequestError, PublicationUnavailable):
        raise HTTPException(503, 'Conversation receipt temporarily unavailable',
                            headers={'X-Error-Code': 'TURN_RECEIPT_UNAVAILABLE'}) from None
    finally:
        storage.client.close()


@router.post('/greeting')
async def greeting(payload: GreetingInput, authorization: str | None = Header(default=None),
                   accept: str = Header(default='application/json')):
    if payload.project_id is not None and valid_family_project_id(payload.project_id) is None:
        raise HTTPException(422, 'Invalid Family project id')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    from .lifetime_memory_runtime import lifetime_http_turn
    return await lifetime_http_turn(runtime, storage, GREETING_PROMPTS[payload.action], accept=accept, options={
        'project_id': payload.project_id, 'language': payload.language, 'user_response': False,
        'client_turn_id': str(payload.client_turn_id) if payload.client_turn_id else None})


@router.post('/turn')
async def turn(payload: TurnInput, request: Request, authorization: str | None = Header(default=None),
               accept: str = Header(default='application/json')):
    if payload.project_id is not None and valid_family_project_id(payload.project_id) is None:
        raise HTTPException(422, 'Invalid Family project id')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    focus = payload.workspace_focus.model_dump(mode='json', exclude_none=True) if payload.workspace_focus else None
    from .lifetime_memory_runtime import lifetime_http_turn
    return await lifetime_http_turn(runtime, storage, payload.text, accept=accept, options={
        'project_id': payload.project_id, 'language': payload.language,
        'client_turn_id': str(payload.client_turn_id) if payload.client_turn_id else None,
        'conversation_text': payload.conversation_text, 'source_kind': payload.source_kind,
        'uploaded_photo_ids': [str(id) for id in payload.uploaded_photo_ids],
        'photo_selection': payload.photo_selection, 'workspace_focus': focus,
        'recording_ids': [str(id) for id in payload.recording_ids]})


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
        document = await asyncio.to_thread(with_photo_urls, storage, document)
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


@router.put('/family-context/{project_id}/people/{person_id}/photo')
@router.delete('/family-context/{project_id}/people/{person_id}/photo')
async def family_person_photo(project_id: str, person_id: str, request: Request,
                              authorization: str | None = Header(default=None)):
    if valid_family_project_id(project_id) is None:
        raise HTTPException(422, 'Invalid Family project id')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        entitlement = await asyncio.to_thread(storage.story_entitlement)
        if not family_features_enabled(entitlement):
            raise HTTPException(403, 'Family tree access is required')
        document = await asyncio.to_thread(storage.family_context, project_id)
        family_person(document, person_id)
        path = None
        if request.method == 'PUT':
            chunks = bytearray()
            async for chunk in request.stream():
                if len(chunks) + len(chunk) > MAX_PHOTO_BYTES:
                    raise HTTPException(413, 'Photo exceeds 10 MiB')
                chunks.extend(chunk)
            content_type = request.headers.get('content-type', '').split(';')[0].strip().lower()
            photo = await asyncio.to_thread(portrait_bytes, bytes(chunks), content_type)
            path = await asyncio.to_thread(storage.put_attachment, f'portrait-{uuid4().hex}.jpg', photo, 'image/jpeg')
        return await asyncio.to_thread(save_person_photo, storage, project_id, person_id, path)
    except (httpx.HTTPStatusError, httpx.RequestError):
        raise HTTPException(502, 'The person photo could not be saved') from None
    finally:
        await asyncio.to_thread(storage.client.close)
