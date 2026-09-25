"""The small, Supabase-backed anonymous-to-paid memoir journey."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Callable

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .agent_routes_support import authenticated_storage
from .store import MemoryStore, new_id
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


class StoryRoundInput(BaseModel):
    round: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=100000)


class StoryCheckoutCreate(BaseModel):
    plan_key: str = "electronic_memoir_v1"
    book_count: int | None = Field(default=None, ge=0, le=20)


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
    state["payment_status"] = "paid" if paid else "unpaid"
    state["payment_plan"] = entitlement.get("plan_key") if paid else None
    state["book_count"] = int(entitlement.get("book_count", 0)) if paid else 0
    state["payment_features"] = [
        key
        for key in ("electronic_only", "family_tree", "timeline", "expanded_details")
        if paid and entitlement.get(key)
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
) -> APIRouter:
    router = APIRouter(prefix="/v1/story", tags=["Story journey"])
    payment_store = entitlement_store or build_story_entitlement_store(MemoryStore())
    stripe = stripe_client or StripeCheckoutClient()

    def storage_for(authorization: str | None):
        return storage_factory(authorization)

    @router.get("/plans")
    def story_plans() -> dict[str, Any]:
        return {"items": list_story_plans(), "currency": "AUD"}

    @router.get("/state")
    def story_state(authorization: str | None = Header(default=None)):
        storage = storage_for(authorization)
        try:
            profile = _profile(storage)
            return _state_response(storage, _state(profile, _entitlement(payment_store, storage)))
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
            storage.save_memory(
                json.dumps({"type": "story_round", "round": payload.round, "answer": payload.answer}),
                kind="memoir",
                source_paths=[f"story-round:{payload.round}"],
            )
            state["rounds_completed"] = payload.round
            _save_state(storage, profile, state)
            return _state_response(storage, state)
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
            if not state["free_chapter_claimed"]:
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
        try:
            result = payment_store.mark_paid(
                user_id=user_id,
                session_id=str(session["id"]),
                payment_intent_id=str(payment_intent) if payment_intent else None,
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
            memoir = {
                "id": new_id("memoir"),
                "title": "Your memoir",
                "status": "generated",
                "source_memory_count": len(_round_memories(storage)),
                "package": state["payment_plan"],
                "book_count": state["book_count"],
                "features": state["payment_features"],
            }
            storage.save_memory(json.dumps(memoir), kind="memoir", source_paths=["full-memoir"])
            return {"memoir": memoir, **_state_response(storage, state)}
        finally:
            _close(storage)

    return router


router = build_router()
