from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from apps.api.main import _artifact_bytes, create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def make_memory(client: TestClient) -> tuple[dict, dict]:
    project = client.post(
        "/v1/projects",
        json={"mode": "self", "language": "en-AU"},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()
    consent = client.post(f"/v1/projects/{project['id']}/consents", json={"purpose": "recording"}, headers={"X-Account-Id": "storyteller-1"})
    assert consent.status_code == 200
    session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()
    client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"text": "My older brother and I walked to school. We passed a little shop."},
        headers={"X-Account-Id": "storyteller-1"},
    )
    completed = client.post(
        f"/v1/memory-sessions/{session['id']}/complete",
        json={"visibility": "family", "include_in_digital": True, "include_in_print": True},
        headers={"X-Account-Id": "storyteller-1", "Idempotency-Key": "memory-1"},
    )
    assert completed.status_code == 200, completed.text
    return project, completed.json()["memory"]


def test_revision_conflict_and_frozen_edition_outputs(client: TestClient) -> None:
    project, memory = make_memory(client)
    chapter_response = client.post(
        f"/v1/projects/{project['id']}/chapter-builds",
        json={"title": "Getting to school", "memory_ids": [memory["id"]]},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert chapter_response.status_code == 202
    chapter = chapter_response.json()["chapter"]
    conflict = client.patch(
        f"/v1/chapters/{chapter['id']}",
        json={"title": "Stale edit", "expected_revision": 0},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert conflict.status_code == 409
    approved_chapter = client.post(
        f"/v1/chapters/{chapter['id']}/approvals",
        json={"expected_revision": 1},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert approved_chapter.status_code == 200

    edition_response = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": [chapter["id"]], "locale": "en-AU"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert edition_response.status_code == 201, edition_response.text
    edition = edition_response.json()
    assert edition["manifest"]["chapter_versions"][0]["revision"] == 1
    assert set(edition["manifest"]["artifact_hashes"]) == {"html", "pdf", "epub", "archive"}

    preflight = client.post(f"/v1/editions/{edition['id']}/preflight", headers={"X-Account-Id": "storyteller-1"})
    assert preflight.status_code == 200
    assert preflight.json()["ok"] is True
    approval = client.post(
        f"/v1/editions/{edition['id']}/approvals",
        json={"manifest_hash": edition["manifest_hash"]},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert approval.status_code == 200
    pdf = client.get(f"/v1/editions/{edition['id']}/artifacts/pdf", headers={"X-Account-Id": "storyteller-1"})
    assert pdf.status_code == 200
    assert pdf.headers["x-artifact-sha256"] == edition["manifest"]["artifact_hashes"]["pdf"]
    assert pdf.content.startswith(b"%PDF")

    changed_memory = client.patch(
        f"/v1/memories/{memory['id']}",
        json={"text": "My older brother and I walked to school, and I remember the shop.", "expected_revision": 1},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert changed_memory.status_code == 200
    chapter_after = client.get(f"/v1/chapters/{chapter['id']}", headers={"X-Account-Id": "storyteller-1"}).json()
    assert chapter_after["status"] == "STALE"
    frozen = client.get(f"/v1/editions/{edition['id']}", headers={"X-Account-Id": "storyteller-1"}).json()
    assert frozen["manifest"]["chapter_versions"][0]["revision"] == 1


def test_zip_artifacts_are_byte_stable_across_rebuilds(client: TestClient) -> None:
    project, memory = make_memory(client)
    chapter = client.post(
        f"/v1/projects/{project['id']}/chapter-builds",
        json={"memory_ids": [memory["id"]]},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()["chapter"]
    client.post(
        f"/v1/chapters/{chapter['id']}/approvals",
        json={"expected_revision": chapter["revision"]},
        headers={"X-Account-Id": "storyteller-1"},
    )
    edition = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": [chapter["id"]]},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()
    stored = client.app.state.store.projects[project["id"]]["editions"][edition["id"]]

    for fmt in ("epub", "archive"):
        first = _artifact_bytes(stored, fmt)
        assert first == _artifact_bytes(stored, fmt)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())


def test_print_proof_change_invalidates_approval_and_supplier_gets_only_final_files(client: TestClient) -> None:
    project, memory = make_memory(client)
    chapter = client.post(
        f"/v1/projects/{project['id']}/chapter-builds",
        json={"memory_ids": [memory["id"]]},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()["chapter"]
    client.post(f"/v1/chapters/{chapter['id']}/approvals", json={}, headers={"X-Account-Id": "storyteller-1"})
    edition = client.post(
        f"/v1/projects/{project['id']}/editions",
        json={"chapter_ids": [chapter["id"]]},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()
    client.post(f"/v1/editions/{edition['id']}/preflight", headers={"X-Account-Id": "storyteller-1"})
    client.post(f"/v1/editions/{edition['id']}/approvals", json={"manifest_hash": edition["manifest_hash"]}, headers={"X-Account-Id": "storyteller-1"})
    invalid_quantity = client.post(
        f"/v1/editions/{edition['id']}/print-quotes",
        json={"supplier_id": "supplier_demo", "quantity": 100, "trim_size": "A5"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert invalid_quantity.status_code == 422
    quote = client.post(
        f"/v1/editions/{edition['id']}/print-quotes",
        json={"supplier_id": "supplier_demo", "quantity": 2, "trim_size": "A5"},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()
    accepted_quote = client.post(
        f"/v1/print-quotes/{quote['id']}/accept",
        json={},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert accepted_quote.status_code == 200
    order = client.post(
        f"/v1/editions/{edition['id']}/print-orders",
        json={"quote_id": quote["id"], "delivery_name": "Storyteller", "delivery_address": "1 Memory Lane"},
        headers={"X-Account-Id": "storyteller-1"},
    ).json()
    proof = client.post(
        f"/v1/print-orders/{order['id']}/proofs",
        json={"manifest_hash": "manifest-a"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert proof.status_code == 201
    approved = client.post(
        f"/v1/print-orders/{order['id']}/proof-approvals",
        json={"manifest_hash": "manifest-a"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert approved.status_code == 200
    changed = client.post(
        f"/v1/print-orders/{order['id']}/supplier-update",
        json={"manifest_hash": "manifest-b"},
        headers={"X-Account-Id": "storyteller-1"},
    )
    assert changed.status_code == 200
    assert changed.json()["status"] == "REQUIRES_REVISION"
    blocked = client.post(f"/v1/print-orders/{order['id']}/submit", json={}, headers={"X-Account-Id": "ops-1"})
    assert blocked.status_code == 409

    client.post(f"/v1/print-orders/{order['id']}/proofs", json={"manifest_hash": "manifest-b"}, headers={"X-Account-Id": "storyteller-1"})
    client.post(f"/v1/print-orders/{order['id']}/proof-approvals", json={"manifest_hash": "manifest-b"}, headers={"X-Account-Id": "storyteller-1"})
    package = client.get(f"/v1/print-orders/{order['id']}/supplier-package", headers={"X-Account-Id": "ops-1"})
    assert package.status_code == 200
    assert package.json()["raw_audio_included"] is False
    assert package.json()["source_transcripts_included"] is False
    submitted = client.post(f"/v1/print-orders/{order['id']}/submit", json={"ack_lost": True}, headers={"X-Account-Id": "ops-1"})
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMISSION_UNKNOWN"
    duplicate = client.post(f"/v1/print-orders/{order['id']}/submit", json={}, headers={"X-Account-Id": "ops-1"})
    assert duplicate.status_code == 409
