"""Real isolated PostgreSQL W5 atomic outbox/fence and artifact contracts."""
import json
from copy import deepcopy
from uuid import UUID

import pytest

from test_agent_commit_postgres import database, as_user, OWNER, OTHER, OLD, NEW
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, rpc, literal
from test_lifetime_memory_postgres import resolve
from apps.api.lifetime_memory_artifacts import ArtifactFile, upload_incremental
from apps.api.lifetime_memory_outbox import artifact_manifest_bytes


@pytest.fixture
def sql(event_database):
    event_database('truncate public.user_memoir_project cascade;')
    event_database('truncate public.user_memory,public.user_agent_turn_lease,public.user_agent_session,public.user_profile,public.user_recall_usage cascade;')
    event_database('update auth.users set is_anonymous=false;')
    return event_database


def setup(sql):
    identity=resolve(sql)
    source=rpc(sql,'accept_user_interview_turn',f"{literal(identity['project_id'])},'{UUID(int=1)}','Original exact wording','narrator_chat','en-AU'")['source']
    rpc(sql,'acquire_user_agent_turn_lease',f"'{OLD}'")
    return identity,source,current(sql,identity)



def save_reply(sql,source,fence):
    from test_interview_work_plan_postgres import plan
    value=plan(mode='extract',name=None)
    return rpc(sql,'commit_lifetime_turn',f"{literal(fence)}::jsonb,'{source['client_turn_id']}',{literal(value)}::jsonb,'[]','Tell me more.','[]','thread','lifetime-v1','fixture-model'")


def current(sql,identity,token=OLD):
    return rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{token}'")


def claim(sql,fence):return rpc(sql,'claim_lifetime_memory_obligation',f'{literal(fence)}::jsonb')

def complete(sql,fence,job,**kwargs):
    return rpc(sql,'complete_lifetime_memory_obligation',f"{literal(fence)}::jsonb,'{job['id']}','{job['claim_token']}'",**kwargs)


def test_source_and_reply_commit_enqueue_once_with_unchanged_receipts_and_counters(sql):
    identity,source,fence=setup(sql)
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{UUID(int=1)}','Original exact wording'")
    assert sql('select count(*) from public.user_lifetime_memory_obligation;').stdout.strip()=='1'
    first=save_reply(sql,source,fence)
    assert save_reply(sql,source,first['fence'])['memory']==first['memory']
    assert sql('select count(*) from public.user_lifetime_memory_obligation;').stdout.strip()=='2'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'
    job=claim(sql,current(sql,identity));done=complete(sql,current(sql,identity),job)
    assert done['status']=='succeeded' and done['backup_complete'] is False
    assert done['projection']['sources']==[{'source_id':source['id'],'version':1,'char_start':0,'char_end':22}]
    assert 'Original exact wording' not in json.dumps(done)


def test_enqueue_rolls_back_with_canonical_acceptance_and_failed_commit(sql):
    identity=resolve(sql)
    query=f"begin; {as_user(f'select public.accept_user_narrator_source({literal(identity["project_id"])},\'{UUID(int=2)}\',\'Rolled back\');')} rollback;"
    sql(query)
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_memory_obligation;').stdout.strip()=='0'


