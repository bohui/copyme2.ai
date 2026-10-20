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
