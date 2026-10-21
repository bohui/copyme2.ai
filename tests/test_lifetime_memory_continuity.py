"""Governed continuity proposals remain current-source, typed and attributed."""
from copy import deepcopy
import json
from uuid import UUID

import pytest
from jsonschema import validate

from apps.api.interview_plan import collector_schema, validate_collector_result
from apps.api.lifetime_memory_continuity import (
    GOVERNED_CONTINUITY_INSTRUCTIONS,
    governed_collector_schema,
    validate_governed_collector_result,
)

SOURCE_ID = str(UUID(int=101))


def context(text='My brother Ming moved to Perth.'):
    source = {'id': SOURCE_ID, 'version': 3, 'status': 'active',
              'kind': 'narrator_chat', 'role': 'storyteller', 'text': text}
    return {'source': source, 'sources': [source], 'events': [], 'photo_context': [],
            'interview_language': 'en-AU'}


def reply(updates=None):
    result = {'acknowledgement': 'We can continue at your pace.',
        'plan': {'candidates': [{'id': 'q1', 'question': 'What comes to mind?',
            'context': {'event_id': None, 'photo_id': None, 'life_stage': None,
                        'year': None, 'historical_clue_id': None, 'evidence': None}, 'order': 0, 'bridge': ''}],
            'chosen_id': 'q1', 'active_event_id': None, 'work': None},
        'associations': [], 'response_photo_ids': [], 'stopped': False}
    if updates is not None:
        result['continuity_updates'] = updates
    return result


def update(ctx, kind='person', quote=None, **changes):
    source = ctx['source']
    quote = source['text'] if quote is None else quote
    start = source['text'].index(quote)
    result = {'kind': kind, 'text': quote, 'assertion': 'asserted', 'uncertainty': None,
        'source_id': source['id'], 'source_version': source['version'],
        'char_start': start, 'char_end': start + len(quote), 'quote': quote}
    result.update(changes)
    return result


def test_schema_is_governed_only_bounded_strict_and_current_source_constrained():
    ctx = context()
    legacy = collector_schema(ctx)
    schema = governed_collector_schema(ctx)
    assert 'continuity_updates' not in legacy['properties']
    field = schema['properties']['continuity_updates']
    assert field['maxItems'] == 8
    item = schema['$defs'][field['items']['$ref'].split('/')[-1]]
    assert item['additionalProperties'] is False
    assert set(item['required']) == set(item['properties'])
    assert item['properties']['source_id']['const'] == SOURCE_ID
    assert item['properties']['source_version']['const'] == 3
    assert item['properties']['text']['maxLength'] == 500
    for forbidden in ('owner_id', 'policy_epoch', 'record_id', 'revision'):
        assert forbidden not in item['properties']
    validate({**reply([update(ctx)]), 'place_journeys': []}, schema)


def test_missing_optional_extension_keeps_legacy_results_and_does_not_mutate_input():
    ctx = context()
    raw = reply()
    before = deepcopy(raw)
    old = validate_collector_result(raw, ctx)
    assert validate_governed_collector_result(raw, ctx) == {**old, 'continuity_updates': [], 'place_journeys': []}
    assert raw == before


def test_original_language_exact_span_maps_to_existing_rpc_data_contract():
    ctx = context('我记得大哥阿明。后来他搬去了珀斯。')
    proposed = update(ctx, quote='大哥阿明')
    out = validate_governed_collector_result(json.dumps(reply([proposed]), ensure_ascii=False), ctx)
    row = out['continuity_updates'][0]
    assert set(row) == {'record_id', 'kind', 'data'}
    assert row['kind'] == 'person'
    assert row['data'] == {'text': '大哥阿明', 'assertion': 'asserted', 'uncertainty': None,
        'source_refs': [{'source_id': SOURCE_ID, 'version': 3, 'char_start': 3,
                         'char_end': 7, 'quote': '大哥阿明'}]}
    assert len(row['record_id']) <= 128
    assert out['reply'] == validate_collector_result(reply(), ctx)['reply']


