"""Timeline estimates remain bounded, cited and distinct from stated dates."""
from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest
from pydantic import ValidationError

from apps.api.memory_events import EventProposal, TemporalEstimate, extraction_schema, validate_extraction
from apps.api.two_lane_memory import extraction_contract
from test_agent_commit_postgres import database
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database  # noqa: F401
from test_shared_memory_events_postgres import TURN, extract, literal, rpc


SOURCE=dict(id='source',version=1,text='I have lived in Sydney for fourteen years.',created_at='2026-10-30T23:17:00Z')
REF=dict(source_id='source',version=1,quote=SOURCE['text'])
ESTIMATE=dict(year_start=2011,year_end=2013,age_start=None,age_end=None,confidence=.8,
    reference_year=2026,rationale='Fourteen years before the original narration, allowing rounding.',basis=[REF])


def proposal(**changes):
    return dict(kind='period',title='Sydney residence',source_refs=[REF],yearConfidenceScore=.8,
        temporal_estimate=deepcopy(ESTIMATE),**changes)


def test_cited_relative_year_estimate_is_saved_without_manufacturing_a_stated_date():
    event=validate_extraction({'events':[proposal()]},[SOURCE],[])[0]
    assert event['temporal_estimate']['year_start']==2011
    assert event['temporal_estimate']['confidence']==.8
    assert 'temporal' not in event


@pytest.mark.parametrize('field,value', [('confidence',0),('confidence',1),('confidence',True),
    ('year_start',0),('age_start',-1),('age_end',131),('basis',[]),('rationale','')])
def test_estimates_reject_invalid_ranges_and_missing_evidence(field,value):
    value={**ESTIMATE,field:value}
    with pytest.raises(ValidationError):
        EventProposal.model_validate({**proposal(),'temporal_estimate':value})


def test_relative_estimate_anchor_matches_an_original_source_capture_year():
    event=proposal()
    event['temporal_estimate']['reference_year']=2036
    with pytest.raises(ValueError,match='capture year'):
        validate_extraction({'events':[event]},[SOURCE],[])


def test_estimates_require_authorized_original_evidence_and_increasing_bounds():
    event=proposal()
    event['temporal_estimate']['basis']=[{**REF,'quote':'An assistant guessed this date.'}]
    with pytest.raises(ValueError,match='original'):
        validate_extraction({'events':[event]},[SOURCE],[])
    event=proposal()
    event['temporal_estimate'].update(year_start=2015,year_end=2010)
    with pytest.raises(ValueError,match='range'):
        EventProposal.model_validate(event)


@pytest.mark.parametrize('bounds', [
    dict(year_start=None), dict(year_end=None),
    dict(age_start=20), dict(age_end=40),
    dict(year_start=None, age_end=40), dict(year_start=None, year_end=None),
])
def test_model_schema_cannot_admit_incomplete_or_empty_estimated_ranges(bounds):
    estimate={**TemporalEstimate.model_validate(ESTIMATE).model_dump(mode='json'), **bounds}
    with pytest.raises(ValidationError):
        TemporalEstimate.model_validate(estimate)
    schema=extraction_contract(attribution=True,continuity=True)[1]
    validator=Draft202012Validator({'$defs':schema['$defs'],'$ref':'#/$defs/TemporalEstimate'})
    assert not validator.is_valid(estimate), 'The model schema permits the range rejected by the host'


@pytest.mark.parametrize('bounds', [
    {}, dict(year_start=2012,year_end=2012),
    dict(year_start=None,year_end=None,age_start=20,age_end=40),
    dict(age_start=20,age_end=40), dict(age_start=0,age_end=0),
])
def test_model_schema_preserves_supported_year_age_and_combined_estimates(bounds):
    estimate=TemporalEstimate.model_validate({**ESTIMATE,**bounds}).model_dump(mode='json')
    schema=extraction_schema()
    Draft202012Validator({'$defs':schema['$defs'],'$ref':'#/$defs/TemporalEstimate'}).validate(estimate)


