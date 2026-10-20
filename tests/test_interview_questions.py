"""Queue retirement cites narrator answers, never an assistant's own question."""
from copy import deepcopy

import pytest

from apps.api.lifetime_memory_continuity import validate_governed_collector_result
from test_interview_strategy import context, wire


def answered_confirmation():
    value = context(text='We played together by the river.')
    value['two_lane_memory'] = True
    question = {'id': 'bq-' + 'a' * 64, 'question': 'Was Aunt Lin his mother?',
                'requires_confirmation': True}
    value['prepared_questions'] = [question]
    value['recent_dialogue'] = [{'question': {'text': 'Was Aunt Lin Xiaoming’s mum?',
        'role': 'assistant', 'personal_testimony': False}, 'response': {
            'id': '00000000-0000-4000-8000-000000000002', 'version': 1, 'text': 'Yes.',
            'role': 'user', 'kind': 'narrator_chat', 'complete': True}}]
    resolution = {'question_id': question['id'], 'source_id': value['recent_dialogue'][0]['response']['id'],
                  'source_version': 1, 'char_start': 0, 'char_end': 4, 'quote': 'Yes.'}
    output = wire(question='What did you play?', selection_reason='latest_story',
                  resolved_questions=[resolution])
    return value, output


def test_answered_paraphrase_can_retire_without_overriding_a_new_followup():
    value, output = answered_confirmation()
    result = validate_governed_collector_result(output, value)
    assert result['reply'].endswith('What did you play?')
    assert result['plan']['resolved_questions'] == output['resolved_questions']
    assert result['strategy_outcome']['question_delivered'] == 'What did you play?'


def test_current_narrator_testimony_can_resolve_a_hint_without_prior_dialogue():
    from apps.api.lifetime_memory_continuity import governed_collector_schema
    value, output = answered_confirmation()
    value['recent_dialogue'] = []
    source = value['source']
    output['resolved_questions'][0].update(source_id=source['id'], source_version=source['version'],
        char_start=0, char_end=len(source['text']), quote=source['text'])
    assert 'resolved_questions' in governed_collector_schema(value)['properties']
    assert validate_governed_collector_result(output, value)['reply'].endswith('What did you play?')


@pytest.mark.parametrize('invalid', ['unknown_question', 'wrong_version', 'wrong_span',
                                   'assistant_answer', 'truncated_answer', 'duplicate_resolution'])
def test_invalid_resolution_cannot_silently_remove_a_confirmation(invalid):
    value, output = answered_confirmation()
    item = output['resolved_questions'][0]
    if invalid == 'unknown_question': item['question_id'] = 'another-project-question'
    elif invalid == 'wrong_version': item['source_version'] = 2
    elif invalid == 'wrong_span': item.update(char_start=1, char_end=5)
    elif invalid == 'assistant_answer': value['recent_dialogue'][0]['response']['role'] = 'assistant'
    elif invalid == 'truncated_answer': value['recent_dialogue'][0]['response']['complete'] = False
    else: output['resolved_questions'].append(deepcopy(item))
    with pytest.raises(ValueError, match='Question resolution requires'):
        validate_governed_collector_result(output, value)


def test_a_resolution_cannot_be_selected_again_in_the_same_reply():
    value, output = answered_confirmation()
    output.update(selected_candidate_id=value['prepared_questions'][0]['id'],
                  question=value['prepared_questions'][0]['question'], selection_reason='prepared_candidate')
    with pytest.raises(ValueError, match='answered question cannot also be chosen'):
        validate_governed_collector_result(output, value)


