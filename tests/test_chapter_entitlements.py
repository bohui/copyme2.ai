from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore


def _headers(account: str) -> dict[str, str]:
    return {"X-Account-Id": account}


def test_chapter_model_has_no_five_session_cap_and_closes_after_free_first_chapter(monkeypatch) -> None:
    monkeypatch.setenv("MEMORY_SPARK_ENTITLEMENT_MODEL", "chapter")
    client = TestClient(create_app(MemoryStore()))
    account = "chapter-model-storyteller"
    headers = _headers(account)

    project = client.post("/v1/projects", json={"mode": "self"}, headers=headers).json()
    project_id = project["id"]
    assert project["entitlements"]["entitlement_model"] == "chapter"
    assert project["entitlements"]["free_chapter_available"] is True
    assert project["entitlements"]["available_primary_sessions"] is None

    assert client.post(
        f"/v1/projects/{project_id}/consents",
        json={"purpose": "recording"},
        headers=headers,
    ).status_code == 200

    memories = []
    for index in range(6):
        started = client.post(
            f"/v1/projects/{project_id}/memory-sessions",
            json={"topic_id": "childhood_home"},
            headers=headers,
        )
        assert started.status_code == 201, started.text
        session_id = started.json()["id"]
        answered = client.post(
            f"/v1/memory-sessions/{session_id}/answers",
            json={"text": f"A remembered detail from session {index + 1}."},
            headers=headers,
        )
        assert answered.status_code == 200, answered.text
        completed = client.post(
            f"/v1/memory-sessions/{session_id}/complete",
            json={},
            headers={**headers, "Idempotency-Key": f"chapter-complete-{index}"},
        )
        assert completed.status_code == 200, completed.text
        memories.append(completed.json()["memory"])

    progress = client.get(f"/v1/projects/{project_id}", headers=headers).json()
    assert progress["completed_sessions"] == 6
    assert progress["entitlements"]["free_chapter_sessions_completed"] == 6
    assert progress["entitlements"]["trial_units_consumed"] == 0
    assert progress["entitlements"]["free_chapter_available"] is True

    decision = client.post(
        f"/v1/projects/{project_id}/chapter-decisions",
        json={"memory_id": memories[0]["id"], "topic_id": memories[0]["topic_id"]},
        headers=headers,
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["free"] is True

    built = client.post(
        f"/v1/projects/{project_id}/chapter-builds",
        json={"title": decision.json()["title"], "memory_ids": decision.json()["memory_ids"]},
        headers=headers,
    )
    assert built.status_code == 202, built.text
    approved = client.post(
        f"/v1/chapters/{built.json()['chapter']['id']}/approvals",
        json={"expected_revision": built.json()["chapter"]["revision"]},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text

    after_chapter = client.get(f"/v1/projects/{project_id}", headers=headers).json()
    assert after_chapter["entitlements"]["free_chapter_available"] is False
    assert after_chapter["workspace_unlocked"] is True

    blocked = client.post(
        f"/v1/projects/{project_id}/memory-sessions",
        json={"topic_id": "work"},
        headers=headers,
    )
    assert blocked.status_code == 409
    assert blocked.headers["x-error-code"] == "ENTITLEMENT_REQUIRED"