def test_claim_crash_retries_bounded_backoff_and_failure_is_inspectable(sql):
    identity,source,fence=setup(sql);one=claim(sql,fence)
    assert one['attempts']==1
    assert claim(sql,fence)['status']=='not_ready'
    sql("update public.user_lifetime_memory_obligation set claim_expires_at=clock_timestamp()-interval '1 second';")
    two=claim(sql,fence)
    assert two['id']==one['id'] and two['claim_token']!=one['claim_token'] and two['attempts']==2
    assert complete(sql,fence,one,check=False).returncode!=0
    args=f"{literal(fence)}::jsonb,'{two['id']}','{two['claim_token']}','storage_unavailable'"
    failed=rpc(sql,'fail_lifetime_memory_obligation',args)
    assert failed['status']=='retryable' and failed['backup_complete'] is False
    assert claim(sql,fence)['status']=='not_ready'
    for attempt in range(3,6):
        sql("update public.user_lifetime_memory_obligation set next_attempt_at=clock_timestamp()-interval '1 second';")
        job=claim(sql,fence);assert job['attempts']==attempt
        failed=rpc(sql,'fail_lifetime_memory_obligation',f"{literal(fence)}::jsonb,'{job['id']}','{job['claim_token']}','projection_failed'")
    assert failed['status']=='failed'
    page=rpc(sql,'read_lifetime_memory_obligations',f"'{identity['conversation_id']}'")
    assert page['records'][0]['status']=='failed' and page['records'][0]['error_code']=='projection_failed'
    assert claim(sql,fence)['status']=='not_ready'


def test_owner_project_source_and_lease_fences_reject_stale_completion(sql):
    identity,source,fence=setup(sql);job=claim(sql,fence)
    assert complete(sql,fence,job,owner=OTHER,check=False).returncode!=0
    forged=deepcopy(fence);forged['identity']['project_id']='arbitrary'
    assert complete(sql,forged,job,check=False).returncode!=0
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{UUID(int=2)}','A later fact'")
    assert complete(sql,fence,job,check=False).returncode!=0
    assert complete(sql,current(sql,identity),job,check=False).returncode!=0
    sql("update public.user_agent_turn_lease set expires_at=clock_timestamp()-interval '1 second';")
    assert complete(sql,fence,job,check=False).returncode!=0
    rpc(sql,'acquire_user_agent_turn_lease',f"'{NEW}'")
    assert complete(sql,current(sql,identity,NEW),job,check=False).returncode!=0


def test_policy_invalidation_revokes_links_and_old_claims_without_deleting_objects(sql):
    identity,source,fence=setup(sql);job=claim(sql,fence);complete(sql,fence,job)
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{source['id']}',1,'withdraw',null")
    saved=json.loads(sql(f"select to_jsonb(o) from public.user_lifetime_memory_obligation o where id='{job['id']}';").stdout)
    assert saved['status']=='superseded' and saved['projection'] is None
    assert complete(sql,fence,job,check=False).returncode!=0
    new_fence=current(sql,identity);new_job=claim(sql,new_fence)
    assert new_job['policy_epoch']==2
    assert complete(sql,new_fence,new_job)['projection']['sources']==[]


def test_required_outbox_rls_bounded_inspection_and_cancellation(sql):
    identity,source,fence=setup(sql);job=claim(sql,fence)
    assert sql(as_user('select * from public.user_lifetime_memory_obligation;'),check=False).returncode!=0
    assert rpc(sql,'read_lifetime_memory_obligations',f"'{identity['conversation_id']}'",owner=OTHER,check=False).returncode!=0
    assert rpc(sql,'read_lifetime_memory_obligations',f"'{identity['conversation_id']}',null,33",check=False).returncode!=0
    result=rpc(sql,'cancel_lifetime_memory_obligation',f"{literal(fence)}::jsonb,'{job['id']}'")
    assert result['status']=='cancelled'
    assert complete(sql,fence,job,check=False).returncode!=0


