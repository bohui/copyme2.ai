"""Cross-stack contracts: canonical event lanes and legacy source-claim routing."""
import asyncio
import json

import pytest
from pydantic import ValidationError

from apps.api.codex_runtime import CodexRuntime, build_workspace_extraction_prompt
from apps.api.codex_worker_service import WorkerTurnInput
from apps.api.memory_events import extraction_instructions, validate_extraction


def event(title, quote, **reference):
    return {'kind': 'event', 'title': title, 'source_refs': [
        {'source_id': 'original', 'version': 1, 'quote': quote, **reference}
    ]}


def approved(text, proposals):
    return validate_extraction({'events': proposals}, [
        {'id': 'original', 'version': 1, 'text': text, 'status': 'active'}
    ], [])


@pytest.mark.parametrize('purchase_title', ['Purchase of house', 'Property acquisition', 'Becoming a homeowner'])
def test_canonical_exact_quotes_preserve_purchase_but_veto_same_year_sale(purchase_title):
    purchase = 'I bought a house in 1980.'
    sale = 'I sold the house in 1980.'
    text = purchase + ' ' + sale + ' Please do not add this event to my timeline.'
    result = approved(text, [event(purchase_title, purchase), event('Sale of house', sale)])
    assert [item['title'] for item in result] == [purchase_title]
    assert 'source_claim_id' not in json.dumps(result)
    assert '_resolved_source_span_indices' not in json.dumps(result)


def test_canonical_later_event_survives_prior_item_veto():
    first, later = 'I sold my house in 1980.', 'I bought another house in 1990.'
    text = first + ' Please do not add this event to my timeline. ' + later
    assert [item['title'] for item in approved(text, [event('New home', later)])] == ['New home']
    assert approved(text, [event('Old home sale', first)]) == []


def test_canonical_broad_veto_cannot_be_bypassed_by_exact_quote():
    quote = 'I bought a house in 1980.'
    assert approved(quote + ' Do not add events to my timeline.', [event('Purchase', quote)]) == []


def test_canonical_repeated_quote_needs_span_when_one_occurrence_is_vetoed():
    quote = 'I bought a house in 1980.'
    text = quote + ' ' + quote + ' Please do not add this event to my timeline.'
    assert approved(text, [event('Ambiguous purchase', quote)]) == []
    first = event('First purchase', quote, char_start=0, char_end=len(quote))
    assert [item['title'] for item in approved(text, [first])] == ['First purchase']
    offset = len(quote) + 1
    second = event('Second purchase', quote, char_start=offset, char_end=offset + len(quote))
    assert approved(text, [second]) == []


def test_canonical_full_turn_quote_cannot_hide_a_vetoed_claim():
    text = 'I bought a house in 1980. I sold the house in 1980. Do not add this event to my timeline.'
    assert approved(text, [event('Home', text)]) == []


@pytest.mark.parametrize('quote', [
    'My father remembers my first day at school.',
    'Aunt June recalls my birth in Hobart.',
    '父亲记得我第一天上学的情景。',
])
def test_canonical_attributed_claim_honours_item_veto_without_first_person_gate(quote):
    text = quote + ' Please do not add this event to my timeline.'
    assert approved(text, [event('Attributed memory', quote)]) == []
    assert len(approved(quote, [event('Attributed memory', quote)])) == 1


def test_canonical_attributed_veto_does_not_shift_back_to_allowed_author_claim():
    allowed, blocked = 'I bought a house in 1980.', 'Aunt June recalls the sale in 1980.'
    text = allowed + ' ' + blocked + ' Please do not add this event to my timeline.'
    assert [item['title'] for item in approved(text, [event('Purchase', allowed), event('Sale', blocked)])] == ['Purchase']


@pytest.mark.parametrize('field', ['temporal', 'stage_evidence', 'relations'])
def test_canonical_veto_applies_to_placement_and_relation_evidence(field):
    allowed, blocked = 'I bought a house.', 'I sold the house in 1990.'
    text = allowed + ' ' + blocked + ' Please do not add this event to my timeline.'
    proposal = event('Purchase', allowed)
    ref = {'source_id': 'original', 'version': 1, 'quote': blocked}
    saved = []
    if field == 'temporal':
        proposal['temporal'] = {'expression': '1990', 'precision': 'year', 'year_start': 1990, 'basis': [ref]}
    elif field == 'stage_evidence':
        proposal.update(life_stage='midlife', stage_evidence=[ref])
    else:
        proposal['relations'] = [{'kind': 'before', 'event_id': 'saved', 'source_refs': [ref]}]
        saved = [{'id': 'saved', 'revision': 1, 'kind': 'event'}]
    source = {'id': 'original', 'version': 1, 'text': text}
    assert validate_extraction({'events': [proposal]}, [source], saved) == []


