"""Supabase-authenticated Codex conversation endpoints."""
import asyncio
from datetime import date
import os
from uuid import UUID, uuid4
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from .turn_stream import STREAM_HEADERS, turn_events

from .agent_lock import AgentTurnBusyError, AgentTurnLease
from .agent_routes_support import authenticated_storage
from .codex_runtime import CodexRuntime
from .conversation_recovery import PROJECT_ID_PATTERN, TurnReceipt, turn_receipt
from .family_context import family_features_enabled, valid_family_project_id
from .family_photos import MAX_PHOTO_BYTES, family_person, portrait_bytes, save_person_photo, with_photo_urls
from .place_journey import normalize_persisted_place_journey

router = APIRouter(prefix='/v1/agent', tags=['Codex agent'])
runtime = CodexRuntime()


class TurnInput(BaseModel):
    text: str = Field(min_length=1, max_length=100000)
    client_turn_id: UUID | None = None
    conversation_text: str | None = Field(default=None, min_length=1, max_length=100000)
    source_kind: Literal['narrator_chat', 'narrator_transcript'] = 'narrator_chat'
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    # The UI locale is not the interview language.  Omit this when the
    # storyteller has not explicitly chosen a conversation language so the
    # runtime can infer it from the conversation without changing the UI.
    language: Literal['en-AU', 'zh-CN'] | None = None
    # The browser sends this only for the first onboarding answer. It is a
    # compatibility hint. The server's durable first-reply state decides
    # whether detection is still eligible; this cannot override saved settings.
    first_reply_localization: bool = False


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
    configured = bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_PUBLISHABLE_KEY'))
    show_thinking_steps = os.getenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    return {
        'enabled': configured,
        'auth_mode': 'supabase' if configured else ('test' if os.getenv('MEMORY_SPARK_TEST_MODE') == '1' else 'disabled'),
        'supabase_url': os.getenv('SUPABASE_URL'),
        'supabase_publishable_key': os.getenv('SUPABASE_PUBLISHABLE_KEY'),
        # This is a browser-restricted key for Cesium's Google 2D Tiles only.
        # The server-side geocoding key is intentionally never returned here.
        'google_maps_browser_api_key': os.getenv('GOOGLE_MAPS_BROWSER_API_KEY'),
        'show_thinking_steps': show_thinking_steps,
        'free_recall_rounds':free_recall_rounds(),
        'private_draft_cadence':private_draft_cadence(),
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


@router.get('/turns/{client_turn_id}', response_model=TurnReceipt)
def read_turn_receipt(client_turn_id: UUID,
                      project_id: str = Query(..., pattern=PROJECT_ID_PATTERN),
                      authorization: str | None = Header(default=None)):
    """Reconcile a lost response without admitting or generating another turn."""
    storage = authenticated_storage(authorization)
    try:
        return turn_receipt(storage, project_id, str(client_turn_id))
    except (httpx.HTTPStatusError, httpx.RequestError):
        raise HTTPException(503, 'Conversation receipt temporarily unavailable',
                            headers={'X-Error-Code': 'TURN_RECEIPT_UNAVAILABLE'}) from None
    finally:
        storage.client.close()


@router.post('/greeting')
async def greeting(payload: GreetingInput, authorization: str | None = Header(default=None),
                   accept: str = Header(default='application/json')):
    """Run one of the server-owned assistant-only onboarding actions.

    This route deliberately has no free-form ``text`` field. The runtime's
    ``user_response=False`` seam is reachable here only after the action has
    been reduced to one of the two product-owned prompts above; ordinary
    ``/turn`` requests always remain billable user responses.
    """
    if payload.project_id is not None and valid_family_project_id(payload.project_id) is None:
        raise HTTPException(422, 'Invalid Family project id')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    prompt = GREETING_PROMPTS[payload.action]
    if 'application/x-ndjson' in accept:
        async def run_stream(emit):
            options = {
                'project_id': payload.project_id,
                'language': payload.language,
                'on_delta': emit,
                'on_event': emit.event,
                'user_response': False,
            }
            if payload.first_reply_localization:
                options['first_reply_localization'] = True
            if payload.client_turn_id:
                options['client_turn_id'] = str(payload.client_turn_id)
            return await runtime.turn(storage, prompt, **options)

        return StreamingResponse(
            turn_events(run_stream,
                        cleanup=lambda: asyncio.to_thread(storage.client.close)),
            media_type='application/x-ndjson', headers=STREAM_HEADERS,
        )
    try:
        options = {
            'project_id': payload.project_id,
            'language': payload.language,
            'user_response': False,
        }
        if payload.first_reply_localization:
            options['first_reply_localization'] = True
        if payload.client_turn_id:
            options['client_turn_id'] = str(payload.client_turn_id)
        return await runtime.turn(storage, prompt, **options)
    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        raise HTTPException(502, f'Supabase persistence failed: {error}') from None
    except AgentTurnBusyError as error:
        raise HTTPException(409, str(error), headers={'X-Error-Code': 'AGENT_TURN_IN_PROGRESS'}) from None
    except RuntimeError as error:
        raise HTTPException(502, f'Codex agent failed: {error}') from None
    finally:
        await asyncio.to_thread(storage.client.close)


def _project_place_hints(store, project_id, user_id):
    """Read only the authenticated project's bounded geographic history."""
    if not project_id:
        return []
    from .main import _project
    with store.lock:
        # Legacy callers may have only the separate user-memoir project row.
        if project_id not in store.projects:
            return []
        project = _project(store, project_id, user_id)
        history = project.get('profile', {}).get('memory_places') or []
        if not isinstance(history, list):
            return []
        from .place_journey import validate_place_journey
        return [place for raw in history[-50:]
                if (place := validate_place_journey(raw)) is not None]


@router.post('/turn')
async def turn(payload: TurnInput, request: Request, authorization: str | None = Header(default=None),
               accept: str = Header(default='application/json')):
    if payload.project_id is not None and valid_family_project_id(payload.project_id) is None:
        raise HTTPException(422, 'Invalid Family project id')
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        place_hints = await asyncio.to_thread(_project_place_hints,
            request.app.state.store, payload.project_id, storage.user_id) if payload.project_id else []
    except BaseException:
        await asyncio.to_thread(storage.client.close)
        raise
    if 'application/x-ndjson' in accept:
        async def run_stream(emit):
            options = {
                'project_id': payload.project_id,
                'language': payload.language,
                'on_delta': emit,
                'on_event': emit.event,
            }
            if place_hints:
                options['saved_place_hints'] = place_hints
            if payload.source_kind != 'narrator_chat':
                options['source_kind'] = payload.source_kind
            if payload.first_reply_localization:
                options['first_reply_localization'] = True
            if payload.conversation_text is not None:
                options['conversation_text'] = payload.conversation_text
            if payload.client_turn_id:
                options['client_turn_id'] = str(payload.client_turn_id)
            return await runtime.turn(storage, payload.text, **options)

        return StreamingResponse(
            turn_events(run_stream,
                        cleanup=lambda: asyncio.to_thread(storage.client.close)),
            media_type='application/x-ndjson', headers=STREAM_HEADERS,
        )
    try:
        options = {'project_id': payload.project_id, 'language': payload.language}
        if place_hints:
            options['saved_place_hints'] = place_hints
        if payload.source_kind != 'narrator_chat':
            options['source_kind'] = payload.source_kind
        if payload.first_reply_localization:
            options['first_reply_localization'] = True
        if payload.conversation_text is not None:
            options['conversation_text'] = payload.conversation_text
        if payload.client_turn_id:
            options['client_turn_id'] = str(payload.client_turn_id)
        return await runtime.turn(storage, payload.text, **options)
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