def test_optional_artifact_requires_explicit_auth_persisted_predecessor_and_current_fence(sql):
    identity,source,fence=setup(sql)
    objects={}
    def put(key,data):
        absent=key not in objects;objects[key]=data;return absent
    scope=dict(conversation_id=identity['conversation_id'],policy_epoch=1,execution_generation=1)
    candidate=upload_incremental(OWNER,[ArtifactFile('sessions/a',b'opaque',True)],put,**scope)
    wire=artifact_manifest_bytes(candidate).decode()
    args=f"{literal(fence)}::jsonb,{literal(candidate['manifest_id'])},{literal(wire)}"
    assert rpc(sql,'link_lifetime_optional_artifact',args,check=False).returncode!=0
    linked=rpc(sql,'link_lifetime_optional_artifact',args+',true')
    assert linked['backup_complete'] is False and linked['optional'] is True
    repeated=upload_incremental(OWNER,[ArtifactFile('sessions/a',b'opaque',True)],put,previous=candidate,**scope)
    assert artifact_manifest_bytes(repeated) is None
    assert rpc(sql,'link_lifetime_optional_artifact',f"{literal(fence)}::jsonb,{literal(repeated['manifest_id'])},null,true")==linked
    assert rpc(sql,'link_lifetime_optional_artifact',f"{literal(fence)}::jsonb,{'0' * 64!r},null,true",check=False).returncode!=0
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{source['id']}',1,'withdraw',null")
    assert sql('select count(*) from public.user_lifetime_optional_artifact where linked;').stdout.strip()=='0'
    for table in ('head','file','chunk'):
        assert sql(f'select count(*) from public.user_lifetime_artifact_{table};').stdout.strip()=='0'
        assert sql(as_user(f'select * from public.user_lifetime_artifact_{table};'),check=False).returncode!=0
    assert len(objects)==1
    assert rpc(sql,'link_lifetime_optional_artifact',args+',true',check=False).returncode!=0


def test_optional_artifact_rejects_cross_tenant_chunks_unverified_digest_and_incomplete_success(sql):
    identity,source,fence=setup(sql)
    candidate=upload_incremental(OWNER,[ArtifactFile('sessions/a',b'opaque',True)],lambda *a:True,
        conversation_id=identity['conversation_id'],policy_epoch=1,execution_generation=1)
    manifest=json.loads(artifact_manifest_bytes(candidate));manifest['files'][0]['chunks'][0]['key']=f'{OTHER}/agent/chunks/v1/'+('a'*64)
    from hashlib import sha256
    wire=json.dumps(manifest,sort_keys=True,separators=(',',':'));digest=sha256(wire.encode()).hexdigest()
    args=f"{literal(fence)}::jsonb,{literal(digest)},{literal(wire)},true"
    assert rpc(sql,'link_lifetime_optional_artifact',args,check=False).returncode!=0


def test_concurrent_claims_have_one_live_holder_and_completion_replays(sql):
    from concurrent.futures import ThreadPoolExecutor
    identity,source,fence=setup(sql)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims=list(pool.map(lambda _:claim(sql,fence),range(2)))
    assert sorted(c['status'] for c in claims)==['not_ready','running']
    winner=next(c for c in claims if c['status']=='running')
    first=complete(sql,fence,winner)
    assert complete(sql,fence,winner)==first
    assert claim(sql,fence) is None


def test_inspection_cursor_is_scoped_and_created_order_is_stable(sql):
    identity,source,fence=setup(sql)
    for i in range(2,5):rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{UUID(int=i)}','Next {i}'")
    seen=[];cursor=None
    while True:
        page=rpc(sql,'read_lifetime_memory_obligations',f"'{identity['conversation_id']}',{literal(cursor)+'::uuid' if cursor else 'null'},2")
        seen.extend(row['origin_id'] for row in page['records'])
        if page['complete']:break
        cursor=page['next_cursor']
    assert len(set(seen))==4 and seen[0]==source['id']
    assert rpc(sql,'read_lifetime_memory_obligations',f"'{identity['conversation_id']}','{UUID(int=999)}'",check=False).returncode!=0


def test_retries_exhaust_after_crashes_and_inspection_never_returns_private_bytes(sql):
    identity,source,fence=setup(sql)
    for attempt in range(1,6):
        job=claim(sql,fence);assert job['attempts']==attempt
        sql("update public.user_lifetime_memory_obligation set claim_expires_at=clock_timestamp()-interval '1 second';")
    assert claim(sql,fence)['status']=='not_ready'
    page=rpc(sql,'read_lifetime_memory_obligations',f"'{identity['conversation_id']}'")
    assert page['records'][0]['status']=='failed' and page['records'][0]['error_code']=='retry_exhausted'
    assert 'Original exact wording' not in json.dumps(page)


