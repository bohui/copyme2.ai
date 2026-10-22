"""Governed-only, evidence-bound continuity for the visible collector turn.

This extension does not own interview strategy, language or chosen-name policy.
It delegates the original interview result to its existing validator and emits
only data suitable for the existing transactional continuity writer. Model text
is kept verbatim: an authentic quote cannot license an invented paraphrase.
"""
from __future__ import annotations

from pathlib import Path

from copy import deepcopy
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .prompt_artifact import load_prompt_artifact, prompt_path
from .interview_plan import collector_schema, constrain_acknowledgement, validate_collector_result
from .place_journey import grounded_place_journeys, validate_place_journey, PlaceResearchWindow


MAX_CONTINUITY_UPDATES = 8


GOVERNED_CONTINUITY_INSTRUCTIONS = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/legacy/governed-continuity'))


class _ContinuityUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    kind: Literal['person', 'unresolved_reference', 'commitment', 'excluded_topic', 'paused_topic']
    text: str = Field(min_length=1, max_length=500)
    assertion: Literal['asserted', 'inferred']
    uncertainty: str | None = Field(max_length=500)
    source_id: str = Field(min_length=1, max_length=128)
    source_version: int = Field(ge=1, strict=True)
    char_start: int = Field(ge=0, strict=True)
    char_end: int = Field(ge=1, strict=True)
    quote: str = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def faithful_text(self):
        if not self.text.strip() or self.text != self.quote:
            raise ValueError('Continuity text must preserve the exact attributed quote')
        if self.char_end - self.char_start != len(self.quote):
            raise ValueError('Continuity span must cover exact original characters')
        if self.assertion == 'inferred' and not (self.uncertainty or '').strip():
            raise ValueError('Inferred continuity requires explicit uncertainty')
        return self


