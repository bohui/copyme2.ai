"""A size rejection must constrain the next generated selective summary."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from jsonschema import validate

from apps.api.lifetime_memory_composer import _summarize
from apps.api.lifetime_memory_lane_engine import lane_contract
from apps.api.lifetime_memory_summary import MAX_SUMMARY_BYTES, validate_summary


def summary_fixture():
    quote='茶馆门口买茶。'*10
    item={'text':'茶馆里的童年。'*7,'uncertainty':'记忆仍不确定。'*7,'source_refs':[
        {'source_id':'6ff628fc-d61c-4148-9072-ff71fa852183','version':1,'quote':quote,
         'char_start':None,'char_end':None}]}
    page={'lane_id':'owned-lane','source':{'id':item['source_refs'][0]['source_id'],'version':1,'text':quote,'char_start':0},
        'memory_summary':{'work_mode':'extract','prior':{'items':[]},'maintenance_id':'maintenance',
                          'revision':0,'through_sequence':1}}
    assert len(json.dumps({'items':[item]*14},ensure_ascii=False).encode())>MAX_SUMMARY_BYTES
    assert len(json.dumps({'items':[item]*8},ensure_ascii=False).encode())<MAX_SUMMARY_BYTES
    return page,item


def test_budget_retry_constrains_generation_and_keeps_original_evidence(monkeypatch):
    page,item=summary_fixture();original=deepcopy(page);calls=[]
    monkeypatch.setattr('apps.api.lifetime_memory_lane_engine.build_bounded_lane_input',
        lambda page,**kwargs:deepcopy(kwargs['packet']))
    async def provider(**kwargs):
        packet=kwargs['bounded_lane']
        _,schema=lane_contract('summarize','zh-CN',fence=page,retry_reason=packet.get('retry_reason'))
        value={'items':[deepcopy(item) for _ in range(min(14,schema['properties']['items']['maxItems']))]}
        validate(value,schema)
        calls.append(packet)
        return {'reply':json.dumps(value,ensure_ascii=False)}
    monkeypatch.setattr('apps.api.lifetime_memory_lane_engine.send_bounded_lane_request',provider)
    result=asyncio.run(_summarize(page,SimpleNamespace(worker_url='fixture',worker_secret='fixture')))
    assert len(calls)==2 and calls[1].pop('retry_reason')=='SUMMARY_BUDGET'
    assert calls[0]==calls[1] and page==original
    assert 0<len(result['items'])<14
    assert len(json.dumps(result,ensure_ascii=False).encode())<=MAX_SUMMARY_BYTES
    assert all(ref['quote']==page['source']['text'] and ref['char_start']==0
        for entry in result['items'] for ref in entry['source_refs'])


def test_budget_retry_does_not_relax_size_or_evidence_validation():
    page,item=summary_fixture()
    with pytest.raises(ValueError,match='byte budget'):
        validate_summary({'items':[item]*14},page)
    item['source_refs'][0]['source_id']='foreign-source'
    with pytest.raises(ValueError,match='unseen or ambiguous'):
        validate_summary({'items':[item]},page)
