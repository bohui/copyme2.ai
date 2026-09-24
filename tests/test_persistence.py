from __future__ import annotations

import json
import subprocess
import sys
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore


def headers(account: str) -> dict[str, str]:
    return {"X-Account-Id": account}


def test_persistent_cell_restores_projects_grants_and_events_after_restart(tmp_path) -> None:
    path = tmp_path / "memory-spark" / "store.json"
    first_app = create_app(MemoryStore(persistence_path=str(path)))
    first_client = TestClient(first_app)

    created = first_client.post(
        "/v1/projects",
        json={"mode": "self", "childhood_place": "unknown"},
        headers=headers("restart-owner"),
    )
    assert created.status_code == 201
    project_id = created.json()["id"]
    assert path.exists()

    consent = first_client.post(
        f"/v1/projects/{project_id}/consents",
        json={"purpose": "recording"},
        headers=headers("restart-owner"),
    )
    assert consent.status_code == 200
    started = first_client.post(
        f"/v1/projects/{project_id}/memory-sessions",
        json={"topic_id": "childhood_home"},
        headers=headers("restart-owner"),
    )
    assert started.status_code == 201
    session_id = started.json()["id"]

    restored_store = MemoryStore.from_path(path)
    restored_app = create_app(restored_store)
    restored_client = TestClient(restored_app)
    project = restored_client.get(f"/v1/projects/{project_id}", headers=headers("restart-owner"))
    assert project.status_code == 200
    assert project.json()["id"] == project_id
    assert project.json()["entitlements"]["trial_units_reserved"] == 1
    session = restored_client.get(f"/v1/memory-sessions/{session_id}", headers=headers("restart-owner"))
    assert session.status_code == 200
    assert session.json()["id"] == session_id
    assert session.json()["question"]["elicitation"] == "unaided"
    assert restored_app.state.store.audit_events


def test_persistent_snapshot_is_atomic_and_json_safe_for_conflict_metadata(tmp_path) -> None:
    path = tmp_path / "store.json"
    store = MemoryStore(persistence_path=str(path))
    store.projects["project_1"] = {"conflict_claim_ids": {"claim_b", "claim_a"}}
    store.save()

    restored = MemoryStore.from_path(path)
    assert restored.projects["project_1"]["conflict_claim_ids"] == ["claim_a", "claim_b"]
    assert not list(path.parent.glob("*.tmp"))


