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


@pytest.mark.parametrize('text,kind', [
    ("Don't discuss my school", 'excluded_topic'),
    ('Please do not mention my school.', 'excluded_topic'),
    ('I do not want to discuss my school.', 'excluded_topic'),
    ("Let's set aside my school for now.", 'paused_topic'),
    ("I'll return to the garden later", 'commitment'),
    ('I will bring the photographs next time.', 'commitment'),
    ('不要讨论我的学校。', 'excluded_topic'),
    ('先不聊我的学校。', 'paused_topic'),
    ('我下次会带照片来。', 'commitment'),
])
def test_literal_direct_requests_survive_model_omission(text, kind):
    ctx = context(text)
    for raw in (reply(), reply([])):
        rows = validate_governed_collector_result(raw, ctx)['continuity_updates']
        assert len(rows) == 1 and rows[0]['kind'] == kind
        data = rows[0]['data']
        assert data['assertion'] == 'asserted'
        assert data['uncertainty']
        ref = data['source_refs'][0]
        assert ref['quote'] == text[ref['char_start']:ref['char_end']] == data['text']


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


@pytest.mark.parametrize('text,quote,kind', [
    ('My school days were difficult.', 'My school days were difficult.', 'excluded_topic'),
    ('She said, "Don\'t discuss my school."', "Don't discuss my school", 'excluded_topic'),
    ('She said:\nDon\'t discuss my school.', "Don't discuss my school", 'excluded_topic'),
    ('He said: Let\'s set aside my school for now.', "Let's set aside my school for now", 'paused_topic'),
])
def test_model_cannot_promote_a_true_quote_into_unsupported_privacy_control(text, quote, kind):
    ctx = context(text)
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([update(ctx, kind, quote)]), ctx)


def test_privacy_control_is_asserted_and_not_inferred_from_preference():
    ctx = context("Don't discuss my school")
    item = update(ctx, 'excluded_topic', assertion='inferred', uncertainty='Maybe a preference.')
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([item]), ctx)


def test_model_and_literal_fallback_deduplicate_same_control():
    ctx = context("Don't discuss my school")
    rows = validate_governed_collector_result(reply([update(ctx, 'excluded_topic')]), ctx)['continuity_updates']
    assert len(rows) == 1


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


def test_prompt_requires_explicit_pending_items_and_keeps_evidence_separate():
    for expected in ('continuity_updates', 'commitment', 'unresolved_reference',
                     'excluded_topic', 'paused_topic', 'original', 'quoted', 'source'):
        assert expected in GOVERNED_CONTINUITY_INSTRUCTIONS


def test_pre_generation_literal_controls_share_final_canonical_ids_and_payloads():
    from apps.api.lifetime_memory_continuity import literal_continuity_updates
    ctx = context("Don't discuss my school. I'll return to the garden later.")
    early = literal_continuity_updates(ctx)
    item = update(ctx, 'excluded_topic', "Don't discuss my school.", uncertainty='Model-specific wording.')
    final = validate_governed_collector_result(reply([item]), ctx)['continuity_updates']
    assert early == final
    assert early[0]['kind'] == 'excluded_topic'
    assert len({row['record_id'] for row in early}) == len(early)


def test_all_literal_privacy_controls_take_priority_at_the_eight_record_bound():
    from apps.api.lifetime_memory_continuity import literal_continuity_updates
    sentences = [f'Person {i} visited.' for i in range(7)]
    ctx = context(' '.join([*sentences, "Don't discuss my school.", "Don't mention my workplace."]))
    items = [update(ctx, quote=sentence) for sentence in sentences]
    items.append(update(ctx, 'excluded_topic', "Don't mention my workplace"))
    rows = validate_governed_collector_result(reply(items), ctx)['continuity_updates']
    controls = [row for row in rows if row['kind'] == 'excluded_topic']
    assert len(rows) == 8 and len(controls) == 2
    assert controls == literal_continuity_updates(ctx)


def test_too_many_literal_privacy_controls_fail_closed_without_truncation():
    from apps.api.lifetime_memory_continuity import literal_continuity_updates
    ctx = context(' '.join(f'Do not mention topic {n}.' for n in range(9)))
    with pytest.raises(ValueError, match='Too many'):
        literal_continuity_updates(ctx)


def test_quoted_speech_cannot_become_the_narrators_pending_commitment():
    ctx = context('She said, "I\'ll return to the garden later."')
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([update(ctx, 'commitment', "I'll return to the garden later")]), ctx)


def test_commitment_pre_generation_and_model_punctuation_have_identical_payloads():
    from apps.api.lifetime_memory_continuity import literal_continuity_updates
    ctx = context("I'll return to the garden later.")
    item = update(ctx, 'commitment', uncertainty='The model is not sure when.')
    assert validate_governed_collector_result(reply([item]), ctx)['continuity_updates'] == literal_continuity_updates(ctx)


def test_later_commitment_subset_cannot_shift_pre_generation_record_identity():
    from apps.api.lifetime_memory_continuity import literal_continuity_updates
    ctx = context("I'll bring the photos tomorrow. I'll return to the garden later.")
    item = update(ctx, 'commitment', "I'll return to the garden later.")
    assert validate_governed_collector_result(reply([item]), ctx)['continuity_updates'] == literal_continuity_updates(ctx)


def test_source_occurrence_record_ids_do_not_depend_on_other_selected_rows():
    ctx = context('Ming came home. Fang came home.')
    first = update(ctx, quote='Ming came home')
    second = update(ctx, quote='Fang came home')
    all_rows = validate_governed_collector_result(reply([first, second]), ctx)['continuity_updates']
    subset = validate_governed_collector_result(reply([second]), ctx)['continuity_updates']
    assert all_rows[1]['record_id'] == subset[0]['record_id']


