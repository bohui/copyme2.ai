"""Invalidate local derived caches when canonical evidence is revoked."""
import os
from pathlib import Path
import sqlite3


def prune_saved_cache(owner, project, *, preserve_lifetime_pages=False):
    """Remove restricted derived bytes before acknowledging a revocation receipt."""
    path = os.getenv('MEMORY_SPARK_TASK_DB')
    if not path or not Path(path).is_file():
        return
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA secure_delete=ON')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'private_draft_projects' in tables:
            db.execute("UPDATE private_draft_projects SET stale=1,draft=NULL,proposal=NULL,payload='{}',source_epoch=source_epoch+1 WHERE user_id=? AND project_id=?",
                       (owner, project))
        if 'private_draft_jobs' in tables:
            # Governed page jobs contain only scope, counters and digests. The
            # policy-fenced pager invalidates obsolete receipts itself; pruning
            # every retry would destroy its current durable continuation.
            db.execute("""UPDATE private_draft_jobs SET status='STALE',payload='{}',checkpoint='{}',lease_token=NULL,lease_until=NULL
                WHERE user_id=? AND project_id=? AND (?=0 OR coalesce(json_extract(payload,'$.protocol'),'')<>'lifetime_draft_pages')""",
                       (owner, project, int(preserve_lifetime_pages)))
        if 'preview_jobs' in tables:
            db.execute("UPDATE preview_jobs SET status='STALE',payload='{}',checkpoint='{}',lease_token=NULL,lease_until=NULL WHERE user_id=? AND project_id=?",
                       (owner, project))
