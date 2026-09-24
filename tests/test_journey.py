from fastapi.testclient import TestClient

from apps.api.main import create_app


def test_storyteller_can_create_project_and_start_first_memory():
    client = TestClient(create_app())

    created = client.post(
        "/v1/projects",
        json={
            "mode": "self",
            "language": "zh-CN",
            "birth_year": None,
            "childhood_place": None,
        },
        headers={"X-Account-Id": "storyteller-1"},
    )

    assert created.status_code == 201
    project = created.json()
    assert project["trial_units_remaining"] == 5
    assert project["profile"]["birth_year"] is None

    started = client.post(
        f"/v1/projects/{project['id']}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers={"X-Account-Id": "storyteller-1"},
    )

    assert started.status_code == 201
    session = started.json()
    assert session["status"] == "QUESTION_READY"
    assert session["question"]["elicitation"] == "unaided"
    assert "school" in session["question"]["text"].lower()
