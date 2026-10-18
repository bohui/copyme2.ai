#!/usr/bin/env python3
"""Reset user/application data while preserving shared public photo research.

Supabase Storage objects are removed through the Storage API rather than by
deleting rows from ``storage.objects``. The latter leaves the physical blobs
orphaned in the backing object store. Authentication users are deleted from
``auth.users`` after the application tables are cleared; Supabase's cascading
foreign keys remove their identities, sessions, and other account records.
The keyword-to-photo cache is independent public research, not user data.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


APP_TABLES = (
    "public.guest_conversation_transfer",
    "public.guest_merge_asset_access",
    "public.story_entitlement",
    "public.user_agent_session",
    "public.user_agent_turn_lease",
    "public.user_background_skill_work",
    "public.user_completed_round",
    "public.user_conversation_attachment",
    "public.user_family_context",
    "public.user_formal_memoir_chapter",
    "public.user_formal_memoir_edition",
    "public.user_formal_memoir_head",
    "public.user_formal_memoir_plan",
    "public.user_formal_memoir_run",
    "public.user_historical_news_clue",
    "public.user_historical_news_job",
    "public.user_historical_news_state",
    "public.user_interview_photo",
    "public.user_interview_photo_link",
    "public.user_interview_photo_transfer",
    "public.user_interview_plan",
    "public.user_interview_turn",
    "public.user_lifetime_artifact_chunk",
    "public.user_lifetime_artifact_file",
    "public.user_lifetime_artifact_head",
    "public.user_lifetime_checkpoint",
    "public.user_lifetime_chosen_name",
    "public.user_lifetime_collection",
    "public.user_lifetime_collection_job",
    "public.user_lifetime_collection_job_cursor",
    "public.user_lifetime_collection_job_edge",
    "public.user_lifetime_collection_job_node",
    "public.user_lifetime_collection_job_page",
    "public.user_lifetime_collection_job_source",
    "public.user_lifetime_collection_selection",
    "public.user_lifetime_compaction",
    "public.user_lifetime_continuity",
    "public.user_lifetime_conversation",
    "public.user_lifetime_covered_evidence",
    "public.user_lifetime_draft_cursor",
    "public.user_lifetime_draft_snapshot",
    "public.user_lifetime_interview_strategy",
    "public.user_lifetime_lane_output",
    "public.user_lifetime_lane_page_receipt",
    "public.user_lifetime_lane_snapshot",
    "public.user_lifetime_memoir_cursor",
    "public.user_lifetime_memoir_section",
    "public.user_lifetime_memory_obligation",
    "public.user_lifetime_milestone_cursor",
    "public.user_lifetime_optional_artifact",
    "public.user_lifetime_pending_policy",
    "public.user_lifetime_place_journey",
    "public.user_lifetime_policy_inventory_pending",
    "public.user_lifetime_prepared_question",
    "public.user_lifetime_profile_authority",
    "public.user_lifetime_profile_coverage",
    "public.user_lifetime_profile_dependency",
    "public.user_lifetime_profile_progress",
    "public.user_lifetime_profile_receipt",
    "public.user_lifetime_read_cursor",
    "public.user_lifetime_reply",
    "public.user_lifetime_source_cursor",
    "public.user_lifetime_source_extraction",
    "public.user_lifetime_source_inventory",
    "public.user_lifetime_source_policy_receipt",
    "public.user_lifetime_source_position",
    "public.user_lifetime_stage_volume",
    "public.user_lifetime_strategy_frontier",
    "public.user_lifetime_strategy_outcome",
    "public.user_lifetime_strategy_page_receipt",
    "public.user_lifetime_summary_receipt",
    "public.user_lifetime_two_lane_source",
    "public.user_memoir_checkpoint",
    "public.user_memoir_edition",
    "public.user_memoir_lane",
    "public.user_memoir_milestone",
    "public.user_memoir_project",
    "public.user_memory",
    "public.user_memory_attribution_receipt",
    "public.user_memory_attribution_window",
    "public.user_memory_delivered_context",
    "public.user_memory_event",
    "public.user_memory_event_change",
    "public.user_memory_event_place",
    "public.user_memory_event_revision",
    "public.user_memory_event_source",
    "public.user_memory_event_source_exclusion",
    "public.user_memory_reply_context",
    "public.user_narrator_source",
    "public.user_narrator_source_version",
    "public.user_original_recording",
    "public.user_original_recording_cancel",
    "public.user_original_recording_transfer",
    "public.user_original_recording_upload",
    "public.user_place_journey",
    "public.user_private_draft_outbox",
    "public.user_profile",
    "public.user_recall_usage",
    "public.user_shared_memoir_transfer",
    "public.user_source_recording",
    "public.user_story_game_consent",
    "public.user_ui_locale_preference",
    "public.user_workspace_section_rework",
)
PRESERVED_TABLES = (
    "public.lifetime_profile_cadence",
    "public.lifetime_two_lane_rollout",
    "public.original_recording_rollout",
    "public.place_photo_search",
)
STORAGE_PAGE_SIZE = 1000
STORAGE_REMOVE_BATCH_SIZE = 1000

LOCAL_CODEX_DATA_PATHS = (
    ("LOCAL_CODEX_HOME_PATH", "var/codex-users", "codex-users"),
    ("LOCAL_CODEX_WORKER_HOME_PATH", "var/codex-worker-users", "codex-worker-users"),
    ("LOCAL_LEGACY_CODEX_HOME_PATH", "var/memory-spark/codex-users", "codex-users"),
)


class StorageClient:
    def __init__(self, url: str, key: str, bucket: str | None = None) -> None:
        self.base_url = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "apikey": key,
        }

    def _request(self, method: str, path: str, payload: object | None = None) -> object:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/{path}",
            data=data,
            headers=self.headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Supabase Storage request failed ({error.code}) for {method} {path}: {detail}"
            ) from error
        except URLError as error:
            raise RuntimeError(
                f"Supabase Storage request failed for {method} {path}: {error.reason}"
            ) from error
        return json.loads(body) if body else None

    def _post(self, path: str, payload: object) -> object:
        return self._request("POST", path, payload)

    def _delete(self, path: str, payload: object) -> object:
        return self._request("DELETE", path, payload)

    def list_buckets(self) -> list[str]:
        entries = self._request("GET", "bucket")
        if not isinstance(entries, list):
            raise RuntimeError("Supabase Storage bucket response was not an array")
        buckets = {
            str(entry["name"])
            for entry in entries
            if isinstance(entry, dict) and entry.get("name")
        }
        return sorted(buckets)

    def _bucket_name(self, bucket: str | None) -> str:
        name = bucket or self.bucket
        if not name:
            raise RuntimeError("A Supabase Storage bucket is required")
        return name

    def list_objects(self, bucket: str | None = None) -> list[str]:
        objects: list[str] = []
        visited_prefixes: set[str] = set()
        bucket_name = self._bucket_name(bucket)
        encoded_bucket = quote(bucket_name, safe="")

        def walk(prefix: str) -> None:
            if prefix in visited_prefixes:
                return
            visited_prefixes.add(prefix)
            offset = 0
            while True:
                entries = self._post(
                    f"object/list/{encoded_bucket}",
                    {
                        "prefix": prefix,
                        "limit": STORAGE_PAGE_SIZE,
                        "offset": offset,
                        "sortBy": {"column": "name", "order": "asc"},
                    },
                )
                if not isinstance(entries, list):
                    raise RuntimeError("Supabase Storage list response was not an array")
                for entry in entries:
                    if not isinstance(entry, dict) or not entry.get("name"):
                        continue
                    name = str(entry["name"])
                    if entry.get("id") is None:
                        walk(f"{prefix}{name.rstrip('/')}/")
                    else:
                        objects.append(f"{prefix}{name}")
                if len(entries) < STORAGE_PAGE_SIZE:
                    return
                offset += len(entries)

        walk("")
        return sorted(set(objects))

    def remove_objects(self, objects: list[str], bucket: str | None = None) -> None:
        encoded_bucket = quote(self._bucket_name(bucket), safe="")
        for start in range(0, len(objects), STORAGE_REMOVE_BATCH_SIZE):
            self._delete(
                f"object/{encoded_bucket}",
                {"prefixes": objects[start : start + STORAGE_REMOVE_BATCH_SIZE]},
            )

    def clear_bucket(self, bucket: str) -> int:
        objects = self.list_objects(bucket)
        self.remove_objects(objects, bucket)
        remaining = self.list_objects(bucket)
        if remaining:
            raise RuntimeError(
                f"Supabase Storage bucket {bucket!r} still contains "
                f"{len(remaining)} object(s) after deletion"
            )
        return len(objects)


def reset_scope_guard() -> str:
    roots = ", ".join(repr(table) for table in APP_TABLES if table not in PRESERVED_TABLES)
    preserved = ", ".join(repr(table) for table in PRESERVED_TABLES)
    return f"""
