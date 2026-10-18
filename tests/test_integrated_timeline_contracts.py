"""Canonical evidence and user-veto contracts."""
import json

import pytest
from pydantic import ValidationError

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
