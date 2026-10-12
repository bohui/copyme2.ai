"""Provider-free selected-collection job transport and bounded hierarchy tests."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import tomllib
from uuid import UUID

import httpx
import pytest

from apps.api.codex_worker_service import WorkerTurnInput, CodexWorker
from apps.api.lifetime_memory_context import serialize_packet
from apps.api.lifetime_memory_job_engine import (
    BoundedJobInput, JobFence, JobOutputInvalid, JobRequestBody, build_bounded_job_input,
    job_request_tokens, job_summary_metadata, run_bounded_job, send_bounded_job_request,
    validate_job_result,
)
from apps.api.lifetime_memory_publication import PublicationUnavailable
from test_lifetime_memory_lane_engine import BUDGET, Connection as LaneConnection, Publisher, page as lane_page


def page(phase='leaf',count=1):
    lane=lane_page()
    current={key:lane[key] for key in ('schema_version','snapshot_id','user_id','project_id',
        'conversation_id','locale','policy_epoch','preference_revision','root_digest',
        'page_number','page_digest','preferences','complete')}
    current.update(protocol='lifetime_collection_jobs',job_id=str(UUID(int=10)),token=str(UUID(int=11)),
        kind='BuildOutline',phase=phase,collection_revision=2,
        sources=[lane['source']] if phase=='leaf' else [],child_groups=[])
    if phase=='merge':
        for identity in (20,21):
            child_id=str(UUID(int=identity))
            current['child_groups'].append({'id':child_id,'digest':'c'*64,'title':'A bounded theme',
                'sections':[{'id':f'{child_id}:{n}','title':f'Theme {n}'} for n in range(1,count+1)]})
    return current


def transport(phase='leaf',**kwargs):
    return build_bounded_job_input(page(phase,**kwargs),budget=BUDGET)


def reply_for(bounded):
    fence=bounded.fence
    if fence.phase=='leaf':
        return {'title':'Collected memories','sections':[{'title':'A narrow window',
            'memory_ids':[str(source.id) for source in fence.sources]}]}
    return {'title':'A global memoir','sections':[{'title':section.title,'section_ids':[section.id]}
        for child in fence.child_groups for section in child.sections]}


class Connection(LaneConnection):
    reply=None
    async def turn(self,thread,prompt,**options):
        async with self.options['request_admission']():self.turns.append((thread,prompt,options))
        return self.reply


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv("MEMOIR_LIFETIME_MEMORY","true")
    Connection.instances=[];Connection.failure=None;Connection.reply=None
    for name in ('MEMOIR_PUBLICATION_DATABASE_URL','MEMOIR_LIFETIME_GENERATION_PAUSED'):
        monkeypatch.delenv(name,raising=False)


def run(tmp_path,bounded=None,publisher=None):
    bounded=bounded or transport()
    if Connection.reply is None:Connection.reply=json.dumps(reply_for(bounded))
    return asyncio.run(run_bounded_job(command=['fake'],home_root=tmp_path,
        base_url='http://provider.invalid',api_key='transient-only',model=BUDGET.model,
        bounded_job=bounded,publisher=publisher or Publisher(),connection_factory=Connection))


@pytest.mark.parametrize('phase',['leaf','merge'])
def test_job_engine_is_fresh_private_and_fenced(tmp_path,phase):
    bounded=transport(phase);publisher=Publisher()
    result=run(tmp_path,bounded,publisher)
    connection=Connection.instances[0]
    assert connection.requests[0][0]=='thread/start' and connection.requests[0][1]['ephemeral']
    assert connection.turns[0][1]==bounded.packet and result['artifacts']==[]
    assert publisher.snapshots==[bounded.fence.model_dump(mode='json')]*2
    config=tomllib.loads((connection.home/'config.toml').read_text())
    assert config['memories']=={'generate_memories':False,'use_memories':False}
    assert config['project_doc_max_bytes']==0 and 'transient-only' not in (connection.home/'config.toml').read_text()
    assert 'A narrow original window.' not in connection.requests[0][1]['baseInstructions']
    assert job_request_tokens(bounded)<=65536
    run(tmp_path,bounded,publisher)
    assert Connection.instances[0].home!=Connection.instances[1].home


@pytest.mark.parametrize('phase',['leaf','merge'])
def test_packet_cannot_swap_foreign_evidence_or_derived_titles(phase):
    raw=transport(phase).model_dump(mode='json');packet=json.loads(raw['packet'])
    if phase=='leaf':packet['sources'][0]['text']='Foreign private memory'
    else:packet['child_groups'][0]['sections'][0]['title']='Other tenant title'
    raw['packet']=serialize_packet(packet)
    with pytest.raises(ValueError,match='authoritative'):BoundedJobInput.model_validate(raw)


def test_structured_job_context_cannot_carry_unbound_personal_fields():
    raw=transport().model_dump(mode='json');packet=json.loads(raw['packet'])
    packet['profile']={'name':'unbound'};raw['packet']=serialize_packet(packet)
    with pytest.raises(ValueError,match='authoritative'):BoundedJobInput.model_validate(raw)


def test_output_retains_100_sections_and_exact_ordered_ancestry():
    bounded=transport('merge',count=50);result=reply_for(bounded)
    assert len(validate_job_result(bounded.fence,result)['sections'])==100
    metadata=job_summary_metadata(result,UUID(int=30),'d'*64)
    assert len(metadata['sections'])==100 and metadata['sections'][99]['id']==f'{UUID(int=30)}:100'


def test_merge_can_group_cross_child_themes_without_losing_references():
    bounded=transport('merge',count=2);children=bounded.fence.child_groups
    result={'title':'A shared life','sections':[
        {'title':'Home','section_ids':[children[1].sections[0].id,children[0].sections[1].id]},
        {'title':'Work','section_ids':[children[0].sections[0].id,children[1].sections[1].id]}]}
    assert validate_job_result(bounded.fence,result)==result


@pytest.mark.parametrize('change',['omit','duplicate','invent','extra'])
def test_job_result_rejects_coverage_change(change):
    bounded=transport('merge');result=reply_for(bounded)
    if change=='omit':result['sections'].pop()
    elif change=='duplicate':result['sections'][1]['section_ids']=result['sections'][0]['section_ids'][:]
    elif change=='invent':result['sections'][0]['section_ids']=['invented']
    else:result['other_context']='unproved source'
    with pytest.raises(JobOutputInvalid) as error:validate_job_result(bounded.fence,result)
    assert error.value.retryable


def test_long_cjk_output_fails_recoverably_without_clipping_or_auto_retry(tmp_path):
    bounded=transport('merge',count=50);result=reply_for(bounded)
    for section in result['sections']:section['title']='记'*200
    original=deepcopy(result);Connection.reply=json.dumps(result)
    with pytest.raises(JobOutputInvalid):run(tmp_path,bounded)
    assert result==original and len(Connection.instances)==1 and len(Connection.instances[0].turns)==1


def test_oversized_child_metadata_never_starts_a_provider(tmp_path):
    current=page('merge',count=100)
    for child in current['child_groups']:
        for section in child['sections']:section['title']='记'*200
    with pytest.raises(ValueError,match='metadata'):build_bounded_job_input(current,budget=BUDGET)
    assert not Connection.instances and not list(tmp_path.iterdir())


def test_full_job_prompt_and_schema_budget_not_just_packet_is_enforced():
    raw=transport().model_dump(mode='json');raw['budget']['input_budget']=len(raw['packet'])+10
    with pytest.raises(ValueError,match='budget'):BoundedJobInput.model_validate(raw)


def test_current_job_privacy_cannot_be_partial_or_omitted():
    current=page();current['preferences']['privacy_complete']=False
    with pytest.raises(ValueError,match='privacy'):build_bounded_job_input(current,budget=BUDGET)


def test_job_edition_language_is_independent_of_conversation():
    current=page();current['locale']='zh-CN'
    bounded=build_bounded_job_input(current,budget=BUDGET)
    assert bounded.fence.preferences.language=='en-AU' and bounded.fence.locale=='zh-CN'


@pytest.mark.parametrize('error',[PermissionError('auth'),TimeoutError('timeout'),RuntimeError('provider')])
def test_provider_failures_are_not_missing_state_and_never_retry(tmp_path,error):
    Connection.failure=error
    with pytest.raises(type(error)):run(tmp_path)
    assert len(Connection.instances)==1


def test_changed_fence_before_dispatch_blocks_all_job_bytes(tmp_path):
    publisher=Publisher();publisher.stale=True
    with pytest.raises(PublicationUnavailable):run(tmp_path,publisher=publisher)
    assert Connection.instances[0].requests==[] and Connection.instances[0].turns==[]


def test_job_http_body_retains_immutable_fence_and_releases_on_close():
    async def scenario():
        publisher=Publisher();fence=transport().fence
        body=JobRequestBody(b'personal',publisher=publisher,fence=fence)
        fence.preferences.excluded_topics.append('Changed after body creation')
        assert await anext(body.__aiter__())==b'personal' and publisher.active
        assert publisher.snapshots[0]['preferences']['excluded_topics']==[]
        await body.aclose();assert not publisher.active
    asyncio.run(scenario())


def test_sender_uses_only_typed_job_payload_and_validates_response():
    async def scenario():
        bounded=transport();publisher=Publisher()
        def handler(request):
            raw=json.loads(request.content)
            assert raw['agent_role']=='organiser' and raw['bounded_job']==bounded.model_dump(mode='json')
            assert not {'text','task_sources','profile','memories','thread_id'} & raw.keys()
            return httpx.Response(200,json={'reply':json.dumps(reply_for(bounded)),'artifacts':[]})
        result=await send_bounded_job_request(worker_url='http://synthetic.invalid',worker_secret='synthetic',
            bounded_job=bounded,worker_transport=httpx.MockTransport(handler),publisher=publisher)
        assert result['artifacts']==[] and not publisher.active
    asyncio.run(scenario())


def test_worker_accepts_typed_job_and_rejects_mixed_legacy_fields():
    bounded=transport();values=dict(user_id=bounded.fence.user_id,project_id=bounded.fence.project_id,
        agent_role='organiser',model=BUDGET.model,bounded_job=bounded)
    payload=WorkerTurnInput(**values)
    assert payload.bounded_job==bounded
    for key,value in [('text','legacy'),('task_sources',[{'id':'old','content':'private'}]),
        ('profile',{'name':'old'}),('thread_id','prior'),('agent_role','collector')]:
        with pytest.raises(ValueError):WorkerTurnInput(**{**values,key:value})


def test_missing_worker_database_fails_before_any_legacy_home(tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    import apps.api.codex_worker_service as worker_module
    monkeypatch.setattr(worker_module,'CodexConnection',Connection)
    bounded=transport();payload=WorkerTurnInput(user_id=bounded.fence.user_id,
        project_id=bounded.fence.project_id,agent_role='organiser',model=BUDGET.model,bounded_job=bounded)
    with pytest.raises(PublicationUnavailable):asyncio.run(CodexWorker(home_root=tmp_path,model=BUDGET.model).turn(payload))
    assert not Connection.instances and not list(tmp_path.glob('job-*'))


@pytest.mark.parametrize('change',[{'context_window':131073},{'input_budget':65537},
    {'framing_headroom':2047},{'model':'unreviewed-model'}])
def test_job_budget_cannot_be_enlarged_by_service_payload(change):
    raw=transport().model_dump(mode='json');raw['budget'].update(change)
    with pytest.raises(ValueError,match='reviewed'):BoundedJobInput.model_validate(raw)


def test_job_rejects_mixed_leaf_and_generated_child_evidence():
    current=page('merge');current['sources']=page()['sources']
    with pytest.raises(ValueError):build_bounded_job_input(current,budget=BUDGET)


def test_child_section_ids_are_bound_to_exact_host_assigned_order():
    current=page('merge');current['child_groups'][0]['sections'][0]['id']=f'{UUID(int=90)}:1'
    with pytest.raises(ValueError,match='database-owned'):build_bounded_job_input(current,budget=BUDGET)


def test_job_pause_rechecked_inside_actual_admission(tmp_path,monkeypatch):
    class PausingPublisher(Publisher):
        @asynccontextmanager
        async def guard(self,fence):
            async with super().guard(fence):
                monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
                yield
    publisher=PausingPublisher()
    with pytest.raises(PublicationUnavailable):run(tmp_path,publisher=publisher)
    assert Connection.instances[0].requests==[] and not publisher.active


def test_job_owner_mismatch_never_connects_database():
    from apps.api.lifetime_memory_job_engine import JobPublication
    async def scenario():
        publisher=JobPublication('synthetic-invalid',authenticated_owner=UUID(int=999))
        with pytest.raises(PublicationUnavailable,match='owner'):
            async with publisher.guard(transport().fence):pytest.fail('foreign admission')
    asyncio.run(scenario())


@pytest.mark.parametrize('remaining',[2.0,0.05])
def test_job_database_guard_holds_exact_snapshot_and_closes(monkeypatch,remaining):
    from types import SimpleNamespace
    import psycopg
    from apps.api.lifetime_memory_job_engine import JobPublication
    calls=[];closed=[]
    class Database:
        @staticmethod
        async def connect(dsn,**kwargs):
            assert dsn=='synthetic-only';return Database()
        async def execute(self,statement,args=None):
            calls.append((statement,args))
            async def fetchone():return (remaining,)
            return SimpleNamespace(fetchone=fetchone)
        async def close(self):closed.append(True)
    monkeypatch.setattr(psycopg,'AsyncConnection',Database)
    async def scenario():
        fence=transport().fence;publisher=JobPublication('synthetic-only',authenticated_owner=fence.user_id)
        if remaining>.1:
            async with publisher.guard(fence):assert not closed
        else:
            with pytest.raises(PublicationUnavailable):
                async with publisher.guard(fence):pytest.fail('expired lease admitted')
        assert closed==[True] and calls[0][0]=='set local role authenticated'
        assert calls[-1][0]=='select public.lock_lifetime_collection_job_publication(%s)'
        assert calls[-1][1][0].obj==fence.model_dump(mode='json')
    asyncio.run(scenario())


def test_worker_propagates_bounded_output_failure_as_typed_retryable_error(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import apps.api.codex_worker_service as worker_module
    worker=CodexWorker(home_root=tmp_path,model=BUDGET.model)
    async def failed(*args,**kwargs):raise JobOutputInvalid('No private reply text')
    monkeypatch.setattr(worker,'turn',failed);monkeypatch.setattr(worker_module,'worker',worker)
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    bounded=transport()
    with TestClient(worker_module.app) as client:
        response=client.post('/internal/codex/turn',headers={'X-Codex-Worker-Secret':'synthetic'},json={
            'user_id':str(bounded.fence.user_id),'project_id':bounded.fence.project_id,
            'agent_role':'organiser','model':BUDGET.model,'bounded_job':bounded.model_dump(mode='json')})
    assert response.status_code==502 and response.headers['X-Error-Code']=='LIFETIME_JOB_OUTPUT_INVALID'
    assert response.headers['Retry-After']=='60'


def test_organiser_model_preferences_are_purpose_scoped_but_fence_is_complete():
    current=page();current['preferences']['active_question']='A conversation-only question'
    current['preferences']['excluded_topics']=['Private school']
    current['preferences']['paused_topics']=['Work']
    current['preferences']['unresolved_references']=['Uncertain relative']
    bounded=build_bounded_job_input(current,budget=BUDGET)
    model=json.loads(bounded.packet)['job_context']['preferences']
    assert not {'known_continuity','active_question','conversation_phase'} & model.keys()
    assert model['excluded_topics']==['Private school'] and model['paused_topics']==['Work']
    assert model['unresolved_references']==['Uncertain relative'] and model['privacy_complete']
    assert bounded.fence.preferences.active_question=='A conversation-only question'


def test_two_maximum_cjk_children_and_complete_privacy_fit_actual_prompt_schema():
    from apps.api.lifetime_memory_job_engine import _metadata_size
    current=page('merge',count=100)
    for child in current['child_groups']:
        child['title']='纲'*200
        for section in child['sections']:section['title']='中'
        for section in child['sections']:
            while len(section['title'])<200:
                section['title']+='中'
                if _metadata_size(child)>12000:
                    section['title']=section['title'][:-1];break
        assert 11997<=_metadata_size(child)<=12000
    preferences=current['preferences']
    privacy={'excluded_topics':['私'*5400],'paused_topics':[],'unresolved_references':[]}
    while len(serialize_packet(privacy).encode())<16384:privacy['excluded_topics'][0]+='x'
    assert len(serialize_packet(privacy).encode())==16384
    preferences.update(privacy,active_question='问'*2000,chosen_name='名'*200)
    # Match the actual CollectionJobWorker defaults, including its larger
    # framing reservation rather than relying on the smaller lane fixture.
    budget=BUDGET.model_copy(update={'framing_headroom':4096,'output_headroom':32768})
    bounded=build_bounded_job_input(current,budget=budget)
    tokens=job_request_tokens(bounded)
    assert tokens<=65536
    assert json.loads(bounded.packet)['job_context']['preferences']['excluded_topics']==privacy['excluded_topics']


def test_disabled_rollout_blocks_governed_job_before_home(tmp_path,monkeypatch):
    from apps.api.lifetime_memory_lane_engine import LaneGenerationPaused
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
    with pytest.raises(LaneGenerationPaused):run(tmp_path)
    assert not Connection.instances and not list(tmp_path.iterdir())
