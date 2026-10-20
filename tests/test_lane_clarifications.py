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
    start = '我小时候住在大石庙。'.index('大石庙')
    assert result['prepared_questions'] == [{**question, 'char_start': start, 'char_end': start + len('大石庙')}]


@pytest.mark.parametrize('selector', [False, True])
def test_confirmation_hijacks_the_next_question_in_both_collectors(selector):
    context = strategy_context(text='I remember our walks.')
    context.update(two_lane_memory=True, strategy_selector=selector,
                   prepared_questions=[{**CONFIRMATION, 'requires_confirmation': False}, CONFIRMATION])
    before = deepcopy(context)
    value = wire(selection_reason='latest_story') if selector else proposal(
        mode='extract', name=None, question='What happened on those walks?')
    if not selector:
        value['selection_reason'] = 'latest_story'
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
        value['selection_reason'] = 'pause'
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
@pytest.mark.parametrize('mode', ['active', 'legacy', 'shadow'])
def test_model_recognized_controls_outrank_confirmation_without_literal_keyword(text, reason, question, mode):
    from apps.api.interview_strategy import current_constraints
    context = strategy_context(text=text)
    confirmation = {**CONFIRMATION, 'question': 'Did you mean Hobart in Tasmania?', 'topic': 'Hobart'}
    context.update(two_lane_memory=True, strategy_selector=mode == 'active', prepared_questions=[confirmation])
    if mode == 'shadow':
        context['strategy_context']['mode'] = 'shadow'
    assert current_constraints(text) == {}, 'Exercise semantic intent beyond the literal fallback'
    value = wire(question=question, selection_reason=reason) if mode == 'active' else {
        **proposal(mode='extract', name=None, question=question), 'selection_reason': reason}
    result = validate_governed_collector_result(value, context)
    assert result['reply'].endswith(question)
    if mode == 'active':
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


@pytest.mark.parametrize('reason', ['pause', 'direct_answer'])
def test_control_reason_cannot_disguise_an_ordinary_question(reason):
    context = strategy_context(text='I remember our walks.')
    context.update(two_lane_memory=True, prepared_questions=[CONFIRMATION])
    with pytest.raises(ValueError, match='requires no question'):
        validate_governed_collector_result(wire(selection_reason=reason), context)


@pytest.mark.parametrize('changes', [
    {'selection_reason': 'current_redirect'},
    {'selection_reason': 'current_pacing'},
    {'selection_reason': 'adapted_candidate', 'selected_candidate_id': 'cross-project'},
    {'question': 7},
])
def test_confirmation_cannot_launder_an_invalid_selector_proposal(changes):
    context = strategy_context(text='I remember our walks.')
    context.update(two_lane_memory=True, prepared_questions=[CONFIRMATION])
    with pytest.raises(ValueError):
        validate_governed_collector_result(wire(**{'selection_reason': 'latest_story', **changes}), context)


@pytest.mark.parametrize('reason,stopped', [('pause', True), ('direct_answer', False)])
def test_valid_terminal_selector_outcomes_preserve_a_confirmation(reason, stopped):
    context = strategy_context(text='I remember our walks.')
    context.update(two_lane_memory=True, prepared_questions=[CONFIRMATION])
    result = validate_governed_collector_result(wire(question=None, selection_reason=reason, stopped=stopped), context)
    assert result['plan']['candidates'] == []
    assert result['strategy_outcome']['selection_reason'] == reason
    assert result['stopped'] is stopped
    assert context['prepared_questions'] == [CONFIRMATION]


@pytest.mark.parametrize('reason', [None, 'pause', 'direct_answer'])
def test_valid_terminal_legacy_outcomes_preserve_a_confirmation(reason):
    context = strategy_context(text='I remember our walks.')
    context.update(two_lane_memory=True, strategy_selector=False, prepared_questions=[CONFIRMATION])
    value = proposal(mode='reply_only', name=None)
    value['stopped'] = True
    value['plan'].update(candidates=[], chosen_id=None)
    if reason is not None:
        value['selection_reason'] = reason
    result = validate_governed_collector_result(value, context)
    assert result['plan']['candidates'] == [] and result['stopped'] is True
    assert context['prepared_questions'] == [CONFIRMATION]


def test_legacy_schema_requests_intent_without_changing_the_single_lane_contract():
    from jsonschema import validate, ValidationError
    from apps.api.lifetime_memory_continuity import governed_collector_schema
    context = strategy_context(text='Actually, it was Perth, not Hobart.')
    context.update(two_lane_memory=True, strategy_selector=False, prepared_questions=[CONFIRMATION])
    value = {**proposal(mode='extract', name=None, question='What do you remember about Perth?'),
             'continuity_updates': [], 'selection_reason': 'current_correction'}
    value['plan']['candidates'][0]['context']['historical_clue_id'] = None
    value['plan']['candidates'][0]['context']['evidence'] = None
    value['plan']['resolved_questions'] = []
    schema = governed_collector_schema(context)
    validate(value, schema)
    with pytest.raises(ValidationError):
        validate({k: v for k, v in value.items() if k != 'selection_reason'}, schema)
    assert 'selection_reason' not in governed_collector_schema()['properties']


def test_a_pending_legacy_confirmation_requires_an_explicit_intent_signal():
    context = strategy_context(text='Actually, it was Perth, not Hobart.')
    context.update(two_lane_memory=True, strategy_selector=False, prepared_questions=[CONFIRMATION])
    with pytest.raises(ValueError, match='selection_reason'):
        validate_governed_collector_result(proposal(mode='extract', name=None,
            question='What do you remember about Perth?'), context)


def test_legacy_confirmation_priority_uses_the_validated_stop_value():
    context = strategy_context(text='I remember our walks.')
    context.update(two_lane_memory=True, strategy_selector=False, prepared_questions=[CONFIRMATION])
    value = {**proposal(mode='extract', name=None), 'selection_reason': 'latest_story', 'stopped': 'false'}
    result = validate_governed_collector_result(value, context)
    assert result['stopped'] is False
    assert result['plan']['chosen_id'] == CONFIRMATION['id']


@pytest.mark.parametrize('changes', [
    {'selection_reason': 'current_redirect'},
    {'selection_reason': 'pause'},
    {'selection_reason': 'direct_answer'},
    {'selection_reason': 7},
    {'plan': {'candidates': [], 'chosen_id': 'missing', 'active_event_id': None}},
])
def test_confirmation_cannot_launder_an_invalid_legacy_proposal(changes):
    context = strategy_context(text='I remember our walks.')
    context.update(two_lane_memory=True, strategy_selector=False, prepared_questions=[CONFIRMATION])
    with pytest.raises(ValueError):
        validate_governed_collector_result({**proposal(mode='extract', name=None),
                                           'selection_reason': 'latest_story', **changes}, context)
