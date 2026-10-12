from uuid import uuid4

from apps.api.lifetime_memory_contracts import EvidenceEnvelope
from apps.api.lifetime_memory_context import ContextCheckpoint
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER,OLD,as_user
from test_shared_memory_events_postgres import rpc,literal


def setup(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    source=rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','I remember a blue umbrella'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    evidence=EvidenceEnvelope(source_id=source['id'],version=1,char_start=0,char_end=len(source['text']),original=source['text'],language='en-AU',assertion='asserted',allowed_use=['conversation'],policy_epoch=1).model_dump(mode='json')
    return identity,source,fence,evidence


def proof_for(sql,fence,end):
    proof=rpc(sql,'begin_lifetime_compaction',f"{literal(fence)}::jsonb,{end}")
    while not proof['complete']:
        proof=rpc(sql,'step_lifetime_compaction',f"'{proof['id']}',{literal(fence)}::jsonb,{proof['revision']}")
    return proof


def create(sql,fence,evidence,end=1):
    proof=proof_for(sql,fence,end)
    return rpc(sql,'create_lifetime_checkpoint',f"{literal(fence)}::jsonb,{end},'fixture-model','lifetime-v1',{literal([evidence])}::jsonb,'{proof['id']}'")


def read(sql,identity,epoch=1,prompt='lifetime-v1'):
    return rpc(sql,'read_lifetime_checkpoint',f"'{identity['conversation_id']}',{epoch},'fixture-model',{literal(prompt)}")


def test_candidate_failure_does_not_publish_and_replay_publish_is_atomic(sql):
    identity,source,fence,evidence=setup(sql)
    candidate=create(sql,fence,evidence)
    assert read(sql,identity) is None
    assert rpc(sql,'publish_lifetime_checkpoint',f"'{candidate}',{literal(fence)}::jsonb") is True
    assert rpc(sql,'publish_lifetime_checkpoint',f"'{candidate}',{literal(fence)}::jsonb") is True
    checkpoint=read(sql,identity)
    assert ContextCheckpoint.model_validate(checkpoint).coverage_end==1
    assert checkpoint['evidence']==[evidence]
    assert read(sql,identity,prompt='old-prompt') is None


def test_stale_candidate_cannot_replace_predecessor_or_survive_withdrawal(sql):
    identity,source,fence,evidence=setup(sql)
    first=create(sql,fence,evidence)
    rpc(sql,'publish_lifetime_checkpoint',f"'{first}',{literal(fence)}::jsonb")
    later=rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','A later memory'")
    next_fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    candidate=create(sql,next_fence,evidence,2)
    assert read(sql,identity)['checkpoint_id']==first
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{source['id']}',1,'withdraw',null")
    assert rpc(sql,'publish_lifetime_checkpoint',f"'{candidate}',{literal(next_fence)}::jsonb",check=False).returncode!=0
    assert read(sql,identity,epoch=2) is None
    assert sql('select count(*) from public.user_lifetime_checkpoint;').stdout.strip()=='0'


def test_checkpoint_rejects_unsupported_evidence_span(sql):
    identity,source,fence,evidence=setup(sql)
    proof=proof_for(sql,fence,1)
    evidence['original']='I invented a different detail'
    assert rpc(sql,'create_lifetime_checkpoint',f"{literal(fence)}::jsonb,1,'fixture-model','lifetime-v1',{literal([evidence])}::jsonb,'{proof['id']}'",check=False).returncode!=0


def test_checkpoint_rehydrates_current_pins_without_losing_coverage(sql):
    identity,source,fence,evidence=setup(sql)
    candidate=create(sql,fence,evidence)
    rpc(sql,'publish_lifetime_checkpoint',f"'{candidate}',{literal(fence)}::jsonb")
    sql(as_user("update public.user_profile set profile='{\"name\":\"慧博\",\"preferred_language\":\"zh-CN\"}';"))
    checkpoint=read(sql,identity)
    assert checkpoint['checkpoint_id']==candidate and checkpoint['coverage_end']==1
    assert checkpoint['pinned']['chosen_name']=='慧博' and checkpoint['pinned']['language']=='zh-CN'
    assert checkpoint['pinned']['preference_revision']>fence['preference_revision']


def test_checkpoint_rejects_unbounded_or_unknown_claim_metadata(sql):
    identity,source,fence,evidence=setup(sql)
    proof=proof_for(sql,fence,1)
    for changes in [dict(unknown='unvalidated'),dict(translation='x'*2001,translation_attribution='translator'),
        dict(translation='translated',translation_attribution=None),dict(uncertainty='x'*2001),
        dict(contradicts=['x'*129]),dict(allowed_use=['conversation']*4)]:
        claim={**evidence,**changes}
        assert rpc(sql,'create_lifetime_checkpoint',f"{literal(fence)}::jsonb,1,'fixture-model','lifetime-v1',{literal([claim])}::jsonb,'{proof['id']}'",check=False).returncode!=0


def test_no_checkpoint_can_skip_an_unprocessed_interval(sql):
    identity,source,fence,evidence=setup(sql)
    assert rpc(sql,'create_lifetime_checkpoint',f"{literal(fence)}::jsonb,1,'fixture-model','lifetime-v1','[]'",check=False).returncode!=0
    proof=rpc(sql,'begin_lifetime_compaction',f"{literal(fence)}::jsonb,1")
    assert not proof['complete']
    assert rpc(sql,'create_lifetime_checkpoint',f"{literal(fence)}::jsonb,1,'fixture-model','lifetime-v1','[]','{proof['id']}'",check=False).returncode!=0
    completed=rpc(sql,'step_lifetime_compaction',f"'{proof['id']}',{literal(fence)}::jsonb,{proof['revision']}")
    assert completed['complete'] and completed['item_count']==1 and len(completed['digest'])==64
    assert proof_for(sql,fence,1)['id']==proof['id']
    assert rpc(sql,'step_lifetime_compaction',f"'{proof['id']}',{literal(fence)}::jsonb,{proof['revision']}",check=False).returncode!=0


def test_typed_commitment_and_exclusions_survive_checkpoint_and_cold_read(sql):
    identity,source,fence,evidence=setup(sql)
    data={'text':'Remember the blue umbrella.','assertion':'asserted','uncertainty':'Original recollection',
        'source_refs':[{'source_id':source['id'],'version':1,'char_start':0,'char_end':len(source['text']),'quote':source['text']}]}
    rpc(sql,'save_lifetime_continuity',f"'{identity['conversation_id']}','umbrella-commitment','commitment',0,1,'{OLD}',{literal(data)}::jsonb")
    sql(as_user("update public.user_profile set profile='{\"name\":\"慧博\",\"preferred_language\":\"zh-CN\",\"memory_preferences\":{\"excluded_topics\":[\"private\"],\"unresolved_references\":[\"Which Ming?\"]}}';"))
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    candidate=create(sql,fence,evidence)
    rpc(sql,'publish_lifetime_checkpoint',f"'{candidate}',{literal(fence)}::jsonb")
    restored=ContextCheckpoint.model_validate(read(sql,identity))
    assert restored.pinned.chosen_name=='慧博' and restored.pinned.language=='zh-CN'
    assert restored.pinned.excluded_topics==['private'] and restored.pinned.unresolved_references==['Which Ming?']
    assert restored.pinned.known_continuity[0].kind=='commitment'
    assert restored.pinned.known_continuity[0].data.source_refs[0].quote==source['text']


def test_more_than_100_historical_records_keep_recent_pronoun_context_bounded(sql):
    identity,source,fence,evidence=setup(sql)
    ref={'source_id':source['id'],'version':1,'char_start':0,'char_end':len(source['text']),'quote':source['text']}
    data={'text':'Ming is the person referred to by him.','assertion':'inferred','uncertainty':'Two people may share this name','source_refs':[ref]}
    # Set up 120 separately addressable historical records through the real RPC.
    statement=''.join(f"select public.save_lifetime_continuity('{identity['conversation_id']}','person-{n:03d}','person',0,1,'{OLD}',{literal(data)}::jsonb);" for n in range(120))
    sql(as_user(statement))
    rpc(sql,'save_lifetime_continuity',f"'{identity['conversation_id']}','active-pronoun','unresolved_reference',0,1,'{OLD}',{literal(data)}::jsonb")
    rpc(sql,'save_lifetime_continuity',f"'{identity['conversation_id']}','privacy-exclusion','excluded_topic',0,1,'{OLD}',{literal({**data,'text':'Do not discuss the private school incident.'})}::jsonb")
    pins=rpc(sql,'read_lifetime_pinned',f"'{identity['conversation_id']}'")
    assert 'Do not discuss the private school incident.' in pins['excluded_topics']
    assert len(pins['known_continuity'])<=8 and not pins['known_continuity_complete']
    assert pins['known_continuity'][0]['record_id']=='active-pronoun'
    assert pins['known_continuity'][0]['data']['uncertainty']=='Two people may share this name'
    assert pins['continuity_retrieval']=='read_lifetime_continuity'
    page=rpc(sql,'read_lifetime_continuity',f"'{identity['conversation_id']}',1,'',100")
    assert len(page['records'])==100 and not page['complete']
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    candidate=create(sql,fence,evidence)
    rpc(sql,'publish_lifetime_checkpoint',f"'{candidate}',{literal(fence)}::jsonb")
    restored=ContextCheckpoint.model_validate(read(sql,identity))
    assert restored.pinned.known_continuity[0].record_id=='active-pronoun'
