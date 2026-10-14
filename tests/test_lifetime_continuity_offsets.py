from copy import deepcopy

import pytest

from apps.api.lifetime_memory_continuity import validate_governed_collector_result, governed_collector_schema
from test_lifetime_memory_continuity import context, reply, update


@pytest.mark.parametrize('text,quote', [
    ('At our house I remember Ming.', 'Ming'),
    ('我记得大哥阿明，后来他搬去了珀斯。', '大哥阿明'),
])
@pytest.mark.parametrize('end_shift',[1,2])
def test_unique_current_quote_gets_original_offsets_without_changing_testimony(text, quote, end_shift):
    ctx=context(text)
    item=update(ctx,quote=quote)
    item['char_start']+=1
    item['char_end']+=end_shift
    raw=reply([item])
    before=deepcopy(raw)
    result=validate_governed_collector_result(raw,ctx)
    ref=result['continuity_updates'][0]['data']['source_refs'][0]
    assert ref['char_start']==text.index(quote)
    assert ref['char_end']==text.index(quote)+len(quote)
    assert ref['quote']==text[ref['char_start']:ref['char_end']]==quote
    assert raw==before


def test_repeated_quote_with_wrong_position_remains_ambiguous():
    ctx=context('Ming left. Ming left.')
    item=update(ctx,quote='Ming left',char_start=1,char_end=10)
    with pytest.raises(ValueError,match='exact current narrator evidence'):
        validate_governed_collector_result(reply([item]),ctx)


@pytest.mark.parametrize('bad_start',[True,1.0,'1',-1])
def test_unique_quote_does_not_repair_malformed_coordinate_types(bad_start):
    ctx=context('I remember Ming.')
    item=update(ctx,quote='Ming',char_start=bad_start,char_end=14)
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]),ctx)


def test_model_schema_does_not_offer_global_controls_for_a_family_tree_permission_request():
    from jsonschema import Draft202012Validator, ValidationError
    text='Our children learned to sand scraps of wood, but I do not want their names stored in the family tree yet.'
    ctx=context(text)
    item=update(ctx,quote=text,kind='excluded_topic')
    schema=governed_collector_schema(ctx)['$defs']['_ContinuityUpdate']
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(item)


@pytest.mark.parametrize('text,kind',[
    ('Do not discuss my address.', 'excluded_topic'),
    ('我们先不聊学校。', 'paused_topic'),
    ('I promise to send the photograph.', 'commitment'),
])
def test_model_schema_still_accepts_exact_supported_direct_controls(text,kind):
    from jsonschema import Draft202012Validator
    ctx=context(text)
    Draft202012Validator(governed_collector_schema(ctx)['$defs']['_ContinuityUpdate']).validate(
        update(ctx,quote=text,kind=kind))
