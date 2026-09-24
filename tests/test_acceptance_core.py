from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def create_project(client: TestClient, account: str = "storyteller-1", **extra: object) -> dict:
    payload = {"mode": "self", "language": "en-AU", "birth_year": None, "childhood_place": None, **extra}
    response = client.post("/v1/projects", json=payload, headers={"X-Account-Id": account})
    assert response.status_code == 201, response.text
    project = response.json()
    if payload["mode"] == "self":
        consent = client.post(f"/v1/projects/{project['id']}/consents", json={"purpose": "recording"}, headers={"X-Account-Id": account})
        assert consent.status_code == 200, consent.text
    return project


def test_invitation_preview_does_not_redeem_and_acceptance_is_single_use(client: TestClient) -> None:
    project = create_project(client)
    created = client.post(
        f"/v1/projects/{project['id']}/invitations",
        json={"intended_role": "editor", "capability_set": ["read_shared"]},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert created.status_code == 201
    token = created.json()["token"]

    preview = client.get(f"/v1/invitations/{token}")
    assert preview.status_code == 200
    assert preview.json()["redeemed"] is False

    accepted = client.post(f"/v1/invitations/{token}/accept", headers={"X-Account-Id": "editor-1"})
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "editor"
    replay = client.post(f"/v1/invitations/{token}/accept", headers={"X-Account-Id": "editor-2"})
    assert replay.status_code == 409


def test_family_payment_does_not_replace_storyteller_consent(client: TestClient) -> None:
    project = create_project(client, account="daughter-1", mode="family", storyteller_account_id="father-1")
    blocked = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers={"X-Account-Id": "daughter-1"},
    )
    assert blocked.status_code == 403

    consent = client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "storyteller_assent", "assistance_method": "helper_operated_device"},
        headers={"X-Account-Id": "father-1"},
    )
    assert consent.status_code == 200
    started = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers={"X-Account-Id": "father-1"},
    )
    assert started.status_code == 201


