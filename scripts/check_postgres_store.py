#!/usr/bin/env python3
"""Exercise the PostgreSQL state, object and transactional-outbox boundary."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.store import PostgresMemoryStore, new_id
from scripts.dispatch_outbox import dispatch_once


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="memory-spark-supabase-check-") as temporary:
        object_root = Path(temporary) / "objects"
        store = PostgresMemoryStore.from_url(args.database_url, object_store_path=object_root)
        account_id = new_id("supabase-check-account")
        project_id = new_id("supabase-check-project")
        chapter_id = new_id("supabase-check-chapter")
        object_key = f"checks/{account_id}/sample.bin"
        payload = b"memory-spark-supabase-boundary"

        with store.transaction():
            store.ensure_account(account_id)
            store.projects[project_id] = {
                "id": project_id,
                "deletion_state": "ACTIVE",
                "events": [],
                "event_cursor": 0,
                "memories": {},
                "preview_jobs": {},
                "chapters": {chapter_id: {"id": chapter_id}},
                "exports": {},
                "outline_versions": [],
            }
            job = store.queue_job(project_id, "BuildChapter", {"chapter_id": chapter_id})
            store.put_object(object_key, payload)

        reloaded = PostgresMemoryStore.from_url(args.database_url, object_store_path=object_root)
        assert account_id in reloaded.accounts
        assert job["id"] in reloaded.jobs
        assert reloaded.read_object(object_key) == payload

        dispatch_once(reloaded, worker_id="supabase-check", limit=10, lease_seconds=30)
        dispatched = PostgresMemoryStore.from_url(args.database_url, object_store_path=object_root)
        assert dispatched.jobs[job["id"]]["dispatch_state"] == "WORKFLOW_ACCEPTED"
        assert dispatched.pending_outbox_count() == 0

        if dispatched.jobs[job["id"]]["status"] == "QUEUED":
            with dispatched.transaction():
                dispatched.complete_job(job["id"], {"checked": True})

        finished = PostgresMemoryStore.from_url(args.database_url, object_store_path=object_root)
        assert finished.jobs[job["id"]]["status"] == "SUCCEEDED"

        with finished.transaction():
            finished.accounts.pop(account_id, None)
            finished.projects.pop(project_id, None)
            finished.jobs.pop(job["id"], None)
            finished.outbox = [event for event in finished.outbox if event.get("job_id") != job["id"]]

    print("Supabase PostgreSQL store: state reload, object bytes, outbox lease/ack and job completion passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