def test_optional_incomplete_manifest_is_explicit_and_cannot_claim_a_complete_backup(sql):
    identity,source,fence=setup(sql)
    candidate=upload_incremental(OWNER,[ArtifactFile('sessions/a',b'private',False)],lambda *a:True,
        conversation_id=identity['conversation_id'],policy_epoch=1,execution_generation=1)
    wire=artifact_manifest_bytes(candidate).decode()
    result=rpc(sql,'link_lifetime_optional_artifact',f"{literal(fence)}::jsonb,{literal(candidate['manifest_id'])},{literal(wire)},true")
    assert result['manifest_complete'] is False and result['backup_complete'] is False


def test_unchanged_and_delta_artifacts_reuse_authorized_predecessor_across_source_revisions(sql):
    identity,source,fence=setup(sql)
    objects={}
    def put(key,data):
        absent=key not in objects;objects[key]=data;return absent
    scope=dict(conversation_id=identity['conversation_id'],policy_epoch=1,execution_generation=1,chunk_bytes=4)
    first=upload_incremental(OWNER,[ArtifactFile('sessions/a',b'abcdabcd',True)],put,**scope)
    rpc(sql,'link_lifetime_optional_artifact',f"{literal(fence)}::jsonb,{literal(first['manifest_id'])},{literal(artifact_manifest_bytes(first).decode())},true")
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{UUID(int=2)}','Another memory'")
    fresh=current(sql,identity)
    unchanged=upload_incremental(OWNER,[ArtifactFile('sessions/a',b'abcdabcd',True)],put,previous=first,**scope)
    assert unchanged['manifest_bytes']==0 and unchanged['uploaded_content_bytes']==0
    assert rpc(sql,'link_lifetime_optional_artifact',f"{literal(fresh)}::jsonb,{literal(unchanged['manifest_id'])},null,true")['status']=='linked'
    changed=upload_incremental(OWNER,[ArtifactFile('sessions/a',b'abcdefgh',True)],put,previous=unchanged,**scope)
    assert len(changed['files'][0]['chunks'])==1 and changed['uploaded_content_bytes']==4
    assert rpc(sql,'link_lifetime_optional_artifact',f"{literal(fresh)}::jsonb,{literal(changed['manifest_id'])},{literal(artifact_manifest_bytes(changed).decode())},true")['status']=='linked'
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{source['id']}',1,'withdraw',null")
    assert rpc(sql,'link_lifetime_optional_artifact',f"{literal(current(sql,identity))}::jsonb,{literal(first['manifest_id'])},null,true",check=False).returncode!=0


def artifact_fixture(sql,content=b'abcdefghijkl',*,previous=None):
    identity=resolve(sql)
    scope=dict(conversation_id=identity['conversation_id'],policy_epoch=1,execution_generation=1,chunk_bytes=4)
    return upload_incremental(OWNER,[ArtifactFile('sessions/a',content,True)],lambda *a:True,previous=previous,**scope)


def link_wire(sql,fence,manifest,*,check=True):
    from hashlib import sha256
    wire=json.dumps(manifest,sort_keys=True,separators=(',',':'))
    return rpc(sql,'link_lifetime_optional_artifact',f"{literal(fence)}::jsonb,{literal(sha256(wire.encode()).hexdigest())},{literal(wire)},true",check=check)