@pytest.mark.parametrize('field', ['source_claim_id', '_source_claim_id', '_resolved_source_span_indices'])
def test_canonical_schema_rejects_legacy_private_metadata(field):
    proposal = event('Purchase', 'I bought a house in 1980.')
    proposal[field] = 'c0'
    with pytest.raises(ValidationError):
        approved('I bought a house in 1980.', [proposal])


def test_canonical_and_legacy_skill_contracts_are_separate():
    canonical = extraction_instructions()
    legacy = build_workspace_extraction_prompt(
        '(none)', family_enabled=True, source_text='I bought a house in 1980.'
    )
    assert '{"events": [...]}' in canonical
    assert 'source_claim_id' not in canonical
    assert 'source_claim_id' in legacy
    assert '- c0: I bought a house in 1980' in legacy


@pytest.mark.parametrize('field', ['source_claim_id', '_source_claim_id'])
def test_explicit_null_legacy_claim_is_not_absent_metadata(field):
    from apps.api.codex_runtime import _sanitize_author_timeline_markers
    item = {'id': 'purchase', 'kind': 'event', 'title': 'Bought a house',
            'date_expression': '1980', field: None}
    marker = '[[MEMORY_SPARK_AUTHOR_TIMELINE]]' + json.dumps({'timeline': [item]}) + '[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'
    assert _sanitize_author_timeline_markers(marker, 'I bought a house in 1980.') == ''


def test_canonical_place_recovery_prompt_retains_place_only_contract():
    prompt = build_workspace_extraction_prompt(
        '(none)', canonical_events=True, focus='place_journey',
        source_text='I moved to Hobart.', family_enabled=True,
    )
    assert 'Focused place-journey recovery pass' in prompt
    assert 'Do not reuse a saved place' in prompt
    assert 'source_claim_id' not in prompt
    assert '[[MEMORY_SPARK_AUTHOR_TIMELINE]]' not in prompt


def test_worker_input_preserves_both_stack_features():
    model = WorkerTurnInput(
        user_id='11111111-1111-4111-8111-111111111111',
        text='I moved to Hobart.', canonical_events=True,
        agent_role='author_timeline', extraction_focus='place_journey',
        composer_phase='prepare', preparation_id='a' * 64,
    )
    assert model.canonical_events is True
    assert model.agent_role == 'author_timeline'


@pytest.mark.parametrize('role,canonical,focus', [
    ('workspace', False, 'author_timeline'),
    ('workspace', True, 'place_journey'),
    ('author_timeline', True, None),
])
def test_actual_worker_keeps_prompt_and_output_contract_for_each_lane(tmp_path, monkeypatch, role, canonical, focus):
    from apps.api.codex_worker_service import CodexWorker
    observed = {}

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, params):
            assert method == 'thread/start'
            assert params['ephemeral'] is True
            observed['instructions'] = params['baseInstructions']
            return {'thread': {'id': 'isolated-contract'}}

        async def turn(self, thread_id, prompt, **kwargs):
            observed['turn'] = kwargs
            assert 'I bought a house in 1980.' in prompt
            return '{"events": []}' if role == 'author_timeline' else ''

    worker = CodexWorker(home_root=tmp_path)
    monkeypatch.setattr(worker, '_home', lambda *args: tmp_path)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', Connection)
    result = asyncio.run(worker.turn(WorkerTurnInput(
        user_id='11111111-1111-4111-8111-111111111111',
        text='I bought a house in 1980.', agent_role=role,
        canonical_events=canonical, extraction_focus=focus, family_enabled=True,
    )))
    assert result['artifacts'] == []
    if not canonical:
        assert '- c0: I bought a house in 1980' in observed['instructions']
        assert 'source_claim_id' in observed['instructions']
    else:
        assert 'source_claim_id' not in observed['instructions']
        assert '[[MEMORY_SPARK_AUTHOR_TIMELINE]]' not in observed['instructions']
    if role == 'author_timeline':
        assert observed['turn']['output_schema']['required'] == ['events']
    elif focus == 'place_journey':
        assert 'Focused place-journey recovery pass' in observed['instructions']


def test_canonical_family_recovery_keeps_bounded_retries_without_legacy_timeline(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='synthetic')
    calls = []

    async def worker_turn(**kwargs):
        calls.append(kwargs)
        return {'reply': ''}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    asyncio.run(runtime._workspace_extraction(
        user_id='synthetic', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text='Aunt June remembers carrying me past the bench.',
        language='en-AU', canonical_events=True,
    ))
    assert [call.get('extraction_focus') for call in calls] == [None, 'family_tree', 'family_tree', 'family_tree']
    assert all(call['canonical_events'] is True for call in calls)
