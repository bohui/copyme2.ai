from __future__ import annotations

from scripts.dispatch_outbox import dispatch_once
from scripts.worker import process_accepted_jobs
from apps.api.store import MemoryStore


def _project(project_id: str) -> dict:
    return {
        "id": project_id,
        "deletion_state": "ACTIVE",
        "events": [],
        "event_cursor": 0,
        "memories": {},
        "preview_jobs": {},
        "chapters": {},
        "exports": {},
        "outline_versions": [],
    }


def test_worker_completes_a_recovered_chapter_job() -> None:
    store = MemoryStore()
    project = _project("project_worker_chapter")
    project["chapters"]["chapter_1"] = {"id": "chapter_1"}
    store.projects[project["id"]] = project
    job = store.queue_job(project["id"], "BuildChapter", {"chapter_id": "chapter_1"})

    dispatch_once(store, worker_id="test-worker", limit=10, lease_seconds=30)
    result = process_accepted_jobs(store)

    assert result == {"processed": 1, "succeeded": 1, "failed": 0}
    assert store.jobs[job["id"]]["status"] == "SUCCEEDED"
    assert store.jobs[job["id"]]["result"] == {"chapter_id": "chapter_1"}


def test_worker_fails_unknown_workflow_without_story_text() -> None:
    store = MemoryStore()
    project = _project("project_worker_unknown")
    store.projects[project["id"]] = project
    job = store.queue_job(project["id"], "UnknownWorkflow", {"private": "must not be copied into error"})

    dispatch_once(store, worker_id="test-worker", limit=10, lease_seconds=30)
    process_accepted_jobs(store)

    assert store.jobs[job["id"]]["status"] == "FAILED"
    assert store.jobs[job["id"]]["error"] == {
        "code": "UNSUPPORTED_WORKFLOW_KIND",
        "message": "UNSUPPORTED_WORKFLOW_KIND",
        "retryable": False,
    }
