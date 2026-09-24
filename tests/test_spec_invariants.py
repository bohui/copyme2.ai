from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def h(account: str, **extra: str) -> dict[str, str]:
    return {"X-Account-Id": account, **extra}


def make_approved_edition(client: TestClient, account: str = "owner") -> tuple[dict, dict]:
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h(account)).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=h(account),
    ).status_code == 200
    session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={},
        headers=h(account),
    ).json()
    assert client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"text": "My older brother and I walked to school past a little shop."},
        headers=h(account),
    ).status_code == 200
    memory = client.post(
        f"/v1/memory-sessions/{session['id']}/complete",
        json={"include_in_digital": True, "include_in_print": True},
        headers=h(account, **{"Idempotency-Key": f"complete-{account}"}),
    ).json()["memory"]
    chapter = client.post(
        f"/v1/projects/{project['id']}/chapter-builds",
        json={"memory_ids": [memory["id"]]},
        headers=h(account),
    ).json()["chapter"]
    assert client.post(
        f"/v1/chapters/{chapter['id']}/approvals",
        json={"expected_revision": chapter["revision"]},
        headers=h(account),
    ).status_code == 200
    edition = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": [chapter["id"]]},
        headers=h(account),
    ).json()
    assert client.post(
        f"/v1/editions/{edition['id']}/preflight",
        headers=h(account),
    ).json()["ok"] is True
    assert client.post(
        f"/v1/editions/{edition['id']}/approvals",
        json={"manifest_hash": edition["manifest_hash"]},
        headers=h(account),
    ).status_code == 200
    return project, edition


def test_trial_offer_is_allocated_once_per_storyteller_account(client: TestClient) -> None:
    first = client.post("/v1/projects", json={"mode": "self"}, headers=h("same-account"))
    second = client.post("/v1/projects", json={"mode": "self"}, headers=h("same-account"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["entitlements"]["trial_units_remaining"] == 5
    assert second.json()["entitlements"]["trial_units_remaining"] == 0


def test_family_memory_requires_explicit_sharing_consent(client: TestClient) -> None:
    project = client.post(
        "/v1/projects",
        json={"mode": "family", "storyteller_account_id": "father"},
        headers=h("organiser"),
    ).json()
    project_id = project["id"]
    assert client.post(
        f"/v1/projects/{project_id}/consents",
        json={"purpose": "storyteller_assent"},
        headers=h("father"),
    ).status_code == 200
    session = client.post(
        f"/v1/projects/{project_id}/memory-sessions",
        json={},
        headers=h("father"),
    ).json()
    assert client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"text": "A family memory I want to keep."},
        headers=h("father"),
    ).status_code == 200
    assert client.post(
        f"/v1/memory-sessions/{session['id']}/complete",
        json={"visibility": "family"},
        headers=h("father", **{"Idempotency-Key": "family-memory"}),
    ).status_code == 200

    private_view = client.get(f"/v1/projects/{project_id}/memories", headers=h("organiser"))
    assert private_view.status_code == 200
    assert private_view.json()["items"] == []

    assert client.post(
        f"/v1/projects/{project_id}/consents",
        json={"purpose": "family_sharing"},
        headers=h("father"),
    ).status_code == 200
    shared_view = client.get(f"/v1/projects/{project_id}/memories", headers=h("organiser"))
    assert len(shared_view.json()["items"]) == 1