@pytest.mark.parametrize('selector', [False, True])
@pytest.mark.parametrize('invalid', ['source', 'version', 'span', 'ambiguous', 'assistant'])
def test_question_references_cannot_claim_an_unseen_or_ambiguous_passage(selector, invalid):
    from test_name_only_opening import proposal
    value = context(text='At school we played. At work we travelled.')
    value.update(two_lane_memory=True, strategy_selector=selector)
    source = value['source']
    evidence = dict(source_id=source['id'], version=1, quote='we', char_start=10, char_end=12, attribution=None)
    if invalid == 'source': evidence['source_id'] = 'another-source'
    elif invalid == 'version': evidence['version'] = 2
    elif invalid == 'span': evidence['char_end'] = 13
    elif invalid == 'ambiguous': evidence.update(char_start=None, char_end=None)
    else: source['kind'] = 'assistant'
    output = (wire(question='Who was with you?', selection_reason='latest_story', question_evidence=evidence)
              if selector else {**proposal(mode='extract', name=None), 'selection_reason': 'latest_story'})
    if not selector: output['plan']['candidates'][0]['context']['evidence'] = evidence
    with pytest.raises(ValueError, match='Question evidence'):
        validate_governed_collector_result(output, value)


def test_identical_candidate_wording_can_target_two_exact_passages():
    from apps.api.interview_plan import validate_collector_result
    from test_name_only_opening import proposal
    value = context(text='At school we played. At work we travelled.')
    output = proposal(mode='extract', name=None, question='Who do you mean by we?')
    first = output['plan']['candidates'][0]
    first['context']['evidence'] = dict(source_id=value['source']['id'], version=1, quote='we', char_start=10, char_end=12)
    second = deepcopy(first)
    second.update(id='work-group', order=1)
    start = value['source']['text'].rindex('we')
    second['context']['evidence'].update(char_start=start, char_end=start + 2)
    output['plan']['candidates'].append(second)
    saved = validate_collector_result(output, value)
    assert [q['context']['evidence']['char_start'] for q in saved['plan']['candidates']] == [10, start]


def test_background_offsets_are_absolute_and_repeated_quotes_require_them():
    from apps.api.two_lane_memory import derived_hints
    page = {'source': {'text': 'we and we', 'char_start': 2000}}
    hint = {'question': 'Who do you mean?', 'topic': 'group', 'quote': 'we'}
    raw = {'place_journeys': [], 'prepared_questions': [hint]}
    with pytest.raises(ValueError, match='Question evidence'):
        derived_hints(raw, page)
    raw['prepared_questions'] = [{**hint, 'char_start': start, 'char_end': start + 2} for start in (2000, 2007)]
    assert [q['char_start'] for q in derived_hints(raw, page)['prepared_questions']] == [2000, 2007]


def test_a_background_candidate_cannot_be_retargeted_to_another_passage():
    from apps.api.interview_plan import validate_collector_result
    from test_name_only_opening import proposal
    value = context(text='At school we played. At work we travelled.')
    value['two_lane_memory'] = True
    hint = dict(id='bq-' + 'b' * 64, question='Who do you mean?', topic='school', quote='we',
                source_id=value['source']['id'], source_version=1, char_start=10, char_end=12)
    value['prepared_questions'] = [hint]
    output = proposal(mode='extract', name=None, question=hint['question'])
    output['plan']['chosen_id'] = hint['id']
    output['plan']['candidates'][0]['id'] = hint['id']
    output['plan']['candidates'][0]['context']['evidence'] = dict(
        source_id=value['source']['id'], version=1, quote='we', char_start=29, char_end=31)
    with pytest.raises(ValueError, match='cannot change its referenced passage'):
        validate_collector_result(output, value)


@pytest.mark.parametrize('selector', [False, True])
def test_unique_question_quote_resolves_offsets_without_accepting_a_wrong_explicit_span(selector):
    from test_name_only_opening import proposal
    text='I am Joan. My father repaired bicycles in our shed. We lived in Hobart.'
    value=context(text=text)
    value.update(two_lane_memory=True,strategy_selector=selector)
    quote='My father repaired bicycles in our shed.'
    evidence=dict(source_id=value['source']['id'],version=1,quote=quote,
        char_start=None,char_end=None,attribution=None)
    output=(wire(question='What do you remember about the shed?', selection_reason='latest_story', question_evidence=evidence)
        if selector else {**proposal(mode='extract',name=None), 'selection_reason':'latest_story'})
    if not selector:output['plan']['candidates'][0]['context']['evidence']=evidence
    saved=validate_governed_collector_result(output,value)
    ref=saved['plan']['candidates'][0]['context']['evidence']
    assert ref['char_start']==text.index(quote) and ref['char_end']==text.index(quote)+len(quote)
    evidence.update(char_start=12,char_end=52)
    with pytest.raises(ValueError,match='Question evidence span must match'):
        validate_governed_collector_result(output,value)


