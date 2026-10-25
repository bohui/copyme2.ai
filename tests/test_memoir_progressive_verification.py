import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest
from test_memoir_supabase_evaluation import setup  # noqa: F401 - fixture

from scripts.memoir_progressive_verification import original_evidence, preserve_unchanged, sources_unchanged, streamed_turn


def checkpoint(text='Original prose.'):
    return {'draft':{'policy_epoch':1},'pages':[{'records':[{'id':'passage','event_id':'event',
        'preview':{'text':text},'source_refs':[{'source_id':'source','version':'1','char_start':0,'char_end':8}]}]}]}


def test_retained_baseline_cannot_change_and_new_evidence_is_exact():
    original = {'id':'source','version':1,'text':'Original testimony','sequence':1}
    assert sources_unchanged([original],[original,{'id':'new'}])
    edited = {**original,'text':'Edited'}
    assert not sources_unchanged([original],[edited])
    assert original_evidence(checkpoint(),[original])['references_verified']==1
    forged = checkpoint()
    forged['pages'][0]['records'][0]['source_refs'][0]['char_end']=99
    with pytest.raises(ValueError,match='invalid_original'):
        original_evidence(forged,[original])


def test_unchanged_dependency_requires_identical_stored_writing():
    events = [{'id':'event','revision':1,'source_refs':[{'source_id':'source','version':1}]}]
    proof=preserve_unchanged(checkpoint(),checkpoint(),events,events)
    assert len(proof['unchanged_passages'])==1
    with pytest.raises(ValueError,match='writing_changed'):
        preserve_unchanged(checkpoint(),checkpoint('Rewritten'),events,events)
    assert preserve_unchanged(checkpoint(),checkpoint('Updated'),events,[{**events[0],'revision':2}])['changed_event_passages']==1
    absent=deepcopy(checkpoint());absent['pages'][0]['records']=[]
    with pytest.raises(ValueError,match='missing'):
        preserve_unchanged(checkpoint(),absent,events,events)


def test_privacy_fence_change_allows_regeneration_but_profile_revision_alone_does_not():
    previous, current = checkpoint(), checkpoint()
    previous['draft']['snapshot_id'] = 'before'
    current['draft']['snapshot_id'] = 'after'
    current['pages'][0]['records'] = []
    events = [{'id':'event','revision':1,'source_refs':[{'source_id':'source','version':1}]}]
    fence = {'previous_snapshot_id':'before','current_snapshot_id':'after',
        'previous_privacy_digest':'a'*64,'current_privacy_digest':'b'*64}
    proof = preserve_unchanged(previous,current,events,events,privacy_fence=fence)
    assert proof['privacy_changed_passages'] == 1 and not proof['unchanged_passages']
    with pytest.raises(ValueError,match='writing_changed_or_missing'):
        preserve_unchanged(previous,current,events,events,
            privacy_fence={**fence,'current_privacy_digest':'a'*64})
    for patch in [{'current_snapshot_id':'foreign'}, {'previous_snapshot_id':'foreign'},
                  {'previous_privacy_digest':None}, {'current_privacy_digest':'invalid'}]:
        with pytest.raises(ValueError,match='privacy_fence'):
            preserve_unchanged(previous,current,events,events,privacy_fence={**fence,**patch})


@pytest.mark.parametrize('mismatch', [None,'missing','root_digest','policy_epoch','preference_revision'])
def test_summary_reads_and_matches_owned_frozen_privacy_roots(monkeypatch, mismatch):
    from unittest.mock import MagicMock
    import psycopg
    from scripts.memoir_progressive_verification import saved_message_summary
    previous, current = checkpoint(), checkpoint()
    roots = []
    for key, saved in [('before',previous),('after',current)]:
        saved['draft'].update(snapshot_id=key,root_digest=key+'-root')
        saved['pages'][0]['preference_revision'] = 3
        roots.append([key,key+'-root',1,3,('a' if key=='before' else 'b')*64])
    if mismatch == 'missing':
        roots.pop()
    elif mismatch:
        roots[-1][{'root_digest':1,'policy_epoch':2,'preference_revision':3}[mismatch]] = 'changed'
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [[tuple(row) for row in roots],[]]
    monkeypatch.setattr(psycopg,'connect',lambda *args,**kwargs:connection)
    binding = {'owner_id':'owned','project_id':'project'}
    if mismatch:
        with pytest.raises(ValueError,match='privacy_fence_mismatch'):
            saved_message_summary({'SUPABASE_DB_URL':'fixture'},binding,current,[],previous=previous)
    else:
        result = saved_message_summary({'SUPABASE_DB_URL':'fixture'},binding,current,[],previous=previous)
        assert result['privacy_fence']['previous_privacy_digest'] == 'a'*64
        assert result['privacy_fence']['current_privacy_digest'] == 'b'*64
    assert connection.read_only is True
    assert cursor.execute.call_args_list[0].args[1] == ('owned','project',['after','before'])


