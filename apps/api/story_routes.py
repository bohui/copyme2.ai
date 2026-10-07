"""The small, Supabase-backed anonymous-to-paid memoir journey."""

from __future__ import annotations

import base64
import asyncio
import binascii
import json
import os
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any, Callable

import httpx

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agent_routes_support import authenticated_storage
from .agent_storage import UserStorage
from .family_context import family_features_enabled
from .speech import SpeechProviderError, SpeechUnavailable, UnavailableSpeechService
from .store import MemoryStore, new_id, sha256_json
from .recall import storage_recall_status
from .agent_lock import AgentTurnLease, AgentTurnBusyError
from .memoir_preview import (compose_preview, source_snapshot, snapshot_key, cached_preview,
                             normalize_conversation_language, PreviewSourceChanged)
from .preview_jobs import PreviewJobs
from .stage_readiness import stage_readiness
from .story_payments import (
    StripeAPIError,
    StripeCheckoutClient,
    StripeConfigurationError,
    StoryPlanError,
    build_story_entitlement_store,
    checkout_summary,
    list_story_plans,
    public_checkout_urls,
    verify_stripe_signature,
)


FLOW_KEY = "story_flow"
ROUNDS_REQUIRED = 5


class StoryEventCorrection(BaseModel):
    expected_revision: int = Field(ge=1)
    patch: dict[str, Any]
    statement: str = Field(min_length=1, max_length=2000)


class StoryRoundInput(BaseModel):
    round: int = Field(ge=1)
    answer: str = Field(default="", max_length=100000)
    audio_base64: str | None = None
    audio_filename: str = "story-round.webm"
    audio_mime_type: str = "audio/webm"
    audio_source_path: str | None = None


class StoryTranscriptionInput(BaseModel):
    audio_base64: str = Field(min_length=1)
    filename: str = "story-round.webm"
    mime_type: str = "audio/webm"
    language: str | None = None
    prompt: str | None = None


