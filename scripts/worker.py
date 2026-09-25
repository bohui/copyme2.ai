#!/usr/bin/env python3
"""Run the Memory Spark workflow worker.

When ``MEMORY_SPARK_TEMPORAL_ADDRESS`` is configured, this process runs the
Temporal workflow/activity worker and its local deterministic dispatcher.
The current product journey persists user-owned memory through Supabase RLS;
the legacy project worker remains an explicit local adapter only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.store import MemoryStore, new_id, now_iso
from scripts.dispatch_outbox import dispatch_once


def _preview_for_job(store: MemoryStore, project: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    if project.get("preview"):
        return project["preview"]
    memory_ids = job.get("snapshot", {}).get("memory_ids", sorted(project.get("memories", {})))
    memories = [project.get("memories", {}).get(memory_id) for memory_id in memory_ids]
    memories = [memory for memory in memories if memory]
    preview = {
        "id": new_id("preview"),
        "project_id": project["id"],
        "title": "A beginning to remember",
        "narrative": "\n\n".join(memory.get("text", "") for memory in memories).strip() or "Your saved memories will appear here.",
        "memory_cards": [
            {
                "memory_id": memory["id"],
                "text": memory.get("text", ""),
                "source_version_ids": list(memory.get("source_version_ids", [])),
            }
            for memory in memories
        ],
        "created_at": now_iso(),
        "source_snapshot": {"memory_ids": [memory["id"] for memory in memories]},
    }
    project["preview"] = preview
    snapshot_hash = job.get("snapshot", {}).get("snapshot_hash")
    if snapshot_hash:
        project.setdefault("preview_jobs", {})[snapshot_hash] = job["id"]
    store.emit(project, "preview.ready", preview_id=preview["id"])
    return preview


def _process_job(store: MemoryStore, job: dict[str, Any]) -> bool:
    project = store.projects.get(job.get("project_id"))
    if not project:
        store.fail_job(job["id"], "PROJECT_NOT_FOUND")
        return False
    if project.get("deletion_state") not in {None, "ACTIVE", "REQUESTED"}:
        store.fail_job(job["id"], "PROJECT_DELETED")
        return False

    kind = job.get("kind")
    snapshot = job.get("snapshot", {})
    if kind == "BuildFreePreview":
        preview = _preview_for_job(store, project, job)
        store.complete_job(job["id"], {"preview_id": preview["id"]})
        return True
    if kind == "BuildOutline":
        outline_id = snapshot.get("outline_id")
        exists = any(item.get("id") == outline_id for item in project.get("outline_versions", []))
        if not exists:
            store.fail_job(job["id"], "OUTLINE_NOT_FOUND")
            return False
        store.complete_job(job["id"], {"outline_id": outline_id})
        return True
    if kind == "BuildChapter":
        chapter_id = snapshot.get("chapter_id")
        if chapter_id not in project.get("chapters", {}):
            store.fail_job(job["id"], "CHAPTER_NOT_FOUND")
            return False
        store.complete_job(job["id"], {"chapter_id": chapter_id})
        return True
    if kind == "BuildSourceExport":
        export_id = snapshot.get("export_id")
        if export_id not in project.get("exports", {}):
            store.fail_job(job["id"], "EXPORT_NOT_FOUND")
            return False
        store.complete_job(job["id"], {"export_id": export_id})
        return True

    store.fail_job(job["id"], "UNSUPPORTED_WORKFLOW_KIND")
    return False


def process_accepted_jobs(store: MemoryStore, limit: int = 100) -> dict[str, int]:
    processed = 0
    succeeded = 0
    failed = 0
    with store.transaction():
        for job in sorted(store.jobs.values(), key=lambda item: item.get("created_at", "")):
            if processed >= limit or job.get("status") != "QUEUED" or job.get("dispatch_state") != "WORKFLOW_ACCEPTED":
                continue
            processed += 1
            if _process_job(store, job):
                succeeded += 1
            else:
                failed += 1
    return {"processed": processed, "succeeded": succeeded, "failed": failed}


def worker_once(store: MemoryStore, worker_id: str, limit: int, lease_seconds: int) -> dict[str, int]:
    dispatched = dispatch_once(store, worker_id=worker_id, limit=limit, lease_seconds=lease_seconds)
    processed = process_accepted_jobs(store, limit=limit)
    return {**dispatched, **processed}


def _store_from_args(args: argparse.Namespace) -> MemoryStore:
    if args.store:
        return MemoryStore.from_path(args.store, object_store_path=args.objects)
    return MemoryStore(object_store_path=args.objects)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--objects", type=Path, default=Path(os.environ.get("MEMORY_SPARK_OBJECT_STORE_PATH", "var/memory-spark/objects")))
    parser.add_argument("--worker-id", default=os.environ.get("MEMORY_SPARK_WORKER_ID", "memory-spark-worker"))
    parser.add_argument("--temporal-address", default=os.environ.get("MEMORY_SPARK_TEMPORAL_ADDRESS"))
    parser.add_argument("--temporal-namespace", default=os.environ.get("MEMORY_SPARK_TEMPORAL_NAMESPACE", "default"))
    parser.add_argument("--temporal-task-queue", default=os.environ.get("MEMORY_SPARK_TEMPORAL_TASK_QUEUE", "memory-spark"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--lease-seconds", type=int, default=60)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--readiness", action="store_true")
    args = parser.parse_args()
    if args.limit < 1 or args.lease_seconds < 1 or args.interval <= 0:
        raise SystemExit("--limit and --lease-seconds must be positive; --interval must be greater than zero")
    store = _store_from_args(args)
    if args.readiness:
        store.pending_outbox_count()
        print("Memory Spark worker: ready")
        return 0
    if args.temporal_address:
        from scripts.temporal_runtime import run_temporal_worker

        asyncio.run(
            run_temporal_worker(
                address=args.temporal_address,
                namespace=args.temporal_namespace,
                task_queue=args.temporal_task_queue,
                worker_id=args.worker_id,
                store=store,
                interval=args.interval,
                limit=args.limit,
                lease_seconds=args.lease_seconds,
            )
        )
        return 0
    if args.once:
        print(f"Memory Spark worker: {worker_once(store, args.worker_id, args.limit, args.lease_seconds)}")
        return 0
    while True:
        worker_once(store, args.worker_id, args.limit, args.lease_seconds)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
