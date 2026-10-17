"""Verify the live suite cannot substitute plausible output for model evidence."""
import asyncio
from copy import deepcopy
import json
import time

import httpx
import pytest

from scripts.memoir_live_skill_cases import cases, validate_case
from scripts.run_memoir_live_skills import LiveProvider, manifest, provider_rejection, json_framing_kind


def provider(tmp_path):
    receipt = {'calls': []}
    config = {'MEMORY_SPARK_LLM_MODEL': 'fixture-model', 'MEMORY_SPARK_LLM_API_KEY': 'private-test-key',
              'MEMORY_SPARK_LLM_BASE_URL': 'https://gateway.test/v1'}
    return LiveProvider(config, receipt, tmp_path, timeout=5, deadline=time.monotonic() + 10,
                        max_calls=1, effort='max')


def use_transport(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
                        client_type(transport=httpx.MockTransport(handler), **kwargs))


def profile_reply(case):
    source = case['input']['source']
    return {'profile_patch': [dict(field=field, value=value, source_refs=[dict(
        source_id=source['id'], version=source['version'], quote=source['text'],
        char_start=0, char_end=len(source['text']))]) for field, value in case['expected'].items()]}


def response(text=None, **kwargs):
    if text is None:
        text = json.dumps(profile_reply(cases()[0]))
    return {'id': 'resp_fixture', 'status': 'completed', 'model': 'actually-served-model',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}], **kwargs}


def test_every_checked_in_skill_has_a_live_case():
    covered = {c['skill'] for c in cases()} | {'memoir-composer', 'historical-news-research', 'place-photo-research'}
    assert covered == set(manifest()['skills'])


def test_real_completion_evidence_and_schema_are_required(monkeypatch, tmp_path):
    live = provider(tmp_path)
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response(usage={'input_tokens': 2, 'output_tokens': 3}))
    use_transport(monkeypatch, handle)
    case = cases()[0]
    value, _ = asyncio.run(live.call(case['id'], case['skill'], case['instructions'], case['input'], case['schema']))
    validate_case(case, value)
    record, = live.receipt['calls']
    assert record['status'] == 'completed' and record['served_model'] == 'actually-served-model'
    assert record['provider_response_id'] == 'resp_fixture' and record['usage']['output_tokens'] == 3
    sent = json.loads(requests[0].content)
    assert sent['store'] is False and sent['text']['format']['strict'] is True
    assert sent['reasoning']['effort'] == 'max'
    assert 'private-test-key' not in (tmp_path / 'receipt.json').read_text()


def test_composer_uses_its_configured_background_route_and_effort(monkeypatch, tmp_path):
    live = provider(tmp_path)
    live.config.update(MEMORY_SPARK_MEMOIR_COMPOSER_MODEL='memoir-luna-low',
                       MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT='low')
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response(text='{}'))
    use_transport(monkeypatch, handle)
    asyncio.run(live.call('composer', 'memoir-composer', 'test', {}))
    assert requests[0]['model'] == 'memoir-luna-low'
    assert requests[0]['reasoning']['effort'] == 'low'
    assert live.receipt['calls'][0]['requested_model'] == 'memoir-luna-low'


@pytest.mark.parametrize('payload', [response(status='incomplete'), response(id=None),
    response(text='{"profile_patch":[{"field":"preferred_language","value":"en-AU","source_refs":[]}]}'), response(text='private-test-key'),
    response(id='private-test-key'), response(usage={'unexpected': 'private-test-key'})])
def test_incomplete_invalid_or_secret_output_cannot_pass(monkeypatch, tmp_path, payload):
    live = provider(tmp_path)
    use_transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    case = cases()[0]
    with pytest.raises(Exception):
        asyncio.run(live.call(case['id'], case['skill'], case['instructions'], case['input'], case['schema']))
    assert live.receipt['calls'][0]['status'] == 'failed'
    assert 'private-test-key' not in (tmp_path / 'receipt.json').read_text()


def test_failed_dispatch_consumes_budget_and_never_retries(monkeypatch, tmp_path):
    live = provider(tmp_path)
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(429, text='private provider detail')
    use_transport(monkeypatch, handle)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(live.call('one', 'memoir-memory-context', 'test', {}))
    with pytest.raises(RuntimeError, match='budget'):
        asyncio.run(live.call('two', 'memoir-memory-context', 'test', {}))
    assert len(requests) == len(live.receipt['calls']) == 1
    assert 'private provider detail' not in (tmp_path / 'receipt.json').read_text()