do $scope$
declare protected_table regclass;
begin
  for protected_table in select to_regclass(name)
    from unnest(array[{preserved}]::text[]) as names(name)
    where to_regclass(name) is not null
  loop
    -- Fence concurrent schema changes while checking/clearing user tables.
    execute format('lock table %s in share mode', protected_table);
  end loop;
  if exists (
    with recursive edges(parent, child) as (
      select confrelid, conrelid from pg_catalog.pg_constraint where contype = 'f'
      union select inhparent, inhrelid from pg_catalog.pg_inherits
    ), affected(oid) as (
      select to_regclass(name)::oid
        from unnest(array[{roots}, 'auth.users']::text[]) as names(name)
        where to_regclass(name) is not null
      union select edges.child from edges join affected on edges.parent = affected.oid
    )
    select 1 from affected
      where oid in (select to_regclass(name)::oid
        from unnest(array[{preserved}]::text[]) as names(name))
  ) then
    raise exception 'Refusing reset: shared photo cache depends on reset tables; remove that dependency before resetting user data';
  end if;
end
$scope$;
"""


def run_database_sql(database_url: str, sql: str) -> None:
    try:
        subprocess.run(
            ["psql", "-X", database_url, "-v", "ON_ERROR_STOP=1", "-c", sql],
            check=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError("Missing psql. Install the PostgreSQL client first.") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"psql failed with exit status {error.returncode}") from error


def check_reset_scope(database_url: str) -> None:
    run_database_sql(database_url, f"begin;\n{reset_scope_guard()}\ncommit;")


def truncate_database(database_url: str) -> None:
    table_array = ", ".join(repr(table) for table in APP_TABLES if table not in PRESERVED_TABLES)
    sql = f"""
