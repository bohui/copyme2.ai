"""Current intent wins over the bounded, source-backed breadth checkpoint."""
from copy import deepcopy

from jsonschema import ValidationError, validate
import pytest

from test_interview_strategy import context, wire


@pytest.mark.parametrize('text,reason', [
    ('Please take it slowly, one short question at a time.', 'pacing'),
    ('请慢慢聊，每次只问一个简短问题。', 'pacing'),
    ('I meant my mother, not my father, repaired bicycles.', 'current_correction'),
    ('我说错了，修自行车的是母亲，不是父亲。', 'current_correction'),
])
def test_current_pacing_or_correction_cannot_be_acknowledgement_only(text, reason):
    from apps.api.lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
    c = {**context(text=text), 'two_lane_memory': True}
    bad = wire(question=None, selection_reason='direct_answer')
    with pytest.raises(ValidationError):
        validate(bad, governed_collector_schema(c))
    with pytest.raises(ValueError):
        validate_governed_collector_result(bad, c)
    good = wire(selection_reason=reason)
    validate(good, governed_collector_schema(c))
    validate_governed_collector_result(good, c)


def test_breadth_checkpoint_uses_canonical_events_and_remains_an_invitation():
    from apps.api.interview_strategy import stage_breadth_checkpoint
    coverage = [dict(life_stage='childhood', grounded_events=2, last_source_sequence=7),
                dict(life_stage='baby', grounded_events=1, last_source_sequence=1)]
    assert stage_breadth_checkpoint(coverage) is None
    coverage[0]['grounded_events'] = 3
    before = deepcopy(coverage)
    assert stage_breadth_checkpoint(coverage) == dict(current_stage='childhood',
        suggested_stage='adolescence', grounded_events=3, minimum_grounded_events=3)
    assert coverage == before
    assert stage_breadth_checkpoint([]) is None
    assert stage_breadth_checkpoint([dict(life_stage='unplaced', grounded_events=20, last_source_sequence=10)]) is None
    assert stage_breadth_checkpoint([dict(life_stage='later_life', grounded_events=3, last_source_sequence=10)])['suggested_stage'] == 'baby'
    from apps.api.stage_readiness import LIFE_STAGES
    assert stage_breadth_checkpoint([dict(life_stage=s, grounded_events=3, last_source_sequence=1) for s in LIFE_STAGES]) is None


@pytest.mark.parametrize('text,quote', [
    ('I meant my mother, not my father, repaired bicycles.', 'my father'),
    ('我说错了，修自行车的是母亲，不是父亲。', '父亲'),
])
def test_correction_does_not_assert_the_negated_alternative_as_current_continuity(text, quote):
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result
    c = context(text=text)
    update = dict(kind='person', text=quote, quote=quote, assertion='asserted', uncertainty=None,
        source_id=c['source']['id'], source_version=1, char_start=None, char_end=None)
    with pytest.raises(ValueError, match='superseded'):
        validate_governed_collector_result(wire(selection_reason='current_correction', continuity_updates=[update]), c)


def test_real_direct_question_remains_optional_but_a_reported_question_is_not_current_intent():
    from apps.api.lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
    c = {**context(text='I meant my mother. What happens to the old text?'), 'two_lane_memory': True}
    good = wire(question=None, selection_reason='direct_answer')
    validate(good, governed_collector_schema(c))
    validate_governed_collector_result(good, c)
    c['source']['text'] = 'Please take it slowly. He asked, what happens to the old text?'
    with pytest.raises(ValidationError):
        validate(good, governed_collector_schema(c))
