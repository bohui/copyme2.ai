"""Offline requests reproduce repeated-evidence failures; no live provider."""
import asyncio
import hashlib
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
from jsonschema import Draft202012Validator
import pytest

from apps.api.lifetime_memory_composer import _extract
from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, run_bounded_lane
from test_conversation_reply_transport import events, sse
from test_lifetime_composer_capacity import page
from test_memory_context_transport import Publisher


@pytest.mark.parametrize('offset', [0, 2048])
@pytest.mark.parametrize('text,quote', [
    ('🌱 Notes. Copied words. Copied words.', 'Copied words.'),
    ('🌱笔记。重复句子。重复句子。', '重复句子。'),
    ('🌱 Notes.\nThe following words are filler from that fictional guide, not my memory.\nThe following words are filler from that fictional guide, not my memory.',
     'The following words are filler from that fictional guide, not my memory.'),
])
def test_ambiguous_span_repair_requires_coordinates_and_keeps_second_occurrence(monkeypatch, tmp_path, offset, text, quote):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    current = page(text=text)
    current['source'].update(char_start=offset, char_end=offset + len(text), original_length=offset + len(text))
    current['two_lane'] = dict(schema_version=1, task_version='two-lane-v1', execution_generation=1,
        phase_revision=0, work_mode='extract', reply_contract='reply-v2')
    current['attribution_context'] = dict(schema_version=1, decision='extract', reason='new_testimony', delivered_event=None)
    original = {**current['source'], 'text': 'x' * offset + text}
    publisher = Publisher()
    bodies = []

    class Broker:
        async def rpc(self, name, **params):
            assert name == 'read_lifetime_lane_policy_source'
            return original

    class Provider(httpx.AsyncBaseTransport):
        def __init__(self, bounded):
            self.bounded = bounded

        async def handle_async_request(self, request):
            body = json.loads(b''.join([chunk async for chunk in request.stream]))
            bodies.append(body)
            payload = json.loads(body['input'])['payload']
            assert payload['sources'] == [current['source']]
            schema = body['text']['format']['schema']
            from apps.api.lifetime_memory_lane_engine import lane_request_tokens
            from apps.api.lifetime_memory_context import serialize_packet
            budget = self.bounded.budget
            assert lane_request_tokens(self.bounded) == (budget.count(body['instructions'])
                + budget.count(body['input']) + budget.count(serialize_packet(schema)) + budget.framing_headroom)
            assert body['metadata']['schema_sha256'] == hashlib.sha256(
                json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            evidence = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/EvidenceRef'})
            ref = dict(source_id=current['source']['id'], version=1, quote=quote,
                char_start=None, char_end=None, attribution=None)
            if len(bodies) == 1:
                assert evidence.is_valid(ref), 'First attempt keeps the optional-offset contract'
            else:
                assert payload['retry_reason'] == 'PAGE_AMBIGUOUS'
                assert not evidence.is_valid(ref), 'Ambiguous repair still permits the null offsets that caused the failure'
                catalog = payload['quote_occurrences']
                assert catalog['coordinate_system'] == 'window_unicode_codepoints'
                item = next(row for row in catalog['quotes'] if row['quote'] == quote)
                assert len(item['spans']) == 2
                ref.update(item['spans'][1])
                evidence.validate(ref)
            result = dict(events=[], place_journeys=[], prepared_questions=[], continuity_updates=[],
                event_places=[], passage_dispositions=[dict(disposition='non_story', reason='no_supported_event', source_ref=ref)])
            return httpx.Response(200, content=sse(events(json.dumps(result))))

    async def worker(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])
        return httpx.Response(200, json=await run_bounded_lane(command=['must-not-start'], home_root=tmp_path,
            base_url='https://provider.invalid/v1', api_key='fixture-span-key', model=bounded.budget.model,
            bounded_lane=bounded, publisher=publisher, provider_transport=Provider(bounded), timeout=5))

    scope = SimpleNamespace(broker=Broker(), worker_url='https://worker.invalid', worker_secret='fixture',
        worker_transport=httpx.MockTransport(worker), lane_publisher=publisher)
    result = asyncio.run(_extract(deepcopy(current), scope))
    assert len(bodies) == 2
    ref = result['passage_dispositions'][0]['source_ref']
    expected = text.find(quote, text.index(quote) + 1)
    assert (ref['char_start'], ref['char_end']) == (offset + expected, offset + expected + len(quote))
    assert original['text'][ref['char_start']:ref['char_end']] == quote


