import pytest
from jsonschema import ValidationError, validate

from apps.api.interview_plan import collector_schema, validate_collector_result
from test_lifetime_memory_continuity import context, reply


@pytest.mark.parametrize('field,value', [('life_stage','childhood'),('year',1984),('event_id','missing-event')])
def test_schema_prevents_pointers_without_current_canonical_evidence(field,value):
    ctx=context()
    candidate=reply()
    candidate['plan']['candidates'][0]['context'][field]=value
    with pytest.raises(ValidationError):
        validate(candidate,collector_schema(ctx))


def test_schema_and_runtime_accept_current_canonical_metadata_and_nulls():
    ctx=context()
    ctx['events']=[{'id':'event','status':'active','life_stage':'childhood',
        'temporal':{'year_start':1984,'year_end':1985}}]
    candidate=reply()
    candidate['plan']['candidates'][0]['context'].update(event_id='event',life_stage='childhood',year=1984)
    candidate['plan']['active_event_id']='event'
    validate(candidate,collector_schema(ctx))
    assert validate_collector_result(candidate,ctx)['reply']
    validate(reply(),collector_schema(ctx))
