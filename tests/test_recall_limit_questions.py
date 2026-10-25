"""Recall difficulty changes question scope without resolving uncertain facts."""
from copy import deepcopy

import pytest

from apps.api.lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
from apps.api.interview_questions import recall_question
from test_conversation_reply import proposal, reply_context
from test_reply_v2_contract_compatibility import hint
from test_interview_strategy import wire


def recall_case(text="I cannot remember that detail. We lived there for years."):
    context = reply_context(text)
    detail = {**hint(context, 'a', confirmation=True), 'question': 'What exactly did you do while waiting?'}
    broader = {**hint(context, 'b'), 'question': 'What comes to mind about life in that home?', 'scope': 'broader'}
    context.update(strategy_selector=True, prepared_questions=[detail], strategy_context={
        'mode': 'active', 'plan': dict(plan_revision=1, strategy='explore', candidates=[detail, broader])})
    output = {**proposal(), 'reason': 'recall_limit', 'hint': 1, 'question': broader['question']}
    return context, output, detail, broader


def deferral(context, question):
    source = context['source']
    return dict(question_id=question['id'], source_id=source['id'], source_version=source['version'],
        quote=source['text'], char_start=0, char_end=len(source['text']))


@pytest.mark.parametrize('text', [
    'I cannot remember that detail. We lived there for years.',
    '那有点记不得了，只记得和爸爸买了涂料，在旁边等了半天。',
    '那就记不清了，越想越想不起来。我还记得家里用煤炉烧水。',
])
def test_recall_limit_can_select_a_broader_pool_question_over_a_pending_detail(text):
    context, output, detail, broader = recall_case(text)
    output.update(deferred_hints=[0], quote=context['source']['text'])
    result = validate_governed_collector_result(output, context)
    assert result['plan']['chosen_id'] == broader['id']
    assert result['plan']['deferred_questions'] == [deferral(context, detail)]
    assert result['plan'].get('resolved_questions', []) == []
    assert result['strategy_outcome']['selection_reason'] == 'recall_limit'
    assert result['strategy_outcome']['selected_candidate_id'] == broader['id']


@pytest.mark.parametrize('selector', [False, True])
def test_empty_pool_keeps_the_recall_limit_and_a_broader_fallback(selector):
    context, output, _, _ = recall_case()
    context.update(prepared_questions=[], strategy_selector=selector, strategy_context={'mode': 'active', 'plan': None})
    output['hint'] = None
    result = validate_governed_collector_result(output, context)
    assert result['reply'].endswith(recall_question(context))
    assert result['plan']['chosen_id'].startswith('immediate-')
    assert result['plan'].get('resolved_questions', []) == []


@pytest.mark.parametrize('use_pool', [False, True])
def test_recall_limit_cannot_smuggle_detail_through_question_wording_or_skip_new_testimony(use_pool):
    context, output, _, broader = recall_case()
    output.update(question='What exactly did you do while waiting?', work={'mode': 'reply_only', 'name': None})
    if not use_pool:
        output['hint'] = None
    result = validate_governed_collector_result(output, context)
    expected = broader['question'] if use_pool else recall_question(context)
    assert result['reply'].endswith(expected)
    assert output['question'] not in result['reply']
    assert result['plan']['work']['mode'] == 'extract'


def test_recall_limit_filters_detail_before_selecting_a_broader_hint_from_the_same_source():
    context, output, detail, broader = recall_case()
    output.update(hint=0, question=detail['question'])
    result = validate_governed_collector_result(output, context)
    assert result['plan']['chosen_id'] == broader['id']
    assert result['reply'].endswith(broader['question'])


def test_current_recall_evidence_overrides_an_ordinary_followup_reason():
    context, output, _, broader = recall_case()
    output.update(reason='return_context', hint=0, recall_limit_quote='I cannot remember that detail.')
    result = validate_governed_collector_result(output, context)
    assert result['strategy_outcome']['selection_reason'] == 'recall_limit'
    assert result['plan']['chosen_id'] == broader['id']