def test_resumable_upload_finalisation_is_idempotent_and_validates_checksum(client: TestClient) -> None:
    project = create_project(client)
    raw = b"persisted audio bytes"
    checksum = hashlib.sha256(raw).hexdigest()
    created = client.post(
        "/v1/uploads",
        json={"project_id": project["id"], "kind": "audio", "filename": "answer.webm", "mime_type": "audio/webm", "expected_size": len(raw), "expected_checksum": checksum},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert created.status_code == 201
    upload_id = created.json()["id"]
    part = client.post(
        f"/v1/uploads/{upload_id}/parts",
        json={"sequence": 0, "content": base64.b64encode(raw).decode()},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert part.status_code == 200
    first = client.post(f"/v1/uploads/{upload_id}/finalize", json={}, headers={"X-Account-Id": "storyteller-1"})
    second = client.post(f"/v1/uploads/{upload_id}/finalize", json={}, headers={"X-Account-Id": "storyteller-1"})
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    spoofed = client.post(
        "/v1/uploads",
        json={"project_id": project["id"], "kind": "document", "filename": "bad.zip", "mime_type": "application/zip"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert spoofed.status_code == 415


def test_cue_reaction_alone_does_not_create_biography_and_completion_is_idempotent(client: TestClient) -> None:
    project = create_project(client)
    started = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()
    answered = client.post(
        f"/v1/memory-sessions/{started['id']}/answers",
        json={"text": "My older brother and I walked to school. I am not sure which year."},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert answered.status_code == 200
    cues = answered.json()["context_cues"]
    assert len(cues) <= 3
    assert all("Historical reference" in cue["label"] for cue in cues)
    reacted = client.post(
        f"/v1/memory-sessions/{started['id']}/cue-reactions",
        json={"asset_id": cues[0]["asset_id"], "reaction": "familiar"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert reacted.status_code == 200
    assert reacted.json()["creates_personal_claim"] is False

    follow_up = client.post(
        f"/v1/memory-sessions/{started['id']}/answers",
        json={"text": "We walked past a little shop with him.", "turn_type": "follow_up"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert follow_up.status_code == 200
    assert any(claim["elicitation"] == "after_cue" for claim in follow_up.json()["claims"])
    completed = client.post(
        f"/v1/memory-sessions/{started['id']}/complete",
        json={"visibility": "private"},
        headers={"X-Account-Id": "storyteller-1", "Idempotency-Key": "complete-once"},
    )
    replay = client.post(
        f"/v1/memory-sessions/{started['id']}/complete",
        json={"visibility": "private"},
        headers={"X-Account-Id": "storyteller-1", "Idempotency-Key": "complete-once"},
    )
    assert completed.status_code == replay.status_code == 200
    assert completed.json()["memory"]["id"] == replay.json()["memory"]["id"]
    assert completed.json()["entitlements"]["trial_units_consumed"] == 1


def test_five_sessions_create_one_free_preview_and_gate_the_sixth(client: TestClient) -> None:
    project = create_project(client)
    completed_ids = []
    for index in range(5):
        started = client.post(
            f"/v1/projects/{project['id']}/memory-sessions",
            json={"topic_id": "childhood_home"},
            headers={"X-Account-Id": "storyteller-1"},
        )
        assert started.status_code == 201, started.text
        session_id = started.json()["id"]
        answered = client.post(
            f"/v1/memory-sessions/{session_id}/answers",
            json={"text": f"I remember a short moment from memory number {index + 1}."},
            headers={"X-Account-Id": "storyteller-1"},
        )
        assert answered.status_code == 200
        completed = client.post(
            f"/v1/memory-sessions/{session_id}/complete",
            json={},
            headers={"X-Account-Id": "storyteller-1", "Idempotency-Key": f"completion-{index}"},
        )
        assert completed.status_code == 200
        completed_ids.append(completed.json()["memory"]["id"])

    project_state = client.get(f"/v1/projects/{project['id']}", headers={"X-Account-Id": "storyteller-1"}).json()
    assert project_state["entitlements"]["trial_units_consumed"] == 5
    assert project_state["preview"]["status"] == "READY"
    assert client.get(f"/v1/projects/{project['id']}/preview", headers={"X-Account-Id": "storyteller-1"}).status_code == 200
    preview_retry = client.post(f"/v1/projects/{project['id']}/preview-builds", headers={"X-Account-Id": "storyteller-1"})
    assert preview_retry.status_code == 202
    assert preview_retry.json()["job"]["id"] == next(iter(client.app.state.store.jobs))

    sixth = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "work"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert sixth.status_code == 409
    assert sixth.headers["x-error-code"] == "ENTITLEMENT_REQUIRED"


def test_sponsored_checkout_grants_capacity_without_granting_private_access(client: TestClient) -> None:
    project = create_project(client, account="father-1")
    checkout = client.post(
        f"/v1/projects/{project['id']}/checkout",
        json={"plan_key": "complete_digital_memoir_v1", "beneficiary_project_id": project["id"]},
        headers={"X-Account-Id": "daughter-1"},
    )
    assert checkout.status_code == 201, checkout.text
    order = checkout.json()
    paid = client.post(
        "/v1/webhooks/payments/demo",
        json={"event_id": "evt-1", "order_id": order["id"], "status": "paid", "amount_minor": order["amount_minor"], "currency": order["currency"], "signature": "demo-signature"},
    )
    assert paid.status_code == 200
    replay = client.post(
        "/v1/webhooks/payments/demo",
        json={"event_id": "evt-1", "order_id": order["id"], "status": "paid", "amount_minor": order["amount_minor"], "currency": order["currency"], "signature": "demo-signature"},
    )
    assert replay.status_code == 200
    entitlements = client.get(f"/v1/projects/{project['id']}/entitlements", headers={"X-Account-Id": "father-1"}).json()
    assert entitlements["paid_units_total"] == 60
    private_read = client.get(f"/v1/projects/{project['id']}/memories", headers={"X-Account-Id": "daughter-1"})
    assert private_read.status_code == 403
    forged = client.post(
        "/v1/webhooks/payments/demo",
        json={"event_id": "evt-forged", "order_id": order["id"], "status": "paid", "amount_minor": 1, "currency": order["currency"], "signature": "bad"},
    )
    assert forged.status_code == 400