class _Updates(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    continuity_updates: list[_ContinuityUpdate] = Field(max_length=MAX_CONTINUITY_UPDATES)


class _PlaceJourney(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    place: str = Field(min_length=1, max_length=120)
    hierarchy: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(min_length=2, max_length=6)
    granularity: Literal['country', 'region', 'city', 'suburb']
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    research: PlaceResearchWindow | None = None


class _Places(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    place_journeys: list[_PlaceJourney] = Field(max_length=8)


class _LegacyIntent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    selection_reason: Literal['latest_story', 'user_redirect', 'current_correction',
                              'pacing', 'pause', 'direct_answer']


def governed_collector_schema(context=None):
    """Extend the governed wire without modifying saved legacy plans.

    Older responses may omit extensions unless a pending confirmation requires
    current intent. The caller budgets these full required wire-schema bytes.
    """
    if (context or {}).get('reply_contract') == 'reply-v2':
        from .conversation_reply import reply_schema
        schema = reply_schema(context)
        if context.get('reviewed_acknowledgement') is not None:
            constrain_acknowledgement(schema, [context['reviewed_acknowledgement']])
        return schema
    if (context or {}).get('strategy_selector'):
        from .interview_strategy import selector_schema
        schema=selector_schema(context)
    else:
        schema = deepcopy(collector_schema(context))
        if (context or {}).get('two_lane_memory') is True:
            intent = _LegacyIntent.model_json_schema()['properties']['selection_reason']
            intent.pop('default', None)
            schema['properties']['selection_reason'] = intent
            schema['required'].append('selection_reason')
    if (context or {}).get('reviewed_acknowledgement') is not None:
        constrain_acknowledgement(schema, [context['reviewed_acknowledgement']])
    extension = continuity_schema((context or {}).get('source'))
    schema.setdefault('$defs', {}).update(extension['$defs'])
    schema['properties']['continuity_updates'] = extension['properties']['continuity_updates']
    schema['required'].append('continuity_updates')
    if (context or {}).get('two_lane_memory') is True:
        return schema
    places = _Places.model_json_schema()
    places['$defs']['_PlaceJourney']['required'] = list(places['$defs']['_PlaceJourney']['properties'])
    for field in ('latitude', 'longitude'):
        places['$defs']['_PlaceJourney']['properties'][field].pop('default', None)
    schema['$defs'].update(places['$defs'])
    schema['properties']['place_journeys'] = places['properties']['place_journeys']
    schema['required'].append('place_journeys')
    return schema


def _current_source(context):
    source = context.get('source')
    if source is None:
        return None
    # Older governed fixtures omit kind/role. Any explicit non-narrator
    # provenance is rejected; actual production rows have a canonical kind.
    if (not isinstance(source, dict) or source.get('status') != 'active'
            or source.get('kind', 'narrator_chat') not in {'narrator_chat', 'narrator_transcript'}
            or source.get('role', 'storyteller') not in {'storyteller', 'narrator', 'user'}
            or not isinstance(source.get('id'), str) or not source['id']
            or type(source.get('version')) is not int or source['version'] < 1
            or not isinstance(source.get('text'), str)):
        raise ValueError('Continuity requires an active original current narrator source')
    return source


_PRIVACY_KINDS = {'excluded_topic', 'paused_topic'}


def continuity_schema(source=None, *, background=False):
    schema = _Updates.model_json_schema()
    item = schema['$defs']['_ContinuityUpdate']['properties']
    for field in ('char_start', 'char_end'):
        item[field] = {'anyOf': [item[field], {'type': 'null'}]}
    if source:
        item['source_id']['const'] = source['id']
        item['source_version']['const'] = source['version']
    if background:
        item['kind']['enum'] = ['person', 'unresolved_reference', 'commitment']
    return schema


def validate_continuity_updates(updates, source, *, background=False):
    """Locate only explicitly null, unique spans in the admitted original window."""
    offset = (source or {}).get('char_start', 0)
    if isinstance(updates, list):
        updates = deepcopy(updates)
        for item in updates:
            if not isinstance(item, dict) or source is None:
                continue
            start, end, quote = item.get('char_start'), item.get('char_end'), item.get('quote')
            locate = start is None and end is None and 'char_start' in item and 'char_end' in item
            if isinstance(quote, str) and locate:
                position = source['text'].find(quote)
                if position >= 0 and source['text'].find(quote, position + 1) < 0:
                    item.update(char_start=offset + position, char_end=offset + position + len(quote))
    proposed = _Updates.model_validate({'continuity_updates': updates}).continuity_updates
    if proposed and source is None:
        raise ValueError('Continuity requires exact current narrator evidence')
    seen = set()
    for item in proposed:
        if (item.source_id != source['id'] or item.source_version != source['version']
                or item.char_start < offset or item.char_end > offset + len(source['text'])
                or source['text'][item.char_start-offset:item.char_end-offset] != item.quote):
            raise ValueError('Continuity requires exact current narrator evidence')
        key = (item.kind, item.char_start, item.char_end)
        if key in seen:
            raise ValueError('Duplicate continuity update')
        seen.add(key)
        if background and item.kind in _PRIVACY_KINDS:
            raise ValueError('Background continuity cannot propose privacy controls')
        if item.kind in _PRIVACY_KINDS and item.assertion != 'asserted':
            raise ValueError('Privacy restrictions require a completed current-source review')
    return _rows(proposed)


def validate_governed_collector_result(raw, context):
    """Validate existing planning first, then return server-owned continuity rows."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise ValueError('Collector result must be an object')
    outcome=None
    selection_reason=None
    immediate_name=None
    if context.get('reply_contract') == 'reply-v2':
        from .conversation_reply import adapt_reply
        value, selection_reason, outcome, stopped, immediate_name = adapt_reply(value, context)
    elif context.get('strategy_selector'):
        from .interview_strategy import adapt_selection
        value,outcome,stopped=adapt_selection(value,context)
        selection_reason=outcome['selection_reason']
    elif context.get('two_lane_memory') is True:
        intent = {key: item for key, item in value.items() if key == 'selection_reason'}
        if intent:
            selection_reason = _LegacyIntent.model_validate(intent).selection_reason
        value = {key: item for key, item in value.items() if key != 'selection_reason'}
    ordinary = {key: item for key, item in value.items() if key not in {'continuity_updates', 'place_journeys'}}
    result = validate_collector_result(ordinary, context)
    if (context.get('reviewed_acknowledgement') is not None
            and result['acknowledgement'] != context['reviewed_acknowledgement']):
        raise ValueError('Correction cannot replace the streamed acknowledgement')
    ordinary['stopped'] = result['stopped']
    if selection_reason in {'pause', 'direct_answer'} and result['plan']['candidates']:
        raise ValueError('A pause or direct answer requires no question')
    if context.get('prepared_questions'):
        from .two_lane_memory import pending_confirmation, prioritize_confirmation
        # A validated stop already carries intent; a follow-up needs the model's signal.
        if selection_reason is None and not result['stopped'] and pending_confirmation(context):
            raise ValueError('Pending confirmation requires selection_reason')
        prioritized = prioritize_confirmation(ordinary, context, selection_reason=selection_reason)
        if prioritized is not ordinary:
            result = validate_collector_result(prioritized, context)
            if outcome is not None:
                chosen = result['plan']['candidates'][0]
                outcome = {**outcome, 'selected_candidate_id': chosen['id'],
                           'selection_reason': 'prepared_candidate', 'question_delivered': chosen['question']}
    if outcome is not None:result.update(strategy_outcome=outcome,stopped=stopped)
    source = _current_source(context)
    updates = validate_continuity_updates(value.get('continuity_updates', []), source)

    places = _Places.model_validate({'place_journeys': [] if context.get('two_lane_memory') is True
        else value.get('place_journeys', [])}).place_journeys
    candidates = [validate_place_journey(place.model_dump()) for place in places
                  if place.hierarchy[-1] == place.place]
    journeys = grounded_place_journeys([place for place in candidates if place is not None],
                                      source['text']) if source else []
    return {**result, **({'immediate_name': immediate_name} if context.get('reply_contract') == 'reply-v2' else {}),
            'continuity_updates': updates,
            'place_journeys': journeys}


def _rows(selected):
    # A source-span index stays stable if another proposal is omitted or reordered.
    selected.sort(key=lambda item: (item.char_start, item.char_end, item.kind))
    rows = []
    for item in selected:
        seed = f'memoir:continuity:{item.source_id}:{item.source_version}:{item.kind}:{item.char_start}:{item.char_end}'
        record_id = ('semantic-v1:' + sha256(seed.encode('utf-8')).hexdigest()
                     if item.kind in _PRIVACY_KINDS else str(uuid5(NAMESPACE_URL, seed)))
        rows.append({'record_id': record_id, 'kind': item.kind, 'data': {
            'text': item.text, 'assertion': item.assertion, 'uncertainty': None if item.kind in _PRIVACY_KINDS else item.uncertainty,
            'source_refs': [{'source_id': item.source_id, 'version': item.source_version,
                'char_start': item.char_start, 'char_end': item.char_end, 'quote': item.quote}],
        }})
    return rows