@pytest.mark.parametrize('text,quote', [
    ('My brother Ming moved to Perth.', 'Ming'),
    ('我记得大哥阿明。后来他搬去了珀斯。', '大哥阿明'),
    ('😀 Mum held my hand.', 'Mum held my hand'),
])
def test_server_locates_unique_exact_quotes_without_model_character_counting(text, quote):
    ctx = context(text)
    item = update(ctx, quote=quote, char_start=None, char_end=None)
    raw = {**reply([item]), 'place_journeys': []}
    before = deepcopy(raw)
    validate(raw, governed_collector_schema(ctx))
    result = validate_governed_collector_result(raw, ctx)
    ref = result['continuity_updates'][0]['data']['source_refs'][0]
    assert ref['char_start'] == text.index(quote)
    assert text[ref['char_start']:ref['char_end']] == ref['quote'] == quote
    assert raw == before


@pytest.mark.parametrize('text,changes', [
    ('Ming left. Ming left.', {}), ('Ming left.', {'source_version': 2}),
    ('Ming left.', {'source_id': 'another-source'}), ('Ming left.', {'char_start': 0}),
    ('Ming left.', {'quote': 'Invented narrator wording', 'text': 'Invented narrator wording'}),
])
def test_server_cannot_guess_ambiguous_or_unauthorized_quote_positions(text, changes):
    ctx = context(text)
    item = update(ctx, quote='Ming left', char_start=None, char_end=None)
    item.update(changes)
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


def test_server_record_identity_is_stable_by_source_version_kind_and_index():
    ctx = context()
    person = update(ctx)
    reference = update(ctx, 'unresolved_reference', assertion='inferred', uncertainty='Identity is unresolved.')
    a = validate_governed_collector_result(reply([person, reference]), ctx)['continuity_updates']
    b = validate_governed_collector_result(reply([reference, person]), ctx)['continuity_updates']
    assert {x['kind']: x['record_id'] for x in a} == {x['kind']: x['record_id'] for x in b}
    newer = deepcopy(ctx)
    newer['source']['version'] += 1
    c = validate_governed_collector_result(reply([update(newer)]), newer)['continuity_updates'][0]
    assert c['record_id'] != a[0]['record_id']


@pytest.mark.parametrize('change', [
    {'source_id': str(UUID(int=999))}, {'source_version': 2},
    {'source_version': True}, {'source_version': '3'}, {'source_version': 3.0},
    {'char_start': True}, {'char_start': '0'}, {'char_start': 0.0},
    {'char_end': False}, {'char_end': '29'}, {'char_end': 29.0},
    {'char_start': -1}, {'char_end': 1000}, {'char_end': 0},
    {'quote': 'Invented narrator wording'}, {'text': 'Ming is a doctor.'},
    {'text': ''}, {'text': 'x' * 501}, {'uncertainty': 'x' * 501},
    {'owner_id': str(UUID(int=1000))}, {'policy_epoch': 100},
    {'record_id': 'forged'}, {'revision': 2}, {'kind': 'chosen_name'},
    {'translation': 'Ming is my brother.'}, {'assertion': 'inferred'},
])
def test_fabricated_or_untyped_proposals_fail_closed(change):
    ctx = context()
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([update(ctx, **change)]), ctx)


@pytest.mark.parametrize('source_change', [
    {'status': 'withdrawn'}, {'status': 'superseded'}, {'kind': 'public_news'},
    {'kind': 'public_reference'}, {'kind': 'photo'}, {'kind': 'generated_assistant'},
    {'role': 'assistant'}, {'role': 'family_contributor'}, {'version': True},
])
def test_current_source_must_be_active_original_narrator(source_change):
    ctx = context()
    item = update(ctx)
    ctx['source'].update(source_change)
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


def test_old_authorized_sources_and_photo_metadata_cannot_supply_new_continuity():
    ctx = context()
    old = {**ctx['source'], 'id': str(UUID(int=102)), 'text': 'Ming was a doctor.'}
    ctx['sources'].append(old)
    ctx['photos'] = [{'photo_id': 'public:1', 'caption': old['text']}]
    item = update({'source': old})
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


def test_repeated_exact_quote_uses_explicit_occurrence_not_substring_search():
    ctx = context('Ming left. Ming left.')
    item = update(ctx, quote='Ming left', char_start=11, char_end=20)
    result = validate_governed_collector_result(reply([item]), ctx)
    assert result['continuity_updates'][0]['data']['source_refs'][0]['char_start'] == 11
    item['char_start'] = 1
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


