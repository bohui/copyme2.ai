"""Bounded W5 adapter contracts; persistence is exercised separately on real PG."""
from copy import deepcopy
from uuid import UUID
import json

import pytest

from apps.api.lifetime_memory_artifacts import ArtifactFile, upload_incremental
from apps.api.lifetime_memory_outbox import LifetimeMemoryOutbox, artifact_manifest_bytes


def fence():
    return {'schema_version':1,'identity':{'schema_version':1,'owner_id':str(UUID(int=1)),
        'conversation_id':str(UUID(int=2)),'project_id':'project','product':'memoir'},
        'policy_epoch':1,'source_revision':1,'execution_generation':1,'phase_revision':0,
        'preference_revision':0,'lease_token':str(UUID(int=3))}


def test_adapter_drains_bounded_required_work_without_changing_receipts():
    calls=[]
    def rpc(name, **kwargs):
        calls.append((name,kwargs))
        if name=='claim_lifetime_memory_obligation':
            return {'id':str(UUID(int=len(calls)+10)),'claim_token':str(UUID(int=4))}
        return {'status':'succeeded','canonical_recovery_required':False}
    receipt={'source_accepted':True,'conversation_saved':True}
    before=deepcopy(receipt)
    result=LifetimeMemoryOutbox(rpc).drain(fence(),limit=2)
    assert result=={'processed':2,'failed':0,'pending':True,'backup_complete':False}
    assert len(calls)==4 and receipt==before
    assert all(name in {'claim_lifetime_memory_obligation','complete_lifetime_memory_obligation'} for name,_ in calls)


def test_failed_work_is_visible_and_does_not_claim_backup_success():
    calls=[]
    def rpc(name, **kwargs):
        calls.append((name,kwargs))
        if name=='claim_lifetime_memory_obligation':return {'id':str(UUID(int=10)),'claim_token':str(UUID(int=4))}
        if name=='complete_lifetime_memory_obligation':raise RuntimeError('private raw provider details')
        return {'status':'retryable'}
    result=LifetimeMemoryOutbox(rpc).drain(fence(),limit=1)
    assert result['failed']==1 and result['backup_complete'] is False and result['pending']
    assert calls[-1][0]=='fail_lifetime_memory_obligation'
    assert calls[-1][1]['p_error_code']=='projection_failed'
    assert 'private raw' not in json.dumps(calls)


def test_invalid_bounds_and_fence_fail_before_rpc():
    calls=[]
    adapter=LifetimeMemoryOutbox(lambda *a,**kw:calls.append((a,kw)))
    for limit in (0,33,True):
        with pytest.raises(ValueError):adapter.drain(fence(),limit=limit)
    invalid=fence();invalid['source_revision']=-1
    with pytest.raises(ValueError):adapter.claim(invalid)
    assert calls==[]


def test_artifact_wire_is_exact_measured_delta_without_local_state_or_counters():
    uploaded={}
    def put(key,data):
        created=key not in uploaded;uploaded[key]=data;return created
    scope=dict(conversation_id=UUID(int=2),policy_epoch=1,execution_generation=1)
    first=upload_incremental(UUID(int=1),[ArtifactFile('sessions/a',b'abc',True)],put,**scope)
    wire=artifact_manifest_bytes(first)
    assert len(wire)==first['manifest_bytes']
    decoded=json.loads(wire)
    assert '_state' not in decoded and 'uploaded_content_bytes' not in decoded and 'manifest_id' not in decoded
    retry=upload_incremental(UUID(int=1),[ArtifactFile('sessions/a',b'abc',True)],put,previous=first,**scope)
    assert retry['manifest_id']==first['manifest_id'] and artifact_manifest_bytes(retry) is None
    tampered=dict(first,manifest_id='0'*64)
    with pytest.raises(ValueError,match='digest'):artifact_manifest_bytes(tampered)


def test_raw_artifact_link_requires_explicit_authorization_and_matching_scope():
    calls=[]
    adapter=LifetimeMemoryOutbox(lambda *a,**kw:calls.append((a,kw)))
    candidate=upload_incremental(UUID(int=1),[],lambda *a:True,conversation_id=UUID(int=2),policy_epoch=1,execution_generation=1)
    with pytest.raises(ValueError,match='authorization'):adapter.link_artifact(fence(),candidate)
    adapter.link_artifact(fence(),candidate,authorized=True)
    assert calls[-1][0]==('link_lifetime_optional_artifact',)
    assert '_state' not in calls[-1][1]['p_manifest']
    bad=fence();bad['policy_epoch']=2
    with pytest.raises(ValueError,match='scope'):adapter.link_artifact(bad,candidate,authorized=True)


def test_empty_queue_and_failed_failure_record_remain_honest():
    assert LifetimeMemoryOutbox(lambda *a,**kw:None).drain(fence())=={
        'processed':0,'failed':0,'pending':False,'backup_complete':False}
    def rpc(name,**kwargs):
        if name=='claim_lifetime_memory_obligation':return {'id':str(UUID(int=10)),'claim_token':str(UUID(int=4))}
        raise RuntimeError('unavailable')
    result=LifetimeMemoryOutbox(rpc).drain(fence(),limit=1)
    assert result=={'processed':0,'failed':1,'pending':True,'backup_complete':False}


def test_not_ready_is_pending_and_unchanged_cannot_smuggle_new_delta():
    adapter=LifetimeMemoryOutbox(lambda *a,**kw:{'status':'not_ready','backup_complete':False})
    assert adapter.drain(fence())['pending'] is True
    candidate=upload_incremental(UUID(int=1),[],lambda *a:True,conversation_id=UUID(int=2),policy_epoch=1,execution_generation=1)
    with pytest.raises(ValueError,match='integer'):artifact_manifest_bytes(dict(candidate,manifest_bytes=False))
    with pytest.raises(ValueError,match='predecessor'):artifact_manifest_bytes(dict(candidate,manifest_bytes=0))
