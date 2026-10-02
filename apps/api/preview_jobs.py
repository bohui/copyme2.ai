"""Credential-free preview checkpoints; execution resumes with fresh user auth.

Reuse the private task volume and SQLite transactions. Only the API executes
these jobs: tenant workers never receive database credentials or bearer tokens.
"""
import json
import os
import time
from uuid import uuid4

from .task_queue import TaskQueue


class PreviewJobs(TaskQueue):
    def __init__(self, path=None):
        super().__init__(path or os.getenv('MEMORY_SPARK_TASK_DB', 'var/memory-spark/preview-jobs.sqlite'))
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS preview_jobs (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
                snapshot_key TEXT NOT NULL, language TEXT NOT NULL, status TEXT NOT NULL,
                phase TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL, checkpoint TEXT NOT NULL DEFAULT '{}',
                error TEXT, outcome TEXT, available_at REAL NOT NULL, lease_token TEXT, lease_until REAL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                UNIQUE(user_id, project_id, snapshot_key)
            )''')

    @staticmethod
    def public(row):
        return {'id': row['id'], 'project_id': row['project_id'], 'language': row['language'],
                'snapshot_key': row['snapshot_key'], 'status': row['status'], 'phase': row['phase'],
                'attempts': row['attempts'], 'error': row['error'], 'outcome': row['outcome']}

    def submit(self, user_id, project_id, key, language, payload, *, retry=False):
        now = time.time()
        with self._transaction() as db:
            db.execute('''INSERT OR IGNORE INTO preview_jobs
                (id,user_id,project_id,snapshot_key,language,status,phase,payload,available_at,created_at,updated_at)
                VALUES (?,?,?,?,?,'QUEUED','indexing',?,?,?,?)''',
                (str(uuid4()), user_id, project_id, key, language, json.dumps(payload), now, now, now))
            if retry:
                db.execute("""UPDATE preview_jobs SET status='QUEUED',attempts=0,error=NULL,available_at=?,updated_at=?
                    WHERE user_id=? AND project_id=? AND snapshot_key=? AND status IN ('FAILED', 'SUCCEEDED')""",
                    (now, now, user_id, project_id, key))
            row = db.execute('SELECT * FROM preview_jobs WHERE user_id=? AND project_id=? AND snapshot_key=?',
                             (user_id, project_id, key)).fetchone()
            return self.public(row)

    def get(self, user_id, job_id):
        with self._connect() as db:
            row = db.execute('SELECT * FROM preview_jobs WHERE user_id=? AND id=?', (user_id, job_id)).fetchone()
            return self.public(row) if row else None

    def claim(self, user_id, job_id, *, lease_seconds=900):
        now = time.time()
        with self._transaction() as db:
            db.execute("""UPDATE preview_jobs SET status='FAILED',error='PREVIEW_INTERRUPTED'
                WHERE user_id=? AND id=? AND status='RUNNING' AND lease_until<=? AND attempts>=3""",
                (user_id, job_id, now))
            row = db.execute("""SELECT * FROM preview_jobs WHERE user_id=? AND id=? AND attempts<3
                AND ((status='QUEUED' AND available_at<=?) OR (status='RUNNING' AND lease_until<=?))""",
                (user_id, job_id, now, now)).fetchone()
            if not row:
                return None
            token = str(uuid4())
            db.execute("""UPDATE preview_jobs SET status='RUNNING',attempts=attempts+1,lease_token=?,lease_until=?,updated_at=?
                WHERE id=?""", (token, now + lease_seconds, now, job_id))
            return {**dict(row), 'lease_token': token,
                    'payload': json.loads(row['payload']), 'checkpoint': json.loads(row['checkpoint'])}

    def checkpoint(self, job_id, token, phase, checkpoint):
        now = time.time()
        with self._transaction() as db:
            changed = db.execute("""UPDATE preview_jobs SET phase=?,checkpoint=?,lease_until=?,updated_at=?
                WHERE id=? AND status='RUNNING' AND lease_token=? AND lease_until>?""",
                (phase, json.dumps(checkpoint), now + 900, now, job_id, token, now)).rowcount
            if not changed:
                raise RuntimeError('Preview job lease lost')

    def finish(self, job_id, token, *, error=None, retryable=False, outcome=None):
        now = time.time()
        with self._transaction() as db:
            row = db.execute("""SELECT attempts FROM preview_jobs
                WHERE id=? AND status='RUNNING' AND lease_token=? AND lease_until>?""", (job_id, token, now)).fetchone()
            if not row:
                return False
            busy = error == 'AGENT_TURN_IN_PROGRESS'
            status = 'SUCCEEDED' if error is None else ('QUEUED' if busy or retryable and row['attempts'] < 3 else 'FAILED')
            delay = 15 if busy else 2 ** row['attempts'] if error else 0
            # Waiting for a conversation lease has not attempted composition.
            db.execute('''UPDATE preview_jobs SET status=?,error=?,outcome=?,attempts=attempts-?,
                available_at=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?''',
                (status, error, outcome, int(busy), now + delay, now, job_id))
            return True