def test_rights_revocation_marks_dependent_edition_blocked(client: TestClient) -> None:
    project, edition = make_approved_edition(client, "rights-owner")
    store = client.app.state.store
    store.context_assets["ctx_school_lane"]["rights"].update(
        {"can_include_in_download": True, "can_print": True}
    )
    # Build a fresh edition that records the asset in its frozen dependency set.
    chapter_id = next(iter(store.projects[project["id"]]["chapters"]))
    selected = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": [chapter_id], "context_asset_ids": ["ctx_school_lane"]},
        headers=h("rights-owner"),
    ).json()
    assert client.post(
        f"/v1/editions/{selected['id']}/preflight",
        headers=h("rights-owner"),
    ).json()["ok"] is True
    assert client.post(
        f"/v1/editions/{selected['id']}/approvals",
        json={"manifest_hash": selected["manifest_hash"]},
        headers=h("rights-owner"),
    ).status_code == 200

    revoked = client.patch(
        "/v1/ops/context-assets/ctx_school_lane/rights",
        json={"rights": {"can_print": False}},
        headers=h("ops-rights", **{"X-Role": "operator"}),
    )
    assert revoked.status_code == 200
    current = client.get(f"/v1/editions/{selected['id']}", headers=h("rights-owner"))
    assert current.json()["release_blocked"] is True
    preflight = client.post(f"/v1/editions/{selected['id']}/preflight", headers=h("rights-owner"))
    assert "context_rights:ctx_school_lane" in preflight.json()["issues"]
    assert edition["id"] != selected["id"]


def test_print_order_requires_accepted_quote_and_current_supplier_profile(client: TestClient) -> None:
    project, edition = make_approved_edition(client, "print-owner")
    quote = client.post(
        f"/v1/editions/{edition['id']}/print-quotes",
        json={"quantity": 1, "trim_size": "A5"},
        headers=h("print-owner"),
    ).json()
    before_accept = client.post(
        f"/v1/editions/{edition['id']}/print-orders",
        json={"quote_id": quote["id"], "delivery_name": "Storyteller", "delivery_address": "1 Memory Lane"},
        headers=h("print-owner"),
    )
    assert before_accept.status_code == 409
    assert client.post(
        f"/v1/print-quotes/{quote['id']}/accept",
        json={},
        headers=h("print-owner"),
    ).status_code == 200
    changed_profile = client.patch(
        "/v1/ops/suppliers/supplier_demo",
        json={"data_handling_terms": "updated terms"},
        headers=h("ops-print", **{"X-Role": "operator"}),
    )
    assert changed_profile.status_code == 200
    stale_quote = client.post(
        f"/v1/editions/{edition['id']}/print-orders",
        json={"quote_id": quote["id"], "delivery_name": "Storyteller", "delivery_address": "1 Memory Lane"},
        headers=h("print-owner"),
    )
    assert stale_quote.status_code == 409
    assert project["id"]


def test_request_id_error_contract_and_idempotency_conflict(client: TestClient) -> None:
    missing = client.get("/v1/projects/does-not-exist", headers={"X-Request-ID": "req-contract-1"})
    assert missing.status_code == 404
    assert missing.headers["x-request-id"] == "req-contract-1"
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert missing.json()["error"]["request_id"] == "req-contract-1"

    project = client.post("/v1/projects", json={"mode": "self"}, headers=h("idempotent-owner")).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=h("idempotent-owner"),
    ).status_code == 200
    first = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers=h("idempotent-owner", **{"Idempotency-Key": "start-one"}),
    )
    replay = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers=h("idempotent-owner", **{"Idempotency-Key": "start-one"}),
    )
    conflict = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "food"},
        headers=h("idempotent-owner", **{"Idempotency-Key": "start-one"}),
    )
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_expired_paid_grant_is_not_available_for_a_new_session(client: TestClient) -> None:
    account = "expired-grant-owner"
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h(account)).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=h(account),
    ).status_code == 200
    checkout = client.post(
        f"/v1/projects/{project['id']}/checkout",
        json={},
        headers=h(account),
    ).json()
    assert client.post(
        "/v1/webhooks/payments/demo",
        json={
            "event_id": "expired-grant-payment",
            "order_id": checkout["id"],
            "status": "paid",
            "amount_minor": checkout["amount_minor"],
            "currency": checkout["currency"],
            "signature": "demo-signature",
        },
    ).status_code == 200
    stored = client.app.state.store.projects[project["id"]]
    stored["trial_units_consumed"] = 5
    stored["grants"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    blocked = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={},
        headers=h(account),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "ENTITLEMENT_REQUIRED"
    assert client.get(f"/v1/projects/{project['id']}/entitlements", headers=h(account)).json()["paid_units_revoked"] == 60


def test_expired_session_reservation_can_be_rebooked_without_a_new_session(client: TestClient) -> None:
    account = "expired-session-owner"
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h(account)).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=h(account),
    ).status_code == 200
    session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={},
        headers=h(account),
    ).json()
    client.app.state.store.projects[project["id"]]["sessions"][session["id"]]["reservation_expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    blocked = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={},
        headers=h(account),
    )
    assert blocked.status_code == 409
    resumed = client.post(f"/v1/memory-sessions/{session['id']}/resume", headers=h(account))
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "QUESTION_READY"
    assert client.get(f"/v1/projects/{project['id']}/entitlements", headers=h(account)).json()["trial_units_reserved"] == 1


