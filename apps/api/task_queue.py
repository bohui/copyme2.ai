"""Durable local task queue shared only by API and deterministic workers.

SQLite transactions claim work across processes. Lease tokens fence late
completions; deterministic results are committed in the queue transaction.
The task volume is not mounted in the tenant-hosting Codex container.
"""
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

from .memoir_tasks import MemoirTask


def configured_queue():
    path = os.getenv('MEMORY_SPARK_TASK_DB')
    if not path:
        raise RuntimeError('MEMORY_SPARK_TASK_DB is required for background tasks')
    return TaskQueue(path)


class TaskQueue:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Named-volume roots can be normalized to 0755. Create the DB privately
        # before SQLite opens it, rather than relying on the mount's permissions.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    dedup_key TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'QUEUED', attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL, lease_token TEXT, lease_until REAL,
                    result TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(user_id, project_id, dedup_key)
                );
                CREATE INDEX IF NOT EXISTS tasks_ready ON tasks(status, available_at);
                CREATE TABLE IF NOT EXISTS collection (
                    user_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    document TEXT NOT NULL, PRIMARY KEY(user_id, project_id)
                );
                CREATE TABLE IF NOT EXISTS workspace_jobs (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT,
                    turn_id TEXT NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'QUEUED', attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL, lease_token TEXT, lease_until REAL,
                    error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(user_id, turn_id)
                );
                CREATE INDEX IF NOT EXISTS workspace_jobs_ready
                    ON workspace_jobs(status, available_at);
                CREATE TABLE IF NOT EXISTS guest_workspace_imports (
                    transfer_id TEXT PRIMARY KEY, source_user_id TEXT NOT NULL,
                    target_user_id TEXT NOT NULL
                );
            ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def submit(self, user_id, project_id, task: MemoirTask):
        payload = json.dumps(task.model_dump(), ensure_ascii=False, sort_keys=True)
        key = hashlib.sha256(payload.encode()).hexdigest()
        now = time.time()
        with self._transaction() as db:
            db.execute('''INSERT OR IGNORE INTO tasks
                (id, user_id, project_id, dedup_key, payload, available_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (str(uuid4()), user_id, project_id, key, payload, now, now, now))
            row = db.execute('SELECT * FROM tasks WHERE user_id=? AND project_id=? AND dedup_key=?',
                             (user_id, project_id, key)).fetchone()
            return self._public(row)

    @staticmethod
    def _public(row):
        return {'id': row['id'], 'project_id': row['project_id'],
                'kind': json.loads(row['payload'])['kind'], 'status': row['status'],
                'attempts': row['attempts'], 'created_at': row['created_at'],
                'result': json.loads(row['result']) if row['result'] else None,
                'error': row['error']}

    def get(self, user_id, task_id):
        with self._connect() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=? AND user_id=?', (task_id, user_id)).fetchone()
            return self._public(row) if row else None

    def status(self, task_id):
        """Internal executor lookup; never returns another owner's content."""
        with self._connect() as db:
            row = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
            return row['status'] if row else None

    def fail_dispatch(self, task_id):
        with self._transaction() as db:
            db.execute("""UPDATE tasks SET status='FAILED', error='WORKFLOW_FAILED',
                lease_token=NULL, lease_until=NULL, updated_at=?
                WHERE id=? AND status IN ('QUEUED', 'RUNNING')""", (time.time(), task_id))

    def list(self, user_id, project_id):
        with self._connect() as db:
            return [self._public(row) for row in db.execute('''SELECT * FROM tasks
                WHERE user_id=? AND project_id=? ORDER BY created_at DESC LIMIT 100''',
                (user_id, project_id))]

    def invalidate_readiness(self, user_id, project_id):
        with self._transaction() as db:
            row = db.execute('SELECT document FROM collection WHERE user_id=? AND project_id=?',
                             (user_id, project_id)).fetchone()
            if row:
                document = json.loads(row['document'])
                document['ready'] = False
                document['revision'] += 1
                db.execute('UPDATE collection SET document=? WHERE user_id=? AND project_id=?',
                           (json.dumps(document), user_id, project_id))

    def claim(self, *, lease_seconds=60, task_id=None):
        now = time.time()
        with self._transaction() as db:
            db.execute("""UPDATE tasks SET status='FAILED', error='ATTEMPTS_EXHAUSTED',
                lease_token=NULL, lease_until=NULL, updated_at=?
                WHERE status='RUNNING' AND lease_until<=? AND attempts>=3""", (now, now))
            row = db.execute("""SELECT * FROM tasks WHERE attempts<3 AND
                ((status='QUEUED' AND available_at<=?) OR (status='RUNNING' AND lease_until<=?))
                AND (? IS NULL OR id=?) ORDER BY created_at LIMIT 1""", (now, now, task_id, task_id)).fetchone()
            if not row:
                return None
            token = str(uuid4())
            db.execute("""UPDATE tasks SET status='RUNNING', attempts=attempts+1,
                lease_token=?, lease_until=?, updated_at=? WHERE id=?""",
                (token, now + lease_seconds, now, row['id']))
            return {'id': row['id'], 'lease_token': token, 'task': MemoirTask.model_validate_json(row['payload'])}

    def finish(self, task_id, token, *, result=None, error=None):
        now = time.time()
        with self._transaction() as db:
            row = db.execute("""SELECT attempts FROM tasks WHERE id=? AND lease_token=?
                AND status='RUNNING' AND lease_until>?""", (task_id, token, now)).fetchone()
            if not row:
                return False
            status = 'SUCCEEDED' if error is None else ('QUEUED' if row['attempts'] < 3 else 'FAILED')
            db.execute('''UPDATE tasks SET status=?, result=?, error=?, available_at=?,
                lease_token=NULL, lease_until=NULL, updated_at=? WHERE id=?''',
                (status, json.dumps(result, ensure_ascii=False) if error is None else None,
                 error, now + (2 ** row['attempts'] if error else 0), now, task_id))
            return True

    def pending_ids(self, limit=100):
        with self._connect() as db:
            return [row['id'] for row in db.execute("""SELECT id FROM tasks
                WHERE status IN ('QUEUED', 'RUNNING') ORDER BY created_at LIMIT ?""", (limit,))]

    @staticmethod
    def _workspace_public(row):
        if not row:
            return None
        return {
            'id': row['id'],
            'project_id': row['project_id'],
            'turn_id': row['turn_id'],
            'status': row['status'],
            'attempts': row['attempts'],
            'created_at': row['created_at'],
            'error': row['error'],
        }

    @staticmethod
    def _delivery_tables(db):
        tables = ['tasks', 'workspace_jobs']
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='preview_jobs'").fetchone():
            tables.append('preview_jobs')
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='private_draft_jobs'").fetchone():
            tables.append('private_draft_jobs')
        return tables

    def has_pending_user_work(self, user_id):
        with self._connect() as db:
            return any(db.execute(f"SELECT 1 FROM {table} WHERE user_id=? "
                                  "AND status IN ('QUEUED', 'RUNNING') LIMIT 1", (user_id,)).fetchone()
                       for table in self._delivery_tables(db))

    def import_guest_results(self, guest_id, owner_id, transfer_id, memory_id_map):
        """Copy completed deliveries and coverage; keep the guest recoverable.

        Task IDs remain stable across retries. Memory citations are translated
        to the corresponding imported Supabase rows, never discarded.
        """
        from .workspace_merge import remap_memory_ids, merge_collection_periods
        with self._transaction() as db:
            imported = db.execute('SELECT * FROM guest_workspace_imports WHERE transfer_id=?', (transfer_id,)).fetchone()
            if imported:
                if (imported['source_user_id'], imported['target_user_id']) != (guest_id, owner_id):
                    raise ValueError('Transfer owner changed')
                return
            for table in self._delivery_tables(db):
                if db.execute(f"SELECT 1 FROM {table} WHERE user_id=? AND status IN ('QUEUED', 'RUNNING') LIMIT 1",
                              (guest_id,)).fetchone():
                    raise ValueError('Guest deliveries are still being generated')
            for row in db.execute('SELECT * FROM tasks WHERE user_id=?', (guest_id,)).fetchall():
                payload = remap_memory_ids(json.loads(row['payload']), memory_id_map)
                result = remap_memory_ids(json.loads(row['result']), memory_id_map) if row['result'] else None
                task_id = str(uuid5(NAMESPACE_URL, f'memoir-guest-task:{owner_id}:{row["id"]}'))
                db.execute('''INSERT OR IGNORE INTO tasks
                    (id, user_id, project_id, dedup_key, payload, status, attempts, available_at,
                     result, error, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (task_id, owner_id, row['project_id'], f'guest:{guest_id}:{row["dedup_key"]}',
                     json.dumps(payload), row['status'], row['attempts'], row['available_at'],
                     json.dumps(result) if result is not None else None, row['error'], row['created_at'], row['updated_at']))
            for row in db.execute('SELECT * FROM collection WHERE user_id=?', (guest_id,)).fetchall():
                source = remap_memory_ids(json.loads(row['document']), memory_id_map)
                existing = db.execute('SELECT document FROM collection WHERE user_id=? AND project_id=?',
                                      (owner_id, row['project_id'])).fetchone()
                target = json.loads(existing['document']) if existing else {'revision': 0, 'periods': {}}
                document = {'revision': target['revision'] + 1, 'ready': False,
                            'periods': merge_collection_periods(target.get('periods', {}), source.get('periods', {}))}
                db.execute('''INSERT INTO collection VALUES (?, ?, ?) ON CONFLICT(user_id, project_id)
                              DO UPDATE SET document=excluded.document''',
                           (owner_id, row['project_id'], json.dumps(document)))
            db.execute('INSERT INTO guest_workspace_imports VALUES (?, ?, ?)', (transfer_id, guest_id, owner_id))

    def submit_workspace(self, user_id, project_id, turn_id, payload):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        now = time.time()
        with self._transaction() as db:
            db.execute('''INSERT OR IGNORE INTO workspace_jobs
                (id, user_id, project_id, turn_id, payload, available_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (str(uuid4()), user_id, project_id, turn_id, encoded, now, now, now))
            row = db.execute('''SELECT * FROM workspace_jobs
                WHERE user_id=? AND turn_id=?''', (user_id, turn_id)).fetchone()
            return self._workspace_public(row)

    def claim_workspace(self, user_id, *, job_id=None, lease_seconds=300):
        now = time.time()
        with self._transaction() as db:
            row = db.execute('''SELECT * FROM workspace_jobs
                WHERE user_id=? AND attempts < 3
                  AND ((status='QUEUED' AND available_at<=?)
                    OR (status='RUNNING' AND lease_until<=?))
                  AND (? IS NULL OR id=?)
                ORDER BY created_at LIMIT 1''',
                (user_id, now, now, job_id, job_id)).fetchone()
            if not row:
                return None
            token = str(uuid4())
            db.execute('''UPDATE workspace_jobs SET status='RUNNING', attempts=attempts+1,
                lease_token=?, lease_until=?, updated_at=? WHERE id=?''',
                (token, now + lease_seconds, now, row['id']))
            return {
                'id': row['id'],
                'lease_token': token,
                'project_id': row['project_id'],
                'turn_id': row['turn_id'],
                'payload': json.loads(row['payload']),
            }

    def finish_workspace(self, job_id, token, *, error=None):
        now = time.time()
        with self._transaction() as db:
            row = db.execute('''SELECT attempts FROM workspace_jobs
                WHERE id=? AND lease_token=? AND status='RUNNING' AND lease_until>?''',
                (job_id, token, now)).fetchone()
            if not row:
                return False
            status = 'SUCCEEDED' if error is None else ('QUEUED' if row['attempts'] < 3 else 'FAILED')
            db.execute('''UPDATE workspace_jobs SET status=?, error=?, available_at=?,
                lease_token=NULL, lease_until=NULL, updated_at=? WHERE id=?''',
                (status, error, now + (2 ** row['attempts'] if error else 0), now, job_id))
            return True

    def pending_workspace(self, user_id, limit=20):
        with self._connect() as db:
            return [self._workspace_public(row) for row in db.execute('''SELECT * FROM workspace_jobs
                WHERE user_id=? AND status IN ('QUEUED', 'RUNNING')
                ORDER BY created_at LIMIT ?''', (user_id, limit))]

    def collection(self, user_id, project_id):
        with self._connect() as db:
            row = db.execute('SELECT document FROM collection WHERE user_id=? AND project_id=?',
                             (user_id, project_id)).fetchone()
            return json.loads(row['document']) if row else {'revision': 0, 'periods': {}, 'ready': False}

    def update_collection(self, user_id, project_id, *, periods, ready, expected_revision, source_fingerprint=None):
        with self._transaction() as db:
            row = db.execute('SELECT document FROM collection WHERE user_id=? AND project_id=?',
                             (user_id, project_id)).fetchone()
            previous = json.loads(row['document']) if row else {'revision': 0}
            if previous['revision'] != expected_revision:
                raise ValueError('Collection has changed; reload before updating')
            document = {'revision': expected_revision + 1, 'periods': periods, 'ready': ready}
            if source_fingerprint is not None:
                document['source_fingerprint'] = source_fingerprint
            db.execute('''INSERT INTO collection VALUES (?, ?, ?)
                ON CONFLICT(user_id, project_id) DO UPDATE SET document=excluded.document''',
                (user_id, project_id, json.dumps(document)))
            return document
