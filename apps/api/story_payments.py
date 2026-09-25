"""Stripe Checkout and server-controlled story entitlements.

The story journey stores its conversational state in Supabase user tables. Payment
state is deliberately kept outside that user-editable profile so a client cannot
grant itself a paid memoir by writing ``payment_status``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from copy import deepcopy
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .store import MemoryStore, now_iso


STORY_CURRENCY = "AUD"
MAX_PRINTED_BOOKS = 20
ADDITIONAL_BOOK_AMOUNT_MINOR = 1000


STORY_PLANS: dict[str, dict[str, Any]] = {
    "electronic_memoir_v1": {
        "plan_key": "electronic_memoir_v1",
        "name": "Electronic memoir",
        "price_minor": 2900,
        "currency": STORY_CURRENCY,
        "description": "A beautifully shaped electronic version of your memoir.",
        "features": ["Electronic memoir", "Source-linked story chapters", "Private digital delivery"],
        "electronic_only": True,
        "family_tree": False,
        "timeline": False,
        "expanded_details": False,
        "minimum_books": 0,
        "default_books": 0,
    },
    "printed_memoir_v1": {
        "plan_key": "printed_memoir_v1",
        "name": "Printed memoir",
        "price_minor": 5900,
        "currency": STORY_CURRENCY,
        "description": "Two printed books, with extra copies available for A$10 each.",
        "features": ["Electronic memoir", "2 printed books", "Add extra books for A$10 each"],
        "electronic_only": False,
        "family_tree": False,
        "timeline": False,
        "expanded_details": False,
        "minimum_books": 2,
        "default_books": 2,
    },
    "family_memoir_v1": {
        "plan_key": "family_memoir_v1",
        "name": "Family legacy memoir",
        "price_minor": 9900,
        "currency": STORY_CURRENCY,
        "description": "Two printed books plus a richer family record.",
        "features": ["Electronic memoir", "2 printed books", "Family tree", "Life timeline", "More detailed story context"],
        "electronic_only": False,
        "family_tree": True,
        "timeline": True,
        "expanded_details": True,
        "minimum_books": 2,
        "default_books": 2,
    },
}


class StoryPlanError(ValueError):
    """Raised when a requested story plan or quantity is not sellable."""


class StripeConfigurationError(RuntimeError):
    """Raised when Stripe is not configured for this deployment."""


class StripeAPIError(RuntimeError):
    """Raised when Stripe rejects a Checkout Session request."""


def _public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_key": plan["plan_key"],
        "name": plan["name"],
        "price_minor": plan["price_minor"],
        "currency": plan["currency"],
        "description": plan["description"],
        "features": list(plan["features"]),
        "electronic_only": plan["electronic_only"],
        "family_tree": plan["family_tree"],
        "timeline": plan["timeline"],
        "expanded_details": plan["expanded_details"],
        "minimum_books": plan["minimum_books"],
        "default_books": plan["default_books"],
        "additional_book_price_minor": ADDITIONAL_BOOK_AMOUNT_MINOR if not plan["electronic_only"] else 0,
    }


def list_story_plans() -> list[dict[str, Any]]:
    return [_public_plan(plan) for plan in STORY_PLANS.values()]


def checkout_summary(plan_key: str, book_count: int | None = None) -> dict[str, Any]:
    plan = STORY_PLANS.get(plan_key)
    if not plan:
        raise StoryPlanError("Choose one of the available memoir packages.")

    if plan["electronic_only"]:
        if book_count not in (None, 0):
            raise StoryPlanError("The electronic memoir does not include printed books.")
        books = 0
    else:
        books = plan["default_books"] if book_count is None else int(book_count)
        if books < plan["minimum_books"] or books > MAX_PRINTED_BOOKS:
            raise StoryPlanError(f"Choose between {plan['minimum_books']} and {MAX_PRINTED_BOOKS} printed books.")

    additional_books = max(0, books - 2)
    total_minor = plan["price_minor"] + (additional_books * ADDITIONAL_BOOK_AMOUNT_MINOR)
    return {
        "plan": _public_plan(plan),
        "plan_key": plan_key,
        "book_count": books,
        "additional_books": additional_books,
        "amount_minor": total_minor,
        "currency": plan["currency"],
        "features": list(plan["features"]),
        "electronic_only": plan["electronic_only"],
        "family_tree": plan["family_tree"],
        "timeline": plan["timeline"],
        "expanded_details": plan["expanded_details"],
    }


class LocalStoryEntitlementStore:
    """Small local adapter used by tests and credential-free development."""

    def __init__(self, memory: MemoryStore):
        self.memory = memory

    def get(self, user_id: str) -> dict[str, Any] | None:
        with self.memory.lock:
            return deepcopy(self.memory.story_entitlements.get(user_id))

    def mark_paid(self, *, user_id: str, session_id: str, payment_intent_id: str | None, summary: dict[str, Any]) -> dict[str, Any]:
        with self.memory.lock:
            existing = self.memory.story_entitlements.get(user_id)
            if existing and existing.get("stripe_session_id") == session_id and existing.get("status") == "paid":
                return {"entitlement": deepcopy(existing), "duplicate": True}
            entitlement = {
                "user_id": user_id,
                "status": "paid",
                "plan_key": summary["plan_key"],
                "book_count": summary["book_count"],
                "amount_minor": summary["amount_minor"],
                "currency": summary["currency"],
                "electronic_only": summary["electronic_only"],
                "family_tree": summary["family_tree"],
                "timeline": summary["timeline"],
                "expanded_details": summary["expanded_details"],
                "stripe_session_id": session_id,
                "stripe_payment_intent_id": payment_intent_id,
                "paid_at": now_iso(),
                "updated_at": now_iso(),
            }
            self.memory.story_entitlements[user_id] = entitlement
            return {"entitlement": deepcopy(entitlement), "duplicate": False}


class SupabaseStoryEntitlementStore:
    """Service-key adapter for the server-only entitlement table."""

    table = "story_entitlements"

    def __init__(self, url: str, service_key: str, *, client: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.service_key = service_key
        self.client = client or httpx.Client(timeout=15)
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, f"{self.url}{path}", headers={**self.headers, **kwargs.pop("headers", {})}, **kwargs)
        response.raise_for_status()
        return response

    def get(self, user_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            f"/rest/v1/{self.table}",
            params={"select": "*", "user_id": f"eq.{quote(user_id, safe='')}", "limit": "1"},
        ).json()
        return deepcopy(rows[0]) if rows else None

    def mark_paid(self, *, user_id: str, session_id: str, payment_intent_id: str | None, summary: dict[str, Any]) -> dict[str, Any]:
        existing = self.get(user_id)
        if existing and existing.get("stripe_session_id") == session_id and existing.get("status") == "paid":
            return {"entitlement": existing, "duplicate": True}
        now = now_iso()
        entitlement = {
            "user_id": user_id,
            "status": "paid",
            "plan_key": summary["plan_key"],
            "book_count": summary["book_count"],
            "amount_minor": summary["amount_minor"],
            "currency": summary["currency"],
            "electronic_only": summary["electronic_only"],
            "family_tree": summary["family_tree"],
            "timeline": summary["timeline"],
            "expanded_details": summary["expanded_details"],
            "stripe_session_id": session_id,
            "stripe_payment_intent_id": payment_intent_id,
            "paid_at": now,
            "updated_at": now,
        }
        response = self._request(
            "POST",
            f"/rest/v1/{self.table}",
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json=entitlement,
        )
        rows = response.json()
        return {"entitlement": deepcopy(rows[0] if rows else entitlement), "duplicate": False}

    def close(self) -> None:
        self.client.close()


def build_story_entitlement_store(memory: MemoryStore) -> LocalStoryEntitlementStore | SupabaseStoryEntitlementStore:
    url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if url and service_key:
        return SupabaseStoryEntitlementStore(url, service_key)
    return LocalStoryEntitlementStore(memory)


class StripeCheckoutClient:
    """Minimal Stripe REST client for one-time hosted Checkout sessions."""

    def __init__(self, *, secret_key: str | None = None, request_fn: Callable[..., httpx.Response] | None = None):
        self.secret_key = (secret_key if secret_key is not None else os.getenv("STRIPE_SECRET_KEY", "")).strip()
        self.request_fn = request_fn or httpx.post
        self.price_ids = {
            "electronic_memoir_v1": os.getenv("STRIPE_PRICE_ELECTRONIC", "").strip(),
            "printed_memoir_v1": os.getenv("STRIPE_PRICE_PRINTED", "").strip(),
            "family_memoir_v1": os.getenv("STRIPE_PRICE_FAMILY", "").strip(),
            "additional_book": os.getenv("STRIPE_PRICE_ADDITIONAL_BOOK", "").strip(),
        }

    @property
    def configured(self) -> bool:
        return bool(self.secret_key)

    @staticmethod
    def _append_price_data(fields: list[tuple[str, str]], index: int, *, price_id: str, amount_minor: int, name: str, description: str, quantity: int) -> None:
        prefix = f"line_items[{index}]"
        if price_id:
            fields.extend([(f"{prefix}[price]", price_id), (f"{prefix}[quantity]", str(quantity))])
            return
        fields.extend(
            [
                (f"{prefix}[price_data][currency]", STORY_CURRENCY.lower()),
                (f"{prefix}[price_data][unit_amount]", str(amount_minor)),
                (f"{prefix}[price_data][product_data][name]", name),
                (f"{prefix}[price_data][product_data][description]", description),
                (f"{prefix}[quantity]", str(quantity)),
            ]
        )

    def create_checkout_session(
        self,
        *,
        order_id: str,
        user_id: str,
        summary: dict[str, Any],
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        if not self.configured:
            raise StripeConfigurationError("Stripe is not configured. Set STRIPE_SECRET_KEY on the API service.")

        plan = summary["plan"]
        fields: list[tuple[str, str]] = [
            ("mode", "payment"),
            ("client_reference_id", order_id),
            ("success_url", success_url),
            ("cancel_url", cancel_url),
        ]
        metadata = {
            "order_id": order_id,
            "user_id": user_id,
            "plan_key": summary["plan_key"],
            "book_count": str(summary["book_count"]),
        }
        fields.extend((f"metadata[{key}]", value) for key, value in metadata.items())
        if not summary["electronic_only"]:
            allowed_countries = [
                country.strip().upper()
                for country in os.getenv("MEMORY_SPARK_PRINT_COUNTRIES", "AU").split(",")
                if country.strip()
            ] or ["AU"]
            fields.extend(("shipping_address_collection[allowed_countries][]", country) for country in allowed_countries)
        self._append_price_data(
            fields,
            0,
            price_id=self.price_ids[summary["plan_key"]],
            amount_minor=plan["price_minor"],
            name=plan["name"],
            description=plan["description"],
            quantity=1,
        )
        if summary["additional_books"]:
            self._append_price_data(
                fields,
                1,
                price_id=self.price_ids["additional_book"],
                amount_minor=ADDITIONAL_BOOK_AMOUNT_MINOR,
                name="Additional printed book",
                description="One additional copy of the printed memoir.",
                quantity=summary["additional_books"],
            )

        try:
            response = self.request_fn(
                "https://api.stripe.com/v1/checkout/sessions",
                data=fields,
                auth=(self.secret_key, ""),
                timeout=20,
            )
            response.raise_for_status()
            session = response.json()
        except (httpx.HTTPError, ValueError) as error:
            detail = "Stripe could not create the Checkout Session."
            if isinstance(error, httpx.HTTPStatusError):
                try:
                    detail = error.response.json().get("error", {}).get("message") or detail
                except (ValueError, AttributeError):
                    pass
            raise StripeAPIError(detail) from error
        if not session.get("id") or not session.get("url"):
            raise StripeAPIError("Stripe returned an incomplete Checkout Session.")
        return session


def verify_stripe_signature(payload: bytes, signature: str | None, secret: str, *, tolerance_seconds: int = 300) -> bool:
    """Verify the Stripe-Signature header using the raw request body."""

    if not signature or not secret:
        return False
    timestamp: int | None = None
    signatures: list[str] = []
    for item in signature.split(","):
        key, separator, value = item.partition("=")
        if not separator:
            continue
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return False
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not signatures or abs(int(time.time()) - timestamp) > tolerance_seconds:
        return False
    try:
        body_text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return False
    signed_payload = f"{timestamp}.{body_text}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)


def public_checkout_urls(request_base_url: str) -> tuple[str, str]:
    public_base = os.getenv("MEMORY_SPARK_PUBLIC_URL", "").strip().rstrip("/") or request_base_url.rstrip("/")
    success = os.getenv("STRIPE_SUCCESS_URL", "").strip() or f"{public_base}/memoir/start?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel = os.getenv("STRIPE_CANCEL_URL", "").strip() or f"{public_base}/memoir/start?checkout=cancelled"
    return success, cancel