@pytest.mark.parametrize('text,quote', [
    ("She replied:\nDon't discuss my school.", "Don't discuss my school"),
    ("My teacher wrote.\nDon't discuss my school.", "Don't discuss my school"),
    ("The caption reads:\nDon't discuss my school.", "Don't discuss my school"),
    ('他写道：\n不要讨论我的学校。', '不要讨论我的学校'),
])
def test_additional_reported_speech_boundaries_cannot_grant_privacy_authority(text, quote):
    ctx = context(text)
    assert validate_governed_collector_result(reply(), ctx)['continuity_updates'] == []
    with pytest.raises(ValueError):
        validate_governed_collector_result(reply([update(ctx, 'excluded_topic', quote)]), ctx)


@pytest.mark.parametrize('template', ['Do not mention topic {n}.', '不要讨论话题{n}。'])
def test_preaccept_policy_validation_accepts_eight_and_rejects_nine_without_truncation(template):
    from apps.api.lifetime_memory_continuity import validate_literal_continuity_input, LiteralContinuityInputError
    eight = ' '.join(template.format(n=n) for n in range(8))
    assert validate_literal_continuity_input(eight) is None
    assert len(validate_governed_collector_result(reply(), context(eight))['continuity_updates']) == 8
    nine = eight + ' ' + template.format(n=8)
    with pytest.raises(LiteralContinuityInputError, match='Too many'):
        validate_literal_continuity_input(nine)
    with pytest.raises(LiteralContinuityInputError, match='Too many'):
        validate_governed_collector_result(reply(), context(nine))


def test_preaccept_policy_limit_counts_bilingual_exclusions_and_pauses_together():
    from apps.api.lifetime_memory_continuity import validate_literal_continuity_input, LiteralContinuityInputError
    parts = ["Don't discuss my school.", "Let's set aside my workplace for now."]
    parts += [f'先不聊话题{n}。' for n in range(6)]
    assert validate_literal_continuity_input(' '.join(parts)) is None
    with pytest.raises(LiteralContinuityInputError):
        validate_literal_continuity_input(' '.join([*parts, '不要讨论我的家。']))


@pytest.mark.parametrize('prefix', ['She said:\n', '他写道：\n', 'For example: '])
def test_preaccept_reported_noncontrols_are_not_counted_as_current_preferences(prefix):
    from apps.api.lifetime_memory_continuity import validate_literal_continuity_input
    text = prefix + ' '.join(f'Do not mention topic {n}.' for n in range(9))
    assert validate_literal_continuity_input(text) is None
    assert validate_governed_collector_result(reply(), context(text))['continuity_updates'] == []


def test_preaccept_retries_are_pure_and_match_source_bound_validation():
    from apps.api.lifetime_memory_continuity import validate_literal_continuity_input, literal_continuity_updates
    text = "Don't discuss my school. I'll bring the photos next time."
    before = context(text)
    for _ in range(3):
        assert validate_literal_continuity_input(text, source_kind='narrator_transcript') is None
        assert literal_continuity_updates(before) == literal_continuity_updates(context(text))
    assert before == context(text)


@pytest.mark.parametrize('text', ['Do not discuss ' + 'x' * 500, '不要讨论' + '字' * 500])
def test_recognized_overlong_policy_is_rejected_not_silently_skipped(text):
    from apps.api.lifetime_memory_continuity import validate_literal_continuity_input, LiteralContinuityInputError
    with pytest.raises(LiteralContinuityInputError, match='500'):
        validate_literal_continuity_input(text)
    with pytest.raises(LiteralContinuityInputError, match='500'):
        validate_governed_collector_result(reply(), context(text))


def test_preaccept_many_commitments_do_not_consume_privacy_control_bound():
    from apps.api.lifetime_memory_continuity import validate_literal_continuity_input
    text = ' '.join(f'I will bring photo {n}.' for n in range(20))
    assert validate_literal_continuity_input(text) is None


@pytest.mark.parametrize('space', ['\u00a0', '\u2003', '\u3000', '\u2028', '\u2029', '\r', '\t'])
def test_literal_parser_has_explicit_unicode_whitespace_and_character_offsets(space):
    from apps.api.lifetime_memory_continuity import literal_continuity_updates
    text = space + 'Do not mention my school.' + space
    rows = literal_continuity_updates(context(text))
    assert len(rows) == 1
    ref = rows[0]['data']['source_refs'][0]
    assert ref['char_start'] == len(space)
    assert ref['quote'] == text[ref['char_start']:ref['char_end']]


def test_internal_unicode_spacing_is_recognized_without_normalizing_source_words():
    from apps.api.lifetime_memory_continuity import literal_continuity_updates
    text = 'Do\u00a0not\u2003mention\u3000my school.'
    rows = literal_continuity_updates(context(text))
    assert len(rows) == 1 and rows[0]['data']['text'] == text[:-1]


@pytest.mark.parametrize('separator', ['\r', '\r\n', '\u2028', '\u2029'])
def test_unicode_line_separators_do_not_merge_nine_controls_into_one(separator):
    from apps.api.lifetime_memory_continuity import validate_literal_continuity_input, LiteralContinuityInputError
    text = separator.join(f'Do not mention topic {n}' for n in range(9))
    with pytest.raises(LiteralContinuityInputError, match='Too many'):
        validate_literal_continuity_input(text)
