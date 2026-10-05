"""Durable, credential-free private draft jobs and revision fencing."""
import hashlib
import json
import time
from uuid import uuid4
from .task_queue import TaskQueue


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


class PrivateDraftJobs(TaskQueue):
    def __init__(self, path):
        super().__init__(path)
        with self._connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS private_draft_projects (
                user_id TEXT NOT NULL,project_id TEXT NOT NULL,locale TEXT NOT NULL,
                source_key TEXT NOT NULL,payload TEXT NOT NULL,source_epoch INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 0,
                completed_milestone INTEGER NOT NULL DEFAULT 0,draft TEXT,human_locked INTEGER NOT NULL DEFAULT 0,
                stale INTEGER NOT NULL DEFAULT 0,proposal TEXT,
                PRIMARY KEY(user_id,project_id,locale));
              CREATE TABLE IF NOT EXISTS private_draft_rounds (
                user_id TEXT NOT NULL,project_id TEXT NOT NULL,turn_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
                memory_id TEXT,PRIMARY KEY(user_id,project_id,turn_id),UNIQUE(user_id,project_id,ordinal));
              CREATE TABLE IF NOT EXISTS private_draft_jobs (
                id TEXT PRIMARY KEY,user_id TEXT NOT NULL,project_id TEXT NOT NULL,locale TEXT NOT NULL,
                source_key TEXT NOT NULL,source_epoch INTEGER NOT NULL,milestone INTEGER NOT NULL,payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'QUEUED',attempts INTEGER NOT NULL DEFAULT 0,
                checkpoint TEXT NOT NULL DEFAULT '{}',phase TEXT NOT NULL DEFAULT 'indexing',
                error TEXT,available_at REAL NOT NULL,lease_token TEXT,lease_until REAL,
                created_at REAL NOT NULL,UNIQUE(user_id,project_id,locale,source_key));
            ''')

    def synchronize(self, owner, project, locale, rounds, sources, *, completed, free_limit, cadence, enabled=True, authorization_event_id=None):
        if len(rounds)>1000 or len(sources)>1000 or sum(len(s['text']) for s in sources)>120000:
            raise ValueError('Private draft collection exceeds supported bounds')
        payload={'sources':sources,'rounds':rounds,'completed':completed,'free_limit':free_limit,
                 'cadence':cadence,'enabled':enabled,'policy_version':1,'authorization_event_id':authorization_event_id}
        now=time.time()
        with self._transaction() as db:
            previous=db.execute('SELECT * FROM private_draft_projects WHERE user_id=? AND project_id=? AND locale=?',
                                (owner,project,locale)).fetchone()
            for r in rounds:
                db.execute('INSERT OR IGNORE INTO private_draft_rounds VALUES (?,?,?,?,?)',
                    (owner,project,r['turn_id'],r['ordinal'],r.get('memory_id')))
                db.execute('UPDATE private_draft_rounds SET memory_id=? WHERE user_id=? AND project_id=? AND turn_id=?',
                    (r.get('memory_id'),owner,project,r['turn_id']))
            stale=False
            invalidated=False
            epoch=previous['source_epoch'] if previous else 1
            current={s['id']:s['version'] for s in sources}
            if previous:
                old=json.loads(previous['payload'])
                invalidated=any(current.get(s['id'])!=s['version'] for s in old.get('sources',[])) or any(
                    old.get(k)!=payload[k] for k in ('cadence','free_limit','enabled','policy_version'))
                epoch+=int(invalidated)
            if previous and previous['draft']:
                saved=json.loads(previous['draft'])['request']['sources']
                stale=any(current.get(s['id'])!=s['version'] for s in saved)
            key=digest({**payload,'source_epoch':epoch})
            db.execute('''INSERT INTO private_draft_projects(user_id,project_id,locale,source_key,payload,stale,source_epoch)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id,project_id,locale) DO UPDATE SET
                source_key=excluded.source_key,payload=excluded.payload,stale=excluded.stale,source_epoch=excluded.source_epoch''',
                (owner,project,locale,key,json.dumps(payload),int(stale),epoch))
            # A changed/revoked manifest fences late work and prunes obsolete
            # source/checkpoint bytes. Protected user edits remain recoverable.
            if invalidated:
                db.execute("""UPDATE private_draft_jobs SET status='STALE',payload='{}',checkpoint='{}',lease_token=NULL
                    WHERE user_id=? AND project_id=? AND locale=? AND source_epoch<>?""",(owner,project,locale,epoch))
            ordinal=max((r['ordinal'] for r in rounds),default=0)
            milestone=(ordinal//cadence)*cadence
            requested=db.execute('SELECT coalesce(max(milestone),0) FROM private_draft_jobs WHERE user_id=? AND project_id=? AND locale=? AND source_epoch=?',
                                 (owner,project,locale,epoch)).fetchone()[0]
            if enabled and milestone and (milestone>requested or invalidated):
                db.execute("""UPDATE private_draft_jobs SET status='SUPERSEDED',payload='{}',checkpoint='{}'
                    WHERE user_id=? AND project_id=? AND locale=? AND status='QUEUED'""",(owner,project,locale))
                db.execute('''INSERT OR IGNORE INTO private_draft_jobs
                    (id,user_id,project_id,locale,source_key,source_epoch,milestone,payload,available_at,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''', (str(uuid4()),owner,project,locale,key,epoch,milestone,json.dumps(payload),now,now))
            return self._view(db,owner,project,locale)

    def _view(self, db, owner, project, locale):
        row=db.execute('SELECT * FROM private_draft_projects WHERE user_id=? AND project_id=? AND locale=?',
                       (owner,project,locale)).fetchone()
        if not row:
            return {'status':'collecting','preview':None,'updating':False,'revision':0}
        job=db.execute('SELECT status,error,phase,milestone FROM private_draft_jobs WHERE user_id=? AND project_id=? AND locale=? ORDER BY created_at DESC LIMIT 1',
                       (owner,project,locale)).fetchone()
        bundle=json.loads(row['draft']) if row['draft'] and not row['stale'] else None
        from .memoir_preview import reader_preview
        return {'status':'ready' if bundle else 'stale' if row['stale'] else 'collecting',
                'preview':reader_preview(bundle) if bundle else None,'updating':bool(job and job['status'] in {'QUEUED','RUNNING'}),
                'error':job['error'] if job else None,'revision':row['revision'],
                'milestone':row['completed_milestone'],'proposal_pending':bool(row['proposal'])}

    def pending_ids(self, limit=100):
        with self._connect() as db:
            return [r['id'] for r in db.execute("SELECT id FROM private_draft_jobs WHERE status IN ('QUEUED','RUNNING') ORDER BY created_at LIMIT ?",(limit,))]

    def status(self, job_id):
        with self._connect() as db:
            row=db.execute('SELECT status FROM private_draft_jobs WHERE id=?',(job_id,)).fetchone()
            return row['status'] if row else None

    def authorization_event(self,job_id):
        with self._connect() as db:
            row=db.execute('SELECT payload FROM private_draft_jobs WHERE id=?',(job_id,)).fetchone()
            return json.loads(row['payload']).get('authorization_event_id') if row else None

    def revoke(self,job_id):
        with self._transaction() as db:
            row=db.execute('SELECT user_id,project_id,locale FROM private_draft_jobs WHERE id=?',(job_id,)).fetchone()
            if row:
                scope=tuple(row)
                db.execute("UPDATE private_draft_jobs SET status='STALE',payload='{}',checkpoint='{}',lease_token=NULL WHERE user_id=? AND project_id=? AND locale=?",scope)
                db.execute("UPDATE private_draft_projects SET stale=1,draft=NULL,proposal=NULL,payload='{}' WHERE user_id=? AND project_id=? AND locale=?",scope)

    def invalidate_other_locales(self,owner,project,locale):
        with self._transaction() as db:
            db.execute("UPDATE private_draft_jobs SET status='STALE',payload='{}',checkpoint='{}',lease_token=NULL WHERE user_id=? AND project_id=? AND locale<>? AND status IN ('QUEUED','RUNNING')",(owner,project,locale))
            db.execute('UPDATE private_draft_projects SET stale=1 WHERE user_id=? AND project_id=? AND locale<>?',(owner,project,locale))

    def retry(self, owner, project, locale):
        with self._transaction() as db:
            db.execute("""UPDATE private_draft_jobs SET status='QUEUED',attempts=0,error=NULL,available_at=?
                WHERE user_id=? AND project_id=? AND locale=? AND status='FAILED'
                AND source_epoch=(SELECT source_epoch FROM private_draft_projects WHERE user_id=? AND project_id=? AND locale=?)""",
                (time.time(),owner,project,locale,owner,project,locale))

    def claim(self, job_id):
        now=time.time()
        with self._transaction() as db:
            row=db.execute('SELECT * FROM private_draft_jobs WHERE id=?', (job_id,)).fetchone()
            if not row or row['status'] not in {'QUEUED','RUNNING'} or row['available_at']>now or (row['status']=='RUNNING' and row['lease_until']>now):
                return None
            if row['attempts']>=3:
                db.execute("UPDATE private_draft_jobs SET status='FAILED',error='DRAFT_INTERRUPTED' WHERE id=?",(job_id,))
                return None
            busy=db.execute("""SELECT 1 FROM private_draft_jobs WHERE user_id=? AND project_id=?
                AND status='RUNNING' AND lease_until>? AND id<>?""",(row['user_id'],row['project_id'],now,job_id)).fetchone()
            if busy:
                return None
            project=db.execute('SELECT * FROM private_draft_projects WHERE user_id=? AND project_id=? AND locale=?',
                (row['user_id'],row['project_id'],row['locale'])).fetchone()
            if project['source_epoch']!=row['source_epoch'] or not json.loads(project['payload'])['enabled']:
                db.execute("UPDATE private_draft_jobs SET status='STALE',payload='{}',checkpoint='{}' WHERE id=?",(job_id,))
                return None
            token=str(uuid4())
            db.execute("UPDATE private_draft_jobs SET status='RUNNING',attempts=attempts+1,lease_token=?,lease_until=? WHERE id=?",(token,now+900,job_id))
            return {**dict(row),'lease_token':token,'payload':json.loads(row['payload']),
                    'checkpoint':json.loads(row['checkpoint']),'base_revision':project['revision'],
                    'previous':json.loads(project['draft']) if project['draft'] else None,
                    'previous_milestone':project['completed_milestone'],'human_locked':bool(project['human_locked'])}

    def checkpoint(self, job_id, token, phase, value):
        now=time.time()
        with self._transaction() as db:
            if not db.execute("""UPDATE private_draft_jobs SET checkpoint=?,phase=?,lease_until=?
                WHERE id=? AND status='RUNNING' AND lease_token=? AND lease_until>?""",
                (json.dumps(value),phase,now+900,job_id,token,now)).rowcount:
                raise RuntimeError('Private draft lease lost')

    def finish(self, job, *, result=None, error=None, retryable=False):
        now=time.time()
        with self._transaction() as db:
            held=db.execute("SELECT * FROM private_draft_jobs WHERE id=? AND status='RUNNING' AND lease_token=? AND lease_until>?",
                            (job['id'],job['lease_token'],now)).fetchone()
            if not held:
                return False
            status='QUEUED' if error and retryable and held['attempts']<3 else 'FAILED' if error else 'SUCCEEDED'
            if result:
                project=db.execute('SELECT * FROM private_draft_projects WHERE user_id=? AND project_id=? AND locale=?',
                    (job['user_id'],job['project_id'],job['locale'])).fetchone()
                if project['revision']!=job['base_revision'] or project['source_epoch']!=job['source_epoch']:
                    status,error='STALE','DRAFT_REVISION_CHANGED'
                elif project['human_locked']:
                    db.execute('UPDATE private_draft_projects SET proposal=? WHERE user_id=? AND project_id=? AND locale=?',
                               (json.dumps(result),job['user_id'],job['project_id'],job['locale']))
                else:
                    db.execute('''UPDATE private_draft_projects SET draft=?,revision=revision+1,completed_milestone=?,stale=0,proposal=NULL
                        WHERE user_id=? AND project_id=? AND locale=?''',
                        (json.dumps(result),job['milestone'],job['user_id'],job['project_id'],job['locale']))
            db.execute('UPDATE private_draft_jobs SET status=?,error=?,available_at=?,lease_token=NULL,lease_until=NULL WHERE id=?',
                       (status,error,now+2**held['attempts'],job['id']))
            return status=='SUCCEEDED'

    def protect(self, owner, project, locale, expected_revision):
        with self._transaction() as db:
            if not db.execute('''UPDATE private_draft_projects SET human_locked=1,revision=revision+1
                WHERE user_id=? AND project_id=? AND locale=? AND revision=? AND draft IS NOT NULL''',
                (owner,project,locale,expected_revision)).rowcount:
                raise ValueError('Private draft revision changed')