def test_model_can_leave_an_unsupported_estimate_null_without_losing_the_event():
    schema=extraction_schema()
    field=schema['$defs']['EventProposal']['properties']['temporal_estimate']
    Draft202012Validator({'$defs':schema['$defs'],**field}).validate(None)
    assert EventProposal.model_validate({**proposal(),'temporal_estimate':None}).temporal_estimate is None


def test_model_draft_requires_a_number_and_confidence_even_without_a_timing_range():
    schema = extraction_contract(attribution=True, continuity=True)[1]
    validator = Draft202012Validator({'$defs':schema['$defs'],'$ref':'#/$defs/EventProposal'})
    draft = dict.fromkeys(schema['$defs']['EventProposal']['required'])
    draft.update(kind='period',title='Sydney residence',source_refs=[REF | dict(char_start=None,char_end=None,attribution=None)],
        locationConfidenceScore=0,yearConfidenceScore=0)
    basis = draft['source_refs']
    for hint in (dict(age=0,confidence=0,basis=basis),dict(year=2026,confidence=.3,basis=basis)):
        validator.validate({**draft,'timing_hint':hint})
    for hint in (None,dict(confidence=0,basis=basis),dict(age=43,basis=basis),
                 dict(age=43,year=2026,confidence=.3,basis=basis),dict(age='43',confidence=.3,basis=basis),
                 dict(age=131,confidence=.3,basis=basis),dict(year=2026,confidence=1.1,basis=basis)):
        assert not validator.is_valid({**draft,'timing_hint':hint})
    del draft['timing_hint']
    assert not validator.is_valid(draft)


@pytest.mark.parametrize('bounds,reason', [
    (dict(year_start=None,age_end=40),'TEMPORAL_ESTIMATE_RANGE'),
    (dict(year_start=2020,year_end=2010),'TEMPORAL_ESTIMATE_RANGE'),
    (dict(age_start=40,age_end=20),'TEMPORAL_ESTIMATE_RANGE'),
    (dict(year_start=None,year_end=None),'TEMPORAL_ESTIMATE_RANGE'),
    (None,'TIMING_HINT_REQUIRED'),
])
def test_invalid_estimate_retries_with_specific_range_error_and_same_original(bounds,reason,caplog):
    import asyncio
    import json
    from types import SimpleNamespace
    import httpx
    from apps.api.lifetime_memory_composer import _extract
    from test_lifetime_composer_capacity import page, Publisher

    current=page(text=SOURCE['text'])
    current['source']['created_at']=SOURCE['created_at']
    requests=[]
    class Broker:
        async def rpc(self,name,**payload):
            assert name=='read_lifetime_lane_policy_source'
            return deepcopy(current['source'])
    def model(request):
        bounded=json.loads(request.content)['bounded_lane']
        requests.append(bounded)
        packet=json.loads(bounded['packet'])['payload']
        if len(requests)>1:
            assert packet['retry_reason']==reason
        estimate={**ESTIMATE,'year_end':2026}
        if len(requests)==1 and bounds is not None:
            estimate.update(bounds)
        event={**proposal(),'temporal_estimate':estimate}
        if len(requests)>1 or bounds is not None:
            event['timing_hint']=dict(year=2026,confidence=.3,basis=[REF])
        return httpx.Response(200,json={'reply':json.dumps({'events':[event]})})
    worker=SimpleNamespace(broker=Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',
        worker_transport=httpx.MockTransport(model),lane_publisher=Publisher())
    result=asyncio.run(_extract(current,worker))
    assert len(requests)==2 and requests[0]['fence']==requests[1]['fence']
    first=json.loads(requests[0]['packet']);second=json.loads(requests[1]['packet'])
    assert second['payload'].pop('retry_reason')==reason
    assert first==second
    assert result['events'][0]['temporal_estimate']['year_end']==2026
    assert result['events'][0]['timing_hint']['year']==2026
    assert result['events'][0]['source_refs'][0]['quote']==SOURCE['text']
    assert 'temporal' not in result['events'][0]
    assert f'reason={reason}' in caplog.text
    assert SOURCE['text'] not in caplog.text and ESTIMATE['rationale'] not in caplog.text