def test_verified_auth_uses_http_only_cookie_and_csrf_for_browser_mutations() -> None:
    client = TestClient(create_app())
    challenge = client.post("/v1/auth/challenges", json={"contact": "cookie-owner@example.test"})
    assert challenge.status_code == 202
    verified = client.post(
        f"/v1/auth/challenges/{challenge.json()['challenge_id']}/verify",
        json={"token": challenge.json()["demo_token"]},
    )
    assert verified.status_code == 200
    assert "memory_spark_session=" in verified.headers.get("set-cookie", "")
    assert "HttpOnly" in verified.headers.get("set-cookie", "")

    missing_csrf = client.post("/v1/projects", json={"mode": "self"})
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error"]["code"] == "CSRF_REQUIRED"

    csrf = client.cookies.get("memory_spark_csrf")
    created = client.post(
        "/v1/projects",
        json={"mode": "self"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    assert created.json()["owner_id"] == verified.json()["account_id"]

    assert client.post("/v1/auth/logout").status_code == 200
    after_logout = client.get(f"/v1/projects/{created.json()['id']}")
    assert after_logout.status_code == 403


def test_uploaded_original_is_stored_as_a_separate_object(tmp_path) -> None:
    persistence_path = tmp_path / "store.json"
    object_path = tmp_path / "objects"
    store = MemoryStore(persistence_path=str(persistence_path), object_store_path=str(object_path))
    client = TestClient(create_app(store))
    account = "object-owner"
    project = client.post("/v1/projects", json={"mode": "self"}, headers=headers(account)).json()
    assert client.post(
        f"/v1/projects/{project['id']}/consents",
        json={"purpose": "recording"},
        headers=headers(account),
    ).status_code == 200
    created = client.post(
        "/v1/uploads",
        json={"project_id": project["id"], "kind": "audio", "mime_type": "audio/webm"},
        headers=headers(account),
    ).json()
    raw = b"object-store-recording"
    import base64

    assert client.post(
        f"/v1/uploads/{created['id']}/parts",
        json={"sequence": 0, "content": base64.b64encode(raw).decode()},
        headers=headers(account),
    ).status_code == 200
    asset = client.post(
        f"/v1/uploads/{created['id']}/finalize",
        json={},
        headers=headers(account),
    ).json()
    assert asset["object_key"].startswith(f"projects/{project['id']}/originals/")
    assert (object_path / asset["object_key"]).read_bytes() == raw
    assert "parts" not in client.get(f"/v1/uploads/{created['id']}", headers=headers(account)).json()


def test_synchronous_job_completion_acknowledges_its_outbox_event() -> None:
    store = MemoryStore()
    job = store.queue_job("project_1", "BuildChapter", {"chapter_id": "chapter_1"})

    assert store.pending_outbox_count() == 1
    store.complete_job(job["id"], {"chapter_id": "chapter_1"})

    assert store.jobs[job["id"]]["status"] == "SUCCEEDED"
    assert store.jobs[job["id"]]["result"] == {"chapter_id": "chapter_1"}
    assert store.pending_outbox_count() == 0
    assert store.outbox[0]["status"] == "ACKED"
    assert store.outbox[0]["operation_id"] == job["id"]


def test_backup_and_restore_preserve_filesystem_objects(tmp_path) -> None:
    source_snapshot = tmp_path / "source" / "store.json"
    source_objects = tmp_path / "source" / "objects"
    backup_snapshot = tmp_path / "backup" / "store.json"
    backup_objects = tmp_path / "backup" / "objects.tar.gz"
    restored_snapshot = tmp_path / "restored" / "store.json"
    restored_objects = tmp_path / "restored" / "objects"
    source_objects.mkdir(parents=True)
    store = MemoryStore(persistence_path=str(source_snapshot), object_store_path=str(source_objects))
    object_key = store.put_object("projects/project_1/originals/asset_1", b"immutable-original")
    store.projects["project_1"] = {"id": "project_1", "object_key": object_key}
    store.save()

    subprocess.run(
        [
            sys.executable,
            "scripts/backup_store.py",
            "--source",
            str(source_snapshot),
            "--output",
            str(backup_snapshot),
            "--objects",
            str(source_objects),
            "--objects-output",
            str(backup_objects),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "scripts/restore_store.py",
            "--backup",
            str(backup_snapshot),
            "--destination",
            str(restored_snapshot),
            "--objects-backup",
            str(backup_objects),
            "--objects-destination",
            str(restored_objects),
        ],
        check=True,
    )

    restored = MemoryStore.from_path(restored_snapshot, object_store_path=restored_objects)
    assert restored.projects["project_1"]["object_key"] == object_key
    assert restored.read_object(object_key) == b"immutable-original"
    manifest = json.loads(backup_objects.with_suffix(backup_objects.suffix + ".manifest.json").read_text())
    assert manifest["file_count"] == 1


def test_outbox_dispatcher_leases_and_acknowledges_a_persisted_event(tmp_path) -> None:
    path = tmp_path / "store.json"
    store = MemoryStore(persistence_path=str(path))
    job = store.queue_job("project_1", "BuildChapter", {"chapter_id": "chapter_1"})
    store.save()

    subprocess.run(
        [
            sys.executable,
            "scripts/dispatch_outbox.py",
            "--store",
            str(path),
            "--worker-id",
            "test-dispatcher",
        ],
        check=True,
    )

    restored = MemoryStore.from_path(path)
    event = next(item for item in restored.outbox if item["job_id"] == job["id"])
    assert event["status"] == "ACKED"
    assert event["lease_owner"] is None
    assert restored.jobs[job["id"]]["dispatch_state"] == "WORKFLOW_ACCEPTED"
    assert restored.jobs[job["id"]]["workflow_id"].startswith("memory-spark:")
