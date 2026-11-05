"""Story-owned location selection, independent of map navigation."""
from functools import cmp_to_key
import re

from .place_identity import geographic_label, place_path
from .memory_events import _memory_age_number
from .stage_readiness import LIFE_STAGES


def chronological_event_indices(events, profile):
    def timing(event):
        stated = event.get('temporal') or {}
        estimate = event.get('temporal_estimate') or {}
        year = stated.get('year_start')
        inferred = year is None
        year = year if year is not None else estimate.get('year_start')
        age = estimate.get('age_start')
        if stated.get('precision') == 'age':
            match = re.search(r'\d+', stated.get('expression', ''))
            stated_age = int(match[0]) if match else _memory_age_number(stated.get('expression', ''))
            if stated_age is not None:
                age = stated_age
        if year is None and age is not None and profile.get('birth_year'):
            year = profile['birth_year'] + age
        stage = LIFE_STAGES.index(event['life_stage']) if event.get('life_stage') in LIFE_STAGES else None
        date = re.match(r'^\d{4}[-/年](\d{1,2})(?:[-/月](\d{1,2}))?', stated.get('expression', ''))
        calendar = (year, int(date[1]) if date else 1, int(date[2] or 1) if date else 1) if year is not None else None
        if event.get('timing_conflict'):
            return None, None, None, False
        return calendar, age, stage, inferred

    def compare(a, b):
        ac, aa, ast, ai = timing(a[1])
        bc, ba, bst, bi = timing(b[1])
        if ac and bc:
            # A broad estimate beginning at birth cannot precede the dated birth.
            left, right = ((ac[0], ai, ac), (bc[0], bi, bc)) if ai or bi else (ac, bc)
        elif aa is not None and ba is not None:
            left, right = aa, ba
        elif ast is not None and bst is not None:
            left, right = ast, bst
        else:
            left, right = ac is None and ast is None, bc is None and bst is None
        return (left > right) - (left < right) or a[0] - b[0]

    ordered = [index for index, _ in sorted(enumerate(events), key=cmp_to_key(compare))]
    identities = {event.get('existing_id') or event.get('id'): index for index, event in enumerate(events)}
    dependencies = {index: set() for index in ordered}
    for index, event in enumerate(events):
        if event.get('timing_conflict'):
            continue
        for relation in event.get('relations') or []:
            target = identities.get(relation['event_id'])
            if target is None or target == index or events[target].get('timing_conflict'):
                continue
            if relation['kind'] == 'before':
                dependencies[target].add(index)
            else:
                dependencies[index].add(target)
    remaining, result = set(ordered), []
    while remaining:
        next_index = next((index for index in ordered if index in remaining
                           and not (dependencies[index] & remaining)), None)
        if next_index is None:
            return ordered
        remaining.remove(next_index)
        result.append(next_index)
    return result


def chronological_places(places, events, links, profile):
    ranks = {}
    for rank, index in enumerate(chronological_event_indices(events, profile)):
        event = events[index]
        locations = [link['place'] for link in links if link['event_index'] == index]
        if event.get('location'):
            locations.append(event['location'])
        for place_index, place in enumerate(places):
            path = place_path(place, normalized=True)
            if any(place_path(location, normalized=True)[:len(path)] == path for location in locations):
                ranks.setdefault(place_index, rank)
    return [place for index, place in sorted(enumerate(places), key=lambda item: ranks.get(item[0], len(events)))]


def current_active_location(places, focus=None):
    """Persisted per-source journey order is chronological; a later focus can redirect it."""
    if not places:
        return None
    sequence = max(place.get('source_sequence', 0) for place in places)
    current = next(place for place in places if place.get('source_sequence', 0) == sequence)
    if focus and focus.get('source_sequence', 0) > sequence:
        matches = [place for place in places if geographic_label(place['place']) == geographic_label(focus['place'])]
        if not matches:
            matches = [place for place in places
                if any(geographic_label(part) == geographic_label(focus['place']) for part in place.get('hierarchy', []))]
        if len(matches) == 1:
            current = {**matches[0], 'source_sequence':focus['source_sequence']}
    return current
