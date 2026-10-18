"""The production Lane A builder must stay small and match its output schema."""
import pytest

from apps.api.collector_prompt import governed_collector_instructions


@pytest.mark.parametrize('language', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('strategy', [None, 'comfort', 'explore', 'shape'])
def test_foreground_contract_is_bounded_and_does_not_request_background_places(language, strategy):
    context = {'interview_language': language, 'two_lane_memory': True}
    if strategy:
        context.update(strategy_selector=True, active_strategy=strategy)
    instructions = governed_collector_instructions(context)
    assert len(instructions) < 7500
    assert 'Return place_journeys' not in instructions
    assert 'continuity_updates' in instructions
    assert 'source_id' in instructions and 'source_version' in instructions
    assert 'quoted' in instructions and 'uncertainty' in instructions


def test_single_lane_still_supplies_its_required_place_contract():
    instructions = governed_collector_instructions({'interview_language': 'en-AU'})
    assert instructions.count('Return place_journeys') == 1


def test_selector_contract_is_place_free_without_the_redundant_two_lane_flag():
    instructions = governed_collector_instructions({
        'interview_language': 'en-AU', 'strategy_selector': True, 'active_strategy': 'explore',
    })
    assert 'Return place_journeys' not in instructions