def test_quote_catalog_is_bounded_original_data_and_not_accepted_from_a_caller():
    from apps.api.lifetime_memory_lane_engine import (build_bounded_lane_input,
        lane_contract, lane_extraction_packet, lane_request_tokens, source_quote_occurrences)
    from apps.api.lifetime_memory_context import serialize_packet
    from test_lifetime_memory_lane_engine import BUDGET, fence_for
    text = ''.join(f'笔记[{i}]' + '字' * 45 + '。' for i in range(30)) + '重复。重复。'
    current = page(text=text)
    fence = fence_for(current)
    packet = lane_extraction_packet(fence)
    original = deepcopy(packet)
    normal = build_bounded_lane_input(current, phase='extract', packet=packet, budget=BUDGET)
    assert 'quote_occurrences' not in json.loads(normal.packet)['payload']
    for reason in ('DATE_NUMERIC', 'OUTPUT_SCHEMA'):
        ordinary = build_bounded_lane_input(current, phase='extract', packet={**packet, 'retry_reason': reason}, budget=BUDGET)
        assert 'quote_occurrences' not in json.loads(ordinary.packet)['payload']
        _, schema = lane_contract('extract', fence.locale, fence=fence, retry_reason=reason)
        assert Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/EvidenceRef'}).is_valid(
            dict(source_id=current['source']['id'], version=1, quote='重复。', char_start=None, char_end=None, attribution=None))
    packet['retry_reason'] = 'PAGE_AMBIGUOUS'
    repair = build_bounded_lane_input(current, phase='extract', packet=packet, budget=BUDGET)
    payload = json.loads(repair.packet)['payload']
    catalog = payload['quote_occurrences']
    assert catalog == source_quote_occurrences(current['source'])
    assert catalog['source_id'] == current['source']['id'] and catalog['version'] == 1
    assert len(serialize_packet(catalog).encode('utf-8')) <= 8192
    assert len(catalog['quotes']) <= 16
    assert catalog['quotes'][0]['quote'] == '重复。', 'Repeated quotes get priority over unique sentences'
    for item in catalog['quotes']:
        assert 1 <= len(item['spans']) <= 32
        for span in item['spans']:
            assert text[span['char_start']:span['char_end']] == item['quote']
    assert {key: value for key, value in payload.items() if key not in {'retry_reason', 'quote_occurrences'}} == original
    assert 'quote_occurrences' not in packet, 'The builder must not mutate its caller'
    for field, value in [('source_id', 'foreign'), ('version', 2), ('coordinate_system', 'byte_offsets')]:
        forged = deepcopy(payload)
        forged['quote_occurrences'][field] = value
        with pytest.raises(ValueError, match='authoritative page evidence'):
            build_bounded_lane_input(current, phase='extract', packet=forged, budget=BUDGET)
    forged = deepcopy(payload)
    forged['quote_occurrences']['quotes'][0]['spans'][0]['char_start'] += 1
    with pytest.raises(ValueError, match='authoritative page evidence'):
        build_bounded_lane_input(current, phase='extract', packet=forged, budget=BUDGET)
    limit = lane_request_tokens(repair)
    with pytest.raises(ValueError, match='budget'):
        build_bounded_lane_input(current, phase='extract', packet=packet,
            budget=BUDGET.model_copy(update={'input_budget': limit - 1}))
    many = source_quote_occurrences({**current['source'], 'text': 'x.' * 1000})
    assert len(many['quotes'][0]['spans']) == 32
    for malformed in (None, {}, {'text': None}):
        with pytest.raises(ValueError, match='source window'):
            source_quote_occurrences(malformed)
    for bad in ('', 'x' * 2305):
        with pytest.raises(ValueError, match='source window'):
            source_quote_occurrences({**current['source'], 'text': bad})