@pytest.mark.parametrize('case', [c for c in cases() if c['validator'] == 'equal'], ids=lambda c: c['id'])
def test_deterministic_and_admission_semantics_are_checked(case):
    validate_case(case, case['expected'])
    changed = dict(case['expected'])
    key = next(k for k, v in changed.items() if isinstance(v, bool))
    changed[key] = not changed[key]
    with pytest.raises(ValueError, match='semantic_mismatch'):
        validate_case(case, changed)


def test_place_markers_must_cover_only_current_named_places():
    case = next(c for c in cases() if c['validator'] == 'journey')
    reply = 'One place.\n[[MEMORY_SPARK_PLACE_JOURNEY]]' + json.dumps(
        {'schema_version': 1, 'place': 'Sydney', 'hierarchy': ['Earth', 'Australia', 'Sydney'],
         'granularity': 'city'}) + '[[/MEMORY_SPARK_PLACE_JOURNEY]]'
    with pytest.raises(ValueError, match='place_coverage'):
        validate_case(case, reply)


def test_rejection_categories_never_retain_provider_exception_details():
    assert provider_rejection(json.dumps({'error': {'message': 'private secret; tool_choice is unsupported'}})) == 'tool_choice_rejected'
    assert provider_rejection(b'private secret') == 'unclassified_provider_rejection'


def test_duplicate_json_is_diagnosed_without_silently_accepting_a_document(monkeypatch, tmp_path):
    live = provider(tmp_path)
    reply = '{"profile_patch":[]}' * 4
    use_transport(monkeypatch, lambda request: httpx.Response(200, json=response(text=reply)))
    case = cases()[0]
    with pytest.raises(json.JSONDecodeError):
        asyncio.run(live.call(case['id'], case['skill'], case['instructions'], case['input'], case['schema']))
    assert live.receipt['calls'][0]['json_failure_kind'] == 'repeated_json_documents'
    assert json_framing_kind('{}{"different":true}') == 'multiple_json_documents'


@pytest.mark.parametrize('case', [c for c in cases() if c['validator'] == 'profile'], ids=lambda c: c['id'])
def test_profile_probes_check_expected_changes_and_exact_window_evidence(case):
    original = deepcopy(case['input'])
    reply = profile_reply(case)
    validate_case(case, reply)
    assert case['input'] == original
    if reply['profile_patch']:
        missing = deepcopy(reply)
        missing['profile_patch'].pop()
        with pytest.raises(ValueError, match='profile_semantic_mismatch'):
            validate_case(case, missing)


@pytest.mark.parametrize('mutation', ['absolute', 'utf8', 'quote', 'source', 'version', 'null',
                                     'duplicate', 'unrelated_quote', 'protected', 'language', 'extra'])
def test_profile_probes_reject_fabricated_or_protected_outputs(mutation):
    case = next(c for c in cases() if c['id'] == 'memory-profile-checkpoint-zh-CN')
    reply = profile_reply(case)
    change = reply['profile_patch'][0]
    ref = change['source_refs'][0]
    if mutation == 'absolute':
        ref['char_start'] += case['input']['source']['char_start']
        ref['char_end'] += case['input']['source']['char_start']
    elif mutation == 'utf8':
        ref['char_end'] = len(ref['quote'].encode())
    elif mutation == 'quote':
        ref['quote'] = 'Not original testimony'
    elif mutation == 'source':
        ref['source_id'] = 'saved-profile-reference'
    elif mutation == 'version':
        ref['version'] += 1
    elif mutation == 'null':
        ref['char_start'] = ref['char_end'] = None
    elif mutation == 'duplicate':
        reply['profile_patch'].append(deepcopy(change))
    elif mutation == 'unrelated_quote':
        ref.update(quote='🌱', char_start=0, char_end=1)
    elif mutation == 'protected':
        change.update(field='birth_year', value=1960)
    elif mutation == 'language':
        change.update(field='preferred_language', value='zh-CN')
    else:
        reply['completed_rounds'] = 10
    with pytest.raises(Exception):
        validate_case(case, reply)


def test_checkpoint_probes_use_earlier_originals_and_host_target_allowlists():
    profiles = [c for c in cases() if c['validator'] == 'profile']
    assert all(c['input']['source']['sequence'] < c['input']['profile_context']['target_round']
               for c in profiles if 'checkpoint-' in c['id'])
    for case in profiles:
        assert case['schema']['$defs']['ProfileChange']['properties']['field']['enum'] == case['input']['profile_context']['targets']
    assert not any(c['validator'] == 'language' or c['skill'] == 'app-auto-localization' for c in cases())
