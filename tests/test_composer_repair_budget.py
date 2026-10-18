"""A growing repair must not strand a complete, otherwise bounded source page."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx

from apps.api import lifetime_memory_composer
from apps.api.canonical_composer import composition_request, validate_canonical_candidate
from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input, lane_request_tokens
from apps.api.memoir_preview import composer_call, skill_operation
from apps.api.progressive_composer import batch_job, summary_partition
from test_progressive_composer import batch_page, draft_all
from test_lifetime_memory_lane_engine import Publisher


def test_repair_that_exceeds_input_budget_regenerates_from_the_same_complete_request(monkeypatch):
    async def scenario():
        current = batch_page()
        request, _ = composition_request(batch_job(current))
        partition = summary_partition(current)
        request['context']['prepared_partitions'] = [dict(event_id=partition['id'],
            context='New bicycle memories.', source_refs=partition['source_refs'])]
        plan = await skill_operation('plan', request)
        candidate = draft_all({'request': request, 'plan': plan})
        candidate['chapters'][0]['blocks'][0]['text'] = 'An unsupported rewrite that must not survive.'
        validation = await validate_canonical_candidate(request, candidate)
        packet = dict(request=request, plan=plan, candidate=candidate, validation=validation, review=None)
        before = deepcopy(packet)
        budget = lifetime_memory_composer.lane_model_budget()
        plain = build_bounded_lane_input(current, phase='draft', packet=dict(request=request, plan=plan), budget=budget)
        repair = build_bounded_lane_input(current, phase='draft', packet=packet, budget=budget)
        threshold = (lane_request_tokens(plain) + lane_request_tokens(repair)) // 2
        monkeypatch.setattr(lifetime_memory_composer, 'lane_model_budget',
            lambda **_: budget.model_copy(update={'input_budget': threshold}))
        sent, writes = [], []
        def model(incoming):
            envelope = json.loads(incoming.content)['bounded_lane']
            actual = json.loads(envelope['packet'])['payload']
            sent.append(actual)
            assert actual == dict(request=request, plan=plan)
            return httpx.Response(200, json={'reply': json.dumps(draft_all(actual))})
        class Broker:
            async def rpc(self, name, **parameters):
                writes.append(name)
                assert name == 'record_lifetime_lane_output'
                return True
        runtime = SimpleNamespace(worker_url='https://controlled.invalid', worker_secret='synthetic',
            worker_transport=httpx.MockTransport(model), lifetime_bounded=True, lifetime_page=current,
            lane_broker=Broker(), lane_publisher=Publisher())
        result = await composer_call(runtime, SimpleNamespace(user_id=current['user_id']),
            current['project_id'], current['locale'], 'draft', packet)
        assert result['chapters'][0]['blocks'][0]['text'] != candidate['chapters'][0]['blocks'][0]['text']
        assert packet == before and len(sent) == 1
        assert writes == ['record_lifetime_lane_output']
    asyncio.run(scenario())


def test_observed_large_repair_fits_without_expanding_the_model_context(monkeypatch):
    monkeypatch.delenv('MEMOIR_LANE_INPUT_BUDGET', raising=False)
    budget = lifetime_memory_composer.lane_model_budget(composer=True)
    # The captured round-35 repair, including instructions/schema/framing, used 73,984.
    assert 73984 <= budget.input_budget
    assert budget.input_budget + budget.output_headroom + budget.framing_headroom <= budget.context_window
    assert budget.context_window == 131072
    assert lifetime_memory_composer.lane_model_budget().input_budget == 65536
    monkeypatch.setenv('MEMOIR_LANE_INPUT_BUDGET', '50000')
    assert lifetime_memory_composer.lane_model_budget(composer=True).input_budget == 50000
