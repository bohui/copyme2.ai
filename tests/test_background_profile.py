"""Profile target/evidence enforcement at the actual bounded worker transport."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api.background_profile import extract_profile, profile_contract, profile_packet, validate_profile
from apps.api.codex_worker_service import WorkerTurnInput
from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input
from test_lifetime_memory_lane_engine import BUDGET, page


def profile_page(text='I was born in 1960 in Hobart.'):
    current = page()
    current['source'].update(text=text, char_end=len(text), original_length=len(text))
    current['profile_context'] = {'revision': 4, 'target_round': 5, 'covered_round': 1,
        'source_frontier': 5, 'targets': ['birth_year', 'birth_place'],
        'reference': {'name': 'Joan', 'authority': {'name': 'explicit'}}, 'work_mode': 'extract'}
    return current


def proposal(current, field='birth_year', value=1960, quote=None):
    source = current['source']
    return {'profile_patch': [{'field': field, 'value': value, 'source_refs': [{
        'source_id': source['id'], 'version': source['version'],
        'quote': quote or source['text'], 'char_start': None, 'char_end': None}]}]}


def test_profile_contract_limits_targets_and_never_targets_saved_manual_reference():
    current = profile_page()
    instructions, schema = profile_contract(current)
    assert schema['$defs']['ProfileChange']['properties']['field']['enum'] == ['birth_year', 'birth_place']
    assert profile_packet(current)['profile_context']['reference']['name'] == 'Joan'
    with pytest.raises(ValueError, match='targets'):
        validate_profile(proposal(current, field='name', value='Other'), current)


def test_a_plain_conversation_evaluation_does_not_claim_a_scheduled_profile_skill():
    from apps.api.evaluation_cases import normalise_case
    assert normalise_case({'text': 'Hello'})['enabled_skills'] == []


@pytest.mark.parametrize('mutation', ['field', 'language', 'source', 'version', 'quote', 'bool', 'year', 'duplicate'])
def test_invalid_or_protected_profile_changes_are_rejected(mutation):
    current = profile_page()
    raw = proposal(current)
    change = raw['profile_patch'][0]
    if mutation == 'field':
        change['field'] = 'name'
    elif mutation == 'language':
        change['field'] = 'preferred_language'
    elif mutation in {'source', 'version', 'quote'}:
        change['source_refs'][0][{'source': 'source_id', 'version': 'version', 'quote': 'quote'}[mutation]] = (
            2 if mutation == 'version' else 'invented')
    elif mutation == 'bool':
        change['value'] = True
    elif mutation == 'year':
        change['value'] = 1700
    else:
        raw['profile_patch'].append(deepcopy(change))
    with pytest.raises(ValueError):
        validate_profile(raw, current)


def test_unicode_quotes_restore_absolute_offsets_and_repeated_words_require_a_span():
    current = profile_page('我出生在承德，后来回到承德。')
    current['source'].update(char_start=200, char_end=200 + len(current['source']['text']), original_length=300)
    raw = proposal(current, 'birth_place', '承德', quote='承德')
    with pytest.raises(ValueError, match='exact span'):
        validate_profile(raw, current)
    raw['profile_patch'][0]['source_refs'][0].update(char_start=4, char_end=6)
    ref = validate_profile(raw, current)['profile_patch'][0]['source_refs'][0]
    assert (ref['char_start'], ref['char_end']) == (204, 206)
    assert raw['profile_patch'][0]['source_refs'][0]['char_start'] == 4


@pytest.mark.parametrize('mode', ['skip', 'reply_only'])
def test_no_model_profile_dispositions_do_not_load_the_skill(monkeypatch, mode):
    current = profile_page()
    current['profile_context'].update(work_mode=mode, targets=[])
    monkeypatch.setattr('apps.api.background_profile.profile_contract', lambda _: pytest.fail('skill loaded'))
    result = asyncio.run(extract_profile(current, SimpleNamespace()))
    assert result == ({'profile_patch': [], 'skipped': True} if mode == 'skip' else {'profile_patch': []})


def test_actual_worker_request_preserves_fence_and_retries_only_the_same_original():
    current = profile_page()
    requests = []
    class Publisher:
        @asynccontextmanager
        async def guard(self, fence):
            assert fence['profile_context'] == current['profile_context']
            yield
    def provider(request):
        body = json.loads(request.content)
        WorkerTurnInput.model_validate(body)
        assert body['agent_role'] == 'memory_context'
        bounded = body['bounded_lane']
        assert bounded['phase'] == 'profile'
        requests.append(bounded)
        raw = proposal(current, 'name', 'Not writable') if len(requests) == 1 else proposal(current)
        return httpx.Response(200, json={'reply': json.dumps(raw)})
    worker = SimpleNamespace(worker_url='http://controlled.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(provider), lane_publisher=Publisher())
    result = asyncio.run(extract_profile(current, worker))
    assert result['profile_patch'][0]['value'] == 1960
    assert len(requests) == 2 and requests[0]['fence'] == requests[1]['fence']
    first = json.loads(requests[0]['packet'])
    second = json.loads(requests[1]['packet'])
    assert second['payload'].pop('retry_reason') == 'OUTPUT_SCHEMA'
    assert first == second


def test_profile_transport_rejects_payload_or_phase_substitution():
    current = profile_page()
    packet = profile_packet(current)
    packet['profile_context']['targets'].append('name')
    with pytest.raises(ValueError, match='authoritative'):
        build_bounded_lane_input(current, phase='profile', packet=packet, budget=BUDGET)
    from apps.api.lifetime_memory_lane_engine import lane_extraction_packet, LaneFence
    fence = LaneFence.model_validate({key: value for key, value in current.items() if key in LaneFence.model_fields})
    with pytest.raises(ValueError, match='another lane phase'):
        build_bounded_lane_input(current, phase='extract', packet=lane_extraction_packet(fence), budget=BUDGET)