@pytest.mark.parametrize('updates', [None, {}, 'bad', [1], [None]])
def test_extension_requires_array_of_objects_if_present(updates):
    raw = reply()
    raw['continuity_updates'] = updates
    with pytest.raises(ValueError):
        validate_governed_collector_result(raw, context())


def test_update_count_is_bounded_and_duplicates_are_rejected():
    ctx = context()
    for count in (2, 9):
        with pytest.raises(ValueError):
            validate_governed_collector_result(reply([update(ctx)] * count), ctx)




@pytest.mark.parametrize('text', [
    'My school days were difficult.',
    'I might return to the garden later.',
    'She said, "Don\'t discuss my school."',
    'She said:\nDon\'t discuss my school.',
    "'Don't discuss my school.'",
    "They told me. I'll return to the garden later.",
    'For example: Don\'t discuss my school.',
    'If I ask, don\'t discuss my school.',
    "Don't discuss my school unless I ask.",
    '他说：“不要讨论我的学校。”',
    '如果我提起，先不聊我的学校。',
])
def test_fallback_never_promotes_reported_conditional_or_inferred_preferences(text):
    assert validate_governed_collector_result(reply(), context(text))['continuity_updates'] == []




def test_privacy_control_is_asserted_and_not_inferred_from_preference():
    ctx = context("Don't discuss my school")
    item = update(ctx, 'excluded_topic', assertion='inferred', uncertainty='Maybe a preference.')
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


def test_model_and_literal_fallback_deduplicate_same_control():
    ctx = context("Don't discuss my school")
    rows = validate_governed_collector_result(reply([update(ctx, 'excluded_topic')]), ctx)['continuity_updates']
    assert len(rows) == 1




@pytest.mark.parametrize('kind', ['person', 'unresolved_reference'])
def test_required_offsets_cannot_be_manufactured_for_person_or_reference(kind):
    ctx = context()
    item = update(ctx, kind)
    item.pop('char_start')
    item.pop('char_end')
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


def test_explicit_wrong_span_cannot_be_canonicalized_as_a_control():
    ctx = context("Skip. Don't discuss my school.")
    quote = "Skip. Don't discuss my school"
    item = update(ctx, 'excluded_topic', quote=quote, char_start=1, char_end=1 + len(quote))
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


def test_missing_offsets_cannot_be_canonicalized_as_a_control():
    ctx = context("Don't discuss my school")
    item = update(ctx, 'excluded_topic')
    item.pop('char_start')
    item.pop('char_end')
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)




@pytest.mark.parametrize('changes', [
    {'source_id': str(UUID(int=999))},
    {'source_version': 2},
    {'text': 'fabricated wording', 'quote': 'fabricated wording'},
])
def test_overwide_literal_fallback_validates_source_metadata_and_quote(changes):
    ctx = context('跳过这个问题。我不想聊厨房。')
    item = update(ctx, 'excluded_topic', ctx['source']['text'], char_start=None, char_end=None)
    item.update(changes)
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


def test_overwide_literal_fallback_cannot_bypass_update_limit():
    ctx = context('跳过这个问题。我不想聊厨房。')
    item = update(ctx, 'excluded_topic', ctx['source']['text'], char_start=None, char_end=None)
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([deepcopy(item) for _ in range(9)]), ctx)




def test_old_worker_phase_cannot_become_a_saved_preference():
    ctx = context('My brother Ming moved to Perth.')
    ctx['conversation_phase'] = {'phase':'shape','selection':'explicit','preferred_phase':'shape'}
    raw = reply([update(ctx)])
    raw['plan']['conversation_phase']='explore'
    got = validate_governed_collector_result(raw, ctx)
    assert got['plan'] == validate_collector_result(reply_without_updates(raw), ctx)['plan']
    assert 'phase_update' not in got['plan'] and 'conversation_phase' not in got['plan']



def reply_without_updates(raw):
    return {k: v for k, v in raw.items() if k != 'continuity_updates'}
















def test_source_occurrence_record_ids_do_not_depend_on_other_selected_rows():
    ctx = context('Ming came home. Fang came home.')
    first = update(ctx, quote='Ming came home')
    second = update(ctx, quote='Fang came home')
    all_rows = validate_governed_collector_result(reply([first, second]), ctx)['continuity_updates']
    subset = validate_governed_collector_result(reply([second]), ctx)['continuity_updates']
    assert all_rows[1]['record_id'] == subset[0]['record_id']