@pytest.mark.parametrize('fault', ['unknown', 'foreign_source', 'version', 'span', 'duplicate', 'chosen', 'answered'])
def test_deferral_cannot_consume_a_foreign_or_selected_question(fault):
    context, output, detail, broader = recall_case()
    context.pop('reply_contract')
    output = wire(question=broader['question'], selection_reason='recall_limit', selected_candidate_id=broader['id'])
    item = deferral(context, detail)
    output['deferred_questions'] = [item]
    if fault == 'unknown': item['question_id'] = 'foreign-question'
    elif fault == 'foreign_source': item['source_id'] = 'foreign-source'
    elif fault == 'version': item['source_version'] += 1
    elif fault == 'span': item['char_start'] += 1
    elif fault == 'duplicate': output['deferred_questions'].append(deepcopy(item))
    elif fault == 'chosen': item['question_id'] = broader['id']
    else: output['resolved_questions'] = [deepcopy(item)]
    with pytest.raises(ValueError):
        validate_governed_collector_result(output, context)


def test_deferral_fields_are_offered_only_with_authorized_queued_questions():
    context, _, _, _ = recall_case()
    schema = governed_collector_schema(context)
    assert schema['properties']['deferred_hints']['items']['enum'] == [0]
    context.update(prepared_questions=[], strategy_context={'mode': 'active', 'plan': None})
    assert 'deferred_hints' not in governed_collector_schema(context)['properties']


def test_current_intent_and_pool_selection_are_generated_before_question_wording():
    context, _, _, _ = recall_case()
    fields = list(governed_collector_schema(context)['properties'])
    assert fields[0] == 'acknowledgement'
    assert fields.index('reason') < fields.index('hint') < fields.index('question')


def test_legacy_collector_also_uses_the_host_recall_invitation():
    from test_name_only_opening import proposal as legacy_proposal
    context, _, _, _ = recall_case()
    context.pop('reply_contract')
    context['strategy_selector'] = False
    output = legacy_proposal(mode='reply_only', name=None, question='What exactly did you do while waiting?')
    output['selection_reason'] = 'recall_limit'
    result = validate_governed_collector_result(output, context)
    assert result['reply'].endswith(recall_question(context))
    assert result['plan']['work']['mode'] == 'extract'


@pytest.mark.parametrize('fault', ['unknown', 'chosen', 'duplicate', 'missing_quote', 'fabricated_quote', 'answered'])
def test_compact_deferrals_use_only_host_owned_indices_and_current_evidence(fault):
    context, output, detail, _ = recall_case()
    output.update(deferred_hints=[0], quote=context['source']['text'])
    if fault == 'unknown': output['deferred_hints'] = [99]
    elif fault == 'chosen': output['deferred_hints'] = [1]
    elif fault == 'duplicate': output['deferred_hints'] = [0, 0]
    elif fault == 'missing_quote': output['quote'] = None
    elif fault == 'fabricated_quote': output['quote'] = 'I do not remember a different story.'
    else: output['resolved_questions'] = [deferral(context, detail)]
    with pytest.raises(ValueError):
        validate_governed_collector_result(output, context)


def test_a_stop_still_preempts_recall_difficulty_and_the_pool():
    context, output, _, _ = recall_case('I cannot remember. Please stop for today.')
    output.update(reason='pause', hint=None, question=None, recall_limit_quote='I cannot remember.')
    result = validate_governed_collector_result(output, context)
    assert result['stopped'] and result['plan']['candidates'] == []


@pytest.mark.parametrize('reason', ['direct_answer', 'current_correction', 'user_redirect', 'pacing'])
def test_recall_evidence_preserves_higher_priority_current_intent(reason):
    context, output, _, _ = recall_case()
    question = None if reason == 'direct_answer' else 'What would you like to share next?'
    output.update(reason=reason, hint=None, question=question,
                  recall_limit_quote='I cannot remember that detail.')
    result = validate_governed_collector_result(output, context)
    assert result['strategy_outcome']['selection_reason'] == reason
    assert result['strategy_outcome']['question_delivered'] == question


def test_recall_evidence_cannot_quote_a_different_source():
    context, output, _, _ = recall_case()
    output['recall_limit_quote'] = 'I cannot remember an earlier story.'
    with pytest.raises(ValueError, match='exact'):
        validate_governed_collector_result(output, context)


def test_recall_does_not_replace_a_detail_with_a_broader_hint_from_another_source():
    context, output, _, broader = recall_case()
    broader['source_id'] = 'other-source'
    output.update(hint=0)
    result = validate_governed_collector_result(output, context)
    assert result['strategy_outcome']['selected_candidate_id'] is None
    assert result['reply'].endswith(recall_question(context))
