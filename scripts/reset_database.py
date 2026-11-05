#!/usr/bin/env python3
"""Reset disposable Supabase data, Storage objects and Memoir's Langfuse history."""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.langfuse_prompt_client import prompt_client
from scripts.truncate_local_data import StorageClient

# Bound Langfuse's parallel per-trace audit-log transactions.
TRACE_DELETE_BATCH_SIZE = 100


def pages(fetch, **parameters):
    cursor = None
    cursors = set()
    while True:
        response = fetch(cursor=cursor, **parameters)
        yield response.data
        cursor = response.meta.cursor
        if not cursor:
            return
        if cursor in cursors:
            raise ValueError("Langfuse pagination did not advance; reset stopped.")
        cursors.add(cursor)


def langfuse_history(client):
    projects = client.api.projects.get().data
    # The existing local Memoir project was originally named "memior".
    if len(projects) != 1 or projects[0].name not in {"memoir", "memior"}:
        raise ValueError("Langfuse reset requires credentials for the Memoir project only.")
    project = projects[0]
    cutoff = datetime.now(timezone.utc)
    beginning = datetime(1970, 1, 1, tzinfo=timezone.utc)
    trace_ids = set()
    for observations in pages(client.api.observations.get_many, fields="core", limit=1000,
                              from_start_time=beginning, to_start_time=cutoff):
        for observation in observations:
            if observation.project_id != project.id or not observation.trace_id:
                raise ValueError("Langfuse returned an observation outside the reset scope.")
            trace_ids.add(observation.trace_id)
    score_ids = set()
    for scores in pages(client.api.scores_v3.get_many_v3, limit=100, fields="subject",
                        from_timestamp=beginning, to_timestamp=cutoff):
        for score in scores:
            if score.project_id != project.id or not score.id:
                raise ValueError("Langfuse returned a score outside the reset scope.")
            subject = score.subject
            if subject is not None and subject.kind in {"trace", "observation"}:
                trace_id = subject.id if subject.kind == "trace" else subject.trace_id
                if not trace_id:
                    raise ValueError("Langfuse returned a score without its owning trace.")
                trace_ids.add(trace_id)
            else:
                score_ids.add(score.id)
    return project.name, sorted(trace_ids), sorted(score_ids)


def reset_database(*, include_langfuse, credential_file, include_storage=True):
    database_url = os.environ.get("SUPABASE_DB_URL", "").strip()
    if not database_url:
        raise ValueError("Set SUPABASE_DB_URL in ENV_FILE or the environment.")
    if not shutil.which("supabase"):
        raise ValueError("Missing Supabase CLI. Install it before resetting the database.")

    storage = None
    if include_storage:
        supabase_url = os.environ.get("SUPABASE_URL", "").strip()
        storage_key = (os.environ.get("SUPABASE_SECRET_KEY", "").strip()
                       or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip())
        if not supabase_url or not storage_key:
            raise ValueError(
                "Storage reset requires SUPABASE_URL and SUPABASE_SECRET_KEY "
                "(or SUPABASE_SERVICE_ROLE_KEY) in ENV_FILE or the environment."
            )
        storage = StorageClient(supabase_url, storage_key)

    client = None
    try:
        if include_langfuse:
            try:
                client = prompt_client(credential_file)
                project_name, trace_ids, score_ids = langfuse_history(client)
            except Exception as error:
                raise RuntimeError(
                    "Langfuse preflight failed; Supabase was not reset. "
                    "Check PROMPT_CREDENTIAL_FILE and the Memoir project connection."
                ) from error

        if storage is not None:
            try:
                buckets = storage.list_buckets()
            except Exception as error:
                raise RuntimeError(
                    "Storage preflight failed; the database and bucket contents were not reset. "
                    "Check SUPABASE_URL and the server-only Supabase key."
                ) from error
            try:
                # Use the Storage API while the existing object metadata is still intact.
                for bucket in buckets:
                    removed = storage.clear_bucket(bucket)
                    print(f"Storage {bucket}: deleted {removed} object(s).")
            except Exception as error:
                raise RuntimeError(
                    "Storage cleanup failed; bucket contents may be partially deleted. "
                    "The database was not reset and Langfuse history was not deleted."
                ) from error

        try:
            subprocess.run([
                "supabase", "db", "reset", "--db-url", database_url, "--no-seed", "--yes",
            ], check=True)
        except subprocess.CalledProcessError as error:
            storage_status = " Storage bucket contents were already cleared." if storage is not None else ""
            raise RuntimeError(
                "Supabase reset failed; Langfuse history was not deleted." + storage_status
            ) from error

        if include_langfuse:
            try:
                # Trace deletion clears linked scores; session/experiment scores need explicit deletion.
                for score_id in score_ids:
                    client.api.legacy.score_v1.delete(score_id=score_id)
                for start in range(0, len(trace_ids), TRACE_DELETE_BATCH_SIZE):
                    client.api.trace.delete_multiple(trace_ids=trace_ids[start:start + TRACE_DELETE_BATCH_SIZE])
            except Exception as error:
                raise RuntimeError(
                    "Supabase was reset, but Langfuse history deletion failed; cleanup may be partial."
                ) from error
            print(f"Langfuse {project_name}: submitted {len(trace_ids)} traces and {len(score_ids)} standalone "
                  "scores for deletion. Linked observations and scores are deleted asynchronously "
                  "(usually within 15 minutes). "
                  "Prompt versions and evaluation datasets are preserved.")
    finally:
        if client is not None:
            client.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-langfuse", choices=("true", "false"), default="true")
    parser.add_argument("--include-storage", choices=("true", "false"), default="true")
    parser.add_argument("--credential-file", type=Path,
                        default=Path.home() / "llm_provider" / ".env")
    args = parser.parse_args()
    try:
        reset_database(include_langfuse=args.include_langfuse == "true",
                       include_storage=args.include_storage == "true",
                       credential_file=args.credential_file)
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
