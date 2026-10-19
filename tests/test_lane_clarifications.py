"""Lane B confirmations preempt ordinary follow-ups without overriding narrator controls."""
from copy import deepcopy

import pytest

from apps.api.lifetime_memory_continuity import validate_governed_collector_result
from apps.api.two_lane_memory import derived_hints
from test_name_only_opening import proposal
from test_interview_strategy import context as strategy_context, wire


CONFIRMATION = {'id': 'bq-' + 'a' * 64, 'question': '您说的大石庙是承德双桥区的大石庙镇吗？',
                'topic': '大石庙位置', 'quote': '大石庙', 'requires_confirmation': True}


def test_lane_b_preserves_a_grounded_confirmation_in_the_question_pool():
    question = {key: value for key, value in CONFIRMATION.items() if key != 'id'}
    result = derived_hints({'place_journeys': [], 'prepared_questions': [question]},
                           {'source': {'text': '我小时候住在大石庙。'}})
    assert result['prepared_questions'] == [question]


@pytest.mark.parametrize('selector', [False, True])
def test_confirmation_hijacks_the_next_question_in_both_collectors(selector):
    context = strategy_context(text='I remember our walks.')
    context.update(two_lane_memory=True, strategy_selector=selector,
                   prepared_questions=[{**CONFIRMATION, 'requires_confirmation': False}, CONFIRMATION])
    before = deepcopy(context)
    value = wire(selection_reason='latest_story') if selector else proposal(
        mode='extract', name=None, question='What happened on those walks?')
    result = validate_governed_collector_result(value, context)
    assert result['plan']['chosen_id'] == CONFIRMATION['id']
    assert result['reply'].endswith(CONFIRMATION['question'])
    assert len(result['plan']['candidates']) == 1
    assert context == before


@pytest.mark.parametrize('selector', [False, True])
def test_a_confirmation_does_not_force_a_question_after_a_pause(selector):
    context = strategy_context(text='Not today.')
    context.update(two_lane_memory=True, strategy_selector=selector, prepared_questions=[CONFIRMATION])
    value = wire(question=None, selection_reason='pause', stopped=True) if selector else proposal(
        mode='reply_only', name=None)
    if not selector:
        value['stopped'] = True
        value['plan'].update(candidates=[], chosen_id=None)
    result = validate_governed_collector_result(value, context)
    assert not result['plan']['candidates']


def test_a_confirmation_present_in_both_pools_keeps_a_valid_selector_schema():
    from jsonschema import validate
    from apps.api.lifetime_memory_continuity import governed_collector_schema
    context = strategy_context(text='I remember our walks.')
    context['prepared_questions'] = [CONFIRMATION]
    context['strategy_context']['plan']['candidates'] = [CONFIRMATION]
    schema = governed_collector_schema({**context, 'two_lane_memory': True})
    validate(wire(question=CONFIRMATION['question'], selected_candidate_id=CONFIRMATION['id'],
                  selection_reason='prepared_candidate'), schema)


def test_a_current_correction_still_takes_priority_over_a_pending_confirmation():
    context = strategy_context(text='Correction: I meant the garden.')
    context['prepared_questions'] = [CONFIRMATION]
    result = validate_governed_collector_result(wire(selection_reason='current_correction'), context)
    assert result['plan']['chosen_id'] != CONFIRMATION['id']


@pytest.mark.parametrize('text,reason,question', [
    ('Actually, it was Perth, not Hobart.', 'current_correction', 'What do you remember about Perth?'),
    ("I'd prefer to tell you about my sister.", 'user_redirect', 'What would you like to remember about your sister?'),
    ('Could you make the next question easier?', 'pacing', 'Which part feels easiest to begin with?'),
])
def test_model_recognized_controls_outrank_confirmation_without_literal_keyword(text, reason, question):
    from apps.api.interview_strategy import current_constraints
    context = strategy_context(text=text)
    confirmation = {**CONFIRMATION, 'question': 'Did you mean Hobart in Tasmania?', 'topic': 'Hobart'}
    context.update(two_lane_memory=True, prepared_questions=[confirmation])
    assert current_constraints(text) == {}, 'Exercise semantic intent beyond the literal fallback'
    result = validate_governed_collector_result(wire(question=question, selection_reason=reason), context)
    assert result['reply'].endswith(question)
    assert result['strategy_outcome']['selection_reason'] == reason
    assert result['strategy_outcome']['selected_candidate_id'] is None
    assert result['plan']['chosen_id'] != confirmation['id']
    assert context['prepared_questions'] == [confirmation]


def test_model_recognized_control_still_validates_the_proposed_candidate():
    context = strategy_context(text='Actually, it was Perth, not Hobart.')
    context['prepared_questions'] = [CONFIRMATION]
    with pytest.raises(ValueError, match='Candidate is stale, asked or outside this project'):
        validate_governed_collector_result(wire(selection_reason='current_correction',
            selected_candidate_id='cross-project'), context)
