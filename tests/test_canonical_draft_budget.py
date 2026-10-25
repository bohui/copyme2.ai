from controlled_composer_review import controlled_review
import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api.lifetime_memory_composer import _compose
from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, lane_request_tokens
from test_canonical_composer_provenance import controlled_draft
from test_lifetime_composer_capacity import page, Publisher


@pytest.mark.parametrize('fail', [False, True])
def test_canonical_phase_timings_include_success_and_failure_without_private_content(caplog, fail):
    from apps.api.memoir_preview import composer_call
    caplog.set_level('INFO', logger='apps.api.memoir_preview')
    current = page('composer')
    current['partition'] = dict(id='event', revision=1, kind='event', status='active', title='private event title',
        source_refs=[dict(source_id=current['source']['id'], version=1, quote=current['source']['text'],
                         char_start=0, char_end=len(current['source']['text']))])
    class Broker:
        async def rpc(self, name, **payload):
            assert name == 'record_lifetime_lane_output'
            return True
    result = dict(event_id='event', context='private prepared context', source_refs=current['partition']['source_refs'])
    def model(request):
        if fail:
            return httpx.Response(503, text='private provider detail')
        return httpx.Response(200, json={'reply': json.dumps(result)})
    runtime = SimpleNamespace(worker_url='https://synthetic.invalid', worker_secret='private-secret',
        worker_transport=httpx.MockTransport(model), lifetime_bounded=True, lifetime_page=current,
        lane_publisher=Publisher(), lane_broker=Broker())
    packet = {'partition': current['partition'], 'sources': [current['source']], 'preparation_id': 'a' * 64}
    call = composer_call(runtime, None, 'project', 'zh-CN', 'prepare', packet)
    if fail:
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(call)
    else:
        assert asyncio.run(call)['context'] == result['context']
    assert 'canonical_page phase=prepare page=0 elapsed_ms=' in caplog.text
    assert 'worker_elapsed_ms=' in caplog.text
    assert ('outcome=failed' if fail else 'outcome=completed') in caplog.text
    for text in ['private event title', 'private prepared context', 'private provider detail', 'private-secret', current['source']['text']]:
        assert text not in caplog.text


def test_mandarin_page_can_repair_evidence_within_the_reviewed_model_budget(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    # Keep exercising the stricter 64K setting rather than inheriting the
    # composer's existing 98K default; the product budget is not changed.
    monkeypatch.setenv('MEMOIR_LANE_INPUT_BUDGET', '65536')
    text = '我在承德长大。' * 250
    current = page('composer', text=text)
    source = current['source']
    current['partition'] = dict(id='event-budget', revision=1, kind='event', life_stage='childhood',
        status='active', title='承德的童年', source_refs=[dict(source_id=source['id'], version=1,
            quote=text, char_start=0, char_end=len(text))])
    checkpoints = {}
    phases = []
    inputs = []

    class Broker:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint':
                return copy.deepcopy(checkpoints.get(payload['p_key']))
            if name == 'save_memoir_checkpoint':
                checkpoints[payload['p_key']] = copy.deepcopy(payload['p_value'])
                return True
            assert name == 'record_lifetime_lane_output'
            return True

    def model(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])
        phase = bounded.phase
        packet = json.loads(bounded.packet)['payload']
        phases.append(phase)
        inputs.append(lane_request_tokens(bounded))
        assert bounded.budget.input_budget == 65536
        if phase == 'prepare':
            result = dict(event_id=current['partition']['id'], context='有原文支持的童年回忆。',
                source_refs=current['partition']['source_refs'])
        elif phase == 'draft':
            result = copy.deepcopy(controlled_draft(packet, text, '承德的童年'))
            if phases.count('draft') == 1:
                refs = copy.deepcopy(result['chapters'][0]['blocks'][0]['source_refs'])
                refs[0]['char_end'] -= 1
                result['chapters'][0]['blocks'][0]['source_refs'] = refs
            else:
                assert any(error['code'] == 'NONCANONICAL_EVIDENCE_SPAN'
                    for error in packet['validation']['errors'])
        else:
            result = controlled_review(packet)
        return httpx.Response(200, json={'reply': json.dumps(result, ensure_ascii=False)})

    worker = SimpleNamespace(broker=Broker(), worker_url='https://synthetic.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(model), lane_publisher=Publisher())
    result = asyncio.run(_compose(current, worker))
    assert result['status'] == 'ready'
    assert result['preview']['text'] == text
    assert phases == ['prepare', 'draft', 'draft', 'review']
    assert max(inputs) <= 65536
