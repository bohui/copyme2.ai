from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - the local cell runs on POSIX hosts
    fcntl = None

try:
    import psycopg
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - the JSON adapter does not need psycopg
    psycopg = None
    Jsonb = None


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass
class MemoryStore:
    projects: dict[str, dict[str, Any]] = field(default_factory=dict)
    accounts: dict[str, dict[str, Any]] = field(default_factory=dict)
    auth_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    auth_challenges: dict[str, dict[str, Any]] = field(default_factory=dict)
    invitations: dict[str, dict[str, Any]] = field(default_factory=dict)
    uploads: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_versions: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    people: dict[str, dict[str, Any]] = field(default_factory=dict)
    context_assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    plans: dict[str, dict[str, Any]] = field(default_factory=dict)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    payment_events: dict[str, dict[str, Any]] = field(default_factory=dict)
    chapters: dict[str, dict[str, Any]] = field(default_factory=dict)
    editions: dict[str, dict[str, Any]] = field(default_factory=dict)
    suppliers: dict[str, dict[str, Any]] = field(default_factory=dict)
    print_quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    print_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    outbox: list[dict[str, Any]] = field(default_factory=list)
    idempotency: dict[str, Any] = field(default_factory=dict)
    deleted_projects: dict[str, dict[str, Any]] = field(default_factory=dict)
    provider_policies: dict[str, dict[str, Any]] = field(default_factory=dict)
    support_grants: dict[str, dict[str, Any]] = field(default_factory=dict)
    persistence_path: str | None = field(default=None, repr=False, compare=False)
    object_store_path: str | None = field(default=None, repr=False, compare=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    _PERSISTED_FIELDS = (
        "projects",
        "accounts",
        "auth_sessions",
        "auth_challenges",
        "invitations",
        "uploads",
        "source_versions",
        "claims",
        "people",
        "context_assets",
        "plans",
        "orders",
        "payment_events",
        "chapters",
        "editions",
        "suppliers",
        "print_quotes",
        "print_orders",
        "jobs",
        "audit_events",
        "outbox",
        "idempotency",
        "deleted_projects",
        "provider_policies",
        "support_grants",
    )

    def __post_init__(self) -> None:
        if not self.plans:
            self.plans["complete_digital_memoir_v1"] = {
                "plan_key": "complete_digital_memoir_v1",
                "version": 1,
                "status": "live",
                "name": "Complete digital memoir",
                "amount_minor": 29900,
                "currency": "AUD",
                "additional_primary_sessions": 60,
                "collaborators": 5,
                "translation_source_characters": 60000,
                "creation_days": 365,
                "hosting_days": 730,
                "auto_renew": False,
                "terms_version": "terms-2026-09-21",
                "processing_region": "au",
            }
        if not self.context_assets:
            seed = [
                {
                    "asset_id": "ctx_school_lane",
                    "title": "School life in a regional town",
                    "creator": "Memory Spark reviewed catalogue",
                    "source_url": "https://example.invalid/context/school-lane",
                    "scene_date_range": {"start": 1955, "end": 1975, "precision": "range"},
                    "location": "regional town, broader province",
                    "match_scope": "broader region and period",
                    "topics": ["childhood_home", "school"],
                    "kind": "image",
                    "label": "Historical reference—not your family photograph",
                    "rights": {
                        "can_embed": True,
                        "can_cache": True,
                        "can_transform": True,
                        "can_display_in_paid_app": True,
                        "can_include_in_download": False,
                        "can_print": False,
                        "allowed_regions": ["au", "cn"],
                    },
                    "reviewed": True,
                },
                {
                    "asset_id": "ctx_factory",
                    "title": "Factory street reference",
                    "creator": "Memory Spark reviewed catalogue",
                    "source_url": "https://example.invalid/context/factory",
                    "scene_date_range": {"start": 1960, "end": 1980, "precision": "range"},
                    "location": "broader industrial district",
                    "match_scope": "regional analogue",
                    "topics": ["work", "childhood_home"],
                    "kind": "image",
                    "label": "Historical reference—not your family photograph",
                    "rights": {
                        "can_embed": True,
                        "can_cache": True,
                        "can_transform": True,
                        "can_display_in_paid_app": True,
                        "can_include_in_download": False,
                        "can_print": False,
                        "allowed_regions": ["au", "cn"],
                    },
                    "reviewed": True,
                },
                {
                    "asset_id": "ctx_food",
                    "title": "Market food reference",
                    "creator": "Memory Spark reviewed catalogue",
                    "source_url": "https://example.invalid/context/market-food",
                    "scene_date_range": {"start": 1950, "end": 1985, "precision": "range"},
                    "location": "regional market",
                    "match_scope": "broader region and period",
                    "topics": ["food", "celebration"],
                    "kind": "image",
                    "label": "Historical reference—not your family photograph",
                    "rights": {
                        "can_embed": True,
                        "can_cache": True,
                        "can_transform": True,
                        "can_display_in_paid_app": True,
                        "can_include_in_download": False,
                        "can_print": False,
                        "allowed_regions": ["au", "cn"],
                    },
                    "reviewed": True,
                },
                {
                    "asset_id": "ctx_work_video",
                    "title": "Short oral-history video reference",
                    "creator": "Memory Spark reviewed catalogue",
                    "source_url": "https://example.invalid/context/work-video",
                    "scene_date_range": {"start": 1960, "end": 1980, "precision": "range"},
                    "location": "broader industrial district",
                    "match_scope": "broader region and period",
                    "topics": ["work", "migration"],
                    "kind": "video",
                    "label": "Historical reference—not your family video",
                    "rights": {
                        "can_embed": True,
                        "can_cache": False,
                        "can_transform": False,
                        "can_display_in_paid_app": True,
                        "can_include_in_download": False,
                        "can_print": False,
                        "allowed_regions": ["au"],
                    },
                    "reviewed": True,
                },
                {
                    "asset_id": "ctx_turning_point",
                    "title": "Travel and migration reference",
                    "creator": "Memory Spark reviewed catalogue",
                    "source_url": "https://example.invalid/context/migration",
                    "scene_date_range": {"start": 1950, "end": 1990, "precision": "range"},
                    "location": "coastal route",
                    "match_scope": "broad historical context",
                    "topics": ["migration", "turning_point"],
                    "kind": "image",
                    "label": "Historical reference—not your family photograph",
                    "rights": {
                        "can_embed": True,
                        "can_cache": True,
                        "can_transform": True,
                        "can_display_in_paid_app": True,
                        "can_include_in_download": False,
                        "can_print": False,
                        "allowed_regions": ["au", "cn"],
                    },
                    "reviewed": True,
                },
            ]
            self.context_assets = {asset["asset_id"]: asset for asset in seed}
        if not self.suppliers:
            self.suppliers["supplier_demo"] = {
                "id": "supplier_demo",
                "name": "Approved small-run print partner",
                "qualified": True,
                "enabled": True,
                "supported_quantity": {"min": 1, "max": 99},
                "supported_formats": ["A5", "PDF/X-ready"],
                "data_handling_terms": "Final approved files and delivery details only",
                "delivery_countries": ["AU", "CN"],
                "profile_version": "supplier-supplier_demo-v1",
            }
        if not self.provider_policies:
            self.provider_policies = {
                "demo_asr": {
                    "provider": "demo_asr",
                    "processing_region": "au",
                    "approved": True,
                    "enabled": True,
                    "data_classes": ["audio"],
                },
                "demo_writer": {
                    "provider": "demo_writer",
                    "processing_region": "au",
                    "approved": True,
                    "enabled": True,
                    "data_classes": ["transcript"],
                },
                "demo_context": {
                    "provider": "demo_context",
                    "processing_region": "au",
                    "approved": True,
                    "enabled": True,
                    "data_classes": ["coarse_context_query"],
                },
            }

    def ensure_account(self, account_id: str) -> dict[str, Any]:
        with self.lock:
            return self.accounts.setdefault(
                account_id,
                {
                    "id": account_id,
                    "verified": True,
                    "region": "au",
                    "created_at": now_iso(),
                    "roles": ["user"],
                    "trial_grant_issued": False,
                },
            )

    @classmethod
    def from_path(cls, path: str | Path, object_store_path: str | Path | None = None) -> "MemoryStore":
        persistence_path = Path(path)
        store = cls(persistence_path=str(persistence_path), object_store_path=str(object_store_path) if object_store_path else None)
        store.reload()
        return store

    def _apply_snapshot(self, envelope: dict[str, Any]) -> None:
        payload = envelope.get("store", envelope)
        if not isinstance(payload, dict):
            raise ValueError("Memory Spark store snapshot must contain an object")
        for field_name in self._PERSISTED_FIELDS:
            if field_name in payload:
                setattr(self, field_name, payload[field_name])

    def reload(self) -> None:
        """Refresh persisted state while preserving the store's runtime paths."""
        if not self.persistence_path:
            return
        persistence_path = Path(self.persistence_path)
        if not persistence_path.exists():
            return
        with self.lock:
            with persistence_path.open("r", encoding="utf-8") as handle:
                self._apply_snapshot(json.load(handle))

    def put_object(self, object_key: str, content: bytes) -> str:
        if not object_key or object_key.startswith("/") or ".." in Path(object_key).parts:
            raise ValueError("invalid object key")
        if not self.object_store_path:
            return object_key
        target = Path(self.object_store_path) / object_key
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return object_key

    def read_object(self, object_key: str) -> bytes:
        if not self.object_store_path:
            raise FileNotFoundError(object_key)
        if not object_key or object_key.startswith("/") or ".." in Path(object_key).parts:
            raise ValueError("invalid object key")
        return (Path(self.object_store_path) / object_key).read_bytes()

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): MemoryStore._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [MemoryStore._json_safe(item) for item in value]
        if isinstance(value, set):
            return sorted(MemoryStore._json_safe(item) for item in value)
        if isinstance(value, Path):
            return str(value)
        return value

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "schema_version": 1,
                "saved_at": now_iso(),
                "store": self._json_safe({field_name: getattr(self, field_name) for field_name in self._PERSISTED_FIELDS}),
            }

    @contextmanager
    def _file_lock(self):
        """Serialize API and worker snapshot transactions across processes."""
        if not self.persistence_path or fcntl is None:
            yield
            return
        lock_path = Path(f"{self.persistence_path}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def transaction(self):
        """Run a request-sized read/modify/write transaction.

        The prototype's JSON adapter is intentionally small, but API and worker
        processes still need a single writer. Reloading under an OS lock avoids
        a worker update being overwritten by a stale API process snapshot.
        """
        with self.lock:
            with self._file_lock():
                self.reload()
                try:
                    yield self
                finally:
                    self._save_unlocked()

    def _save_unlocked(self) -> None:
        if not self.persistence_path:
            return
        target = Path(self.persistence_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.snapshot(), handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def save(self) -> None:
        if not self.persistence_path:
            return
        with self.lock:
            with self._file_lock():
                self._save_unlocked()

    def audit(self, action: str, actor_id: str, project_id: str | None = None, **metadata: Any) -> None:
        self.audit_events.append(
            {
                "id": new_id("audit"),
                "action": action,
                "actor_id": actor_id,
                "project_id": project_id,
                "metadata": metadata,
                "created_at": now_iso(),
            }
        )

    def emit(self, project: dict[str, Any], event_type: str, **data: Any) -> dict[str, Any]:
        project["event_cursor"] += 1
        event = {
            "cursor": project["event_cursor"],
            "event": event_type,
            "data": data,
            "created_at": now_iso(),
        }
        project["events"].append(event)
        return event

    def queue_job(self, project_id: str, kind: str, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        job_id = new_id("job")
        created_at = now_iso()
        job = {
            "id": job_id,
            "project_id": project_id,
            "kind": kind,
            "status": "QUEUED",
            "snapshot": snapshot or {},
            "created_at": created_at,
            "updated_at": created_at,
            "status_url": f"/v1/jobs/{job_id}",
            "can_leave_page": True,
        }
        self.jobs[job_id] = job
        self._enqueue_outbox(job)
        return job

    def _enqueue_outbox(self, job: dict[str, Any], retry: bool = False) -> dict[str, Any]:
        event_id = new_id("outbox")
        event = {
            "id": event_id,
            "event_id": event_id,
            "type": f"job.{job['kind']}",
            "schema_version": 1,
            "region": job.get("region", "au"),
            "project_id": job["project_id"],
            "aggregate_id": job["id"],
            "aggregate_version": sum(1 for item in self.outbox if item.get("job_id") == job["id"]) + 1,
            "operation_id": job["id"],
            "occurred_at": now_iso(),
            "payload": {"job_id": job["id"], "kind": job["kind"], "snapshot": self._json_safe(job.get("snapshot", {}))},
            "job_id": job["id"],
            "kind": job["kind"],
            "retry": retry,
            "status": "PENDING",
            "attempts": 0,
            "lease_owner": None,
            "lease_until": None,
            "acknowledged_at": None,
        }
        self.outbox.append(event)
        return event

    def complete_job(self, job_id: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
        """Finish a local job and acknowledge its durable dispatch event."""
        job = self.jobs[job_id]
        job["status"] = "SUCCEEDED"
        if result is not None:
            job["result"] = result
        job["updated_at"] = now_iso()
        for event in reversed(self.outbox):
            if event.get("job_id") != job_id or event.get("status") == "ACKED":
                continue
            event["status"] = "ACKED"
            event["acknowledged_at"] = now_iso()
            event["lease_owner"] = None
            event["lease_until"] = None
            break
        return job

    def fail_job(self, job_id: str, code: str, message: str | None = None) -> dict[str, Any]:
        """Record a safe worker failure without placing story text in errors."""
        job = self.jobs[job_id]
        job["status"] = "FAILED"
        job["error"] = {"code": code, "message": message or code, "retryable": False}
        job["updated_at"] = now_iso()
        for event in reversed(self.outbox):
            if event.get("job_id") != job_id or event.get("status") == "ACKED":
                continue
            event["status"] = "ACKED"
            event["acknowledged_at"] = now_iso()
            event["lease_owner"] = None
            event["lease_until"] = None
            break
        return job

    def requeue_job(self, job: dict[str, Any]) -> dict[str, Any]:
        job["status"] = "QUEUED"
        job["updated_at"] = now_iso()
        self._enqueue_outbox(job, retry=True)
        return job

    def pending_outbox_count(self) -> int:
        return sum(1 for event in self.outbox if event.get("status", "PENDING") not in {"ACKED", "FAILED"})


class PostgresMemoryStore(MemoryStore):
    """Supabase-Postgres-backed store for the runtime deployment.

    The domain service still exposes the same in-process collections so the
    prototype routes remain small and directly testable. Supabase PostgreSQL
    is the source of truth for those collections, while outbox rows are also
    indexed in a separate table so dispatchers can lease work without relying
    on a process-local queue. A single locked JSONB state row keeps the current
    domain adapter transactional while the schema can later be split into
    normalized tables without changing the API service surface.
    """

    request_transaction_enabled = True
    _STATE_TABLE = "public.memory_spark_state"
    _OUTBOX_TABLE = "public.memory_spark_outbox"

    def __init__(
        self,
        database_url: str,
        object_store_path: str | Path | None = None,
        connect_timeout: int = 10,
        startup_retry_seconds: float = 30.0,
    ) -> None:
        if psycopg is None or Jsonb is None:
            raise RuntimeError("psycopg is required when SUPABASE_DB_URL is configured")
        self.database_url = database_url
        self.connect_timeout = connect_timeout
        self.startup_retry_seconds = startup_retry_seconds
        self._database_revision = 0
        self._request_connection: Any | None = None
        super().__init__(object_store_path=str(object_store_path) if object_store_path else None)
        self._ensure_schema()
        self._initialize_if_empty()
        self.reload()

    @classmethod
    def from_url(
        cls,
        database_url: str,
        object_store_path: str | Path | None = None,
    ) -> "PostgresMemoryStore":
        return cls(database_url, object_store_path=object_store_path)

    def _connect(self) -> Any:
        deadline = time.monotonic() + self.startup_retry_seconds
        while True:
            try:
                return psycopg.connect(self.database_url, connect_timeout=self.connect_timeout)
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)

    @classmethod
    def _schema_sql(cls) -> str:
        return f"""
        CREATE TABLE IF NOT EXISTS {cls._STATE_TABLE} (
            id smallint PRIMARY KEY CHECK (id = 1),
            schema_version integer NOT NULL,
            revision bigint NOT NULL,
            snapshot jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE IF NOT EXISTS {cls._OUTBOX_TABLE} (
            event_id text PRIMARY KEY,
            job_id text NOT NULL,
            project_id text NOT NULL,
            event_type text NOT NULL,
            status text NOT NULL,
            attempts integer NOT NULL DEFAULT 0,
            lease_owner text,
            lease_until timestamptz,
            occurred_at timestamptz NOT NULL,
            acknowledged_at timestamptz,
            payload jsonb NOT NULL,
            event jsonb NOT NULL
        );
        CREATE INDEX IF NOT EXISTS memory_spark_outbox_pending_idx
            ON {cls._OUTBOX_TABLE} (status, occurred_at)
            WHERE status IN ('PENDING', 'LEASED');
        CREATE INDEX IF NOT EXISTS memory_spark_outbox_job_idx
            ON {cls._OUTBOX_TABLE} (job_id, occurred_at);
        """

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(self._schema_sql())
            connection.commit()

    def _state_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "store": self._json_safe(
                {field_name: getattr(self, field_name) for field_name in self._PERSISTED_FIELDS if field_name != "outbox"}
            ),
        }

    @staticmethod
    def _timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(value)

    def _replace_outbox(self, connection: Any) -> None:
        connection.execute(f"DELETE FROM {self._OUTBOX_TABLE}")
        for event in self.outbox:
            event_id = str(event.get("event_id") or event.get("id"))
            connection.execute(
                f"""
                INSERT INTO {self._OUTBOX_TABLE}
                    (event_id, job_id, project_id, event_type, status, attempts,
                     lease_owner, lease_until, occurred_at, acknowledged_at, payload, event)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event_id,
                    str(event.get("job_id", "")),
                    str(event.get("project_id", "")),
                    str(event.get("type", "")),
                    str(event.get("status", "PENDING")),
                    int(event.get("attempts", 0)),
                    event.get("lease_owner"),
                    self._timestamp(event.get("lease_until")),
                    self._timestamp(event.get("occurred_at")) or datetime.now(timezone.utc),
                    self._timestamp(event.get("acknowledged_at")),
                    Jsonb(self._json_safe(event.get("payload", {}))),
                    Jsonb(self._json_safe(event)),
                ),
            )

    def _load_connection(self, connection: Any, for_update: bool = False) -> None:
        suffix = " FOR UPDATE" if for_update else ""
        row = connection.execute(
            f"SELECT revision, snapshot FROM {self._STATE_TABLE} WHERE id = 1{suffix}"
        ).fetchone()
        if row is None:
            raise RuntimeError("Memory Spark PostgreSQL state row has not been initialized")
        self._database_revision = int(row[0])
        self._apply_snapshot(row[1])
        events = connection.execute(
            f"SELECT event FROM {self._OUTBOX_TABLE} ORDER BY occurred_at, event_id"
        ).fetchall()
        self.outbox = [dict(event[0]) for event in events]

    def _initialize_if_empty(self) -> None:
        with self._connect() as connection:
            row = connection.execute(f"SELECT revision FROM {self._STATE_TABLE} WHERE id = 1").fetchone()
            if row is not None:
                connection.commit()
                return
            connection.execute(
                f"""
                INSERT INTO {self._STATE_TABLE} (id, schema_version, revision, snapshot)
                VALUES (1, 1, 0, %s)
                """,
                (Jsonb(self._state_payload()),),
            )
            self._replace_outbox(connection)
            connection.commit()

    def reload(self) -> None:
        if self._request_connection is not None:
            return
        with self.lock:
            with self._connect() as connection:
                self._load_connection(connection)
                connection.commit()

    def _save_connection(self, connection: Any) -> None:
        next_revision = self._database_revision + 1
        updated = connection.execute(
            f"""
            UPDATE {self._STATE_TABLE}
               SET schema_version = 1, revision = %s, snapshot = %s, updated_at = now()
             WHERE id = 1 AND revision = %s
            """,
            (next_revision, Jsonb(self._state_payload()), self._database_revision),
        ).rowcount
        if updated != 1:
            raise RuntimeError("Memory Spark PostgreSQL state changed during the request")
        self._replace_outbox(connection)
        self._database_revision = next_revision

    def begin_request(self) -> None:
        if self._request_connection is not None:
            raise RuntimeError("A PostgreSQL request transaction is already active")
        connection = self._connect()
        try:
            self._load_connection(connection, for_update=True)
            self._request_connection = connection
        except BaseException:
            connection.rollback()
            connection.close()
            raise

    def commit_request(self) -> None:
        connection = self._request_connection
        if connection is None:
            return
        try:
            self._save_connection(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
            self._request_connection = None

    def rollback_request(self) -> None:
        connection = self._request_connection
        if connection is None:
            return
        try:
            connection.rollback()
        finally:
            connection.close()
            self._request_connection = None

    @contextmanager
    def transaction(self):
        with self.lock:
            connection = self._connect()
            try:
                self._load_connection(connection, for_update=True)
                yield self
                self._save_connection(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def save(self) -> None:
        if self._request_connection is not None:
            self.commit_request()
            return
        with self.lock:
            with self._connect() as connection:
                connection.execute(f"SELECT revision FROM {self._STATE_TABLE} WHERE id = 1 FOR UPDATE")
                self._save_connection(connection)
                connection.commit()

    def pending_outbox_count(self) -> int:
        if self._request_connection is not None:
            return super().pending_outbox_count()
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT count(*) FROM {self._OUTBOX_TABLE} WHERE status NOT IN ('ACKED', 'FAILED')"
            ).fetchone()
            connection.commit()
        return int(row[0])
