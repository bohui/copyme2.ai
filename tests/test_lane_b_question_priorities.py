"""Ready background findings must be selectable by the current reply contract."""
from copy import deepcopy
import json

import pytest

from apps.api.conversation_reply import reply_candidates, reply_packet
from apps.api.interview_plan import historical_acknowledgements
from apps.api.interview_strategy import validate_proposal
from apps.api.lifetime_memory_continuity import validate_governed_collector_result
from apps.api.lifetime_memory_engine import validate_governed_context
from test_conversation_reply import proposal, reply_context
from test_historical_news import ready_context
from test_lifetime_memory_engine import encode, fixture
from test_reply_v2_contract_compatibility import hint


def test_ready_news_can_change_the_next_reply_question_with_active_strategy():
    context = reply_context('What else was happening in Boston around then?')
    context.update(deepcopy(ready_context()), strategy_selector=True,
        strategy_context={'mode': 'active', 'plan': None}, interview_language='en-AU')
    clue = context['historical_news']['clues'][0]
    raw = {**proposal(), 'acknowledgement': sorted(historical_acknowledgements(context))[0],
        'hint': 0, 'reason': 'prepared_candidate',
        'question': 'Does this bring any memory of that time to mind?'}

    result = validate_governed_collector_result(raw, context)

    assert result['plan']['candidates'][0]['context']['historical_clue_id'] == clue['id']
    assert result['historical_context']['source_url'] == clue['source_url']
    assert result['plan']['candidates'][0]['question'] == raw['question']


@pytest.mark.parametrize('question', [
    'Was the move in 1962 or 1963?',
    'Which sister were you describing?',
    'Did the shop open before or after the move?',
])
def test_plan_confirmation_preempts_an_ordinary_reply(question):
    context = reply_context()
    confirmation = {**hint(context, 'a', confirmation=True), 'question': question}
    context.update(strategy_selector=True, strategy_context={'mode': 'active',
        'plan': dict(plan_revision=1, strategy='shape', objective='clarify_order', candidates=[confirmation])})

    result = validate_governed_collector_result(proposal(), context)

    assert result['plan']['chosen_id'] == confirmation['id']
    assert result['strategy_outcome']['selected_candidate_id'] == confirmation['id']


def test_background_can_propose_broadening_without_declaring_a_completed_stage():
    raw = dict(strategy='explore', objective='broaden_scope', focus_event_ids=[])
    assert validate_proposal(raw, {'events': []}) == raw
    with pytest.raises(ValueError):
        validate_proposal({**raw, 'strategy': 'shape'}, {'events': []})


def test_broadening_plan_reaches_reply_and_ranks_before_optional_news():
    governed, context = fixture()
    broader = {**hint(context, 'a'), 'question': 'What changed in your life after school?'}
    context.update(deepcopy(ready_context()), reply_contract='reply-v2', strategy_selector=True,
        strategy_context={'mode': 'active', 'plan': dict(plan_revision=1, strategy='explore',
            objective='broaden_scope', candidates=[broader])})
    packet = json.loads(governed.packet)
    packet['interview_context'] = {key: value for key, value in context.items() if key not in {'source', 'sources'}}

    view = reply_packet(validate_governed_context(encode(packet), context))

    assert view['brief']['objective'] == 'broaden_scope'
    assert view['brief']['hint_order'] == 'highest_priority_first'
    assert view['brief']['hints'][0]['id'] == broader['id']
    assert view['brief']['hints'][0]['purpose'] == 'broaden_scope'
    assert any(item.get('historical_clue_id') for item in view['brief']['hints'])


@pytest.mark.parametrize('selector', [False, True])
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('reason', ['prepared_candidate', 'adapted_candidate'])
def test_news_uses_the_existing_neutral_cited_reply_and_never_narrator_evidence(selector, locale, reason):
    from apps.api.historical_news import HISTORICAL_INVITATIONS
    context = reply_context()
    context.update(deepcopy(ready_context()), strategy_selector=selector,
        strategy_context={'mode': 'active', 'plan': None}, interview_language=locale)
    question, bridge = HISTORICAL_INVITATIONS[locale]
    raw = {**proposal(), 'acknowledgement': sorted(historical_acknowledgements(context))[0],
        'hint': 0, 'reason': reason, 'question': question}
    result = validate_governed_collector_result(raw, context)
    candidate = result['plan']['candidates'][0]
    assert candidate['bridge'] == bridge
    assert candidate['context'].get('evidence') is None
    assert bridge in result['reply'] and result['reply'].endswith(question)
    assert result['historical_context']['id'] == candidate['id']
    for changed in ({'quote': context['source']['text']}, {'question': 'You were at the fair, right?'}):
        with pytest.raises(ValueError):
            validate_governed_collector_result({**raw, **changed}, context)


