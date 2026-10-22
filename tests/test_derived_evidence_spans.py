"""Derived Lane B coordinates never change the admitted words or other guards."""
from copy import deepcopy

import pytest

from apps.api.interview_questions import question_span
from apps.api.lifetime_memory_continuity import validate_continuity_updates
from apps.api.place_journey import PlaceResearchWindow
from apps.api.two_lane_memory import derived_hints


ENGLISH = 'From 1988 to 1992 I worked in Perth.'
CHINESE = '从1988年到1992年，我在珀斯工作。'


def proposal(quote=ENGLISH, *, repeated=False):
    text = quote + ' ' + quote if repeated else 'A memory: ' + quote
    source = dict(id='source', version=1, text=text, char_start=8192, status='active')
    research = dict(year_start=1988, year_end=1992, anchor_year=None, basis='explicit_period',
        quote=quote, char_start=0, char_end=11)
    raw = dict(place_journeys=[dict(place='Perth', hierarchy=['Earth', 'Australia', 'Perth'],
        granularity='city', latitude=None, longitude=None, research=research)],
        prepared_questions=[dict(question='What do you remember?', topic='work', quote=quote,
            char_start=0, char_end=11)])
    # Keep the geographic label in the original script.
    if quote == CHINESE:
        raw['place_journeys'][0].update(place='珀斯', hierarchy=['Earth', '澳大利亚', '珀斯'])
    return raw, dict(source=source)


@pytest.mark.parametrize('quote', [ENGLISH, CHINESE])
def test_unique_derived_quotes_repair_numeric_coordinates_in_nonzero_source_window(quote):
    raw, page = proposal(quote)
    original = deepcopy(raw)
    result = derived_hints(raw, page)
    start = page['source']['char_start'] + page['source']['text'].index(quote)
    for item in [result['place_journeys'][0]['research'], result['prepared_questions'][0]]:
        assert (item['char_start'], item['char_end'], item['quote']) == (start, start + len(quote), quote)
    assert result['place_journeys'][0]['research']['year_start'] == 1988
    assert result['place_journeys'][0]['research']['year_end'] == 1992
    assert raw == original


def test_correct_explicit_coordinates_preserve_selected_repeated_occurrence():
    raw, page = proposal(repeated=True)
    start = page['source']['char_start'] + len(ENGLISH) + 1
    for item in [raw['place_journeys'][0]['research'], raw['prepared_questions'][0]]:
        item.update(char_start=start, char_end=start + len(ENGLISH))
    result = derived_hints(raw, page)
    assert result['place_journeys'][0]['research'] == raw['place_journeys'][0]['research']
    assert result['prepared_questions'][0]['char_start'] == start


@pytest.mark.parametrize('target', ['research', 'question'])
@pytest.mark.parametrize('failure', ['ambiguous', 'fabricated', 'partial_null', 'bool', 'negative', 'string', 'extra'])
def test_derived_span_repair_cannot_clear_invalid_fields_or_unmatched_quotes(target, failure):
    raw, page = proposal(repeated=failure == 'ambiguous')
    item = raw['place_journeys'][0]['research'] if target == 'research' else raw['prepared_questions'][0]
    other = raw['prepared_questions'][0] if target == 'research' else raw['place_journeys'][0]['research']
    position = page['source']['char_start'] + page['source']['text'].index(other['quote'])
    other.update(char_start=position, char_end=position + len(other['quote']))
    if failure == 'fabricated': item['quote'] = 'An assistant question, absent from narrator testimony.'
    if failure == 'partial_null': item['char_start'] = None
    if failure == 'bool': item['char_end'] = True
    if failure == 'negative': item['char_start'] = -1
    if failure == 'string': item['char_end'] = '11'
    if failure == 'extra': item['source_id'] = 'foreign-source'
    with pytest.raises(ValueError):
        derived_hints(raw, page)


@pytest.mark.parametrize('change', [
    {'year_start': 1799}, {'year_end': 2101}, {'year_end': 1980},
    {'year_end': 2004}, {'anchor_year': 2000}, {'basis': 'inferred'},
    {'char_start': None, 'char_end': None},
])
def test_research_dates_and_required_coordinate_types_validate_before_repair(change):
    raw, page = proposal()
    raw['place_journeys'][0]['research'].update(change)
    with pytest.raises(ValueError):
        derived_hints(raw, page)


@pytest.mark.parametrize('missing', ['char_start', 'char_end'])
def test_required_research_coordinates_are_not_manufactured(missing):
    raw, page = proposal()
    del raw['place_journeys'][0]['research'][missing]
    with pytest.raises(ValueError):
        derived_hints(raw, page)


@pytest.mark.parametrize('field,count', [('place_journeys', 9), ('prepared_questions', 6)])
def test_repair_does_not_drop_proposals_to_bypass_list_bounds(field, count):
    raw, page = proposal()
    raw[field] = [deepcopy(raw[field][0]) for _ in range(count)]
    with pytest.raises(ValueError):
        derived_hints(raw, page)


def test_existing_null_spanned_question_still_resolves_one_exact_passage():
    raw, page = proposal()
    raw['prepared_questions'][0].update(char_start=None, char_end=None)
    result = derived_hints(raw, page)
    assert result['prepared_questions'][0]['char_start'] == 8202


def test_research_without_lane_b_context_and_foreground_questions_remain_strict():
    raw, page = proposal()
    with pytest.raises(ValueError, match='Invalid research evidence span'):
        PlaceResearchWindow.model_validate(raw['place_journeys'][0]['research'])
    with pytest.raises(ValueError, match='Question evidence span'):
        question_span(page['source'], ENGLISH, 0, 11)


@pytest.mark.parametrize('kind', ['person', 'excluded_topic', 'paused_topic'])
def test_continuity_and_privacy_coordinates_remain_strict(kind):
    _, page = proposal()
    source = page['source']
    update = dict(kind=kind, text=ENGLISH, assertion='asserted', uncertainty=None,
        source_id=source['id'], source_version=source['version'], quote=ENGLISH,
        char_start=0, char_end=11)
    with pytest.raises(ValueError):
        validate_continuity_updates([update], source)