@pytest.mark.parametrize('selector', [False, True])
def test_question_schema_only_offers_current_and_queued_narrator_sources(selector):
    from jsonschema import ValidationError, validate
    from apps.api.lifetime_memory_continuity import governed_collector_schema

    value = context(text='We caught beetles by the river.')
    value.update(two_lane_memory=True, strategy_selector=selector)
    queued_source = '00000000-0000-4000-8000-000000000002'
    strategy_source = '00000000-0000-4000-8000-000000000003'
    value['prepared_questions'] = [dict(id='queued-river', question='Who joined you?',
        source_id=queued_source, source_version=2, quote='river', char_start=8, char_end=13)]
    value['strategy_context']['plan'].update(source_id=strategy_source, source_version=1)
    value['strategy_context']['plan']['candidates'][0].update(char_start=4, char_end=10)
    schema = governed_collector_schema(value)['$defs']['EvidenceRef']
    evidence = dict(source_id=value['source']['id'], version=1, quote='beetles',
        char_start=None, char_end=None, attribution=None)
    for source_id in (value['source']['id'], queued_source, strategy_source):
        validate({**evidence, 'source_id': source_id}, schema)
    with pytest.raises(ValidationError):
        validate({**evidence, 'source_id': '00000000-0000-4000-8000-000000000004'}, schema)


@pytest.mark.parametrize('selector', [False, True])
@pytest.mark.parametrize('source', [None,
    dict(id='withdrawn', version=1, text='An old story.', status='withdrawn'),
    dict(id='assistant', version=1, text='A generated reply.', status='active', kind='assistant')])
def test_question_schema_without_narrator_sources_only_allows_null_evidence(selector, source):
    from jsonschema import ValidationError, validate
    from apps.api.lifetime_memory_continuity import governed_collector_schema

    value = {**context(), 'source': source, 'strategy_selector': selector, 'strategy_context': {}}
    schema = governed_collector_schema(value)['$defs']['EvidenceRef']
    validate(None, schema)
    with pytest.raises(ValidationError):
        validate(dict(source_id='unavailable', version=1, quote='An old story.',
            char_start=0, char_end=13, attribution=None), schema)


def test_an_unselected_earlier_source_candidate_is_rejected_by_the_model_schema():
    from jsonschema import ValidationError, validate
    from apps.api.lifetime_memory_continuity import governed_collector_schema
    from test_name_only_opening import proposal

    value = context(text='We caught beetles by the river.')
    value.update(two_lane_memory=True, strategy_selector=False, strategy_context={})
    previous = dict(id='00000000-0000-4000-8000-000000000002', version=1,
        text='We played in the garden.', status='active')
    value['sources'] = [value['source'], previous]
    output = proposal(mode='extract', name=None, question='Which insects did you catch?')
    output.update(selection_reason='latest_story', continuity_updates=[])
    chosen = output['plan']['candidates'][0]
    chosen['context'].update(historical_clue_id=None, evidence=dict(
        source_id=value['source']['id'], version=1, quote='beetles',
        char_start=None, char_end=None, attribution=None))
    schema = governed_collector_schema(value)
    validate(output, schema)
    deferred = deepcopy(chosen)
    deferred.update(id='earlier-garden', order=1, question='Who played in the garden?')
    deferred['context']['evidence'].update(source_id=previous['id'], quote='garden', char_start=17, char_end=23)
    output['plan']['candidates'].append(deferred)
    with pytest.raises(ValidationError):
        validate(output, schema)
    with pytest.raises(ValueError, match='Question evidence is outside the supplied narrator passages'):
        validate_governed_collector_result(output, value)
