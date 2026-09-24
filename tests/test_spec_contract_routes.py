from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def create_project(client: TestClient, account: str = "owner-1") -> dict:
    response = client.post(
        "/v1/projects",
        json={"mode": "self", "language": "en-AU"},
        headers={"X-Account-Id": account},
    )
    assert response.status_code == 201, response.text
    consent = client.post(
        f"/v1/projects/{response.json()['id']}/consents",
        json={"purpose": "recording"},
        headers={"X-Account-Id": account},
    )
    assert consent.status_code == 200, consent.text
    return response.json()


def create_memory(client: TestClient, account: str = "owner-1") -> tuple[dict, dict]:
    project = create_project(client, account)
    session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers={"X-Account-Id": account},
    ).json()
    answered = client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"text": "My older brother and I walked to school."},
        headers={"X-Account-Id": account},
    )
    assert answered.status_code == 200, answered.text
    completed = client.post(
        f"/v1/memory-sessions/{session['id']}/complete",
        json={"include_in_digital": True, "include_in_print": True},
        headers={"X-Account-Id": account},
    )
    assert completed.status_code == 200, completed.text
    return project, completed.json()["memory"]


def test_challenge_project_patch_and_member_removal_contract(client: TestClient) -> None:
    challenge = client.post("/v1/auth/challenges", json={"contact": "person@example.test"})
    assert challenge.status_code == 202
    verified = client.post(
        f"/v1/auth/challenges/{challenge.json()['challenge_id']}/verify",
        json={"token": challenge.json()["demo_token"]},
    )
    assert verified.status_code == 200
    assert verified.json()["verified"] is True

    project = create_project(client)
    invitation = client.post(
        f"/v1/projects/{project['id']}/invitations",
        json={"intended_role": "editor", "capability_set": ["read_shared"]},
        headers={"X-Account-Id": "owner-1"},
    )
    assert invitation.status_code == 201
    accepted = client.post(
        f"/v1/invitations/{invitation.json()['token']}/accept",
        headers={"X-Account-Id": "editor-1"},
    )
    assert accepted.status_code == 200

    current = client.get(f"/v1/projects/{project['id']}", headers={"X-Account-Id": "owner-1"}).json()
    patched = client.patch(
        f"/v1/projects/{project['id']}",
        json={"expected_revision": current["revision"], "childhood_place": "A small town"},
        headers={"X-Account-Id": "owner-1"},
    )
    assert patched.status_code == 200
    assert patched.json()["profile"]["childhood_place"] == "A small town"

    removed = client.delete(
        f"/v1/projects/{project['id']}/members/editor-1",
        headers={"X-Account-Id": "owner-1"},
    )
    assert removed.status_code == 204
    assert client.get(f"/v1/projects/{project['id']}", headers={"X-Account-Id": "editor-1"}).status_code == 403


def test_cue_exposure_source_correction_and_memory_approval_contract(client: TestClient) -> None:
    project, memory = create_memory(client)
    session = client.get(
        f"/v1/projects/{project['id']}/journey",
        headers={"X-Account-Id": "owner-1"},
    ).json()
    # The completed session is still addressable through the project store; start a new one for cue APIs.
    started = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "food"},
        headers={"X-Account-Id": "owner-1"},
    ).json()
    answered = client.post(
        f"/v1/memory-sessions/{started['id']}/answers",
        json={"text": "I remember a market meal."},
        headers={"X-Account-Id": "owner-1"},
    )
    assert answered.status_code == 200
    cues = client.get(f"/v1/memory-sessions/{started['id']}/cues", headers={"X-Account-Id": "owner-1"})
    assert cues.status_code == 200
    assert cues.json()["items"]
    exposure = client.post(
        f"/v1/memory-sessions/{started['id']}/cue-exposures",
        json={"asset_id": cues.json()["items"][0]["asset_id"], "event": "play_started"},
        headers={"X-Account-Id": "owner-1"},
    )
    assert exposure.status_code == 201
    assert exposure.json()["exposure"]["state"] == "play_started"

    upload = client.post(
        f"/v1/projects/{project['id']}/uploads",
        json={"kind": "photo", "filename": "family.jpg", "mime_type": "image/jpeg", "rights_confirmed": True},
        headers={"X-Account-Id": "owner-1"},
    )
    raw = b"\xff\xd8\xff\xe0jpeg fixture"
    part = client.post(
        f"/v1/uploads/{upload.json()['id']}/parts",
        json={"sequence": 0, "content": base64.b64encode(raw).decode()},
        headers={"X-Account-Id": "owner-1"},
    )
    assert part.status_code == 200
    asset = client.post(
        f"/v1/uploads/{upload.json()['id']}/finalize",
        json={},
        headers={"X-Account-Id": "owner-1"},
    ).json()
    correction = client.post(
        f"/v1/sources/{asset['id']}/corrections",
        json={"text": "The caption was corrected by the storyteller.", "expected_revision": 1},
        headers={"X-Account-Id": "owner-1"},
    )
    assert correction.status_code == 201
    assert correction.json()["asset"]["revision"] == 2

    approved = client.post(
        f"/v1/memories/{memory['id']}/approvals",
        json={"expected_revision": memory["revision"]},
        headers={"X-Account-Id": "owner-1"},
    )
    assert approved.status_code == 200
    assert approved.json()["review_status"] == "APPROVED"


