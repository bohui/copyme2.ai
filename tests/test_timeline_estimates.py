"""Timeline estimates remain bounded, cited and distinct from stated dates."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from apps.api.memory_events import EventProposal, validate_extraction
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


def test_sql_estimates_keep_originals_and_author_corrections_take_precedence(sql):
    original=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}',{literal(SOURCE['text'])}")
    year=int(original['created_at'][:4]);ref=dict(source_id=original['id'],version=1,quote=original['text'])
    estimate={**ESTIMATE,'year_start':year-15,'year_end':year-13,'reference_year':year,'basis':[ref]}
    event=validate_extraction({'events':[{**proposal(),'source_refs':[ref],'temporal_estimate':estimate}]},[original],[])[0]
    saved=extract(sql,[original],[event])['events'][0]
    assert saved['temporal_estimate']['year_start']==year-15
    assert saved['temporal'].get('year_start') is None
    corrected=rpc(sql,'correct_user_memory_event',f"'project',{literal(saved['id'])},{saved['revision']},"+
        literal(dict(temporal=dict(expression='2010',precision='year',year_start=2010,year_end=2010)))+
        "::jsonb,'Actually I moved to Sydney in 2010.'")
    assert corrected['temporal']['year_start']==2010
    assert not corrected.get('temporal_estimate')
    assert corrected['yearConfidenceScore']==1
    newer=rpc(sql,'accept_user_narrator_source',"'project','00000000-0000-4000-8000-000000000002','I still live in Sydney.'")
    update={**event,'existing_id':saved['id'],'expected_revision':corrected['revision'],
        'source_refs':[dict(source_id=newer['id'],version=1,quote=newer['text'])]}
    final=extract(sql,[newer],[update])['events'][0]
    assert final['temporal']['year_start']==2010 and not final.get('temporal_estimate')
    assert final['yearConfidenceScore']==1


@pytest.mark.parametrize('change',[dict(confidence=1),dict(year_start=3000,year_end=2000),dict(reference_year=1800)])
def test_sql_rejects_invalid_or_unanchored_estimates(sql,change):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}',{literal(SOURCE['text'])}")
    ref=dict(source_id=source['id'],version=1,quote=source['text'])
    estimate={**ESTIMATE,'reference_year':int(source['created_at'][:4]),'basis':[ref],**change}
    raw={**proposal(),'source_refs':[ref],'temporal_estimate':estimate}
    result=rpc(sql,'apply_user_memory_events',f"'project',{literal([dict(id=source['id'],version=1)])}::jsonb,{literal([raw])}::jsonb",check=False)
    assert result.returncode!=0


def test_estimate_birth_dependency_is_removed_when_its_original_is_withdrawn(sql):
    birth=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I was born in 1983.'")
    source=rpc(sql,'accept_user_narrator_source',"'project','00000000-0000-4000-8000-000000000002','When I was little, I played at school.'")
    birth_ref=dict(source_id=birth['id'],version=1,quote=birth['text'])
    ref=dict(source_id=source['id'],version=1,quote=source['text'])
    estimate={**ESTIMATE,'year_start':1988,'year_end':1995,'reference_year':None,'basis':[birth_ref,ref]}
    saved=extract(sql,[birth,source],[dict(kind='period',title='Playing at school',source_refs=[ref],temporal_estimate=estimate)])['events'][0]
    rpc(sql,'change_user_narrator_source',f"'project',{literal(birth['id'])},1,'withdraw',null")
    after=rpc(sql,'read_user_memory_events',"'project'")['events'][0]
    assert after['id']==saved['id'] and after['status']=='unresolved'
    assert not after.get('temporal_estimate')
