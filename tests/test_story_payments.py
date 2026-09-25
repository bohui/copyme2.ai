import hashlib
import hmac
import json
import time

import httpx
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.story_payments import LocalStoryEntitlementStore, StripeCheckoutClient, checkout_summary

from test_story_flow import FakeSupabaseUserStorage, _auth_headers, _complete_rounds


class FakeStripeCheckout:
    configured = True

    def __init__(self):
        self.calls = []

    def create_checkout_session(self, **kwargs):
        self.calls.append(kwargs)
        return {"id": "cs_test_story", "url": "https://checkout.stripe.test/cs_test_story"}


def _signed_payload(payload: bytes, secret: str) -> str:
    timestamp = int(time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_story_plans_expose_the_three_packages():
    app = create_app(MemoryStore(), story_storage_factory=lambda authorization: FakeSupabaseUserStorage())
    response = TestClient(app).get("/v1/story/plans")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [(item["plan_key"], item["price_minor"]) for item in items] == [
        ("electronic_memoir_v1", 4900),
        ("printed_memoir_v1", 7900),
        ("family_memoir_v1", 12900),
    ]


def test_story_checkout_uses_server_pricing_and_signed_webhook_grants_entitlement(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_story_test")
    storage = FakeSupabaseUserStorage()
    memory = MemoryStore()
    stripe = FakeStripeCheckout()
    app = create_app(
        memory,
        story_storage_factory=lambda authorization: storage,
        story_entitlement_store=LocalStoryEntitlementStore(memory),
        story_stripe_client=stripe,
    )
    from fastapi.testclient import TestClient

    client = TestClient(app)
    _complete_rounds(client)
    storage.is_anonymous = False
    chapter = client.post("/v1/story/free-chapter", headers=_auth_headers())
    assert chapter.status_code == 200

    checkout = client.post(
        "/v1/story/checkout",
        headers=_auth_headers(),
        json={"plan_key": "family_memoir_v1", "book_count": 4},
    )
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["amount_minor"] == 14900
    assert checkout.json()["checkout_url"] == "https://checkout.stripe.test/cs_test_story"
    assert stripe.calls[0]["summary"]["additional_books"] == 2

    event = {
        "id": "evt_story_paid",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_story",
                "payment_status": "paid",
                    "amount_total": 14900,
                "currency": "aud",
                "payment_intent": "pi_story_paid",
                "metadata": {
                    "user_id": storage.user_id,
                    "plan_key": "family_memoir_v1",
                    "book_count": "4",
                },
            }
        },
    }
    payload = json.dumps(event, separators=(",", ":")).encode()
    webhook = client.post(
        "/v1/story/stripe/webhook",
        content=payload,
        headers={"Stripe-Signature": _signed_payload(payload, "whsec_story_test")},
    )
    assert webhook.status_code == 200, webhook.text
    assert webhook.json()["status"] == "paid"

    state = client.get("/v1/story/state", headers=_auth_headers()).json()
    assert state["payment_status"] == "paid"
    assert state["payment_plan"] == "family_memoir_v1"
    assert state["book_count"] == 4
    assert set(state["payment_features"]) == {"family_tree", "timeline", "expanded_details"}
    assert state["next_action"] == "full_memoir"

    memoir = client.post("/v1/story/full-memoir", headers=_auth_headers())
    assert memoir.status_code == 200
    assert memoir.json()["memoir"]["status"] == "generated"


def test_stripe_checkout_client_sends_server_computed_line_items():
    calls = []

    def request(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, request=httpx.Request("POST", url), json={"id": "cs_test", "url": "https://checkout.stripe.test/cs_test"})

    client = StripeCheckoutClient(secret_key="sk_test_story", request_fn=request)
    result = client.create_checkout_session(
        order_id="story-order-1",
        user_id="user-1",
        summary=checkout_summary("printed_memoir_v1", 5),
        success_url="https://copyme2.test/memoir/start?checkout=success",
        cancel_url="https://copyme2.test/memoir/start?checkout=cancelled",
    )

    assert result["id"] == "cs_test"
    assert calls[0][0] == "https://api.stripe.com/v1/checkout/sessions"
    fields = dict(calls[0][1]["data"])
    assert fields["line_items[0][price_data][unit_amount]"] == "7900"
    assert fields["line_items[1][price_data][unit_amount]"] == "1000"
    assert fields["line_items[1][quantity]"] == "3"
    assert fields["metadata[plan_key]"] == "printed_memoir_v1"
    assert fields["shipping_address_collection[allowed_countries][]"] == "AU"
