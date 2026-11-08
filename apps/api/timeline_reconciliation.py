"""The second Timeline phase chooses event identities. The host owns publication."""
import json
from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .active_location import chronological_event_indices
from .memory_events import ExtractionResult, _memory_birth_year
from .place_identity import place_identity
from .place_journey import grounded_place_journeys, validate_place_journey


EVIDENCE_LISTS = frozenset({'source_refs', 'stage_evidence', 'location_basis', 'relations'})
DRAFT_CONFLICT = 'Drafts for the same event disagree'


def uses_reconciliation(selected):
    return selected is not None and 'memoir-author-timeline' in selected


class PublishedOrder(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['before', 'after']
    event_id: str = Field(min_length=1, max_length=128)
    evidence_index: int = Field(ge=0, le=99)


class DraftDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    draft_index: int = Field(ge=0, le=99)
    action: Literal['create', 'update', 'unresolved']
    event_id: str | None = Field(max_length=128)
    candidate_ids: list[str] = Field(max_length=16)
    correction: bool
    order: list[PublishedOrder] = Field(max_length=16)


class ReconciliationResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    decisions: list[DraftDecision] = Field(min_length=1, max_length=100)


def placement_hints(drafts, birth_year):
    def year(timing, estimate, endpoint):
        stated = timing.get('year_'+endpoint)
        inferred = estimate.get('year_'+endpoint)
        age = estimate.get('age_'+endpoint)
        return stated or inferred or (birth_year+age if birth_year is not None and age is not None else None)
    hints = []
    for draft in drafts:
        timing, estimate = draft.get('temporal') or {}, draft.get('temporal_estimate') or {}
        hint = dict(kind=draft['kind'], location=draft.get('location'),
            start_year=year(timing,estimate,'start'), end_year=year(timing,estimate,'end'))
        if hint not in hints:
            hints.append(hint)
    return hints


def assign_event_identities(raw, drafts, candidates):
    """Apply a complete decision set without accepting model-written evidence."""
    result = ReconciliationResult.model_validate(raw)
    by_index = {item.draft_index:item for item in result.decisions}
    if len(by_index) != len(result.decisions) or set(by_index) != set(range(len(drafts))):
        raise ValueError('Each draft requires exactly one reconciliation decision')
    published = {event['id']:event for event in candidates}
    proposals = deepcopy(drafts)
    for index, draft in enumerate(proposals):
        decision = by_index[index]
        possible = decision.candidate_ids
        saved = published.get(decision.event_id)
        if decision.action == 'update':
            if not saved or draft['kind'] != saved['kind'] or possible:
                raise ValueError('Update requires a compatible published event')
            draft.update(existing_id=saved['id'], expected_revision=saved['revision'])
            if decision.correction:
                draft['correction'] = draft['source_refs'][0]
            else:
                draft['title'] = saved['title'] or draft['title']
        elif (decision.event_id or decision.correction or
              bool(possible) != (decision.action == 'unresolved') or
              any(event_id not in published or published[event_id]['kind'] != draft['kind'] for event_id in possible)):
            raise ValueError('Create or unresolved decision has an invalid published target')
        elif possible:
            draft['candidate_ids'] = list(dict.fromkeys(possible))
        for order in decision.order:
            if (order.event_id not in published or order.event_id == decision.event_id
                    or order.evidence_index >= len(draft['source_refs']) or possible):
                raise ValueError('Published order requires its scoped target and draft evidence')
            draft.setdefault('relations', []).append(dict(kind=order.kind, event_id=order.event_id,
                source_refs=[draft['source_refs'][order.evidence_index]]))
    return proposals


def _append_distinct(target, values):
    for value in values:
        if value not in target:
            target.append(value)


def _merge_update(current, draft):
    if draft.get('correction') and not current.get('correction'):
        current['title'] = draft['title']
        if 'description' in draft:
            current['description'] = draft['description']
    for key, value in draft.items():
        if key in EVIDENCE_LISTS:
            _append_distinct(current.setdefault(key, []), value)
        elif key not in current:
            current[key] = value
        elif key == 'timing_hint':
            if value['confidence'] > current[key]['confidence']:
                current[key] = value
        elif key in {'temporal', 'temporal_estimate'} and value and current[key]:
            previous = current[key]
            if any(previous.get(field) != value.get(field) for field in (previous.keys() | value.keys()) - {'basis'}):
                raise ValueError(DRAFT_CONFLICT)
            _append_distinct(previous.setdefault('basis', []), value.get('basis', []))
        elif key not in {'id', 'title', 'description', 'correction'} and current[key] != value:
            raise ValueError(DRAFT_CONFLICT)


def group_event_drafts(drafts, links, published, profile):
    """Return one publication per identity, with all event-link indexes remapped."""
    saved = {event['id']: event for event in published if event.get('status') != 'withdrawn'}
    events, by_identity, draft_indexes = [], {}, []
    draft_targets = {}
    for draft in deepcopy(drafts):
        local_id = draft.pop('id', None)
        identity = draft.get('existing_id')
        if identity:
            current = saved.get(identity)
            if (not current or current['revision'] != draft.get('expected_revision')
                    or current['kind'] != draft['kind']):
                raise ValueError('Canonical event revision conflict')
            timing = draft.get('temporal') or {}
            stated_range = timing.get('year_start') is not None and timing.get('year_end') is not None
            if not draft.get('temporal_estimate') and not stated_range:
                draft.pop('temporal_estimate', None)
                if not timing.get('basis'):
                    draft.pop('yearConfidenceScore', None)
                    if draft.get('correction'):
                        draft.pop('temporal', None)
                        if not draft.get('stage_evidence'):
                            draft.pop('timing_hint', None)
            if not draft.get('location') and not draft.get('location_basis'):
                for key in ('location', 'location_basis', 'locationConfidenceScore'):
                    draft.pop(key, None)
            if draft.get('correction') and not draft.get('stage_evidence'):
                draft.pop('stage_evidence', None)
                if draft.get('life_stage') == 'unplaced':
                    draft.pop('life_stage')
            if identity in by_identity:
                index = by_identity[identity]
                _merge_update(events[index], draft)
            else:
                index = by_identity[identity] = len(events)
                events.append(draft)
        else:
            # Exact duplicates can share a new identity. Similar recollections
            # stay separate unless the original supports a canonical match.
            index = next((i for i, item in enumerate(events) if item == draft), len(events))
            if index == len(events):
                events.append(draft)
        draft_indexes.append(index)
        if local_id:
            draft_targets[local_id] = index

    # Existing timing and order still apply when a draft only adds evidence.
    effective = [{**saved.get(event.get('existing_id'), {}), **event} for event in events]
    identities = [event.get('existing_id') or f'draft@{index}' for index, event in enumerate(events)]
    for index, event in enumerate(effective):
        event['id'] = identities[index]
        relations = []
        for relation in event.get('relations') or []:
            if 'draft_id' not in relation:
                relations.append(relation)
                continue
            target = draft_targets.get(relation['draft_id'])
            if target is not None and target != index and not events[target].get('candidate_ids'):
                relations.append({**relation, 'event_id': identities[target]})
        event['relations'] = relations
    order = chronological_event_indices(effective, profile)
    positions = {index: position for position, index in enumerate(order)}
    event_places = []
    for link in links:
        index = draft_indexes[link['event_index']]
        if events[index].get('candidate_ids'):
            continue
        item = {**link, 'event_index': positions[index]}
        _append_distinct(event_places, [item])
    grouped = [events[index] for index in order]
    ExtractionResult.model_validate({'events': grouped})
    for index, event in zip(order, grouped):
        if 'relations' not in event:
            continue
        relations = []
        for relation in effective[index]['relations']:
            if 'draft_id' in relation:
                target = draft_targets[relation['draft_id']]
                relation = {key: value for key, value in relation.items() if key != 'draft_id'}
                if not events[target].get('existing_id'):
                    relation.pop('event_id')
                    relation['draft_index'] = positions[target]
            _append_distinct(relations, [relation])
        if relations or not event.get('existing_id'):
            event['relations'] = relations
        else:
            del event['relations']
    return grouped, event_places


def event_place_journeys(events, links, page):
    """Keep the legacy research/active-location feed as a projection of events."""
    source = page['source']
    narrator = {'narrator', 'storyteller', 'self', '我', '本人', page['user_id']}
    if name := page.get('preferences', {}).get('chosen_name'):
        narrator.add(name.casefold())
    places = {}
    for link in sorted(links, key=lambda item: item['event_index']):
        event = events[link['event_index']]
        ref = link['source_ref']
        if any(label and label.casefold() not in narrator for label in
               (event.get('attribution'), ref.get('attribution'))):
            continue
        place = link['place']
        if place['granularity'] == 'landmark':
            if len(place['hierarchy']) < 4:
                continue
            hierarchy = place['hierarchy'][:-1]
            place = dict(place=hierarchy[-1], hierarchy=hierarchy, granularity='city')
        # Public research requires stated timing and a source-bound place.
        # Provisional event estimates remain available on the map cards.
        temporal = event.get('temporal') or {}
        start = temporal.get('year_start')
        end = temporal.get('year_end') or start
        for basis in temporal.get('basis', []):
            if (start is None or not 1800 <= start <= end <= 2100 or end - start > 15
                    or basis['source_id'] != source['id'] or place['place'] not in basis['quote']):
                continue
            birth_decade = start == end and _memory_birth_year(basis['quote']) == start
            lower = start // 10 * 10 if birth_decade else start
            upper = lower + 9 if birth_decade else end
            place = {**place, 'research': dict(year_start=lower, year_end=upper, anchor_year=start,
                basis='birth_decade' if birth_decade else 'explicit_period', quote=basis['quote'],
                char_start=basis['char_start'], char_end=basis['char_end'])}
            break
        if place['place'].casefold() in source['text'].casefold() and (normalized := validate_place_journey(place)):
            key = place_identity(normalized)
            if key not in places or not places[key].get('research'):
                places[key] = normalized
    bounded = []
    for place in grounded_place_journeys(list(places.values()), source['text'], source_offset=source['char_start']):
        if len(bounded) == 8:
            break
        if len(json.dumps([*bounded, place], ensure_ascii=False).encode()) <= 8192:
            bounded.append(place)
    return bounded