@pytest.mark.parametrize('defect',['missing','gap','overlap','duplicate_chunk','duplicate_file','duplicate_removal','remove_and_replace'])
def test_optional_complete_manifest_rejects_invalid_effective_coverage(sql,defect):
    identity,source,fence=setup(sql)
    candidate=artifact_fixture(sql);manifest=json.loads(artifact_manifest_bytes(candidate))
    if defect=='missing':manifest['files'][0]['chunks']=[]
    elif defect=='gap':manifest['files'][0]['chunks'].pop(1)
    elif defect=='overlap':manifest['files'][0]['chunks'][1]['offset']=3
    elif defect=='duplicate_chunk':manifest['files'][0]['chunks'].append(deepcopy(manifest['files'][0]['chunks'][0]))
    elif defect=='duplicate_file':manifest['files'].append(deepcopy(manifest['files'][0]))
    elif defect=='duplicate_removal':manifest['removed_paths']=['sessions/deleted','sessions/deleted']
    else:manifest['removed_paths']=['sessions/a']
    assert link_wire(sql,fence,manifest,check=False).returncode!=0
    assert sql('select count(*) from public.user_lifetime_optional_artifact;').stdout.strip()=='0'


def test_delta_truncation_reconstructs_exact_coverage_and_rejects_boundary_loss(sql):
    identity,source,fence=setup(sql)
    first=artifact_fixture(sql);link_wire(sql,fence,json.loads(artifact_manifest_bytes(first)))
    # Dropping the final chunk on an exact boundary is a valid no-content delta.
    shorter=artifact_fixture(sql,b'abcdefgh',previous=first)
    assert shorter['files'][0]['chunks']==[]
    assert link_wire(sql,fence,json.loads(artifact_manifest_bytes(shorter)))['manifest_complete'] is True
    # A partial chunk must be replaced by its exact shorter content chunk.
    partial=artifact_fixture(sql,b'abcdef',previous=shorter)
    bad=json.loads(artifact_manifest_bytes(partial));bad['files'][0]['chunks']=[]
    assert link_wire(sql,fence,bad,check=False).returncode!=0
    assert link_wire(sql,fence,json.loads(artifact_manifest_bytes(partial)))['manifest_complete'] is True
    state=json.loads(sql("select jsonb_agg(jsonb_build_object('offset',chunk_offset,'bytes',byte_count) order by chunk_offset) from public.user_lifetime_artifact_chunk;").stdout)
    assert state==[{'offset':0,'bytes':4},{'offset':4,'bytes':2}]
    assert sql('select byte_count from public.user_lifetime_artifact_file;').stdout.strip()=='6'


def test_delta_gap_overlap_and_stale_predecessor_cannot_corrupt_current_chunks(sql):
    identity,source,fence=setup(sql)
    first=artifact_fixture(sql);link_wire(sql,fence,json.loads(artifact_manifest_bytes(first)))
    changed=artifact_fixture(sql,b'abcdXXXXijkl',previous=first)
    valid=json.loads(artifact_manifest_bytes(changed))
    for offset in (3,5):
        invalid=deepcopy(valid);invalid['files'][0]['chunks'][0]['offset']=offset
        assert link_wire(sql,fence,invalid,check=False).returncode!=0
    assert link_wire(sql,fence,valid)['manifest_complete'] is True
    stale=artifact_fixture(sql,b'YYYYefghijkl',previous=first)
    assert link_wire(sql,fence,json.loads(artifact_manifest_bytes(stale)),check=False).returncode!=0
    assert sql('select count(*) from public.user_lifetime_artifact_chunk;').stdout.strip()=='3'


def test_current_chunk_metadata_is_not_copied_into_every_delta_and_removals_revoke_it(sql):
    identity,source,fence=setup(sql)
    previous=None;total_wire=0
    for turn in range(32):
        candidate=artifact_fixture(sql,b'abcd'*(turn+1),previous=previous)
        wire=artifact_manifest_bytes(candidate);total_wire+=len(wire)
        link_wire(sql,fence,json.loads(wire));previous=candidate
    assert sql('select count(*) from public.user_lifetime_artifact_chunk;').stdout.strip()=='32'
    stored=int(sql('select sum(octet_length(manifest_wire)) from public.user_lifetime_optional_artifact;').stdout.strip())
    assert stored==total_wire and stored<32*1200
    removed=upload_incremental(OWNER,[],lambda *a:True,conversation_id=identity['conversation_id'],policy_epoch=1,execution_generation=1,chunk_bytes=4,previous=previous)
    assert link_wire(sql,fence,json.loads(artifact_manifest_bytes(removed)))['manifest_complete'] is True
    assert sql('select count(*) from public.user_lifetime_artifact_chunk;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_artifact_file;').stdout.strip()=='0'


