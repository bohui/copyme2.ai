import copy
from apps.api.private_draft_jobs import PrivateDraftJobs
from apps.api.private_drafts import request_for_job


def snapshot(n):
    rounds=[{'turn_id':str(i),'memory_id':f's{i}','ordinal':i} for i in range(1,n+1)]
    sources=[{'id':f's{i}','version':'1','project_id':'project','kind':'narrator_chat',
        'author_role':'storyteller','text':'Original memory','status':'active','allowed':True,'derived_from':[]} for i in range(1,n+1)]
    return rounds,sources


def sync(queue,n,**options):
    rounds,sources=snapshot(n)
    queue.synchronize('owner','project','en-AU',rounds,sources,completed=n,free_limit=options.pop('free_limit',20),cadence=options.pop('cadence',5),**options)


def bundle(job):
    request,_=request_for_job(job)
    return {'request':request,'draft':{'input_fingerprint':'f'},
            'manuscript':{'kind':'sample_chapter','chapters':[]},'preview':{'text':'Synthetic draft'}}


def test_exact_milestones_dedup_background_concurrency_and_incremental_context(tmp_path):
    q=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    sync(q,4); assert not q.pending_ids()
    sync(q,5); id=q.pending_ids()[0]; first=q.claim(id)
    sync(q,5); sync(q,6); assert q.pending_ids()==[id]
    sync(q,10); ids=q.pending_ids(); assert len(ids)==2
    second_id=next(i for i in ids if i!=id)
    assert q.claim(second_id) is None
    # Additional interview rounds don't invalidate an unchanged snapshot.
    assert q.finish(first,result=bundle(first))
    second=q.claim(second_id)
    request,index=request_for_job(second)
    assert request['trigger']['type']=='new_context'
    assert request['trigger']['free_rounds_completed']==10
    assert request['trigger']['free_round_limit']==20
    assert request['prior_state']['revision']==1
    assert request['context']['new_source_ids']==['s6','s7','s8','s9','s10']
    assert request['context']['overlap_source_ids']==['s4','s5']
    assert [s['id'] for s in index['sources']]==['s4','s5','s6','s7','s8','s9','s10']


def test_incremental_draft_and_review_packets_keep_only_changed_evidence(tmp_path):
    from apps.api.memoir_preview import incremental_model_request

    q=PrivateDraftJobs(tmp_path/'jobs.sqlite')
    sync(q,5)
    first=q.claim(q.pending_ids()[0])
    assert q.finish(first,result=bundle(first))
    sync(q,10)
    job=q.claim(q.pending_ids()[0])
    request,_=request_for_job(job)
    compact=incremental_model_request(request)
    assert compact is not request
    assert [source['id'] for source in compact['sources']]==['s4','s5','s6','s7','s8','s9','s10']
    assert compact['context']['canonical_source_count']==10
    assert len(compact['context']['canonical_source_manifest'])==10
    assert compact['context']['dirty_chapter_ids']==[]
    assert compact['context']['carry_forward_chapter_ids']==[]
    assert compact['prior_state']['revision']==1
    # The complete request is still available to host-side validation and
    # persistence; the model packet is the only bounded projection.
    assert [source['id'] for source in request['sources']]==[f's{i}' for i in range(1,11)]


def test_old_edits_and_deletions_reindex_dependencies_without_rescanning_history(tmp_path):
    q=PrivateDraftJobs(tmp_path/'jobs.sqlite');sync(q,10)
    first=q.claim(q.pending_ids()[0]);saved=bundle(first)
    ref=lambda id:{'source_id':id,'version':'1'}
    saved['request']['periods']=[{'id':'p1','source_refs':[ref('s1'),ref('s2')]},
                               {'id':'p2','source_refs':[ref('s4')]}]
    saved['request']['events']=[{'id':'e1','period_id':'p1','source_refs':[ref('s3')]},
                              {'id':'e2','period_id':'p2','source_refs':[ref('s4')]}]
    assert q.finish(first,result=saved)
    rounds,sources=snapshot(10)
    sources[0].update(version='2',life_stage='midlife',text='Corrected original memory')
    sources=[s for s in sources if s['id']!='s5']
    q.synchronize('owner','project','en-AU',rounds,sources,completed=10,free_limit=20,cadence=5)
    request,index=request_for_job(q.claim(q.pending_ids()[0]))
    assert request['context']['new_source_ids']==[]
    assert request['context']['changed_source_ids']==['s1']
    assert request['context']['removed_source_ids']==['s5']
    assert [s['id'] for s in index['sources']]==['s1','s2','s3','s9','s10']
    assert [p['id'] for p in request['periods']]==['p2']
    assert [e['id'] for e in request['events']]==['e2']
    assert [p['id'] for p in index['context']['invalidated_index']['periods']]==['p1']
    assert [e['id'] for e in index['context']['invalidated_index']['events']]==['e1']
    assert index['context']['stage_source_ids']['midlife']==['s1']
    assert len(request['sources'])==9  # Full originals retained for evidence review.


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
    request,index=request_for_job(q.claim(q.pending_ids()[0]))
    assert request['context']['changed_source_ids']==['s1']
    assert [s['id'] for s in index['sources']]==['s4','s5','s6','s7','s8','s9','s10','s1']
    assert index['context']['stage_source_ids']['midlife']==['s1']


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


def test_configurable_allowance_is_independent_of_cadence_and_truthful(tmp_path):
    q=PrivateDraftJobs(tmp_path/'jobs.sqlite'); sync(q,2,free_limit=7,cadence=3); assert not q.pending_ids()
    sync(q,3,free_limit=7,cadence=3); job=q.claim(q.pending_ids()[0])
    request,_=request_for_job(job)
    assert request['trigger']['type']=='private_draft_checkpoint'
    assert request['trigger']['free_rounds_completed']==3
    assert request['trigger']['free_round_limit']==7
    assert request['trigger']['private_draft_cadence']==3
    assert request['trigger']['composition_authorized'] is False


def test_first_private_draft_executes_real_validation_and_rendering_with_truthful_quota(tmp_path,monkeypatch):
    import asyncio
    from test_memoir_preview import fixture_storage,model_fixture
    from apps.api.memoir_preview import source_snapshot
    from apps.api.private_drafts import execute
    async def authorized(job_id): pass
    monkeypatch.setattr('apps.api.private_drafts.validate_job',authorized)
    path=tmp_path/'jobs.sqlite';monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path))
    storage,_=fixture_storage();calls=model_fixture(monkeypatch)
    sources=source_snapshot(storage._memories,'project-preview')
    rounds=[{'turn_id':str(i),'ordinal':i,'memory_id':sources[i-1]['id'] if i<=len(sources) else None} for i in range(1,6)]
    q=PrivateDraftJobs(path)
    q.synchronize(storage.user_id,'project-preview','en-AU',rounds,sources,completed=5,free_limit=20,cadence=5)
    assert asyncio.run(execute(q.pending_ids()[0]))['status']=='saved'
    view=q.synchronize(storage.user_id,'project-preview','en-AU',rounds,sources,completed=5,free_limit=20,cadence=5)
    assert view['preview']['text'] and view['milestone']==5 and view['revision']==1
    assert calls==['index','draft','review']
    with q._connect() as db:
        import json
        saved=json.loads(db.execute('SELECT draft FROM private_draft_projects').fetchone()[0])
        assert saved['request']['trigger']['free_rounds_completed']==5
        assert saved['request']['trigger']['free_round_limit']==20
        assert saved['manuscript']['publication_authorized'] is False


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
