from copy import deepcopy

import pytest

from apps.api.lifetime_memory_continuity import validate_governed_collector_result
from test_lifetime_memory_continuity import context, reply, update


@pytest.mark.parametrize('text,quote', [
    ('At our house I remember Ming.', 'Ming'),
    ('我记得大哥阿明，后来他搬去了珀斯。', '大哥阿明'),
])
def test_unique_current_quote_gets_original_offsets_without_changing_testimony(text, quote):
    ctx=context(text)
    item=update(ctx,quote=quote)
    item['char_start']+=1
    item['char_end']+=1
    raw=reply([item]);before=deepcopy(raw)
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