def test_10000_delta_manifests_retain_only_linear_current_chunk_metadata(sql):
    """Synthetic metadata, no object upload/provider; uploader byte test is separate."""
    identity,source,fence=setup(sql)
    sql(as_user(f"""
      set statement_timeout='90s';
      do $fixture$
      declare snapshot jsonb:={literal(fence)}::jsonb; manifest jsonb; wire text;
        predecessor text:=null; manifest_id text; fingerprint text; turn integer;
      begin
        for turn in 1..10000 loop
          fingerprint:=encode(sha256(convert_to('synthetic-chunk-'||turn,'UTF8')),'hex');
          manifest:=jsonb_build_object('schema_version',3,'owner_id','{OWNER}',
            'conversation_id','{identity['conversation_id']}','policy_epoch',1,'execution_generation',1,
            'snapshot_semantics','full_authorized_snapshot','complete',true,'canonical_recovery_required',false,
            'status','unlinked_candidate','predecessor',predecessor,'removed_paths','[]'::jsonb,'omissions','[]'::jsonb,
            'files',jsonb_build_array(jsonb_build_object('path','sessions/growing','bytes',turn*4,
              'chunks',jsonb_build_array(jsonb_build_object('offset',((turn-1)/16)*64,'bytes',((turn-1)%16+1)*4,
                'key','{OWNER}/agent/chunks/v1/'||fingerprint,'sha256',fingerprint)))));
          wire:=manifest::text;manifest_id:=encode(sha256(convert_to(wire,'UTF8')),'hex');
          perform public.link_lifetime_optional_artifact(snapshot,manifest_id,wire,true);
          predecessor:=manifest_id;
        end loop;
      end $fixture$;
    """))
    counters=json.loads(sql("""select jsonb_build_object(
      'manifests',(select count(*) from public.user_lifetime_optional_artifact),
      'manifest_bytes',(select sum(octet_length(manifest_wire)) from public.user_lifetime_optional_artifact),
      'current_files',(select count(*) from public.user_lifetime_artifact_file),
      'current_chunks',(select count(*) from public.user_lifetime_artifact_chunk),
      'logical_bytes',(select sum(byte_count) from public.user_lifetime_artifact_chunk),
      'current_chunk_row_bytes',(select sum(pg_column_size(c)) from public.user_lifetime_artifact_chunk c));""").stdout)
    assert counters['manifests']==10000 and counters['manifest_bytes']<10000*1200
    assert counters['current_files']==1 and counters['current_chunks']==625 and counters['logical_bytes']==40000
    assert counters['current_chunk_row_bytes']<625*400
    print('W5 10000-turn normalized metadata counters:',json.dumps(counters,sort_keys=True))


def test_old_full_manifest_retry_cannot_restore_a_removed_path(sql):
    identity,source,fence=setup(sql)
    first=artifact_fixture(sql);first_manifest=json.loads(artifact_manifest_bytes(first))
    link_wire(sql,fence,first_manifest)
    removed=upload_incremental(OWNER,[],lambda *a:True,conversation_id=identity['conversation_id'],policy_epoch=1,execution_generation=1,chunk_bytes=4,previous=first)
    link_wire(sql,fence,json.loads(artifact_manifest_bytes(removed)))
    assert link_wire(sql,fence,first_manifest,check=False).returncode!=0
    assert sql('select manifest_id from public.user_lifetime_artifact_head;').stdout.strip()==removed['manifest_id']
    assert sql('select count(*) from public.user_lifetime_artifact_chunk;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_artifact_file;').stdout.strip()=='0'