class StorySpeechInput(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    language: str | None = None
    voice: str = "marin"
    instructions: str = "Speak slowly, warmly and clearly with natural pauses."
    output_format: str = "mp3"


class StoryCheckoutCreate(BaseModel):
    plan_key: str = "electronic_memoir_v1"
    book_count: int | None = Field(default=None, ge=0, le=20)


class StoryPreviewCreate(BaseModel):
    project_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    language: str | None = Field(default=None, pattern=r'^(en-AU|zh-CN)$')


class InMemoryStoryStorage:
    """Test-only stand-in for the external Supabase user-data boundary."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.is_anonymous = True
        self._profile: dict[str, Any] = {}
        self._memories: list[dict[str, Any]] = []

    def profile(self):
        return deepcopy(self._profile)

    def save_profile(self, profile):
        self._profile = deepcopy(profile)
        return [self._profile]

    def save_memory(self, text, *, kind="memoir", source_paths=None):
        row = {
            "id": new_id("memory"),
            "user_id": self.user_id,
            "kind": kind,
            "content": text,
            "source_paths": source_paths or [],
        }
        self._memories.append(row)
        return [row]

    def memories(self):
        return list(reversed(self._memories))


def build_test_storage_factory() -> Callable[[str | None], InMemoryStoryStorage]:
    stores: dict[str, InMemoryStoryStorage] = {}

    def factory(authorization: str | None):
        key = authorization or "test-anonymous"
        if key not in stores:
            stores[key] = InMemoryStoryStorage("00000000-0000-0000-0000-000000000001")
        return stores[key]

    return factory


def _default_state() -> dict[str, Any]:
    return {
        "rounds_required": ROUNDS_REQUIRED,
        "rounds_completed": 0,
        "free_chapter_claimed": False,
        "free_chapter_id": None,
        "payment_status": "unpaid",
        "payment_plan": None,
        "book_count": 0,
        "payment_features": [],
        "family_features_enabled": False,
    }


def _close(storage: Any) -> None:
    client = getattr(storage, "client", None)
    if client is not None and hasattr(client, "close"):
        client.close()


def _profile(storage: Any) -> dict[str, Any]:
    profile = storage.profile()
    return deepcopy(profile) if isinstance(profile, dict) else {}


def _state(profile: dict[str, Any], entitlement: dict[str, Any] | None = None) -> dict[str, Any]:
    current = profile.get(FLOW_KEY)
    state = _default_state()
    if isinstance(current, dict):
        state.update(current)
    state["rounds_required"] = ROUNDS_REQUIRED
    state["rounds_completed"] = max(0, min(ROUNDS_REQUIRED, int(state.get("rounds_completed", 0))))
    state["free_chapter_claimed"] = bool(state.get("free_chapter_claimed"))
    # The profile is user-editable, so payment state must come from the
    # server-controlled entitlement store populated by the Stripe webhook.
    paid = bool(entitlement and entitlement.get("status") == "paid")
    family_enabled = family_features_enabled(entitlement)
    state["payment_status"] = "paid" if paid else "unpaid"
    state["payment_plan"] = entitlement.get("plan_key") if paid else None
    state["book_count"] = int(entitlement.get("book_count", 0)) if paid else 0
    state["family_features_enabled"] = family_enabled
    state["payment_features"] = [
        key
        for key in ("electronic_only", "family_tree", "timeline", "expanded_details")
        if paid and entitlement.get(key) and (key not in {"family_tree", "timeline", "expanded_details"} or family_enabled)
    ]
    return state


def _next_action(storage: Any, state: dict[str, Any]) -> str:
    if state["rounds_completed"] < ROUNDS_REQUIRED:
        return "answer"
    if getattr(storage, "is_anonymous", False):
        return "link_identity"
    if not state["free_chapter_claimed"]:
        return "free_chapter"
    if state["payment_status"] != "paid":
        return "payment"
    return "full_memoir"


def _state_response(storage: Any, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "recall_status": storage_recall_status(storage, {"status": state["payment_status"]}),
        "user_id": storage.user_id,
        "is_anonymous": bool(getattr(storage, "is_anonymous", False)),
        **state,
        "free_chapter_available": (
            state["rounds_completed"] >= ROUNDS_REQUIRED
            and not state["free_chapter_claimed"]
            and not getattr(storage, "is_anonymous", False)
        ),
        "next_action": _next_action(storage, state),
    }


def _entitlement(entitlement_store: Any, storage: Any) -> dict[str, Any] | None:
    try:
        return entitlement_store.get(storage.user_id)
    except Exception as error:
        raise HTTPException(503, "Payment entitlement storage is unavailable", headers={"X-Error-Code": "PAYMENT_STORAGE_UNAVAILABLE"}) from error


def _save_state(storage: Any, profile: dict[str, Any], state: dict[str, Any]) -> None:
    profile[FLOW_KEY] = state
    storage.save_profile(profile)


def _round_memories(storage: Any) -> list[dict[str, Any]]:
    rows = []
    for row in storage.memories():
        if row.get("kind") != "memoir":
            continue
        paths = row.get("source_paths") or []
        if not any(str(path).startswith("story-round:") for path in paths):
            continue
        try:
            content = json.loads(row.get("content", ""))
        except (TypeError, json.JSONDecodeError):
            content = {"answer": row.get("content", "")}
        if "round" in content:
            rows.append({"round": int(content["round"]), "answer": content.get("answer", "")})
    return sorted(rows, key=lambda item: item["round"])


def _chapter_from_rounds(storage: Any) -> dict[str, Any]:
    answers = _round_memories(storage)
    text = "\n\n".join(item["answer"].strip() for item in answers if item["answer"].strip())
    return {
        "id": new_id("chapter"),
        "chapter_number": 1,
        "title": "Where your story begins",
        "text": text or "Your first five memories are ready to shape into a chapter.",
    }


def build_router(
    storage_factory: Callable[[str | None], Any] = authenticated_storage,
    *,
    entitlement_store: Any | None = None,
    stripe_client: StripeCheckoutClient | Any | None = None,
    speech_service: Any | None = None,
) -> APIRouter:
    running_previews = {}

    @asynccontextmanager
    async def lifespan(app):
        broker_task=None
        broker=None
        if os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_SECRET_KEY') and os.getenv('MEMORY_SPARK_TASK_DB'):
            from .memory_event_worker import MemoirLaneBroker
            broker=MemoirLaneBroker()
            broker_task=asyncio.create_task(broker.run())
        try:
            yield
        finally:
            if broker_task:
                broker_task.cancel()
                await asyncio.gather(broker_task,return_exceptions=True)
                await broker.client.aclose()
            tasks = list(running_previews.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    router = APIRouter(prefix="/v1/story", tags=["Story journey"], lifespan=lifespan)
    payment_store = entitlement_store or build_story_entitlement_store(MemoryStore())
    stripe = stripe_client or StripeCheckoutClient()
    speech_service = speech_service or UnavailableSpeechService()
    speech_cache: dict[str, dict[str, Any]] = {}

    def storage_for(authorization: str | None):
        return storage_factory(authorization)

    @router.get("/plans")
    def story_plans() -> dict[str, Any]:
        return {"items": list_story_plans(), "currency": "AUD"}

    @router.get('/readiness')
    async def context_readiness(project_id: str, authorization: str | None = Header(default=None)):
        storage = await asyncio.to_thread(storage_for, authorization)
        try:
            rows = await asyncio.to_thread(getattr(storage, 'all_memories', storage.memories))
            return {'project_id': project_id, 'stages': stage_readiness(rows, project_id),
                    'heuristic': 'narrator_context_volume_v1', 'maximum_percent': 50}
        finally:
            await asyncio.to_thread(_close, storage)

    @router.get('/private-draft')
    async def saved_private_draft(project_id: str, language: str | None = None,
                                  authorization: str | None = Header(default=None)):
        storage = await asyncio.to_thread(storage_for, authorization)
        try:
            if isinstance(storage, UserStorage):
                return await asyncio.to_thread(storage.saved_memoir_draft, project_id, language)
            from .private_drafts import synchronize
            # Every render rechecks source authorization and versions using a
            # fresh RLS read, including changes made while the tab was closed.
            return await asyncio.to_thread(synchronize, storage, project_id, language)
        finally:
            await asyncio.to_thread(_close, storage)

    @router.post('/private-draft/retry')
    async def retry_private_draft(payload: StoryPreviewCreate,authorization: str | None = Header(default=None)):
        storage=await asyncio.to_thread(storage_for,authorization)
        try:
            if isinstance(storage, UserStorage):
                await asyncio.to_thread(storage.retry_memoir_lane, payload.project_id, 'timeline')
                await asyncio.to_thread(storage.retry_memoir_lane, payload.project_id, 'composer')
                return await asyncio.to_thread(storage.saved_memoir_draft, payload.project_id, payload.language)
            from .private_drafts import synchronize
            from .private_draft_jobs import PrivateDraftJobs
            view=await asyncio.to_thread(synchronize,storage,payload.project_id,payload.language)
            language=payload.language or normalize_conversation_language((await asyncio.to_thread(storage.profile)).get('preferred_language'))
            await asyncio.to_thread(PrivateDraftJobs(os.environ['MEMORY_SPARK_TASK_DB']).retry,
                                   storage.user_id,payload.project_id,language)
            return view
        finally:
            await asyncio.to_thread(_close,storage)

    @router.get('/events')
    async def memory_events(project_id: str, authorization: str | None = Header(default=None)):
        storage = await asyncio.to_thread(storage_for, authorization)
        try:
            if not family_features_enabled(await asyncio.to_thread(storage.story_entitlement)):
                raise HTTPException(403, 'Timeline display requires Family legacy access')
            return await asyncio.to_thread(storage.memory_events, project_id)
        finally:
            await asyncio.to_thread(_close, storage)

    @router.patch('/events/{project_id}/{event_id}')
    async def correct_event(project_id: str, event_id: str, payload: StoryEventCorrection,
                            authorization: str | None = Header(default=None)):
        storage = await asyncio.to_thread(storage_for, authorization)
        try:
            if not family_features_enabled(await asyncio.to_thread(storage.story_entitlement)):
                raise HTTPException(403, 'Timeline editing requires Family legacy access')
            return await asyncio.to_thread(storage.correct_memory_event, project_id, event_id,
                                           payload.expected_revision, payload.patch, payload.statement)
        except httpx.HTTPStatusError as failure:
            try:
                database_error = failure.response.json()
            except ValueError:
                database_error = None
            conflict = failure.response.status_code == 409 or (failure.response.status_code == 500
                and isinstance(database_error, dict) and database_error.get('code') == '40001')
            raise HTTPException(409 if conflict else 422, 'Reload this event and retry' if conflict else 'Event correction is unavailable',
                headers={'X-Error-Code': 'EVENT_REVISION_CONFLICT' if conflict else 'EVENT_CORRECTION_INVALID'}) from None
        finally:
            await asyncio.to_thread(_close, storage)

    @router.get("/state")
    def story_state(authorization: str | None = Header(default=None)):
        storage = storage_for(authorization)
        try:
            profile = _profile(storage)
            return _state_response(storage, _state(profile, _entitlement(payment_store, storage)))
        finally:
            _close(storage)

    @router.post("/transcriptions")
    def story_transcription(payload: StoryTranscriptionInput, authorization: str | None = Header(default=None)):
        storage = storage_for(authorization)
        try:
            try:
                audio = base64.b64decode(payload.audio_base64.encode(), validate=True)
            except (ValueError, binascii.Error) as error:
                raise HTTPException(422, "The recording payload is not valid base64.", headers={"X-Error-Code": "INVALID_AUDIO_PAYLOAD"}) from error
            try:
                transcription = speech_service.transcribe(
                    audio,
                    filename=payload.filename,
                    mime_type=payload.mime_type,
                    language=payload.language,
                    prompt=payload.prompt,
                )
            except SpeechUnavailable as exc:
                raise HTTPException(503, str(exc), headers={"X-Error-Code": "SPEECH_UNAVAILABLE"}) from exc
            except SpeechProviderError as exc:
                raise HTTPException(503, str(exc), headers={"X-Error-Code": "SPEECH_PROVIDER_FAILED"}) from exc
            text = str(transcription.get("text") or "").strip()
            if not text:
                raise HTTPException(502, "Speech transcription returned no text", headers={"X-Error-Code": "EMPTY_TRANSCRIPT"})
            return {"text": text, "source": {"source_kind": "transcript", "transcription_method": str(transcription.get("provider") or "openai"), "transcription_model": transcription.get("model"), "language": transcription.get("language"), "segments": transcription.get("segments") or []}}
        finally:
            _close(storage)

    @router.post("/question-audio")
    def story_question_audio(payload: StorySpeechInput, authorization: str | None = Header(default=None)):
        storage = storage_for(authorization)
        try:
            cache_key = sha256_json({"user_id": storage.user_id, **payload.model_dump()})
            existing = speech_cache.get(cache_key)
            if existing:
                return JSONResponse(status_code=200, content={**existing, "cached": True})
            try:
                generated = speech_service.synthesize(**payload.model_dump())
            except SpeechUnavailable as exc:
                raise HTTPException(503, str(exc), headers={"X-Error-Code": "SPEECH_UNAVAILABLE"}) from exc
            except SpeechProviderError as exc:
                raise HTTPException(503, str(exc), headers={"X-Error-Code": "SPEECH_PROVIDER_FAILED"}) from exc
            content = generated.get("content") if isinstance(generated, dict) else None
            if not isinstance(content, bytes) or not content:
                raise HTTPException(502, "Speech synthesis returned no audio", headers={"X-Error-Code": "EMPTY_SPEECH"})
            result = {"audio_base64": base64.b64encode(content).decode(), "mime_type": str(generated.get("mime_type") or "audio/mpeg"), "model": generated.get("model"), "voice": generated.get("voice") or payload.voice, "ai_generated": True}
            speech_cache[cache_key] = result
            return JSONResponse(status_code=201, content={**result, "cached": False})
        finally:
            _close(storage)

    @router.post("/rounds")
    def answer_round(payload: StoryRoundInput, authorization: str | None = Header(default=None)):
        storage = storage_for(authorization)
        try:
            profile = _profile(storage)
            state = _state(profile, _entitlement(payment_store, storage))
            expected_round = state["rounds_completed"] + 1
            if state["rounds_completed"] >= ROUNDS_REQUIRED or not getattr(storage, "is_anonymous", False):
                raise HTTPException(
                    status_code=403,
                    detail="Link Google or Facebook before continuing to create your memoir.",
                    headers={"X-Error-Code": "AUTH_REQUIRED"},
                )
            if payload.round != expected_round:
                raise HTTPException(
                    status_code=409,
                    detail=f"Round {expected_round} is required next.",
                    headers={"X-Error-Code": "ROUND_OUT_OF_ORDER"},
                )
            answer = payload.answer.strip()
            audio_source_path = payload.audio_source_path
            audio = None
            if payload.audio_base64:
                try:
                    audio = base64.b64decode(payload.audio_base64.encode(), validate=True)
                except (ValueError, binascii.Error) as error:
                    raise HTTPException(422, "The recording payload is not valid base64.", headers={"X-Error-Code": "INVALID_AUDIO_PAYLOAD"}) from error
                if hasattr(storage, "put_attachment"):
                    audio_source_path = storage.put_attachment(payload.audio_filename, audio, payload.audio_mime_type)
            if audio is not None and not answer:
                try:
                    transcription = speech_service.transcribe(audio, filename=payload.audio_filename, mime_type=payload.audio_mime_type)
                except SpeechUnavailable as exc:
                    raise HTTPException(503, str(exc), headers={"X-Error-Code": "SPEECH_UNAVAILABLE"}) from exc
                except SpeechProviderError as exc:
                    raise HTTPException(503, str(exc), headers={"X-Error-Code": "SPEECH_PROVIDER_FAILED"}) from exc
                answer = str(transcription.get("text") or "").strip()
                if not answer:
                    raise HTTPException(502, "Speech transcription returned no text", headers={"X-Error-Code": "EMPTY_TRANSCRIPT"})
            if not answer:
                raise HTTPException(422, "A story answer or recording is required.", headers={"X-Error-Code": "ANSWER_REQUIRED"})
            storage.save_memory(
                json.dumps({"type": "story_round", "round": payload.round, "answer": answer, "transcription_method": "openai" if payload.audio_base64 else "typed"}),
                kind="memoir",
                source_paths=[f"story-round:{payload.round}", *([audio_source_path] if audio_source_path else [])],
            )
            state["rounds_completed"] = payload.round
            _save_state(storage, profile, state)
            return {**_state_response(storage, state), "transcript": answer if payload.audio_base64 else None}
        finally:
            _close(storage)

    @router.post("/free-chapter")
    def free_chapter(authorization: str | None = Header(default=None)):
        storage = storage_for(authorization)
        try:
            profile = _profile(storage)
            state = _state(profile, _entitlement(payment_store, storage))
            if getattr(storage, "is_anonymous", False):
                raise HTTPException(
                    status_code=403,
                    detail="Link Google or Facebook to claim your free chapter.",
                    headers={"X-Error-Code": "AUTH_REQUIRED"},
                )
            if state["rounds_completed"] < ROUNDS_REQUIRED:
                raise HTTPException(
                    status_code=409,
                    detail="Complete all five story rounds first.",
                    headers={"X-Error-Code": "ROUNDS_REQUIRED"},
                )
            if state["free_chapter_claimed"]:
                chapter = next(
                    (
                        json.loads(row["content"])
                        for row in storage.memories()
                        if row.get("id") == state.get("free_chapter_id")
                    ),
                    None,
                )
                return {"chapter": chapter, **_state_response(storage, state)}
            chapter = _chapter_from_rounds(storage)
            storage.save_memory(
                json.dumps(chapter),
                kind="memoir",
                source_paths=["story-chapter:1", *[f"story-round:{item['round']}" for item in _round_memories(storage)]],
            )
            state["free_chapter_claimed"] = True
            state["free_chapter_id"] = chapter["id"]
            _save_state(storage, profile, state)
            return {"chapter": chapter, **_state_response(storage, state)}
        finally:
            _close(storage)

    async def preview_snapshot(storage, project_id, language):
        access = await AgentTurnLease.io(storage_recall_status, storage, None)
        if not access or access['rounds_completed'] < access['free_rounds']:
            raise HTTPException(409, 'Complete the free recall experience before composing the sample',
                                headers={'X-Error-Code': 'ROUNDS_REQUIRED'})
        reader = getattr(storage, 'composition_memories', None) or getattr(storage, 'all_memories', storage.memories)
        rows = await AgentTurnLease.io(reader)
        profile = await AgentTurnLease.io(storage.profile)
        language = normalize_conversation_language(language or profile.get('preferred_language'))
        sources = source_snapshot(rows, project_id)
        key = snapshot_key(sources, project_id, language)
        return rows, sources, key, language

    async def run_preview(queue, job, storage):
        error = None
        result = None
        retryable = False
        try:
            async def checkpoint(phase, value):
                await AgentTurnLease.io(queue.checkpoint, job['id'], job['lease_token'], phase, value)

            async with AgentTurnLease(storage) as lease:
                result = await compose_preview(storage, lease, job['project_id'], language=job['language'],
                                      prepared=job['payload'], checkpoint=job['checkpoint'],
                                      save_checkpoint=checkpoint)
        except asyncio.CancelledError:
            error, retryable = 'PREVIEW_INTERRUPTED', True
            raise
        except AgentTurnBusyError:
            error, retryable = 'AGENT_TURN_IN_PROGRESS', True
        except PreviewSourceChanged:
            error = 'PREVIEW_SOURCE_CHANGED'
        except Exception as failure:
            # Exception strings can contain private text, headers or URLs.
            offline = isinstance(failure, httpx.HTTPStatusError) and failure.response.headers.get('X-Error-Code') == 'COMPOSER_PROVIDER_UNAVAILABLE'
            error = 'PREVIEW_PROVIDER_UNAVAILABLE' if offline else 'AGENT_TURN_IN_PROGRESS' if isinstance(failure, httpx.HTTPStatusError) and failure.response.status_code == 409 else 'PREVIEW_TIMEOUT' if isinstance(failure, (TimeoutError, httpx.TimeoutException)) or (
                isinstance(failure, httpx.HTTPStatusError) and failure.response.status_code == 504
            ) else 'PREVIEW_UNAVAILABLE'
            retryable = not offline and (isinstance(failure, (TimeoutError, httpx.TransportError)) or (
                isinstance(failure, httpx.HTTPStatusError) and failure.response.status_code in {409, 429, 502, 503, 504}
            ))
            logging.getLogger(__name__).warning('memoir_preview failure_type=%s code=%s', type(failure).__name__, error)
        finally:
            try:
                await AgentTurnLease.io(queue.finish, job['id'], job['lease_token'], error=error, retryable=retryable,
                                          outcome=result['status'] if result else None)
            finally:
                await AgentTurnLease.io(_close, storage)

    async def start_preview(queue, job, storage):
        claimed = await AgentTurnLease.io(queue.claim, storage.user_id, job['id'])
        if not claimed:
            return False
        task = asyncio.create_task(run_preview(queue, claimed, storage))
        running_previews[job['id']] = task

        def settled(completed):
            if running_previews.get(job['id']) is completed:
                running_previews.pop(job['id'], None)
            if not completed.cancelled():
                completed.exception()  # Retrieve failures without logging private exception text.

        task.add_done_callback(settled)
        return True

    def preview_response(job):
        state = 'error' if job['status'] == 'FAILED' else 'pending'
        return {'status': state, 'preview': None, 'job': job, 'retry_after': 3}

    async def shared_preview_response(storage, project_id, language=None, *, retry=False):
        access = await AgentTurnLease.io(storage_recall_status, storage, None)
        if not access or access['rounds_completed'] < access['free_rounds']:
            raise HTTPException(409, 'Complete the free recall experience before composing the sample',
                                headers={'X-Error-Code': 'ROUNDS_REQUIRED'})
        profile = await AgentTurnLease.io(storage.profile)
        locale = normalize_conversation_language(language or profile.get('preferred_language'))
        saved = await AgentTurnLease.io(storage.saved_memoir_draft, project_id, locale)
        if saved['preview']:
            return {**saved, 'status': 'ready', 'cached': True}
        if not saved['updating'] and not saved['error']:
            # The allowance is account-wide, but drafts belong to an interview.
            # An empty/new project has no job to poll even at the account limit.
            return {**saved, 'status': 'stale' if saved['status'] == 'stale' else 'insufficient_context'}
        if retry:
            await AgentTurnLease.io(storage.retry_memoir_lane, project_id, 'timeline')
            await AgentTurnLease.io(storage.retry_memoir_lane, project_id, 'composer')
            saved = await AgentTurnLease.io(storage.saved_memoir_draft, project_id, locale)
        failed = bool(saved['error'] and not saved['updating'])
        return {**saved, 'status': 'error' if failed else 'pending', 'preview': None,
            'job': {'id': f'shared.{locale}.{project_id}', 'project_id': project_id, 'language': locale,
                    'status': 'FAILED' if failed else 'RUNNING', 'phase': 'drafting', 'error': saved['error']},
            'retry_after': 3}

    @router.post('/preview')
    async def preview(payload: StoryPreviewCreate, authorization: str | None = Header(default=None)):
        storage = await asyncio.to_thread(storage_for, authorization)
        transferred = False
        try:
            if isinstance(storage, UserStorage):
                result = await shared_preview_response(storage, payload.project_id, payload.language, retry=True)
                return JSONResponse(status_code=202 if result['status']=='pending' else 200, content=result)
            rows, sources, key, language = await preview_snapshot(storage, payload.project_id, payload.language)
            existing = cached_preview(rows, key)
            if existing:
                return {'status': 'ready', 'preview': existing, 'cached': True}
            if not sources:
                return {'status': 'insufficient_context', 'preview': None}
            queue = await AgentTurnLease.io(PreviewJobs)
            # POST is an explicit retry of a terminal failure; active work is deduplicated.
            job = await AgentTurnLease.io(queue.submit, storage.user_id, payload.project_id, key, language,
                                          {'key': key}, retry=True)
            transferred = await start_preview(queue, job, storage)
            job = await AgentTurnLease.io(queue.get, storage.user_id, job['id'])
            return JSONResponse(status_code=202, content=preview_response(job), headers={'Retry-After': '3'})
        except (RuntimeError, ValueError, KeyError, httpx.HTTPError, OSError) as error:
            logging.getLogger(__name__).warning('memoir_preview admission_failure_type=%s', type(error).__name__)
            raise HTTPException(503, 'Your sample could not be prepared yet. Please try again.',
                                headers={'X-Error-Code': 'PREVIEW_UNAVAILABLE'}) from None
        finally:
            if not transferred:
                await AgentTurnLease.io(_close, storage)

    @router.get('/preview/{job_id}')
    async def preview_status(job_id: str, authorization: str | None = Header(default=None)):
        storage = await asyncio.to_thread(storage_for, authorization)
        transferred = False
        try:
            if isinstance(storage, UserStorage) and job_id.startswith('shared.'):
                parts = job_id.split('.', 2)
                if len(parts)!=3 or parts[1] not in {'en-AU','zh-CN'}:
                    raise HTTPException(404, 'Preview job not found')
                return await shared_preview_response(storage, parts[2], parts[1])
            queue = await AgentTurnLease.io(PreviewJobs)
            job = await AgentTurnLease.io(queue.get, storage.user_id, job_id)
            if not job:
                raise HTTPException(404, 'Preview job not found')
            if isinstance(storage, UserStorage):
                # Old execution jobs remain references to canonical state after
                # cutover; polling must not resume their duplicate event index.
                return await shared_preview_response(storage, job['project_id'], job['language'])
            if job['status'] == 'SUCCEEDED':
                rows, _, key, _ = await preview_snapshot(storage, job['project_id'], job['language'])
                saved = cached_preview(rows, key) if key == job['snapshot_key'] else None
                status = 'insufficient_context' if key == job['snapshot_key'] and job['outcome'] == 'insufficient_context' else 'ready' if saved else 'stale'
                return {'status': status, 'preview': saved, 'cached': True, 'job': job}
            # A process restart leaves only an expiring claim and checkpoints.
            # This fresh authenticated poll resumes it without storing a token.
            transferred = await start_preview(queue, job, storage)
            job = await AgentTurnLease.io(queue.get, storage.user_id, job_id)
            return preview_response(job)
        except (RuntimeError, ValueError, KeyError, httpx.HTTPError, OSError) as error:
            logging.getLogger(__name__).warning('memoir_preview poll_failure_type=%s', type(error).__name__)
            raise HTTPException(503, 'Your sample status is temporarily unavailable',
                                headers={'X-Error-Code': 'PREVIEW_UNAVAILABLE'}) from None
        finally:
            if not transferred:
                await AgentTurnLease.io(_close, storage)

    @router.post("/checkout")
    def checkout(
        request: Request,
        payload: StoryCheckoutCreate | None = None,
        authorization: str | None = Header(default=None),
    ):
        storage = storage_for(authorization)
        try:
            profile = _profile(storage)
            state = _state(profile, _entitlement(payment_store, storage))
            if getattr(storage, "is_anonymous", False):
                raise HTTPException(403, "Link Google or Facebook before purchasing the full memoir.", headers={"X-Error-Code": "AUTH_REQUIRED"})
            recall_access = storage_recall_status(storage, {"status": state["payment_status"]})
            if not state["free_chapter_claimed"] and not (recall_access and recall_access["payment_required"]):
                raise HTTPException(409, "Claim the free chapter before purchasing the full memoir.", headers={"X-Error-Code": "FREE_CHAPTER_REQUIRED"})
            if state["payment_status"] == "paid":
                raise HTTPException(409, "This memoir already has a paid package.", headers={"X-Error-Code": "ALREADY_PAID"})
            requested = payload or StoryCheckoutCreate()
            try:
                summary = checkout_summary(requested.plan_key, requested.book_count)
            except StoryPlanError as error:
                raise HTTPException(422, str(error), headers={"X-Error-Code": "INVALID_STORY_PLAN"}) from error
            base_url = str(request.base_url)
            success_url, cancel_url = public_checkout_urls(base_url)
            if not getattr(stripe, "configured", False):
                return {
                    "status": "payment_required",
                    "provider": "not_configured",
                    "message": "Stripe is not configured on the API service yet.",
                    "currency": summary["currency"],
                    "amount_minor": summary["amount_minor"],
                    "selected_plan": summary,
                    "plans": list_story_plans(),
                }
            order_id = new_id("story-order")
            try:
                session = stripe.create_checkout_session(
                    order_id=order_id,
                    user_id=storage.user_id,
                    summary=summary,
                    success_url=success_url,
                    cancel_url=cancel_url,
                )
            except StripeConfigurationError as error:
                raise HTTPException(503, str(error), headers={"X-Error-Code": "STRIPE_NOT_CONFIGURED"}) from error
            except StripeAPIError as error:
                raise HTTPException(502, str(error), headers={"X-Error-Code": "STRIPE_CHECKOUT_FAILED"}) from error
            return {
                "status": "checkout_created",
                "provider": "stripe",
                "session_id": session["id"],
                "checkout_url": session["url"],
                "order_id": order_id,
                "currency": summary["currency"],
                "amount_minor": summary["amount_minor"],
                "selected_plan": summary,
                "plans": list_story_plans(),
                "message": "Redirecting you to Stripe Checkout.",
            }
        finally:
            _close(storage)

    @router.post("/stripe/webhook")
    async def stripe_webhook(request: Request):
        payload_bytes = await request.body()
        webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
        if not webhook_secret:
            raise HTTPException(503, "Stripe webhook signing is not configured.", headers={"X-Error-Code": "STRIPE_WEBHOOK_NOT_CONFIGURED"})
        if not verify_stripe_signature(payload_bytes, request.headers.get("Stripe-Signature"), webhook_secret):
            raise HTTPException(400, "Invalid Stripe webhook signature", headers={"X-Error-Code": "INVALID_STRIPE_SIGNATURE"})
        try:
            event = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HTTPException(400, "Invalid Stripe webhook payload", headers={"X-Error-Code": "INVALID_STRIPE_PAYLOAD"}) from error

        event_type = event.get("type")
        if event_type not in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
            return {"received": True, "handled": False, "event_type": event_type}
        session = ((event.get("data") or {}).get("object") or {})
        metadata = session.get("metadata") or {}
        user_id = str(metadata.get("user_id") or "")
        plan_key = str(metadata.get("plan_key") or "")
        if not user_id or not plan_key or not session.get("id"):
            return {"received": True, "handled": False, "event_type": event_type}
        try:
            book_count = int(metadata.get("book_count", "0"))
            summary = checkout_summary(plan_key, book_count)
        except (TypeError, ValueError, StoryPlanError) as error:
            raise HTTPException(400, "Stripe session metadata does not match a memoir package.", headers={"X-Error-Code": "INVALID_STRIPE_ORDER"}) from error
        payment_status = session.get("payment_status")
        if event_type == "checkout.session.completed" and payment_status not in {"paid", "no_payment_required"}:
            return {"received": True, "handled": True, "status": "payment_pending", "event_type": event_type}
        if session.get("amount_total") != summary["amount_minor"] or str(session.get("currency", "")).upper() != summary["currency"]:
            raise HTTPException(409, "Stripe session amount or currency does not match the selected memoir package.", headers={"X-Error-Code": "STRIPE_ORDER_MISMATCH"})
        payment_intent = session.get("payment_intent")
        if isinstance(payment_intent, dict):
            payment_intent = payment_intent.get("id")
        stripe_price_id = str(metadata.get("stripe_price_id") or "") or None
        configured_family_price = os.getenv("STRIPE_PRICE_FAMILY", "").strip()
        if plan_key == "family_memoir_v1" and configured_family_price and stripe_price_id != configured_family_price:
            raise HTTPException(409, "The Stripe session does not match the configured Family memoir price.", headers={"X-Error-Code": "STRIPE_PRICE_MISMATCH"})
        try:
            result = payment_store.mark_paid(
                user_id=user_id,
                session_id=str(session["id"]),
                payment_intent_id=str(payment_intent) if payment_intent else None,
                stripe_price_id=stripe_price_id,
                summary=summary,
            )
        except Exception as error:
            raise HTTPException(503, "Payment was received but the memoir entitlement could not be saved.", headers={"X-Error-Code": "PAYMENT_STORAGE_UNAVAILABLE"}) from error
        return {
            "received": True,
            "handled": True,
            "event_type": event_type,
            "status": "paid",
            "duplicate": bool(result.get("duplicate")),
        }

    @router.post("/full-memoir")
    def full_memoir(authorization: str | None = Header(default=None)):
        storage = storage_for(authorization)
        try:
            profile = _profile(storage)
            state = _state(profile, _entitlement(payment_store, storage))
            if getattr(storage, "is_anonymous", False):
                raise HTTPException(403, "Link Google or Facebook before generating your memoir.", headers={"X-Error-Code": "AUTH_REQUIRED"})
            if not state["free_chapter_claimed"]:
                raise HTTPException(409, "Claim the free chapter first.", headers={"X-Error-Code": "FREE_CHAPTER_REQUIRED"})
            if state["payment_status"] != "paid":
                raise HTTPException(
                    status_code=402,
                    detail="Payment is required before the full memoir can be generated.",
                    headers={"X-Error-Code": "PAYMENT_REQUIRED"},
                )
            raise HTTPException(
                409, 'Review the collection and confirm timeline readiness before organising the book.',
                headers={'X-Error-Code': 'COLLECTION_REVIEW_REQUIRED'},
            )
        finally:
            _close(storage)

    return router


router = build_router()
