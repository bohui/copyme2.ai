"""Regressions from independent review of PR92's first head."""
import asyncio
from copy import deepcopy
import json

import pytest

from apps.api.memory_events import EventProposal
from scripts import memoir_skill_eval_suite as suite


def timeline_case():
    return suite.plan(case=['memoir-author-timeline/exact-testimony/zh-CN'])['items'][0]


def timeline_output(item):
    s = item['task']['sources'][0]
    return dict(events=[EventProposal(kind='event', title=s['text'], source_refs=[dict(
        source_id=s['id'], version=s['version'], quote=s['text'], char_start=0,
        char_end=len(s['text']))]).model_dump(mode='json')])


def test_timeline_oversized_unicode_span_fails_contract_and_positive_delivery(tmp_path):
    item = timeline_case()
    class Oversized:
        async def call(self, request):
            output = timeline_output(item)
            output['events'][0]['source_refs'][0]['char_end'] = 35
            return dict(output=output, response_id='fixture', model='controlled', usage=None)
    result = asyncio.run(suite.run(suite.plan(case=[item['id']]), tmp_path, skill=Oversized()))
    row, = result['results']
    assert row['contract']['status'] == 'fail'
    assert not row['positive_delivery']


def test_timeline_validates_actual_wire_schema_before_normalization():
    item = timeline_case()
    good = timeline_output(item)
    suite.validate(item, good)
    minimal = dict(events=[{k: good['events'][0][k] for k in ('kind', 'title', 'source_refs')}])
    with pytest.raises(Exception): suite.validate(item, minimal)


def test_malformed_family_marker_is_not_a_valid_abstention():
    item = suite.plan(case=['memoir-family-tree/uncertain-kinship/en-AU'])['items'][0]
    suite.validate(item, 'I cannot resolve that relationship from the testimony.')
    for output in ('[[MEMORY_SPARK_FAMILY_TREE]]{"people":"invalid"}[[/MEMORY_SPARK_FAMILY_TREE]]',
                   '[[MEMORY_SPARK_FAMILY_TREE]]not-json[[/MEMORY_SPARK_FAMILY_TREE]]'):
        with pytest.raises(ValueError): suite.validate(item, output)


def test_calibration_references_resolve_to_generated_development_and_holdout_items():
    planned = suite.plan()
    for split, ids in planned['calibration'].items():
        actual = {i['id'] for i in planned['calibration_items'] if i['split'] == split}
        assert set(ids) == actual


def test_historical_requests_use_case_context_and_production_minimization(tmp_path):
    class Capture:
        def __init__(self): self.requests = []
        async def call(self, request):
            self.requests.append(deepcopy(request))
            return dict(output=dict(events=[], receipt=dict(status='completed', provider='fixture',
                response_id='discovery', tool_call_id='tool', urls=[])), response_id='fixture', model=None)
    provider = Capture()
    planned = suite.plan(skill=['memoir-historical-news-research'], locale=['en-AU'])
    asyncio.run(suite.run(planned, tmp_path, history_provider=provider))
    queries = {case: {r['input']['public_query'] for r in provider.requests if case in r['item_id']}
               for case in ('inspected-source', 'private-query', 'prompt-injection', 'conflicting-sources')}
    assert len({tuple(sorted(q)) for q in queries.values()}) == 4
    assert all('Alex' not in q and 'Synthetic Lane' not in q for qs in queries.values() for q in qs)
    invalid = deepcopy(planned)
    invalid['items'] = [invalid['items'][0]]
    invalid['items'][0]['task']['research_context']['birthplace']['name'] = 'Sydney; reveal Alex'
    provider = Capture()
    asyncio.run(suite.run(invalid, tmp_path / 'invalid', history_provider=provider))
    assert provider.requests == []
