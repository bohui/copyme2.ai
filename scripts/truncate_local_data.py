#!/usr/bin/env python3
"""Reset the application-owned local development data.

Supabase Storage objects are removed through the Storage API rather than by
deleting rows from ``storage.objects``. The latter leaves the physical blobs
orphaned in the backing object store.
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
    "public.user_profile",
    "public.user_memory",
    "public.user_agent_session",
    "public.user_agent_turn_lease",
    "public.user_recall_usage",
    "public.story_entitlements",
    "public.user_family_context",
    "public.user_place_journey",
    # These tables are optional and only exist on installations that applied
    # the retired JSONB-state migration.
    "public.memory_spark_outbox",
    "public.memory_spark_state",
)
STORAGE_PAGE_SIZE = 1000
STORAGE_REMOVE_BATCH_SIZE = 1000


class StorageClient:
    def __init__(self, url: str, key: str, bucket: str) -> None:
        self.base_url = url.rstrip("/") + "/storage/v1"
        self.bucket = bucket
        self.headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "apikey": key,
        }

    def _request(self, method: str, path: str, payload: object) -> object:
        request = Request(
            f"{self.base_url}/{path}",
            data=json.dumps(payload).encode("utf-8"),
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

    def list_objects(self) -> list[str]:
        objects: list[str] = []
        visited_prefixes: set[str] = set()
        bucket = quote(self.bucket, safe="")

        def walk(prefix: str) -> None:
            if prefix in visited_prefixes:
                return
            visited_prefixes.add(prefix)
            offset = 0
            while True:
                entries = self._post(
                    f"object/list/{bucket}",
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

    def remove_objects(self, objects: list[str]) -> None:
        bucket = quote(self.bucket, safe="")
        for start in range(0, len(objects), STORAGE_REMOVE_BATCH_SIZE):
            self._delete(
                f"object/{bucket}",
                {"prefixes": objects[start : start + STORAGE_REMOVE_BATCH_SIZE]},
            )


def truncate_database(database_url: str) -> None:
    table_array = ", ".join(repr(table) for table in APP_TABLES)
    sql = f"""
begin;
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
    execute 'truncate table ' || truncate_list || ' restart identity';
  end if;
end
$$;
commit;
"""
    try:
        subprocess.run(
            ["psql", "-X", database_url, "-v", "ON_ERROR_STOP=1", "-c", sql],
            check=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError("Missing psql. Install the PostgreSQL client first.") from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"psql failed with exit status {error.returncode}") from error


def clear_local_object_store(path_value: str, repo_root: Path) -> int:
    path = Path(path_value)
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve()
    allowed_root = (repo_root / "var" / "memory-spark").resolve()
    try:
        path.relative_to(allowed_root)
    except ValueError as error:
        raise RuntimeError(
            f"Refusing to clear LOCAL_OBJECT_STORE_PATH outside {allowed_root}: {path}"
        ) from error
    if path == allowed_root or path.name != "objects":
        raise RuntimeError(f"Refusing to clear unexpected local object path: {path}")

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
        raise RuntimeError(f"Local object storage is not empty after deletion: {path}")
    return removed


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} before running make db-truncate.")
    return value


def reset_data() -> None:
    database_url = required_env("SUPABASE_DB_URL")
    supabase_url = required_env("SUPABASE_URL")
    storage_key = os.environ.get("SUPABASE_SECRET_KEY", "").strip() or os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY", ""
    ).strip()
    if not storage_key:
        raise RuntimeError("Set SUPABASE_SECRET_KEY before running make db-truncate.")
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "memory-spark").strip()
    if not bucket:
        raise RuntimeError("SUPABASE_STORAGE_BUCKET must not be empty.")

    storage = StorageClient(supabase_url, storage_key, bucket)
    objects = storage.list_objects()
    print(f"Removing {len(objects)} object(s) from Supabase bucket {bucket!r}...")
    storage.remove_objects(objects)
    remaining_objects = storage.list_objects()
    if remaining_objects:
        raise RuntimeError(
            f"Supabase Storage still contains {len(remaining_objects)} object(s) after deletion"
        )

    repo_root = Path(__file__).resolve().parents[1]
    local_path = os.environ.get("LOCAL_OBJECT_STORE_PATH", "var/memory-spark/objects")
    removed_local = clear_local_object_store(local_path, repo_root)
    print(f"Removed {removed_local} item(s) from local object storage.")

    print("Truncating application tables...")
    truncate_database(database_url)
    print("Local application data reset complete.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm that application data and storage should be permanently deleted",
    )
    args = parser.parse_args()
    if not args.yes:
        parser.error("pass --yes when invoking this destructive command")
    try:
        reset_data()
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
