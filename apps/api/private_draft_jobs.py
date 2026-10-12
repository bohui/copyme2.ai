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
              CREATE TABLE IF NOT EXISTS private_draft_page_receipts (
                job_id TEXT NOT NULL,cursor_key TEXT NOT NULL,page_digest TEXT NOT NULL,
                next_cursor TEXT,record_count INTEGER NOT NULL,
                PRIMARY KEY(job_id,cursor_key));
              CREATE TABLE IF NOT EXISTS private_draft_page_state (
                user_id TEXT NOT NULL,project_id TEXT NOT NULL,conversation_id TEXT NOT NULL,
                policy_epoch INTEGER NOT NULL,preference_revision INTEGER NOT NULL,
                round_revision INTEGER NOT NULL,locale TEXT NOT NULL,
                PRIMARY KEY(user_id,project_id));
              CREATE INDEX IF NOT EXISTS private_draft_snapshot_key ON private_draft_jobs(source_key);
              CREATE INDEX IF NOT EXISTS private_draft_receipt_event ON private_draft_jobs(
                json_extract(payload,'$.authorization_event_id'),created_at DESC);
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

    def synchronize_page(self, page, *, free_limit, cadence, enabled=True):
        """Checkpoint one bounded canonical page, never assemble lifetime bytes.

        The receipt proves exact page consumption, not draft eligibility or a
        complete manuscript. Composition remains explicitly pending until its
        canonical source/event lanes support bounded, provenance-safe assembly.
        """
        if (type(page.get('schema_version')) is not int or page['schema_version'] != 1 or page.get('protocol') != 'lifetime_draft_pages'
                or type(page.get('complete')) is not bool
                or page['complete'] != (page.get('next_cursor') is None)
                or not isinstance(page.get('records'), list) or len(page['records']) > 32
                # JSON may escape each accepted control character as six bytes.
                or len(json.dumps(page, ensure_ascii=False).encode()) > 512 * 1024
                or type(cadence) is not int or not 1 <= cadence <= 1000000
                or type(free_limit) is not int or free_limit < 0 or type(enabled) is not bool):
            raise ValueError('Invalid bounded private draft page')
        for field in ('snapshot_id','event_id','user_id','project_id','conversation_id','locale'):
            if not isinstance(page.get(field),str) or not 1 <= len(page[field]) <= 128:
                raise ValueError('Invalid private draft scope')
        for field in ('policy_epoch','preference_revision','source_revision','event_revision','round_high_water','completed'):
            if type(page.get(field)) is not int or page[field] < (1 if field == 'policy_epoch' else 0):
                raise ValueError('Invalid private draft revision')
        if page['locale'] not in {'en-AU','zh-CN'}:
            raise ValueError('Invalid private draft locale')
        for field in ('cursor','next_cursor'):
            if page.get(field) is not None and (not isinstance(page[field],str) or not 1 <= len(page[field]) <= 128):
                raise ValueError('Invalid private draft cursor')
        if page.get('next_cursor') is not None and page['next_cursor'] == page.get('cursor'):
            raise ValueError('Private draft cursor did not advance')
        for row in page['records']:
            if not isinstance(row,dict):
                raise ValueError('Invalid private draft record')
            if row.get('record_type') == 'source':
                for field in ('source_id','kind','language','status'):
                    if not isinstance(row.get(field),str) or not 1 <= len(row[field]) <= 128:
                        raise ValueError('Invalid canonical source record')
                if (any(type(row.get(field)) is not int for field in ('version','sequence','char_start','char_end'))
                        or row['version'] < 1 or not 1 <= row['sequence'] <= page['source_revision']
                        or row['char_start'] < 0 or row['char_end'] < row['char_start']
                        or row['status'] not in {'active','withdrawn','superseded'}
                        or (row['status']=='active' and (not isinstance(row.get('text'),str)
                            or not 1 <= len(row['text']) <= 2048 or row['char_end']-row['char_start'] != len(row['text'])))
                        or (row['status']!='active' and row.get('text') is not None)):
                    raise ValueError('Invalid canonical source chunk')
            elif row.get('record_type') == 'round':
                if (not isinstance(row.get('turn_id'),str) or not 1 <= len(row['turn_id']) <= 128
                        or type(row.get('ordinal')) is not int or not 1 <= row['ordinal'] <= page['round_high_water']
                        or (row.get('memory_id') is not None and (not isinstance(row['memory_id'],str) or len(row['memory_id']) > 128))):
                    raise ValueError('Invalid completed round')
            else:
                raise ValueError('Unknown private draft record')
        coverage_fields=('coverage_schema_version','base_snapshot_id','source_after','round_after','round_revision')
        inherited=any(field in page for field in coverage_fields)
        source_after=round_after=round_revision=0
        if inherited:
            if not all(field in page for field in coverage_fields):
                raise ValueError('Incomplete private draft coverage contract')
            if type(page.get('coverage_schema_version')) is not int or page['coverage_schema_version']!=1:
                raise ValueError('Unknown private draft coverage contract')
            for field,maximum in (('source_after',page['source_revision']),('round_after',page['round_high_water']),('round_revision',None)):
                if type(page.get(field)) is not int or page[field]<0 or (maximum is not None and page[field]>maximum):
                    raise ValueError('Invalid inherited private draft coverage')
            source_after,round_after,round_revision=(page[field] for field in ('source_after','round_after','round_revision'))
            base=page.get('base_snapshot_id')
            if (source_after or round_after):
                if not isinstance(base,str) or not 1<=len(base)<=128 or base==page['snapshot_id']:
                    raise ValueError('Acknowledged prefix receipt required')
            elif base is not None:
                raise ValueError('Unexpected empty prefix receipt')
        fields=('schema_version','protocol','snapshot_id','event_id','user_id','project_id','conversation_id',
            'policy_epoch','preference_revision','source_revision','event_revision','round_high_water','completed','locale')
        if inherited:
            fields+=coverage_fields
        metadata={field:page[field] for field in fields}
        payload={**metadata,'free_limit':free_limit,'cadence':cadence,'enabled':enabled,
            'authorization_event_id':page['event_id']}
        owner,project,locale=page['user_id'],page['project_id'],page['locale']
        key=page['snapshot_id']; page_key=page.get('cursor') or ''; page_digest=digest(page)
        now=time.time()
        with self._transaction() as db:
            row=db.execute('SELECT * FROM private_draft_jobs WHERE source_key=?',(key,)).fetchone()
            if row:
                old_payload=json.loads(row['payload'])
                if (row['status']=='STALE' or any(field in old_payload for field in coverage_fields)!=inherited
                        or any(old_payload.get(field)!=metadata[field] for field in fields)):
                    raise ValueError('Private draft snapshot scope or policy changed')
                if old_payload != payload:
                    db.execute('UPDATE private_draft_jobs SET payload=?,milestone=? WHERE id=?',
                        (json.dumps(payload),(page['round_high_water']//cadence)*cadence,row['id']))
                    row=db.execute('SELECT * FROM private_draft_jobs WHERE id=?',(row['id'],)).fetchone()
                checkpoint=json.loads(row['checkpoint'])
                replay=db.execute('SELECT page_digest FROM private_draft_page_receipts WHERE job_id=? AND cursor_key=?',
                    (row['id'],page_key)).fetchone()
                if replay:
                    if replay['page_digest'] != page_digest:
                        raise ValueError('Private draft page replay conflict')
                    return self._page_view(dict(row),checkpoint)
                if checkpoint['complete'] or checkpoint['next_cursor'] != page.get('cursor'):
                    raise ValueError('Out of order private draft page')
                job_id=row['id']
            else:
                if page.get('cursor') is not None:
                    raise ValueError('Private draft first page required')
                state=db.execute('SELECT * FROM private_draft_page_state WHERE user_id=? AND project_id=?',
                    (owner,project)).fetchone()
                if state is None:
                    # One compatibility scan when upgrading a pre-coverage
                    # store. Subsequent receipts use this constant-sized fence.
                    previous=db.execute("SELECT payload FROM private_draft_jobs WHERE user_id=? AND project_id=? AND json_extract(payload,'$.protocol')='lifetime_draft_pages' ORDER BY source_epoch DESC,created_at DESC LIMIT 1",
                        (owner,project)).fetchone()
                    if previous:
                        prior=json.loads(previous['payload'])
                        state={'conversation_id':prior['conversation_id'],'policy_epoch':prior['policy_epoch'],
                            'preference_revision':prior['preference_revision'],'round_revision':prior.get('round_revision',0),'locale':prior['locale']}
                if state and (state['conversation_id']!=page['conversation_id'] or state['policy_epoch']>page['policy_epoch']
                        or state['preference_revision']>page['preference_revision'] or state['round_revision']>round_revision):
                    raise ValueError('Stale private draft identity, policy or preferences')
                if state and state['preference_revision']==page['preference_revision'] and state['locale']!=locale:
                    raise ValueError('Private draft locale conflicts with its preference revision')
                changed=state is None or any(state[field]!=value for field,value in (
                    ('policy_epoch',page['policy_epoch']),('preference_revision',page['preference_revision']),
                    ('round_revision',round_revision),('locale',locale)))
                if changed:
                    # Invalidation scales with policy changes, never with each
                    # appended turn or repeated receipt at the same generation.
                    db.execute("""UPDATE private_draft_jobs SET status='STALE',payload='{}',checkpoint='{}',lease_token=NULL,lease_until=NULL
                        WHERE user_id=? AND project_id=? AND status IN ('PAGING','BLOCKED','QUEUED','RUNNING')
                        AND (json_extract(payload,'$.protocol') IS NOT 'lifetime_draft_pages' OR source_epoch<>?
                          OR json_extract(payload,'$.preference_revision')<>? OR locale<>?
                          OR coalesce(json_extract(payload,'$.round_revision'),0)<>?)""",
                        (owner,project,page['policy_epoch'],page['preference_revision'],locale,round_revision))
                    db.execute('UPDATE private_draft_projects SET stale=1 WHERE user_id=? AND project_id=?',(owner,project))
                db.execute('INSERT INTO private_draft_page_state VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id,project_id) DO UPDATE SET policy_epoch=excluded.policy_epoch,preference_revision=excluded.preference_revision,round_revision=excluded.round_revision,locale=excluded.locale',
                    (owner,project,page['conversation_id'],page['policy_epoch'],page['preference_revision'],round_revision,locale))
                job_id=str(uuid4())
                checkpoint={'next_cursor':None,'complete':False,'page_count':0,'record_count':0,'digest':'',
                    'last_source_sequence':source_after,'last_source_offset':2147483647 if source_after else -1,
                    'last_round':round_after,'rounds_started':False}
                db.execute("""INSERT INTO private_draft_jobs(id,user_id,project_id,locale,source_key,source_epoch,milestone,payload,
                    status,phase,error,available_at,created_at) VALUES(?,?,?,?,?,?,?,?, 'PAGING','retrieving',NULL,?,?)""",
                    (job_id,owner,project,locale,key,page['policy_epoch'],(page['round_high_water']//cadence)*cadence,json.dumps(payload),now,now))
            for record in page['records']:
                if record['record_type']=='round':
                    if record['ordinal'] <= checkpoint['last_round']:
                        raise ValueError('Completed rounds must be strictly ordered')
                    checkpoint['last_round']=record['ordinal']
                    checkpoint['rounds_started']=True
                    existing=db.execute('SELECT ordinal FROM private_draft_rounds WHERE user_id=? AND project_id=? AND turn_id=?',
                        (owner,project,record['turn_id'])).fetchone()
                    if existing and existing['ordinal'] != record['ordinal']:
                        raise ValueError('Completed round identity conflict')
                    db.execute('INSERT INTO private_draft_rounds VALUES(?,?,?,?,?) ON CONFLICT(user_id,project_id,turn_id) DO UPDATE SET memory_id=excluded.memory_id',
                        (owner,project,record['turn_id'],record['ordinal'],record.get('memory_id')))
                else:
                    position=(record['sequence'],record['char_start'])
                    if checkpoint.get('rounds_started',bool(checkpoint['last_round'])) or position <= (checkpoint['last_source_sequence'],checkpoint['last_source_offset']):
                        raise ValueError('Canonical chunks must be strictly ordered')
                    if record['sequence'] > checkpoint['last_source_sequence']+1:
                        raise ValueError('Canonical source position coverage is incomplete')
                    checkpoint['last_source_sequence'],checkpoint['last_source_offset']=position
            if page['complete'] and (checkpoint['last_source_sequence'] != page['source_revision']
                    or checkpoint['last_round'] != page['round_high_water']):
                raise ValueError('Private draft high-water coverage is incomplete')
            checkpoint.update(next_cursor=page['next_cursor'],complete=page['complete'],
                page_count=checkpoint['page_count']+1,record_count=checkpoint['record_count']+len(page['records']),
                digest=digest([checkpoint['digest'],page_digest]))
            status='BLOCKED' if page['complete'] else 'PAGING'
            error='LIFETIME_COMPOSER_PENDING' if page['complete'] else None
            db.execute('INSERT INTO private_draft_page_receipts VALUES(?,?,?,?,?)',
                (job_id,page_key,page_digest,page['next_cursor'],len(page['records'])))
            db.execute('UPDATE private_draft_jobs SET checkpoint=?,status=?,error=?,phase=? WHERE id=?',
                (json.dumps(checkpoint),status,error,'composition_pending' if page['complete'] else 'retrieving',job_id))
            row=db.execute('SELECT * FROM private_draft_jobs WHERE id=?',(job_id,)).fetchone()
            return self._page_view(dict(row),checkpoint)

    @staticmethod
    def _page_view(row,checkpoint):
        payload=json.loads(row['payload'])
        return {'job_id':row['id'],'status':'pending','preview':None,'updating':False,
            'error':row['error'],'retrieval_complete':checkpoint['complete'],
            'next_cursor':checkpoint['next_cursor'],'page_count':checkpoint['page_count'],
            'record_count':checkpoint['record_count'],'snapshot_digest':checkpoint['digest'],
            'round_high_water':payload['round_high_water'],'milestone':row['milestone'],
            'source_after':payload.get('source_after',0),'round_after':payload.get('round_after',0),
            'base_snapshot_id':payload.get('base_snapshot_id')}

    def page_resume(self,event_id):
        with self._connect() as db:
            # Only bounded receipt metadata is loaded, never canonical content.
            row=db.execute("SELECT * FROM private_draft_jobs WHERE json_extract(payload,'$.authorization_event_id')=? AND status IN ('PAGING','BLOCKED') ORDER BY created_at DESC LIMIT 1",(event_id,)).fetchone()
            if not row:
                return None
            checkpoint=json.loads(row['checkpoint'])
            return {**self._page_view(dict(row),checkpoint),'complete':checkpoint['complete'],
                'snapshot_id':row['source_key']}

    def restart_page(self,event_id):
        """Discard only a receipt rejected by the authoritative scope fence."""
        with self._transaction() as db:
            db.execute("""UPDATE private_draft_jobs SET status='STALE',payload='{}',checkpoint='{}',
                lease_token=NULL,lease_until=NULL WHERE json_extract(payload,'$.authorization_event_id')=?
                AND json_extract(payload,'$.protocol')='lifetime_draft_pages'""",(event_id,))

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