def test_followups_and_audio_budget_are_bounded(client: TestClient) -> None:
    account = "bounded-session-owner"
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h(account)).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=h(account),
    ).status_code == 200
    session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={},
        headers=h(account),
    ).json()
    first = client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"text": "I remember walking to school."},
        headers=h(account),
    )
    assert first.status_code == 200
    for index in range(3):
        response = client.post(
            f"/v1/memory-sessions/{session['id']}/answers",
            json={"text": f"A follow-up detail {index}.", "turn_type": "follow_up"},
            headers=h(account),
        )
        assert response.status_code == 200
    assert client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"text": "One more detail.", "turn_type": "follow_up"},
        headers=h(account),
    ).status_code == 422

    audio_project = client.post("/v1/projects", json={"mode": "self"}, headers=h("audio-owner")).json()
    assert client.post(
        f"/v1/projects/{audio_project['id']}/consents",
        json={"purpose": "recording"},
        headers=h("audio-owner"),
    ).status_code == 200
    raw = base64.b64encode(b"audio bytes").decode()
    uploads = []
    for duration in (600, 400):
        created = client.post(
            "/v1/uploads",
            json={
                "project_id": audio_project["id"],
                "kind": "audio",
                "mime_type": "audio/webm",
                "filename": f"answer-{duration}.webm",
                "duration_seconds": duration,
            },
            headers=h("audio-owner"),
        )
        assert created.status_code == 201
        upload_id = created.json()["id"]
        assert client.post(
            f"/v1/uploads/{upload_id}/parts",
            json={"sequence": 0, "content": raw},
            headers=h("audio-owner"),
        ).status_code == 200
        uploads.append(client.post(f"/v1/uploads/{upload_id}/finalize", json={}, headers=h("audio-owner")).json()["id"])
    audio_session = client.post(
        f"/v1/projects/{audio_project['id']}/memory-sessions",
        json={},
        headers=h("audio-owner"),
    ).json()
    assert client.post(
        f"/v1/memory-sessions/{audio_session['id']}/answers",
        json={"upload_id": uploads[0]},
        headers=h("audio-owner"),
    ).status_code == 200
    assert client.post(
        f"/v1/memory-sessions/{audio_session['id']}/answers",
        json={"upload_id": uploads[1], "turn_type": "follow_up"},
        headers=h("audio-owner"),
    ).status_code == 422


