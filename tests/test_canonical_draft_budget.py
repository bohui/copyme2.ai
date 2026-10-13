import asyncio
import copy
import json
from types import SimpleNamespace

import httpx

from apps.api.lifetime_memory_composer import _compose
from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, lane_request_tokens
from test_canonical_composer_provenance import controlled_draft
from test_lifetime_composer_capacity import page, Publisher


def test_mandarin_page_can_repair_evidence_within_the_reviewed_model_budget(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
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
            result = dict(ready_for_user_review=True, publication_approved=False, findings=[])
        return httpx.Response(200, json={'reply': json.dumps(result, ensure_ascii=False)})

    worker = SimpleNamespace(broker=Broker(), worker_url='https://synthetic.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(model), lane_publisher=Publisher())
    result = asyncio.run(_compose(current, worker))
    assert result['status'] == 'ready'
    assert result['preview']['text'] == text
    assert phases == ['prepare', 'draft', 'draft', 'review']
    assert max(inputs) <= 65536
