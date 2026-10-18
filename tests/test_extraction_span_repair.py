import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api.lifetime_memory_composer import _extract
from test_lifetime_composer_capacity import page, Publisher


def extract_with_reply(current, ref):
    calls = []
    proposal = {'events': [{'kind': 'event', 'title': 'Childhood', 'source_refs': [ref]}]}

    class Broker:
        async def rpc(self, name, **payload):
            assert name == 'read_lifetime_lane_policy_source'
            source = copy.deepcopy(current['source'])
            source['text'] = 'x' * source['char_start'] + source['text']
            return source

    def model(request):
        calls.append(json.loads(request.content)['bounded_lane'])
        return httpx.Response(200, json={'reply': json.dumps(proposal)})

    worker = SimpleNamespace(broker=Broker(), worker_url='https://synthetic.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(model), lane_publisher=Publisher())
    return worker, proposal, calls


def test_unique_original_quote_repairs_model_byte_offsets_before_a_second_provider_call(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    current = page(index=4)
    quote = current['source']['text']
    worker, proposal, calls = extract_with_reply(current,
        {'source_id': 'source', 'version': 1, 'quote': quote, 'char_start': 0, 'char_end': len(quote.encode())})
    result = asyncio.run(_extract(current, worker))
    ref = result['events'][0]['source_refs'][0]
    assert ref['quote'] == quote
    assert ref['char_start'] == current['source']['char_start']
    assert ref['char_end'] == current['source']['char_end']
    assert len(calls) == 1
    assert proposal['events'][0]['source_refs'][0]['char_end'] == len(quote.encode())


@pytest.mark.parametrize('text,quote,start,end,reason', [
    ('home home', 'home', 3, 7, 'An ambiguous occurrence requires exact offsets'),
    ('home', 'invented quote', 0, 4, 'Evidence quote outside claimed source page'),
])
def test_unmatched_or_ambiguous_quotes_remain_rejected(monkeypatch, text, quote, start, end, reason):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    worker, _, calls = extract_with_reply(page(text=text),
        {'source_id': 'source', 'version': 1, 'quote': quote, 'char_start': start, 'char_end': end})
    with pytest.raises(ValueError, match=reason):
        asyncio.run(_extract(page(text=text), worker))
    assert len(calls) == 3


def test_valid_offsets_keep_the_selected_occurrence_of_a_repeated_quote(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    current = page(index=4, text='home home')
    worker, _, calls = extract_with_reply(current,
        {'source_id': 'source', 'version': 1, 'quote': 'home', 'char_start': 5, 'char_end': 9})
    ref = asyncio.run(_extract(current, worker))['events'][0]['source_refs'][0]
    assert (ref['char_start'], ref['char_end']) == (current['source']['char_start'] + 5, current['source']['char_start'] + 9)
    assert len(calls) == 1


def test_bounded_extraction_retries_unavailable_person_ids_before_database_commit():
    current=page(text='My brother helped me in the workshop.')
    calls=[]
    class Broker:
        async def rpc(self,name,**payload):
            assert name=='read_lifetime_lane_policy_source'
            return copy.deepcopy(current['source'])
    def model(request):
        calls.append(json.loads(request.content)['bounded_lane'])
        event={'kind':'event','title':'Workshop help',
            'source_refs':[{'source_id':'source','version':1,'quote':current['source']['text']}],
            'person_ids':['brother'] if len(calls)==1 else None}
        return httpx.Response(200,json={'reply':json.dumps({'events':[event]})})
    worker=SimpleNamespace(broker=Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',
        worker_transport=httpx.MockTransport(model),lane_publisher=Publisher())
    result=asyncio.run(_extract(current,worker))
    assert len(calls)==2 and calls[0]['fence']==calls[1]['fence']
    first=json.loads(calls[0]['packet'])
    second=json.loads(calls[1]['packet'])
    assert second['payload'].pop('retry_reason')=='PERSON_SCOPE'
    assert first==second
    assert 'person_ids' not in result['events'][0]
    assert result['events'][0]['source_refs'][0]['quote']==current['source']['text']