def test_checkout_and_webhook_keys_reject_different_payloads(client: TestClient) -> None:
    account = "commerce-idempotent-owner"
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h(account)).json()
    first = client.post(
        f"/v1/projects/{project['id']}/checkout",
        json={"plan_key": "complete_digital_memoir_v1"},
        headers=h(account, **{"Idempotency-Key": "checkout-one"}),
    )
    replay = client.post(
        f"/v1/projects/{project['id']}/checkout",
        json={"plan_key": "complete_digital_memoir_v1"},
        headers=h(account, **{"Idempotency-Key": "checkout-one"}),
    )
    changed = client.post(
        f"/v1/projects/{project['id']}/checkout",
        json={"plan_key": "unknown-plan"},
        headers=h(account, **{"Idempotency-Key": "checkout-one"}),
    )
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    order = first.json()
    bad_amount = client.post(
        "/v1/webhooks/payments/demo",
        json={
            "event_id": "commerce-idempotent-event",
            "order_id": order["id"],
            "status": "paid",
            "amount_minor": 1,
            "currency": order["currency"],
            "signature": "demo-signature",
        },
    )
    assert bad_amount.status_code == 409
    correct = client.post(
        "/v1/webhooks/payments/demo",
        json={
            "event_id": "commerce-idempotent-event",
            "order_id": order["id"],
            "status": "paid",
            "amount_minor": order["amount_minor"],
            "currency": order["currency"],
            "signature": "demo-signature",
        },
    )
    assert correct.status_code == 200
    conflict = client.post(
        "/v1/webhooks/payments/demo",
        json={
            "event_id": "commerce-idempotent-event",
            "order_id": order["id"],
            "status": "pending",
            "amount_minor": order["amount_minor"],
            "currency": order["currency"],
            "signature": "demo-signature",
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_support_grant_exposes_only_scoped_metadata_until_expiry(client: TestClient) -> None:
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h("support-owner")).json()
    grant = client.post(
        "/v1/ops/support-grants",
        json={"project_id": project["id"], "account_id": "support-agent", "capabilities": ["read_metadata"], "expires_in_hours": 1},
        headers=h("ops-support", **{"X-Role": "operator"}),
    ).json()
    metadata = client.get(
        f"/v1/ops/support-grants/{grant['id']}/projects/{project['id']}/metadata",
        headers=h("support-agent"),
    )
    assert metadata.status_code == 200
    assert "memory_count" in metadata.json()
    assert "memories" not in metadata.json()
    stored = client.app.state.store.support_grants[grant["id"]]
    stored["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    expired = client.get(
        f"/v1/ops/support-grants/{grant['id']}/projects/{project['id']}/metadata",
        headers=h("support-agent"),
    )
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "SUPPORT_GRANT_EXPIRED"


def test_policy_epoch_rejects_a_late_session_write_after_consent_changes(client: TestClient) -> None:
    account = "policy-epoch-owner"
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h(account)).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=h(account),
    ).status_code == 200
    session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={},
        headers=h(account),
    ).json()
    assert client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"text": "A remembered walk along the river."},
        headers=h(account),
    ).status_code == 200
    before = client.get(f"/v1/projects/{project['id']}", headers=h(account)).json()
    changed = client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "family_sharing", "granted": False},
        headers=h(account),
    )
    assert changed.status_code == 200
    after = client.get(f"/v1/projects/{project['id']}", headers=h(account)).json()
    assert after["policy_epoch"] > before["policy_epoch"]

    late = client.post(
        f"/v1/memory-sessions/{session['id']}/complete",
        json={},
        headers=h(account, **{"Idempotency-Key": "policy-epoch-complete"}),
    )
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "POLICY_EPOCH_CONFLICT"