begin;
{reset_scope_guard()}
do $$
declare
  truncate_list text;
begin
  select string_agg(format('%I.%I', namespace.nspname, relation.relname), ', ' order by requested.ordinality)
    into truncate_list
    from unnest(array[{table_array}]::text[]) with ordinality as requested(table_name, ordinality)
    join pg_catalog.pg_class as relation on relation.oid = to_regclass(requested.table_name)
    join pg_catalog.pg_namespace as namespace on namespace.oid = relation.relnamespace
   where relation.relkind in ('r', 'p');

  if truncate_list is not null then
    execute 'truncate table ' || truncate_list || ' restart identity cascade';
  end if;
end
$$;
delete from auth.users;
commit;
"""
    run_database_sql(database_url, sql)


def clear_local_data_path(
    path_value: str,
    repo_root: Path,
    *,
    allowed_root: Path,
    expected_name: str,
) -> int:
    path = Path(path_value)
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve()
    allowed_root = (repo_root / allowed_root).resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError as error:
        raise RuntimeError(
            f"Refusing to clear local data outside {allowed_root}: {path}"
        ) from error
    if path == allowed_root or path.name != expected_name:
        raise RuntimeError(f"Refusing to clear unexpected local data path: {path}")

    path.mkdir(parents=True, exist_ok=True)
    removed = 0
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    if any(path.iterdir()):
        raise RuntimeError(f"Local data path is not empty after deletion: {path}")
    return removed


def clear_local_object_store(path_value: str, repo_root: Path) -> int:
    return clear_local_data_path(
        path_value,
        repo_root,
        allowed_root=Path("var/memory-spark"),
        expected_name="objects",
    )


def clear_local_codex_data(repo_root: Path) -> int:
    removed = 0
    for env_name, default_path, expected_name in LOCAL_CODEX_DATA_PATHS:
        path_value = os.environ.get(env_name, default_path)
        count = clear_local_data_path(
            path_value,
            repo_root,
            allowed_root=Path("var"),
            expected_name=expected_name,
        )
        removed += count
        print(f"Removed {count} item(s) from local Codex user data {path_value!r}.")
    return removed


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} before running the destructive data reset.")
    return value


def reset_data() -> None:
    database_url = required_env("SUPABASE_DB_URL")
    supabase_url = required_env("SUPABASE_URL")
    storage_key = os.environ.get("SUPABASE_SECRET_KEY", "").strip() or os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY", ""
    ).strip()
    if not storage_key:
        raise RuntimeError(
            "Set SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY before running make db-truncate."
        )
    # Check before any Storage/filesystem deletion, then fence/check again in
    # the SQL transaction. A future FK must not silently pull cache into CASCADE.
    check_reset_scope(database_url)
    storage = StorageClient(supabase_url, storage_key)
    buckets = storage.list_buckets()
    print(f"Clearing {len(buckets)} Supabase Storage bucket(s)...")
    for bucket in buckets:
        removed = storage.clear_bucket(bucket)
        print(f"Removed {removed} object(s) from Supabase bucket {bucket!r}.")

    repo_root = Path(__file__).resolve().parents[1]
    local_path = os.environ.get("LOCAL_OBJECT_STORE_PATH", "var/memory-spark/objects")
    removed_local = clear_local_object_store(local_path, repo_root)
    print(f"Removed {removed_local} item(s) from local object storage.")
    clear_local_codex_data(repo_root)

    print("Truncating application tables and deleting all Supabase Auth users...")
    truncate_database(database_url)
    print("Application, storage, and user data reset complete; shared photo search cache preserved.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-scope", action="store_true",
        help="check that the shared photo cache cannot be affected; delete no data",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm that application, storage, authentication, and local user data should be permanently deleted",
    )
    args = parser.parse_args()
    if not args.yes and not args.check_scope:
        parser.error("pass --yes when invoking this destructive command")
    try:
        if args.check_scope:
            check_reset_scope(required_env("SUPABASE_DB_URL"))
            print("Reset scope checked: shared photo search cache is protected.")
        else:
            reset_data()
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