def test_sql_estimates_keep_originals_and_author_corrections_take_precedence(sql):
    original=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}',{literal(SOURCE['text'])}")
    year=int(original['created_at'][:4]);ref=dict(source_id=original['id'],version=1,quote=original['text'])
    estimate={**ESTIMATE,'year_start':year-15,'year_end':year-13,'reference_year':year,'basis':[ref]}
    hint=dict(year=year,confidence=.3,basis=[ref])
    event=validate_extraction({'events':[{**proposal(),'source_refs':[ref],'temporal_estimate':estimate,'timing_hint':hint}]},[original],[])[0]
    saved=extract(sql,[original],[event])['events'][0]
    assert saved['temporal_estimate']['year_start']==year-15
    assert saved['timing_hint']==hint
    assert saved['temporal'].get('year_start') is None
    corrected=rpc(sql,'correct_user_memory_event',f"'project',{literal(saved['id'])},{saved['revision']},"+
        literal(dict(temporal=dict(expression='2010',precision='year',year_start=2010,year_end=2010)))+
        "::jsonb,'Actually I moved to Sydney in 2010.'")
    assert corrected['temporal']['year_start']==2010
    assert not corrected.get('temporal_estimate') and not corrected.get('timing_hint')
    assert corrected['yearConfidenceScore']==1
    newer=rpc(sql,'accept_user_narrator_source',"'project','00000000-0000-4000-8000-000000000002','I still live in Sydney.'")
    update={**event,'existing_id':saved['id'],'expected_revision':corrected['revision'],
        'source_refs':[dict(source_id=newer['id'],version=1,quote=newer['text'])]}
    final=extract(sql,[newer],[update])['events'][0]
    assert final['temporal']['year_start']==2010 and not final.get('temporal_estimate')
    assert not final.get('timing_hint')
    assert final['yearConfidenceScore']==1


@pytest.mark.parametrize('change',[dict(confidence=1),dict(year_start=3000,year_end=2000),dict(reference_year=1800)])
def test_sql_rejects_invalid_or_unanchored_estimates(sql,change):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}',{literal(SOURCE['text'])}")
    ref=dict(source_id=source['id'],version=1,quote=source['text'])
    estimate={**ESTIMATE,'reference_year':int(source['created_at'][:4]),'basis':[ref],**change}
    raw={**proposal(),'source_refs':[ref],'temporal_estimate':estimate}
    result=rpc(sql,'apply_user_memory_events',f"'project',{literal([dict(id=source['id'],version=1)])}::jsonb,{literal([raw])}::jsonb",check=False)
    assert result.returncode!=0


@pytest.mark.parametrize('field',['temporal_estimate','timing_hint'])
def test_estimate_birth_dependency_is_removed_when_its_original_is_withdrawn(sql,field):
    birth=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I was born in 1983.'")
    source=rpc(sql,'accept_user_narrator_source',"'project','00000000-0000-4000-8000-000000000002','When I was little, I played at school.'")
    birth_ref=dict(source_id=birth['id'],version=1,quote=birth['text'])
    ref=dict(source_id=source['id'],version=1,quote=source['text'])
    estimate={**ESTIMATE,'year_start':1988,'year_end':1995,'reference_year':None,'basis':[birth_ref,ref]}
    hint=dict(year=1991,confidence=.3,basis=[birth_ref,ref])
    saved=extract(sql,[birth,source],[{'kind':'period','title':'Playing at school','source_refs':[ref],
        field:estimate if field=='temporal_estimate' else hint}])['events'][0]
    rpc(sql,'change_user_narrator_source',f"'project',{literal(birth['id'])},1,'withdraw',null")
    after=rpc(sql,'read_user_memory_events',"'project'")['events'][0]
    assert after['id']==saved['id'] and after['status']=='unresolved'
    assert not after.get(field)