def test_outline_release_export_sse_and_print_lifecycle_contract(client: TestClient) -> None:
    project, memory = create_memory(client)
    outline = client.post(
        f"/v1/projects/{project['id']}/outline-builds",
        json={"title": "A short outline"},
        headers={"X-Account-Id": "owner-1"},
    )
    assert outline.status_code == 202
    chapter = client.post(
        f"/v1/projects/{project['id']}/chapter-builds",
        json={"memory_ids": [memory["id"]]},
        headers={"X-Account-Id": "owner-1"},
    ).json()["chapter"]
    assert client.post(f"/v1/chapters/{chapter['id']}/approvals", json={}, headers={"X-Account-Id": "owner-1"}).status_code == 200
    edition = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": [chapter["id"]]},
        headers={"X-Account-Id": "owner-1"},
    ).json()
    assert client.post(f"/v1/editions/{edition['id']}/preflight", headers={"X-Account-Id": "owner-1"}).json()["ok"] is True
    assert client.post(f"/v1/editions/{edition['id']}/approvals", json={"manifest_hash": edition["manifest_hash"]}, headers={"X-Account-Id": "owner-1"}).status_code == 200
    released = client.post(f"/v1/editions/{edition['id']}/releases", json={}, headers={"X-Account-Id": "owner-1"})
    assert released.status_code == 200
    assert released.json()["status"] == "RELEASED"
    artifact = client.get(f"/v1/artifacts/{edition['id']}/download?format=pdf", headers={"X-Account-Id": "owner-1"})
    assert artifact.status_code == 200
    assert artifact.content.startswith(b"%PDF")

    export = client.post(f"/v1/projects/{project['id']}/exports", json={"kind": "owned_sources"}, headers={"X-Account-Id": "owner-1"})
    assert export.status_code == 202
    assert export.json()["export"]["status"] == "READY"

    stream = client.get(
        f"/v1/projects/{project['id']}/events",
        headers={"X-Account-Id": "owner-1", "Accept": "text/event-stream"},
    )
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "project.created" in stream.text

    quote = client.post(
        f"/v1/editions/{edition['id']}/print-quotes",
        json={"quantity": 2, "trim_size": "A5"},
        headers={"X-Account-Id": "owner-1"},
    ).json()
    assert client.post(f"/v1/print-quotes/{quote['id']}/accept", json={}, headers={"X-Account-Id": "owner-1"}).json()["status"] == "ACCEPTED"
    order = client.post(
        f"/v1/editions/{edition['id']}/print-orders",
        json={"quote_id": quote["id"], "delivery_name": "Storyteller", "delivery_address": "1 Memory Lane"},
        headers={"X-Account-Id": "owner-1"},
    ).json()
    cancelled = client.post(f"/v1/print-orders/{order['id']}/cancellation-requests", json={}, headers={"X-Account-Id": "owner-1"})
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "CANCELLED"
