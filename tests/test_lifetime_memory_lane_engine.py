"""Bounded composer/timeline execution without providers or production config."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
import tomllib
from uuid import UUID

import httpx
import pytest

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.lifetime_memory_contracts import ContextBudget, PinnedContinuity
from apps.api.lifetime_memory_context import serialize_packet
from apps.api.lifetime_memory_lane_engine import (
    BoundedLaneInput, LaneFence, LaneRequestBody, build_bounded_lane_input,
    lane_request_tokens, run_bounded_lane, send_bounded_lane_request,
    lane_extraction_packet, canonical_lane_request, lane_artifact_digest, validate_lane_payload,
)
from apps.api.lifetime_memory_publication import PublicationUnavailable

BUDGET = ContextBudget(model='synthetic-byte-bpe', context_window=131072,
    input_budget=65536,output_headroom=16384,framing_headroom=2048)


def page(skill='timeline'):
    text='A narrow original window.'
    source=dict(id=str(UUID(int=6)),project_id='project',version=1,sequence=1,text=text,
        char_start=0,char_end=len(text),original_length=len(text),kind='narrator_chat',
        language='en-AU',status='active',author_role='storyteller')
    partition=dict(id=str(UUID(int=7)),revision=1,kind='event',life_stage='childhood',
        status='active',change_sequence=1,title='A narrow window',temporal={},source_refs=[
            dict(source_id=source['id'],version=1,quote=text,char_start=0,char_end=len(text))])
    return {'protocol':'lifetime_composer_pages','schema_version':1,'lane_id':str(UUID(int=1)),
        'token':str(UUID(int=2)),'snapshot_id':str(UUID(int=3)),'user_id':str(UUID(int=4)),
        'project_id':'project','conversation_id':str(UUID(int=5)),'skill':skill,'locale':'en-AU',
        'policy_epoch':1,'preference_revision':2,'source_high_water':10000,'event_high_water':10000,
        'page_number':3,'root_digest':'a'*64,'page_digest':'b'*64,'input_digest':'c'*64,'complete':False,'coverage_round':10000,'base_revision':0,
        'source':source,'events':[],'partition':partition if skill=='composer' else None,
        'preferences':PinnedContinuity(preference_revision=2,language='en-AU').model_dump(mode='json')}


def fence_for(current):
    return LaneFence.model_validate({k:v for k,v in current.items() if k in LaneFence.model_fields})


def packet_for(current,phase):
    from apps.api.memoir_preview import skill_operation
    fence=fence_for(current)
    if phase=='extract':return lane_extraction_packet(fence)
    if phase=='prepare':return {'preparation_id':'c'*64,'partition':current['partition'],'sources':[current['source']]}
    request=canonical_lane_request(fence)
    plan=asyncio.run(skill_operation('plan',request))
    if phase=='draft':return {'request':request,'plan':plan}
    candidate={'title':'Synthetic invalid draft'}
    validation=asyncio.run(skill_operation('validate',request,candidate))
    return {'request':request,'candidate':candidate,'validation':validation}


def transport(phase='extract',current=None):
    current=current or page('timeline' if phase=='extract' else 'composer')
    return build_bounded_lane_input(current,phase=phase,packet=packet_for(current,phase),budget=BUDGET)


@pytest.mark.parametrize('reason',['PAGE_QUOTE','CHRONOLOGY_SCOPE','DATE_EXPRESSION','OUTPUT_SCHEMA'])
def test_extraction_retry_accepts_only_fixed_feedback_with_unchanged_evidence(reason):
    current=page();packet=packet_for(current,'extract')
    packet['retry_reason']=reason
    bounded=build_bounded_lane_input(current,phase='extract',packet=packet,budget=BUDGET)
    assert json.loads(bounded.packet)['payload']['retry_reason']==reason
    packet['sources'][0]['text']='replacement testimony'
    with pytest.raises(ValueError,match='authoritative page evidence'):
        build_bounded_lane_input(current,phase='extract',packet=packet,budget=BUDGET)


def test_wording_correction_requires_an_ordinary_event_update_instead_of_an_empty_placement_patch():
    from apps.api.memory_events import validate_extraction
    current=page();event=page('composer')['partition'];ref=event['source_refs'][0]
    proposal={'kind':'event','title':'Corrected wording','existing_id':event['id'],
        'expected_revision':event['revision'],'source_refs':[ref],'correction':ref}
    with pytest.raises(ValueError,match='Correction requires timeline placement fields'):
        validate_extraction({'events':[proposal]},[current['source']],[event])


def test_committed_policy_change_releases_the_lane_without_reading_its_old_snapshot(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from apps.api import lifetime_memory_composer as composer
    current=page()
    monkeypatch.setattr(composer,'_extract',AsyncMock(return_value={'events':[]}))
    broker=SimpleNamespace(rpc=AsyncMock(side_effect=[{'status':'page_saved','policy_changed':True},
        {'status':'deferred'}]))
    result=asyncio.run(composer.execute_lifetime_lane(current,SimpleNamespace(broker=broker)))
    assert result=={'status':'deferred'}
    assert [call.args[0] for call in broker.rpc.await_args_list]==[
        'commit_lifetime_memoir_lane_page','yield_lifetime_memoir_lane_metadata']


@pytest.mark.parametrize('reason',['arbitrary instructions',None,{'message':'private error'}])
def test_extraction_retry_rejects_untrusted_feedback(reason):
    current=page();packet=packet_for(current,'extract');packet['retry_reason']=reason
    with pytest.raises(ValueError,match='Unsupported extraction retry reason'):
        build_bounded_lane_input(current,phase='extract',packet=packet,budget=BUDGET)


@pytest.mark.parametrize('saved',[False,True])
def test_extraction_schema_limits_evidence_and_relations_to_the_claimed_page(saved):
    from jsonschema import Draft202012Validator
    from apps.api.lifetime_memory_lane_engine import lane_contract
    current=page()
    if saved:current['events']=[current['partition'] or page('composer')['partition']]
    _,schema=lane_contract('extract',current['locale'],fence=fence_for(current))
    ref=deepcopy(current['events'][0]['source_refs'][0] if saved else page('composer')['partition']['source_refs'][0])
    ref.update(char_start=None,char_end=None,attribution=None)
    evidence=Draft202012Validator(schema['$defs']['EvidenceRef'])
    evidence.validate(ref)
    assert not evidence.is_valid({**ref,'source_id':'invented-source'})
    assert not evidence.is_valid({**ref,'version':999})
    relations=schema['$defs']['EventProposal']['properties']['relations']
    validate=Draft202012Validator({'$defs':schema['$defs'],**relations})
    assert validate.is_valid([]) and validate.is_valid(None)
    assert not validate.is_valid([{'kind':'before','event_id':'invented-event','source_refs':[ref]}])
    if saved:
        validate.validate([{'kind':'before','event_id':current['events'][0]['id'],'source_refs':[ref]}])


@pytest.mark.parametrize('phase',['extract','prepare','draft','review'])
def test_configured_background_model_alias_accepts_bounded_lane(phase):
    current=page('timeline' if phase=='extract' else 'composer')
    budget=BUDGET.model_copy(update={'model':'memoir-luna-low'})
    bounded=build_bounded_lane_input(current,phase=phase,
        packet=packet_for(current,phase),budget=budget)
    assert bounded.budget.model=='memoir-luna-low'


class Publisher:
    def __init__(self):
        self.snapshots=[]
        self.active=False
        self.stale=False
    @asynccontextmanager
    async def guard(self,fence):
        if self.stale:raise PublicationUnavailable('stale lane')
        self.snapshots.append(deepcopy(fence));self.active=True
        try:yield
        finally:self.active=False


class Connection:
    instances=[]
    failure=None
    def __init__(self,command,home,**options):
        self.command=command;self.home=Path(home);self.options=options;self.requests=[];self.turns=[]
        self.instances.append(self)
    async def __aenter__(self):return self
    async def __aexit__(self,*args):return None
    async def request(self,method,params):
        async with self.options['request_admission']():
            if self.failure:raise self.failure
            self.requests.append((method,params))
        return {'thread':{'id':'fresh-lane'}}
    async def turn(self,thread,prompt,**options):
        async with self.options['request_admission']():
            self.turns.append((thread,prompt,options))
        return '{"events":[]}'


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("MEMOIR_LIFETIME_MEMORY","true")
    Connection.instances=[];Connection.failure=None
    for name in ('MEMOIR_PUBLICATION_DATABASE_URL','MEMORY_SPARK_COLLECTOR_MODEL',
        'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL','MEMOIR_LIFETIME_GENERATION_PAUSED'):
        monkeypatch.delenv(name,raising=False)


def run(tmp_path,bounded=None,publisher=None,**kwargs):
    return asyncio.run(run_bounded_lane(command=['fake'],home_root=tmp_path,
        base_url='http://provider.invalid',api_key='transient-secret',model=BUDGET.model,
        bounded_lane=bounded or transport(),publisher=publisher or Publisher(),
        connection_factory=Connection,**kwargs))


@pytest.mark.parametrize('phase',['extract','prepare','draft','review'])
def test_each_lane_phase_is_fresh_bounded_and_fenced(tmp_path,phase):
    bounded=transport(phase);publisher=Publisher()
    result=run(tmp_path,bounded,publisher)
    instance=Connection.instances[0]
    assert [method for method,_ in instance.requests]==['thread/start']
    assert instance.requests[0][1]['ephemeral'] is True
    assert instance.turns[0][1]==bounded.packet
    assert 'A narrow original window.' not in instance.requests[0][1]['baseInstructions']
    assert len(publisher.snapshots)==2 and all(s==bounded.fence.model_dump(mode='json') for s in publisher.snapshots)
    assert lane_request_tokens(bounded)<=bounded.budget.input_budget
    from apps.api.lifetime_memory_lane_engine import lane_contract
    instructions,schema=lane_contract(phase,bounded.fence.locale,fence=bounded.fence)
    assert instance.requests[0][1]['baseInstructions']==instructions
    assert lane_request_tokens(bounded)==(bounded.budget.count(instructions)
        +bounded.budget.count(bounded.packet)+bounded.budget.count(serialize_packet(schema))
        +bounded.budget.framing_headroom)
    config=tomllib.loads((instance.home/'config.toml').read_text())
    assert config['memories']=={'generate_memories':False,'use_memories':False}
    assert config['project_doc_max_bytes']==0
    assert 'transient-secret' not in (instance.home/'config.toml').read_text()
    assert result['artifacts']==[] and result['thread_id']=='fresh-lane'
    assert str(bounded.fence.snapshot_id) in instance.home.name


def test_each_page_attempt_has_new_home(tmp_path):
    run(tmp_path);run(tmp_path)
    assert Connection.instances[0].home!=Connection.instances[1].home


@pytest.mark.parametrize('change',[{'text':'old source'},{'memories':['old']},{'profile':{'name':'old'}},
    {'thread_id':'old-thread'},{'user_id':str(UUID(int=999))},{'project_id':'other'},
    {'interview_context':{'source':'old'}},{'governed':{}},{'agent_role':'collector'}])
def test_bounded_worker_rejects_foreign_or_mixed_context(change):
    bounded=transport()
    value=dict(user_id=bounded.fence.user_id,project_id=bounded.fence.project_id,
        agent_role='author_timeline',model=BUDGET.model,bounded_lane=bounded)
    value.update(change)
    with pytest.raises(ValueError):WorkerTurnInput(**value)


def test_actual_prompt_and_schema_overflow_is_rejected_before_home(tmp_path):
    bounded=transport()
    # The packet alone fits; the actual server instructions and schema do not.
    tight=bounded.model_copy(update={'budget':BUDGET.model_copy(update={'input_budget':len(bounded.packet)+20})})
    with pytest.raises(ValueError,match='budget'):run(tmp_path,tight)
    assert not Connection.instances and not list(tmp_path.iterdir())


@pytest.mark.parametrize('field,value',[('page_number',-1),('token','not-a-token'),('root_digest','bad')])
def test_lane_fence_is_strict(field,value):
    raw=transport().fence.model_dump(mode='json');raw[field]=value
    with pytest.raises(ValueError):LaneFence.model_validate(raw)


def test_fence_stale_before_engine_dispatch_prevents_packet_send(tmp_path):
    publisher=Publisher();publisher.stale=True
    with pytest.raises(PublicationUnavailable):run(tmp_path,publisher=publisher)
    assert Connection.instances[0].requests==[] and Connection.instances[0].turns==[]


@pytest.mark.parametrize('error',[PermissionError('auth'),TimeoutError('timeout'),RuntimeError('provider')])
def test_provider_failures_never_retry_as_missing_state(tmp_path,error):
    Connection.failure=error
    with pytest.raises(type(error)):run(tmp_path)
    assert len(Connection.instances)==1


def test_worker_uses_bounded_branch_and_missing_database_fails_closed(tmp_path,monkeypatch):
    import apps.api.codex_worker_service as worker_module
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setattr(worker_module,'CodexConnection',Connection)
    bounded=transport()
    payload=WorkerTurnInput(user_id=bounded.fence.user_id,project_id=bounded.fence.project_id,
        agent_role='author_timeline',model=BUDGET.model,bounded_lane=bounded)
    with pytest.raises(PublicationUnavailable):
        asyncio.run(CodexWorker(home_root=tmp_path,model=BUDGET.model).turn(payload))
    assert not Connection.instances and not list(tmp_path.glob('lane-*'))


def test_http_body_guard_covers_write_and_releases_before_response():
    async def scenario():
        publisher=Publisher();bounded=transport()
        body=LaneRequestBody(b'personal packet',publisher=publisher,fence=bounded.fence)
        iterator=body.__aiter__()
        assert await anext(iterator)==b'personal packet' and publisher.active
        with pytest.raises(StopAsyncIteration):await anext(iterator)
        assert not publisher.active
        await body.aclose()
        publisher.stale=True
        stale=LaneRequestBody(b'personal',publisher=publisher,fence=bounded.fence)
        with pytest.raises(PublicationUnavailable):await anext(stale.__aiter__())
    asyncio.run(scenario())


def test_http_sender_transmits_same_contract_without_legacy_context():
    async def scenario():
        bounded=transport();publisher=Publisher()
        async def handler(request):
            value=json.loads(await request.aread())
            assert value['bounded_lane']==bounded.model_dump(mode='json')
            assert value['agent_role']=='author_timeline'
            assert 'text' not in value and 'profile' not in value and 'memories' not in value
            return httpx.Response(200,json={'thread_id':'fresh','reply':'{"events":[]}','artifacts':[]})
        result=await send_bounded_lane_request(worker_url='http://worker.invalid',worker_secret='synthetic',
            bounded_lane=bounded,worker_transport=httpx.MockTransport(handler),publisher=publisher)
        assert result['reply']=='{"events":[]}' and not publisher.active and len(publisher.snapshots)==1
    asyncio.run(scenario())


def test_incomplete_privacy_never_enters_a_model_packet():
    current=page();current['preferences']['privacy_complete']=False
    with pytest.raises(ValueError,match='privacy'):
        build_bounded_lane_input(current,phase='extract',packet=lane_extraction_packet(fence_for(current)),budget=BUDGET)


def test_preference_revision_cannot_disagree_with_page_fence():
    current=page();current['preferences']['preference_revision']=99
    with pytest.raises(ValueError,match='preference'):
        build_bounded_lane_input(current,phase='extract',packet=lane_extraction_packet(fence_for(current)),budget=BUDGET)


def test_bounded_composer_does_not_probe_provider_without_admission(tmp_path,monkeypatch):
    import apps.api.codex_worker_service as worker_module
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setattr(worker_module,'CodexConnection',Connection)
    bounded=transport('draft')
    worker=CodexWorker(home_root=tmp_path,model=BUDGET.model)
    payload=WorkerTurnInput(user_id=bounded.fence.user_id,project_id=bounded.fence.project_id,
        agent_role='composer',composer_phase='draft',model=BUDGET.model,bounded_lane=bounded)
    with pytest.raises(PublicationUnavailable):asyncio.run(worker.turn(payload))
    assert not Connection.instances


def test_packet_cannot_omit_fenced_privacy_preferences():
    current=page();current['preferences']['excluded_topics']=['My school']
    bounded=build_bounded_lane_input(current,phase='extract',packet=lane_extraction_packet(fence_for(current)),budget=BUDGET)
    packet=json.loads(bounded.packet);packet['lane_context']['preferences']['excluded_topics']=[]
    changed=bounded.model_dump(mode='json');changed['packet']=serialize_packet(packet)
    with pytest.raises(ValueError,match='preferences'):BoundedLaneInput.model_validate(changed)


def test_supported_complete_privacy_over_eight_kib_is_not_silently_dropped():
    current=page();current['preferences']['excluded_topics']=['x'*9000]
    bounded=build_bounded_lane_input(current,phase='extract',packet=lane_extraction_packet(fence_for(current)),budget=BUDGET)
    assert json.loads(bounded.packet)['lane_context']['preferences']['excluded_topics']==['x'*9000]


def test_lane_publication_owner_mismatch_is_rejected_before_database_connect():
    from apps.api.lifetime_memory_lane_engine import LanePublication
    async def scenario():
        publisher=LanePublication('synthetic-invalid-dsn',authenticated_owner=UUID(int=999))
        with pytest.raises(PublicationUnavailable,match='owner'):
            async with publisher.guard(transport().fence):pytest.fail('foreign admission')
    asyncio.run(scenario())


def test_lane_http_abandoned_body_releases_guard_and_cannot_replay():
    async def scenario():
        publisher=Publisher();body=LaneRequestBody(b'personal',publisher=publisher,fence=transport().fence)
        assert await anext(body.__aiter__())==b'personal' and publisher.active
        await body.aclose()
        assert not publisher.active
        with pytest.raises(RuntimeError,match='replayed'):body.__aiter__()
    asyncio.run(scenario())


def test_edition_language_remains_separate_from_conversation_language():
    current=page('composer');current['locale']='zh-CN'
    assert current['preferences']['language']=='en-AU'
    bounded=transport('draft',current)
    assert bounded.fence.locale=='zh-CN' and bounded.fence.preferences.language=='en-AU'
    from apps.api.lifetime_memory_lane_engine import lane_contract
    instructions,_=lane_contract('draft','zh-CN')
    assert 'Write in Simplified Chinese' in instructions


@pytest.mark.parametrize('phase',['extract','prepare','draft','review'])
def test_payload_from_foreign_page_cannot_borrow_current_fence(phase):
    current=page('timeline' if phase=='extract' else 'composer')
    foreign=deepcopy(current)
    foreign.update(user_id=str(UUID(int=99)),project_id='foreign',snapshot_id=str(UUID(int=100)),
        policy_epoch=8,page_number=9)
    foreign['source'].update(id=str(UUID(int=101)),project_id='foreign',text='Other private testimony.',
        char_end=24,original_length=24)
    if foreign['partition']:
        foreign['partition']['source_refs'][0].update(source_id=foreign['source']['id'],quote=foreign['source']['text'],char_end=24)
    with pytest.raises(ValueError,match='authoritative'):
        build_bounded_lane_input(current,phase=phase,packet=packet_for(foreign,phase),budget=BUDGET)


@pytest.mark.parametrize('phase',['extract','prepare','draft','review'])
def test_unknown_personal_context_is_not_accepted(phase):
    current=page('timeline' if phase=='extract' else 'composer');payload=packet_for(current,phase)
    payload['unreviewed_context']='A stale profile detail'
    with pytest.raises(ValueError):
        build_bounded_lane_input(current,phase=phase,packet=payload,budget=BUDGET)


def test_prepared_bytes_derive_exact_same_page_proof_and_cannot_mutate():
    current=page('composer');payload=packet_for(current,'draft')
    prepared={'event_id':current['partition']['id'],'context':'Grounded synthetic context.',
        'source_refs':current['partition']['source_refs']}
    payload['request']['context']['prepared_partitions']=[prepared]
    bounded=build_bounded_lane_input(current,phase='draft',packet=payload,budget=BUDGET)
    assert bounded.fence.prior_outputs[0].phase=='prepare'
    assert bounded.fence.prior_outputs[0].digest==lane_artifact_digest('prepare',prepared)
    raw=bounded.model_dump(mode='json');packet=json.loads(raw['packet'])
    packet['payload']['request']['context']['prepared_partitions'][0]['context']='Unproved private detail'
    raw['packet']=serialize_packet(packet)
    with pytest.raises(ValueError,match='proof'):BoundedLaneInput.model_validate(raw)


def test_forged_host_plan_is_rejected_before_provider_home(tmp_path):
    current=page('composer');packet=packet_for(current,'draft')
    packet['plan']['unreviewed_context']='Personal bytes smuggled through host plan'
    bounded=build_bounded_lane_input(current,phase='draft',packet=packet,budget=BUDGET)
    with pytest.raises(ValueError,match='plan'):run(tmp_path,bounded)
    assert not Connection.instances and not list(tmp_path.iterdir())


def test_forged_host_validation_is_rejected_before_provider_home(tmp_path):
    current=page('composer');packet=packet_for(current,'review')
    packet['validation']['unreviewed_context']='Personal bytes smuggled through validation'
    bounded=build_bounded_lane_input(current,phase='review',packet=packet,budget=BUDGET)
    with pytest.raises(ValueError,match='validation'):run(tmp_path,bounded)
    assert not Connection.instances and not list(tmp_path.iterdir())


def test_draft_digest_ignores_only_host_pins_and_keeps_personal_prose():
    original={'title':'A supported title','input_snapshot_id':'untrusted model pin','counter':{'model':1}}
    pinned={**original,'input_snapshot_id':'host pin','counter':{'host':2},'expected_manuscript_revision':0}
    assert lane_artifact_digest('draft',original)==lane_artifact_digest('draft',pinned)
    assert lane_artifact_digest('draft',original)!=lane_artifact_digest('draft',{**pinned,'title':'Other private title'})


def test_paused_generation_fails_retryably_before_home(tmp_path,monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
    with pytest.raises(PublicationUnavailable) as error:run(tmp_path)
    assert error.value.code=='LIFETIME_GENERATION_PAUSED' and error.value.retryable
    assert not Connection.instances and not list(tmp_path.iterdir())


def test_pause_after_build_is_rechecked_at_http_body_admission(monkeypatch):
    async def scenario():
        publisher=Publisher();bounded=transport()
        body=LaneRequestBody(b'personal',publisher=publisher,fence=bounded.fence)
        monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
        with pytest.raises(PublicationUnavailable):await anext(body.__aiter__())
        assert not publisher.snapshots
    asyncio.run(scenario())


def test_draft_prepared_context_requires_registered_artifact():
    current=page('composer');payload=packet_for(current,'draft')
    prepared={'event_id':current['partition']['id'],'context':'Prepared bounded context',
        'source_refs':current['partition']['source_refs']}
    payload['request']['context']['prepared_partitions']=[prepared]
    bounded=build_bounded_lane_input(current,phase='draft',packet=payload,budget=BUDGET)
    assert [(ref.phase,ref.digest) for ref in bounded.fence.prior_outputs]==[
        ('prepare',lane_artifact_digest('prepare',prepared))]


def test_review_requires_real_registered_candidate():
    current=page('composer');payload={'request':canonical_lane_request(fence_for(current)),
        'candidate':None,'validation':None}
    with pytest.raises(ValueError,match='candidate'):
        bounded=build_bounded_lane_input(current,phase='review',packet=payload,budget=BUDGET)
        asyncio.run(validate_lane_payload(bounded))


def test_pause_while_waiting_for_lane_guard_blocks_actual_pipe(tmp_path,monkeypatch):
    class PausePublisher(Publisher):
        @asynccontextmanager
        async def guard(self,fence):
            async with super().guard(fence):
                monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
                yield
    publisher=PausePublisher()
    with pytest.raises(PublicationUnavailable):run(tmp_path,publisher=publisher)
    assert Connection.instances[0].requests==[] and not publisher.active


def test_remote_worker_pause_is_typed_and_retryable():
    async def scenario():
        async def handler(request):
            return httpx.Response(503,json={'detail':'Generation paused'},headers={'X-Error-Code':'LIFETIME_GENERATION_PAUSED'})
        with pytest.raises(PublicationUnavailable) as error:
            await send_bounded_lane_request(worker_url='http://worker.invalid',worker_secret='synthetic',
                bounded_lane=transport(),worker_transport=httpx.MockTransport(handler),publisher=Publisher())
        assert error.value.retryable and error.value.code=='LIFETIME_GENERATION_PAUSED'
    asyncio.run(scenario())


@pytest.mark.parametrize('changes',[{'context_window':131073},{'input_budget':65537},
    {'framing_headroom':2047}])
def test_lane_budget_cannot_expand_reviewed_transport_bound(changes):
    raw=transport().model_dump(mode='json');raw['budget'].update(changes)
    with pytest.raises(ValueError,match='reviewed'):BoundedLaneInput.model_validate(raw)


def test_worker_pause_response_has_retryable_machine_code(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import apps.api.codex_worker_service as worker_module
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
    monkeypatch.setattr(worker_module,'worker',CodexWorker(home_root=tmp_path,model=BUDGET.model))
    bounded=transport()
    with TestClient(worker_module.app) as client:
        response=client.post('/internal/codex/turn',headers={'X-Codex-Worker-Secret':'synthetic'},json={
            'user_id':str(bounded.fence.user_id),'project_id':bounded.fence.project_id,
            'agent_role':'author_timeline','model':BUDGET.model,'bounded_lane':bounded.model_dump(mode='json')})
    assert response.status_code==503
    assert response.headers['X-Error-Code']=='LIFETIME_GENERATION_PAUSED'
    assert response.headers['Retry-After']=='60'
    assert not Connection.instances


@pytest.mark.parametrize('remaining,expect_timeout',[(2.0,False),(0.05,False),(2.0,True)])
def test_transactional_lane_guard_exact_snapshot_and_bounded_cleanup(monkeypatch,remaining,expect_timeout):
    from types import SimpleNamespace
    import psycopg
    from apps.api.lifetime_memory_lane_engine import LanePublication
    calls=[];closed=[]
    class Database:
        @staticmethod
        async def connect(dsn,**options):
            assert dsn=='synthetic-only' and options=={'connect_timeout':2}
            return Database()
        async def execute(self,statement,args=None):
            calls.append((statement,args))
            async def fetchone():return (remaining,)
            return SimpleNamespace(fetchone=fetchone)
        async def close(self):closed.append(True)
    monkeypatch.setattr(psycopg,'AsyncConnection',Database)
    async def scenario():
        fence=transport().fence
        publisher=LanePublication('synthetic-only',authenticated_owner=fence.user_id,
            send_timeout=.01 if expect_timeout else 1)
        if remaining<=.1:
            with pytest.raises(PublicationUnavailable):
                async with publisher.guard(fence):pytest.fail('near-expiry lease admitted')
        elif expect_timeout:
            with pytest.raises(TimeoutError):
                async with publisher.guard(fence):await asyncio.Event().wait()
        else:
            async with publisher.guard(fence):assert not closed
        assert closed==[True]
        assert calls[0][0]=='set local role authenticated'
        assert calls[1][1]==(str(fence.user_id),)
        assert calls[-1][0]=='select public.lock_lifetime_provider_activation()'
        assert calls[-2][0]=='select public.lock_lifetime_memoir_lane_publication(%s)'
        assert calls[-2][1][0].obj==fence.model_dump(mode='json')
    asyncio.run(scenario())


@pytest.mark.parametrize('edition_locale',['en-AU','zh-CN'])
@pytest.mark.parametrize('strict_prepare', [False, True])
def test_real_bounded_composer_call_chain_uses_only_same_page_artifacts(edition_locale,strict_prepare,monkeypatch):
    from types import SimpleNamespace
    from apps.api.lifetime_memory_composer import _compose
    from test_canonical_composer_provenance import controlled_draft
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL',BUDGET.model)
    current=page('composer');current['locale']=edition_locale
    checkpoints={};registry=set();phases=[]
    class Broker:
        async def rpc(self,name,**payload):
            if name=='read_memoir_checkpoint':return deepcopy(checkpoints.get(payload['p_key']))
            if name=='save_memoir_checkpoint':
                checkpoints[payload['p_key']]=deepcopy(payload['p_value']);return None
            if name=='record_lifetime_lane_output':
                assert payload['p_lane_id']==current['lane_id'] and payload['p_token']==current['token']
                assert payload['p_page_number']==current['page_number']
                registry.add((payload['p_phase'],payload['p_digest']));return True
            raise AssertionError(name)
    class ArtifactPublisher(Publisher):
        @asynccontextmanager
        async def guard(self,fence):
            checked=LaneFence.model_validate(fence)
            assert checked.source==current['source'] and checked.partition==current['partition']
            assert all((ref.phase,ref.digest) in registry for ref in checked.prior_outputs)
            async with super().guard(fence):yield
    def model(request):
        wire=json.loads(request.content);bounded=BoundedLaneInput.model_validate(wire['bounded_lane'])
        phase=bounded.phase;payload=json.loads(bounded.packet)['payload'];phases.append(phase)
        assert bounded.fence.locale==edition_locale and bounded.fence.preferences.language=='en-AU'
        if phase=='prepare':
            result={'event_id':current['partition']['id'],'context':'Grounded bounded summary',
                'source_refs':deepcopy(current['partition']['source_refs'])}
            if strict_prepare:
                for ref in result['source_refs']:
                    ref['attribution'] = None
        elif phase=='draft':result=controlled_draft(payload,current['source']['text'],'A narrow window')
        else:
            assert phase=='review'
            result={'ready_for_user_review':True,'publication_approved':False,'findings':[]}
        return httpx.Response(200,json={'reply':json.dumps(result)})
    publisher=ArtifactPublisher()
    worker=SimpleNamespace(broker=Broker(),worker_url='http://synthetic.invalid',worker_secret='synthetic',
        worker_transport=httpx.MockTransport(model),lane_publisher=publisher)
    bundle=asyncio.run(_compose(current,worker))
    assert bundle['status']=='ready' and bundle['preview']['text']==current['source']['text']
    assert phases==['prepare','draft','review'] and len(registry)==3
    assert len(publisher.snapshots)==3 and not publisher.active


def test_generation_pause_blocks_governed_lane_before_home(tmp_path,monkeypatch):
    from apps.api.lifetime_memory_lane_engine import LaneGenerationPaused
    monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
    with pytest.raises(LaneGenerationPaused):run(tmp_path)
    assert not Connection.instances and not list(tmp_path.iterdir())


def test_lane_fence_requires_authoritative_token_independent_input_digest():
    current=page();current.pop('input_digest',None)
    with pytest.raises(ValueError):fence_for(current)

@pytest.mark.parametrize('boundary', ['connect', 'lock', 'lock_error'])
def test_pre_send_lane_authority_timeout_is_a_scheduling_deferral(monkeypatch, boundary):
    import psycopg
    from apps.api.lifetime_memory_lane_engine import LanePublication
    from apps.api.lifetime_memory_activation import CanonicalActivationUnavailable
    closed = []

    class Database:
        @staticmethod
        async def connect(*args, **kwargs):
            if boundary == 'connect':
                await asyncio.Event().wait()
            return Database()

        async def execute(self, statement, args=None):
            if 'lock_lifetime_memoir_lane_publication' in statement:
                if boundary == 'lock_error':
                    raise psycopg.errors.LockNotAvailable('private server diagnostic')
                await asyncio.Event().wait()
            return None

        async def close(self):
            closed.append(True)

    monkeypatch.setattr(psycopg, 'AsyncConnection', Database)

    async def scenario():
        fence = transport().fence
        publisher = LanePublication('synthetic-only', authenticated_owner=fence.user_id, lock_timeout=.01)
        with pytest.raises(CanonicalActivationUnavailable):
            async with publisher.guard(fence):
                pytest.fail('A stalled authority cannot admit provider bytes')
        assert closed == ([] if boundary == 'connect' else [True])

    asyncio.run(scenario())


def test_bounded_composer_rejects_narrowed_evidence_before_database_commit():
    from apps.api.canonical_composer import canonical_evidence_errors
    current=page('composer');request=canonical_lane_request(fence_for(current))
    ref={'source_id':current['source']['id'],'version':'1','char_start':0,'char_end':5}
    draft={'chapters':[{'event_ids':[current['partition']['id']], 'source_refs':[ref]}],
        'carry_forward_chapter_ids':[]}
    errors=canonical_evidence_errors(request,draft)
    assert any(error['code']=='NONCANONICAL_EVIDENCE_SPAN' for error in errors)
    ref['char_end']=len(current['source']['text'])
    assert canonical_evidence_errors(request,draft)==[]
    ref.pop('char_start')
    assert canonical_evidence_errors(request,draft)


def test_canonical_page_request_exposes_only_its_exact_evidence_span():
    current=page('composer')
    narrow=deepcopy(current['partition']['source_refs'][0]);narrow['char_end']=5
    narrow['quote']=current['source']['text'][:5]
    current['partition']['source_refs'].append(narrow)
    request=canonical_lane_request(fence_for(current))
    expected={'source_id':current['source']['id'],'version':'1','char_start':0,
        'char_end':len(current['source']['text'])}
    assert request['events'][0]['source_refs']==[expected]
    assert request['periods'][0]['source_refs']==[expected]


def test_default_lane_budget_admits_bounded_repair_with_prepared_context(monkeypatch):
    from apps.api.lifetime_memory_composer import lane_model_budget
    from apps.api.memoir_preview import skill_operation
    from apps.api.canonical_composer import canonical_evidence_errors
    from test_canonical_composer_provenance import controlled_draft
    monkeypatch.delenv('MEMOIR_LANE_INPUT_BUDGET',raising=False)
    current=page('composer');request=canonical_lane_request(fence_for(current))
    request['context']['prepared_partitions']=[{'event_id':current['partition']['id'],
        'context':'derived '*1250,'source_refs':deepcopy(current['partition']['source_refs'])}]
    plan=asyncio.run(skill_operation('plan',request))
    candidate=controlled_draft({'request':request,'plan':plan},current['source']['text'],'A narrow window')
    candidate['chapters'][0]['blocks'][0]['text']=current['source']['text']*400
    validation=asyncio.run(skill_operation('validate',request,candidate))
    if validation.get('ok'):
        errors=canonical_evidence_errors(request,candidate)
        if errors:validation['ok']=False;validation.setdefault('errors',[]).extend(errors)
    packet={'request':request,'plan':plan,'candidate':candidate,'validation':validation,'review':None}
    bounded=build_bounded_lane_input(current,phase='draft',packet=packet,budget=lane_model_budget())
    assert lane_request_tokens(bounded)<=bounded.budget.input_budget
    from apps.api.memoir_preview import composer_instructions
    from apps.api.lifetime_memory_lane_engine import lane_contract
    current_instructions,_=lane_contract('draft',current['locale'])
    assert len(composer_instructions('draft').encode()) < 10000
    assert bounded.budget.input_budget+bounded.budget.output_headroom+bounded.budget.framing_headroom<=bounded.budget.context_window
    asyncio.run(validate_lane_payload(bounded))