def test_ndjson_receipt_measures_real_text_and_requires_durable_save():
    async def run(saved):
        frames=[{'type':'started'},{'type':'heartbeat'},{'type':'text_delta','text':'Visible reply.'}]
        if saved:frames.append({'type':'conversation_saved'})
        frames.append({'type':'result','data':{'reply':'Visible reply.'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(200,headers={'content-type':'application/x-ndjson'},content=''.join(json.dumps(v)+'\n' for v in frames)))) as client:
            requests=SimpleNamespace(client=client,remaining=lambda:5,reserved=0,maximum=2,read_only=False,on_reserve=None)
            result,timing=await streamed_turn(requests,'https://fixture.test/turn',{}, {})
            assert requests.reserved==1 and timing['text_delta_count']==1
            assert timing['first_text_seconds']<=timing['saved_seconds']<=timing['total_seconds']
            assert result['reply']=='Visible reply.'
    asyncio.run(run(True))
    with pytest.raises(ValueError,match='deliver_text_and_save'):
        asyncio.run(run(False))


def test_full_rerun_preserves_five_existing_rounds_and_streams_fifty_new_ones(setup, tmp_path, monkeypatch):  # noqa: F811
    from uuid import uuid4
    from scripts import run_memoir_supabase_evaluation as runner
    from test_memoir_supabase_evaluation import SETTINGS, PROJECTS
    plan, remote = setup()
    plan['progressive_rerun'] = True
    monkeypatch.setattr('scripts.memoir_progressive_verification.saved_message_summary',
        lambda settings,binding,checkpoint,messages,**kwargs: {'saved_summaries':1,'summarised_original_messages':len(messages)})
    case_id = plan['case_ids'][0]
    project = PROJECTS[case_id]
    storage = remote.storages[project]
    storage.sources = [{'id':str(uuid4()),'project_id':project,'text':f'Existing memory number {n}.',
        'language':'en-AU','kind':'narrator_chat','status':'active','version':1,'sequence':n+1} for n in range(5)]
    storage.extracted = 5
    before = deepcopy(storage.sources)
    original = remote.handler
    def handler(request):
        response = original(request)
        if request.url.path.endswith('/agent/turn'):
            assert request.headers['Accept'] == 'application/x-ndjson'
            frames = [{'type':'text_delta','text':'A live-route fixture reply'},
                {'type':'conversation_saved'},{'type':'result','data':response.json()}]
            return httpx.Response(200,headers={'content-type':'application/x-ndjson'},
                content=''.join(json.dumps(frame)+'\n' for frame in frames))
        if request.url.path.endswith('read_lifetime_private_draft_page'):
            value=response.json();value['records'][0]['id']='stable-passage'
            return httpx.Response(200,json=value)
        if request.url.path.endswith('read_user_memory_events'):
            value=response.json();value['events']=[{'id':'controlled-event','revision':1,
                'source_refs':[{'source_id':before[0]['id'],'version':1}]}]
            return httpx.Response(200,json=value)
        return response
    remote.handler=handler
    receipt = asyncio.run(runner.execute(plan,tmp_path/'rerun',SETTINGS))
    assert receipt['status']=='completed',receipt.get('stop_reason')
    assert storage.sources[:5]==before and len(storage.sources)==55
    assert len(remote.submitted)==50
    case=receipt['evaluation']['cases'][0]
    assert [c['coverage_round'] for c in case['checkpoints']]==list(range(10,56,5))
    assert all(len(c['verification']['unchanged_passages'])==1 for c in case['checkpoints'])
    assert all(r['streaming']['first_text_seconds'] is not None for r in case['rounds'])