def test_project_collections_support_opaque_cursor_pagination(client: TestClient) -> None:
    account = "cursor-owner"
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h(account)).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=h(account),
    ).status_code == 200
    for text in ("The first remembered walk.", "The second remembered walk."):
        session = client.post(
            f"/v1/projects/{project['id']}/memory-sessions",
            json={},
            headers=h(account),
        ).json()
        assert client.post(
            f"/v1/memory-sessions/{session['id']}/answers",
            json={"text": text},
            headers=h(account),
        ).status_code == 200
        assert client.post(
            f"/v1/memory-sessions/{session['id']}/complete",
            json={},
            headers=h(account, **{"Idempotency-Key": f"complete-{text}"}),
        ).status_code == 200

    first = client.get(f"/v1/projects/{project['id']}/memories?limit=1", headers=h(account))
    assert first.status_code == 200
    page_one = first.json()
    assert len(page_one["items"]) == 1
    assert page_one["count"] == 2
    assert page_one["next_cursor"]
    assert page_one["next_cursor"] != "1"

    second = client.get(
        f"/v1/projects/{project['id']}/memories",
        params={"limit": 1, "cursor": page_one["next_cursor"]},
        headers=h(account),
    )
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["items"][0]["id"] != page_one["items"][0]["id"]
    assert second.json()["next_cursor"] is None

    too_many = client.get(
        f"/v1/projects/{project['id']}/memories",
        params={"limit": 101},
        headers=h(account),
    )
    assert too_many.status_code == 422
    invalid = client.get(
        f"/v1/projects/{project['id']}/memories",
        params={"cursor": "not-a-cursor"},
        headers=h(account),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_CURSOR"


def test_accepted_print_quote_creates_payment_confirmed_order(client: TestClient) -> None:
    project, edition = make_approved_edition(client, "print-state-owner")
    quote = client.post(
        f"/v1/editions/{edition['id']}/print-quotes",
        json={"quantity": 1, "trim_size": "A5"},
        headers=h("print-state-owner"),
    ).json()
    assert client.post(
        f"/v1/print-quotes/{quote['id']}/accept",
        json={},
        headers=h("print-state-owner"),
    ).status_code == 200
    order = client.post(
        f"/v1/editions/{edition['id']}/print-orders",
        json={
            "quote_id": quote["id"],
            "delivery_name": "Storyteller",
            "delivery_address": "1 Memory Lane",
        },
        headers=h("print-state-owner"),
    )
    assert order.status_code == 201
    assert order.json()["status"] == "PAYMENT_CONFIRMED"
    assert order.json()["payment_status"] == "CONFIRMED"


def test_project_and_edition_creation_keys_are_replay_safe(client: TestClient) -> None:
    account = "creation-idempotency-owner"
    first = client.post(
        "/v1/projects",
        json={"mode": "self", "language": "en-AU"},
        headers=h(account, **{"Idempotency-Key": "project-create-one"}),
    )
    replay = client.post(
        "/v1/projects",
        json={"mode": "self", "language": "en-AU"},
        headers=h(account, **{"Idempotency-Key": "project-create-one"}),
    )
    conflict = client.post(
        "/v1/projects",
        json={"mode": "self", "language": "zh-CN"},
        headers=h(account, **{"Idempotency-Key": "project-create-one"}),
    )
    assert first.status_code == replay.status_code == 201
    assert first.json()["id"] == replay.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    project, edition = make_approved_edition(client, "edition-idempotency-owner")
    first_edition = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": list(client.app.state.store.projects[project["id"]]["chapter_ids"])},
        headers=h("edition-idempotency-owner", **{"Idempotency-Key": "edition-create-one"}),
    )
    replay_edition = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": list(client.app.state.store.projects[project["id"]]["chapter_ids"])},
        headers=h("edition-idempotency-owner", **{"Idempotency-Key": "edition-create-one"}),
    )
    changed_edition = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": list(client.app.state.store.projects[project["id"]]["chapter_ids"]), "locale": "zh-CN"},
        headers=h("edition-idempotency-owner", **{"Idempotency-Key": "edition-create-one"}),
    )
    assert first_edition.status_code == replay_edition.status_code == 201
    assert first_edition.json()["id"] == replay_edition.json()["id"]
    assert changed_edition.status_code == 409
    assert changed_edition.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert edition["id"] != first_edition.json()["id"]


def test_upload_finalisation_key_rejects_a_different_payload(client: TestClient) -> None:
    account = "upload-idempotency-owner"
    project = client.post("/v1/projects", json={"mode": "self"}, headers=h(account)).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=h(account),
    ).status_code == 200
    upload = client.post(
        "/v1/uploads",
        json={"project_id": project["id"], "kind": "audio", "mime_type": "audio/webm"},
        headers=h(account),
    ).json()
    assert client.post(
        f"/v1/uploads/{upload['id']}/parts",
        json={"sequence": 0, "content": base64.b64encode(b"recording").decode()},
        headers=h(account),
    ).status_code == 200
    first = client.post(
        f"/v1/uploads/{upload['id']}/finalize",
        json={"decode": "strict"},
        headers=h(account, **{"Idempotency-Key": "finalize-one"}),
    )
    replay = client.post(
        f"/v1/uploads/{upload['id']}/finalize",
        json={"decode": "strict"},
        headers=h(account, **{"Idempotency-Key": "finalize-one"}),
    )
    conflict = client.post(
        f"/v1/uploads/{upload['id']}/finalize",
        json={"decode": "relaxed"},
        headers=h(account, **{"Idempotency-Key": "finalize-one"}),
    )
    assert first.status_code == replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
