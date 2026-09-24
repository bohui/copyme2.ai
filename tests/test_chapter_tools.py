from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_first_chapter_decision_is_free_and_unlocks_after_approval() -> None:
    client = TestClient(create_app())
    headers = {"X-Account-Id": "chapter-tool-storyteller"}
    project = client.post(
        "/v1/projects",
        json={"mode": "self", "language": "en-AU"},
        headers=headers,
    ).json()
    client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=headers,
    )

    session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers=headers,
    ).json()
    client.post(
        f"/v1/memory-sessions/{session['id']}/answers",
        json={"text": "I remember our small kitchen and the sound of rain."},
        headers=headers,
    ).json()
    memory = client.post(
        f"/v1/memory-sessions/{session['id']}/complete",
        json={"visibility": "private"},
        headers=headers,
    ).json()["memory"]

    decision = client.post(
        f"/v1/projects/{project['id']}/chapter-decisions",
        json={"memory_id": memory["id"], "topic_id": "childhood_home"},
        headers=headers,
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["should_start_new_chapter"] is True
    assert decision.json()["chapter_number"] == 1
    assert decision.json()["free"] is True
    assert decision.json()["memory_ids"] == [memory["id"]]

    chapter = client.post(
        f"/v1/projects/{project['id']}/chapter-builds",
        json={"title": decision.json()["title"], "memory_ids": [memory["id"]]},
        headers=headers,
    ).json()["chapter"]
    approved = client.post(
        f"/v1/chapters/{chapter['id']}/approvals",
        json={"expected_revision": chapter["revision"]},
        headers=headers,
    )
    assert approved.status_code == 200
    assert client.get(f"/v1/projects/{project['id']}", headers=headers).json()["workspace_unlocked"] is True

    same_topic_session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers=headers,
    ).json()
    client.post(
        f"/v1/memory-sessions/{same_topic_session['id']}/answers",
        json={"text": "The rain made the windows glow."},
        headers=headers,
    )
    same_topic_memory = client.post(
        f"/v1/memory-sessions/{same_topic_session['id']}/complete",
        json={"visibility": "private"},
        headers=headers,
    ).json()["memory"]
    same_topic_decision = client.post(
        f"/v1/projects/{project['id']}/chapter-decisions",
        json={"memory_id": same_topic_memory["id"], "topic_id": "childhood_home"},
        headers=headers,
    )
    assert same_topic_decision.status_code == 200
    assert same_topic_decision.json()["should_start_new_chapter"] is False
    assert same_topic_decision.json()["chapter_number"] == 1

    new_topic_session = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "work"},
        headers=headers,
    ).json()
    client.post(
        f"/v1/memory-sessions/{new_topic_session['id']}/answers",
        json={"text": "I learned responsibility through my first job."},
        headers=headers,
    )
    new_topic_memory = client.post(
        f"/v1/memory-sessions/{new_topic_session['id']}/complete",
        json={"visibility": "private"},
        headers=headers,
    ).json()["memory"]
    new_topic_decision = client.post(
        f"/v1/projects/{project['id']}/chapter-decisions",
        json={"memory_id": new_topic_memory["id"], "topic_id": "work"},
        headers=headers,
    )
    assert new_topic_decision.status_code == 200
    assert new_topic_decision.json()["should_start_new_chapter"] is True
    assert new_topic_decision.json()["chapter_number"] == 2
