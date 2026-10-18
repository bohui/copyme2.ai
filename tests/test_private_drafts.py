import copy
from apps.api.private_draft_jobs import PrivateDraftJobs


def snapshot(n):
    rounds=[{'turn_id':str(i),'memory_id':f's{i}','ordinal':i} for i in range(1,n+1)]
    sources=[{'id':f's{i}','version':'1','project_id':'project','kind':'narrator_chat',
        'author_role':'storyteller','text':'Original memory','status':'active','allowed':True,'derived_from':[]} for i in range(1,n+1)]
    return rounds,sources


def sync(queue,n,**options):
    rounds,sources=snapshot(n)
    queue.synchronize('owner','project','en-AU',rounds,sources,completed=n,free_limit=options.pop('free_limit',20),cadence=options.pop('cadence',5),**options)


def bundle(job):
    request={'sources':copy.deepcopy(job['payload']['sources'])}
    return {'request':request,'draft':{'input_fingerprint':'f'},
            'manuscript':{'kind':'sample_chapter','chapters':[]},'preview':{'text':'Synthetic draft'}}


def test_stage_reassignment_fences_running_draft_and_indexes_old_response(tmp_path):
    from apps.api.memoir_preview import source_snapshot
    q=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    rounds,_=snapshot(5)
    rows=[{'id':f's{i}','kind':'agent','life_stage':'childhood','source_sequence':i,
           'content':f'Storyteller: Memory {i}\nMemory Spark: Reply'} for i in range(1,6)]
    sources=source_snapshot(rows,'project')
    q.synchronize('owner','project','en-AU',rounds,sources,completed=5,free_limit=20,cadence=5)
    first=q.claim(q.pending_ids()[0]);assert q.finish(first,result=bundle(first))
    # Queue a ten-round job, then reassign a much older response before save.
    new_rounds,_=snapshot(10)
    rows.extend({'id':f's{i}','kind':'agent','life_stage':'childhood','source_sequence':i,
                 'content':f'Storyteller: Memory {i}\nMemory Spark: Reply'} for i in range(6,11))
    q.synchronize('owner','project','en-AU',new_rounds,source_snapshot(rows,'project'),completed=10,free_limit=20,cadence=5)
    stale=q.claim(q.pending_ids()[0])
    rows[0]['life_stage']='midlife'
    q.synchronize('owner','project','en-AU',new_rounds,source_snapshot(rows,'project'),completed=10,free_limit=20,cadence=5)
    assert not q.finish(stale,result=bundle(stale))
    replacement=q.claim(q.pending_ids()[0])
    assert next(s for s in replacement['payload']['sources'] if s['id']=='s1')['life_stage']=='midlife'


def test_edit_delete_disable_policy_and_protected_revision_fence(tmp_path):
    q=PrivateDraftJobs(tmp_path/'jobs.sqlite'); sync(q,5)
    job=q.claim(q.pending_ids()[0]); q.checkpoint(job['id'],job['lease_token'],'drafting',{'private':'fixture'})
    rounds,sources=snapshot(5); sources[0]['version']='2'; sources[0]['text']='Correction'
    q.synchronize('owner','project','en-AU',rounds,sources,completed=5,free_limit=20,cadence=5)
    assert not q.finish(job,result=bundle(job))
    with q._connect() as db:
        old=db.execute('SELECT checkpoint,payload FROM private_draft_jobs WHERE id=?',(job['id'],)).fetchone()
        assert old['checkpoint']=='{}' and old['payload']=='{}'
    current=q.claim(q.pending_ids()[0]); assert q.finish(current,result=bundle(current))
    q.protect('owner','project','en-AU',1)
    sync(q,10); update=q.claim(q.pending_ids()[0]); assert update['human_locked']
    assert q.finish(update,result=bundle(update))
    with q._connect() as db:
        row=db.execute('SELECT revision,proposal,draft FROM private_draft_projects').fetchone()
        assert row['revision']==2 and row['proposal'] and row['draft']
    # A deletion hides the old saved revision and fences all queued work.
    sources=sources[1:]
    view=q.synchronize('owner','project','en-AU',rounds,sources,completed=10,free_limit=20,cadence=5,enabled=False)
    assert view['preview'] is None and not view['updating']


def test_restart_checkpoint_terminal_offline_and_explicit_retry(tmp_path):
    path=tmp_path/'jobs.sqlite'; q=PrivateDraftJobs(path); sync(q,5)
    job=q.claim(q.pending_ids()[0]); q.checkpoint(job['id'],job['lease_token'],'reviewing',{'draft':'validated'})
    with q._transaction() as db:
        db.execute('UPDATE private_draft_jobs SET lease_until=0')
    resumed=PrivateDraftJobs(path).claim(job['id'])
    assert resumed['checkpoint']=={'draft':'validated'}
    q.finish(resumed,error='DRAFT_PROVIDER_UNAVAILABLE',retryable=False)
    sync(q,5); assert not q.pending_ids()
    q.retry('other','project','en-AU'); assert not q.pending_ids()
    q.retry('owner','project','en-AU'); assert q.pending_ids()==[job['id']]


def test_revocation_prunes_sources_and_reauthorization_can_start_again(tmp_path):
    q=PrivateDraftJobs(tmp_path/'jobs.sqlite');sync(q,5)
    job=q.claim(q.pending_ids()[0]);q.checkpoint(job['id'],job['lease_token'],'drafting',{'source':'private fixture'})
    q.revoke(job['id'])
    assert not q.finish(job,result=bundle(job))
    with q._connect() as db:
        assert db.execute('select payload from private_draft_projects').fetchone()[0]=='{}'
        assert db.execute('select checkpoint from private_draft_jobs').fetchone()[0]=='{}'
    sync(q,5)
    assert len(q.pending_ids())==1


def test_transient_failure_is_bounded_and_resumes_checkpoint(tmp_path):
    q=PrivateDraftJobs(tmp_path/'jobs.sqlite');sync(q,5);job_id=q.pending_ids()[0]
    for attempt in range(3):
        job=q.claim(job_id)
        if attempt: assert job['checkpoint']=={'validated':'fixture'}
        q.checkpoint(job_id,job['lease_token'],'reviewing',{'validated':'fixture'})
        q.finish(job,error='DRAFT_UNAVAILABLE',retryable=True)
        with q._transaction() as db:db.execute('update private_draft_jobs set available_at=0')
    assert q.status(job_id)=='FAILED' and not q.pending_ids()


def test_saved_private_sample_projects_clean_reader_text_without_changing_revision(tmp_path):
    q = PrivateDraftJobs(tmp_path/'jobs.sqlite')
    sync(q,5); job = q.claim(q.pending_ids()[0])
    saved = bundle(job)
    saved['preview'] = {'kind': 'sample_storyline', 'title': 'Sample', 'text': 'Sample\n\nBody'}
    saved['draft']['storyline'] = {'blocks': [{'type': 'heading', 'text': 'Sample'}, {'type': 'paragraph', 'text': 'Body'}]}
    assert q.finish(job,result=saved)
    rounds,sources = snapshot(5)
    view = q.synchronize('owner','project','en-AU',rounds,sources,completed=5,free_limit=20,cadence=5)
    assert view['preview']['text'] == 'Body'
    assert view['revision'] == 1
    with q._connect() as db:
        import json
        stored = json.loads(db.execute('SELECT draft FROM private_draft_projects').fetchone()[0])
        assert stored == saved
