from uuid import UUID
from apps.api.lifetime_memory_artifacts import upload_incremental as _upload_incremental, ArtifactFile


def upload_incremental(*args, **kwargs):
    kwargs.setdefault('conversation_id', UUID(int=10))
    kwargs.setdefault('policy_epoch', 1)
    kwargs.setdefault('execution_generation', 1)
    return _upload_incremental(*args, **kwargs)


class Storage:
    def __init__(self): self.objects={}; self.content_bytes=0
    def put_if_absent(self,key,data):
        if key in self.objects:
            assert self.objects[key]==data
            return False
        self.objects[key]=data; self.content_bytes+=len(data); return True


def test_unchanged_content_and_retry_upload_zero_extra_bytes_and_changed_chunk_only():
    storage=Storage(); owner=UUID(int=1)
    data=b'a'*1024+b'b'*1024+b'c'*1024
    first=upload_incremental(owner,[ArtifactFile('sessions/thread.jsonl',data,authorized=True)],storage.put_if_absent,chunk_bytes=1024)
    assert first['uploaded_content_bytes']==3072
    second=upload_incremental(owner,[ArtifactFile('sessions/thread.jsonl',data,authorized=True)],storage.put_if_absent,chunk_bytes=1024)
    assert second['uploaded_content_bytes']==0
    changed=upload_incremental(owner,[ArtifactFile('sessions/thread.jsonl',data[:1024]+b'd'*1024+data[2048:],authorized=True)],storage.put_if_absent,chunk_bytes=1024)
    assert changed['uploaded_content_bytes']==1024
    assert upload_incremental(owner,[ArtifactFile('sessions/thread.jsonl',data[:1024]+b'd'*1024+data[2048:],authorized=True)],storage.put_if_absent,chunk_bytes=1024)['uploaded_content_bytes']==0


def test_large_file_has_complete_bounded_chunk_manifest_and_no_cross_tenant_dedup():
    storage=Storage(); data=b'a'*(26*1024*1024+19)
    one=upload_incremental(UUID(int=1),[ArtifactFile('sessions/large.jsonl',data,authorized=True)],storage.put_if_absent)
    two=upload_incremental(UUID(int=2),[ArtifactFile('sessions/large.jsonl',data,authorized=True)],storage.put_if_absent)
    assert one['complete'] and len(one['files'][0]['chunks'])==27
    assert sum(c['bytes'] for c in one['files'][0]['chunks'])==len(data)
    assert one['files'][0]['chunks'][0]['key']!=two['files'][0]['chunks'][0]['key']
    assert two['uploaded_content_bytes']>0


def test_unsafe_or_unprovenanced_files_are_explicit_omissions():
    storage=Storage()
    result=upload_incremental(UUID(int=1),[ArtifactFile('../secret',b'x'),ArtifactFile('memories/generated.md',b'secret',authorized=False)],storage.put_if_absent)
    assert not result['complete'] and len(result['omissions'])==2 and storage.content_bytes==0


def test_delta_manifest_does_not_repeat_unchanged_files_or_chunks():
    storage=Storage(); owner=UUID(int=1)
    data=b'a'*1024+b'b'*1024+b'c'*1024
    first=upload_incremental(owner,[ArtifactFile('sessions/t.jsonl',data,True)],storage.put_if_absent,chunk_bytes=1024)
    unchanged=upload_incremental(owner,[ArtifactFile('sessions/t.jsonl',data,True)],storage.put_if_absent,chunk_bytes=1024,previous=first)
    assert unchanged['files']==[] and unchanged['manifest_bytes']==0
    changed=upload_incremental(owner,[ArtifactFile('sessions/t.jsonl',data[:1024]+b'd'*1024+data[2048:],True)],storage.put_if_absent,chunk_bytes=1024,previous=first)
    assert len(changed['files'][0]['chunks'])==1 and changed['files'][0]['chunks'][0]['offset']==1024
    assert changed['predecessor']==first['manifest_id']


def test_10000_turn_artifact_content_and_manifest_bytes_are_linear():
    storage=Storage();previous=None;content_bytes=0;manifest_bytes=0;data=b''
    for turn in range(10000):
        data+=turn.to_bytes(4,'big')
        result=upload_incremental(UUID(int=1),[ArtifactFile('sessions/t.jsonl',data,True)],storage.put_if_absent,chunk_bytes=64,previous=previous)
        content_bytes+=result['uploaded_content_bytes'];manifest_bytes+=result['manifest_bytes'];previous=result
        assert len(result['files'][0]['chunks'])<=1
    assert content_bytes<=10000*64
    assert manifest_bytes<=10000*1200


def test_snapshot_removes_missing_and_newly_unauthorized_paths():
    storage=Storage()
    first=upload_incremental(UUID(int=1),[ArtifactFile('sessions/a',b'private',True),ArtifactFile('sessions/b',b'other',True)],storage.put_if_absent)
    second=upload_incremental(UUID(int=1),[ArtifactFile('sessions/a',b'private',False)],storage.put_if_absent,previous=first)
    assert second['_state']=={}
    assert set(second['removed_paths'])=={'sessions/a','sessions/b'}
    assert second['manifest_bytes']>0
    assert storage.content_bytes==12  # logical unlink, no retained-object deletion


def test_predecessor_rejected_across_conversation_policy_or_generation():
    import pytest
    storage=Storage()
    first=upload_incremental(UUID(int=1),[],storage.put_if_absent)
    for changes in ({'conversation_id':UUID(int=11)},{'policy_epoch':2},{'execution_generation':2}):
        with pytest.raises(ValueError,match='scope'):
            upload_incremental(UUID(int=1),[],storage.put_if_absent,previous=first,**changes)
