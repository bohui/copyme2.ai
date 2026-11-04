"""Recall difficulty follows current testimony without a background question queue."""
import pytest

from apps.api.lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
from apps.api.interview_questions import recall_question
from test_conversation_reply import proposal, reply_context


def recall_case(text='I cannot remember that detail. We lived there for years.'):
    context = {**reply_context(text), 'strategy_selector': True}
    output = {**proposal(), 'reason': 'recall_limit',
        'question': 'What comes to mind about life in that home?'}
    return context, output


@pytest.mark.parametrize('text', [
    'I cannot remember that detail. We lived there for years.',
    '那有点记不得了，只记得和爸爸买了涂料，在旁边等了半天。',
    '那就记不清了，越想越想不起来。我还记得家里用煤炉烧水。',
])
def test_recall_limit_keeps_miras_connected_question_and_unresolved_facts(text):
    context, output = recall_case(text)
    result = validate_governed_collector_result(output, context)
    assert result['reply'].endswith(output['question'])
    assert result['strategy_outcome']['selection_reason'] == 'recall_limit'
    assert result['strategy_outcome']['selected_candidate_id'] is None
    assert result['plan'].get('resolved_questions', []) == result['plan'].get('deferred_questions', []) == []
    assert result['plan']['work']['mode'] == 'extract'


def test_recall_limit_without_a_question_uses_the_localized_invitation():
    context, output = recall_case()
    result = validate_governed_collector_result({**output, 'question': None}, context)
    assert result['reply'].endswith(recall_question(context))
    assert result['plan']['chosen_id'].startswith('immediate-')


def test_current_recall_evidence_overrides_an_ordinary_followup_reason():
    context, output = recall_case()
    output.update(reason='return_context', recall_limit_quote='I cannot remember that detail.')
    result = validate_governed_collector_result(output, context)
    assert result['strategy_outcome']['selection_reason'] == 'recall_limit'
    assert result['plan']['candidates'][0]['question'] == output['question']


@pytest.mark.parametrize('field,value', [('hint', 0), ('deferred_hints', [0]), ('resolved_questions', [])])
def test_recall_has_no_pool_indices_or_queue_mutations(field, value):
    context, output = recall_case()
    schema = governed_collector_schema(context)
    assert field not in schema['properties']
    with pytest.raises(ValueError):
        validate_governed_collector_result({**output, field: value}, context)


def test_current_intent_is_generated_before_question_wording():
    context, _ = recall_case()
    fields = list(governed_collector_schema(context)['properties'])
    assert fields[0] == 'acknowledgement'
    assert fields.index('reason') < fields.index('question')


@pytest.mark.parametrize('reason', ['pause', 'direct_answer', 'current_correction', 'user_redirect', 'pacing'])
def test_recall_evidence_preserves_higher_priority_current_intent(reason):
    context, output = recall_case()
    question = None if reason in {'pause', 'direct_answer'} else 'What would you like to share next?'
    output.update(reason=reason, question=question, recall_limit_quote='I cannot remember that detail.')
    result = validate_governed_collector_result(output, context)
    assert result['strategy_outcome']['selection_reason'] == reason
    assert result['strategy_outcome']['question_delivered'] == question


def test_recall_evidence_cannot_quote_a_different_source():
    context, output = recall_case()
    with pytest.raises(ValueError, match='exact'):
        validate_governed_collector_result({**output, 'recall_limit_quote': 'I cannot remember an earlier story.'}, context)