@pytest.mark.parametrize('fault', ['disabled', 'used', 'uninspected', 'stale', 'foreign', 'missing_receipt'])
def test_unavailable_news_never_enters_selectable_hints(fault):
    context = reply_context()
    context.update(deepcopy(ready_context()))
    state = context['historical_news']
    clue = state['clues'][0]
    if fault == 'disabled': state['enabled'] = False
    elif fault == 'used': clue['status'] = 'used'
    elif fault == 'uninspected': clue['evidence_status'] = 'uninspected'
    elif fault == 'stale': clue['context_revision'] = 'old'
    elif fault == 'foreign': clue['project_id'] = 'another-project'
    else: clue.pop('receipt')
    assert reply_candidates(context) == []


@pytest.mark.parametrize('reason', ['pause', 'direct_answer', 'current_correction', 'user_redirect', 'pacing'])
def test_current_intent_keeps_precedence_over_all_background_priorities(reason):
    context = reply_context()
    confirmation = hint(context, 'a', confirmation=True)
    context.update(deepcopy(ready_context()), strategy_selector=True, strategy_context={'mode': 'active',
        'plan': dict(plan_revision=1, strategy='explore', objective='broaden_scope', candidates=[confirmation])})
    raw = {**proposal(), 'acknowledgement': sorted(historical_acknowledgements(context))[0], 'reason': reason}
    if reason in {'pause', 'direct_answer'}:
        raw['question'] = None
    result = validate_governed_collector_result(raw, context)
    assert result['strategy_outcome']['selection_reason'] == reason
    assert result['strategy_outcome']['selected_candidate_id'] is None
    assert result.get('historical_context') is None


def test_answered_plan_confirmation_is_not_forced_back_into_reply():
    context = reply_context('The umbrella was blue.')
    confirmation = {**hint(context, 'a', confirmation=True), 'question': 'What colour was the umbrella?'}
    context.update(strategy_selector=True, strategy_context={'mode': 'active',
        'plan': dict(plan_revision=1, strategy='explore', candidates=[confirmation])})
    raw = {**proposal(), 'resolved_questions': [dict(question_id=confirmation['id'],
        source_id=context['source']['id'], source_version=context['source']['version'], quote='blue', char_start=17, char_end=21)]}
    result = validate_governed_collector_result(raw, context)
    assert result['plan']['chosen_id'] != confirmation['id']


def test_confirmation_ranks_before_topic_expansion_and_news_without_duplicates():
    context = reply_context()
    confirmation, broader = hint(context, 'a', confirmation=True), hint(context, 'b')
    context.update(deepcopy(ready_context()), strategy_selector=True, prepared_questions=[confirmation],
        strategy_context={'mode': 'active', 'plan': dict(plan_revision=1, strategy='explore',
            objective='broaden_scope', candidates=[confirmation, broader])})
    hints = reply_candidates(context)
    assert [item['purpose'] for item in hints] == ['clarification', 'broaden_scope', 'historical_news']
    assert [item['id'] for item in hints[:2]] == [confirmation['id'], broader['id']]


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_older_strategy_selector_preserves_the_same_public_clue_contract(locale):
    from test_interview_strategy import wire
    context = reply_context()
    context.pop('reply_contract')
    context.update(deepcopy(ready_context()), strategy_selector=True,
        strategy_context={'mode': 'active', 'plan': None}, interview_language=locale)
    hint = reply_candidates(context)[0]
    raw = wire(acknowledgement=sorted(historical_acknowledgements(context))[0],
        selected_candidate_id=hint['id'], question=hint['question'], selection_reason='prepared_candidate')
    result = validate_governed_collector_result(raw, context)
    assert result['historical_context']['id'] == hint['id']
    with pytest.raises(ValueError):
        validate_governed_collector_result({**raw, 'question_evidence': dict(source_id=context['source']['id'],
            version=context['source']['version'], quote=context['source']['text'], char_start=0,
            char_end=len(context['source']['text']), attribution=None)}, context)
