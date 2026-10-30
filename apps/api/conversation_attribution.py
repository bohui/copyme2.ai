"""Narrator attribution guards and exact timeline passage/place proposals."""
from copy import deepcopy
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .memory_events import EvidenceRef
from .place_journey import CoarsePlace, validate_place_journey
from .prompt_artifact import load_prompt_artifact, prompt_path

# Mask quotes across line/sentence boundaries, preserving a completed sentence
# so a subsequent direct request still belongs to the current narrator.
QUOTED_SENTENCE_PATTERN = r'"[^"]*[.!?。！？]\s*"|“[^”]*[.!?。！？]\s*”|‘(?:[^’]|’(?=\w)|(?<=\w)’(?=[ \t]+\w))*[.!?。！？]\s*’|「[^」]*[.!?。！？]\s*」|『[^』]*[.!?。！？]\s*』|`[^`]*[.!?。！？]\s*`'
QUOTED_PATTERN = r'"[^"]*(?:"|$)|“[^”]*(?:”|$)|‘(?:[^’]|’(?=\w)|(?<=\w)’(?=[ \t]+\w))*(?:’(?!\w|[ \t]+\w)|$)|「[^」]*(?:」|$)|『[^』]*(?:』|$)|`[^`]*(?:`|$)'
# Word/possessive apostrophes stay inside a quoted span. A sentence-ending
# quote can close next to Chinese text, which does not require a space.
QUOTED_SENTENCE_PATTERN += r"|(?<!\w)'(?:[^']|'(?=\w)|(?<=\w)'(?=[ \t]+\w))*[.!?。！？]\s*'"
QUOTED_PATTERN += r"|(?<!\w)'(?:[^']|'(?=\w)|(?<=\w)'(?=[ \t]+\w))*(?:'(?!\w|[ \t]+\w)|$)"
ATTRIBUTION_PATTERN = r'\b(?:said|says|told|asked)\b|(?:说|說|告诉|告訴)'


class EventPlace(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    event_index: int = Field(ge=0, le=99)
    role: Literal['setting', 'origin', 'destination']
    place: CoarsePlace
    source_ref: EvidenceRef


class PassageDisposition(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    disposition: Literal['non_story', 'unresolved', 'withheld']
    reason: Literal['conversation_control', 'profile_introduction', 'ambiguous_context',
        'no_supported_event', 'uncertain_identity', 'uncertain_attribution', 'privacy_withheld']
    source_ref: EvidenceRef


class AttributionProposals(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    event_places: list[EventPlace] = Field(default_factory=list, max_length=32)
    passage_dispositions: list[PassageDisposition] = Field(default_factory=list, max_length=64)


def validate_attribution(raw, page, events):
    proposed = AttributionProposals.model_validate({key: raw.get(key, []) for key in AttributionProposals.model_fields})
    source = page['source']
    result = proposed.model_dump(exclude_none=True)
    places = []
    for item in [*result['event_places'], *result['passage_dispositions']]:
        ref = item['source_ref']
        if ref['source_id'] != source['id'] or ref['version'] != source['version']:
            raise ValueError('Attribution requires the current original source')
        quote = ref['quote']
        lo, hi = ref.get('char_start'), ref.get('char_end')
        if not (type(lo) is int and type(hi) is int and 0 <= lo < hi <= len(source['text']) and source['text'][lo:hi] == quote):
            lo = source['text'].find(quote)
            if lo < 0 or source['text'].find(quote, lo + 1) >= 0:
                raise ValueError('Attribution requires an exact unambiguous span')
            hi = lo + len(quote)
        ref.update(char_start=lo + source['char_start'], char_end=hi + source['char_start'])
        if 'event_index' in item:
            if item['event_index'] >= len(raw['events']):
                raise ValueError('Place association requires its accepted event proposal')
            original = raw['events'][item['event_index']]
            def identity(event):
                return (event.get('existing_id'), event['kind'], event['title'],
                    [(r['source_id'], r['version'], r['quote']) for r in event['source_refs']])
            matches = [index for index, event in enumerate(events) if identity(event) == identity(original)]
            if not matches:
                continue  # A privacy-withheld proposal cannot create a place claim.
            if len(matches) != 1:
                raise ValueError('Place association requires one unambiguous event proposal')
            item['event_index'] = matches[0]
            score = events[matches[0]].get('locationConfidenceScore')
            if score is not None and score < 0.85:
                continue
            if events[matches[0]].get('candidate_ids'):
                continue  # An unresolved identity cannot authorize an event place.
            normalized = validate_place_journey(item['place'])
            if not normalized or item['place']['place'] not in quote:
                raise ValueError('Event place requires a named coarse place in its own evidence')
            if (item['place']['hierarchy'][-1] != item['place']['place']
                    or any(item['place'][key] != normalized[key] for key in CoarsePlace.model_fields)):
                raise ValueError('Event place hierarchy must retain its exact source label')
            if not any(r['source_id'] == ref['source_id'] and r['version'] == ref['version']
                    and r['char_start'] <= ref['char_start'] < ref['char_end'] <= r['char_end']
                    for r in events[item['event_index']]['source_refs']):
                raise ValueError('Place evidence must belong to this event passage')
            places.append(item)
    result['event_places'] = places
    return result


def policy_dispositions(page, original):
    from .codex_runtime import _timeline_source_spans, _timeline_veto_scope
    from .memory_events import _source_ref_is_vetoed
    source = page['source']
    original = {**original,'char_start':0}  # This RPC supplies the whole original.
    dispositions = []
    for clause, lo, hi in _timeline_source_spans(original['text']):
        lo, hi = max(lo, source['char_start']), min(hi, source['char_end'])
        for start in range(lo, hi, 2000):
            end = min(start + 2000, hi)
            ref = EvidenceRef(source_id=source['id'], version=source['version'],
                quote=original['text'][start:end], char_start=start, char_end=end)
            if _timeline_veto_scope(clause) or _source_ref_is_vetoed(ref, original):
                dispositions.append({'disposition':'withheld', 'reason':'privacy_withheld',
                    'source_ref':ref.model_dump(exclude_none=True)})
    if len(dispositions) > 64:
        raise ValueError('Attribution privacy budget exceeded')
    return dispositions


def attribution_schema(schema):
    schema = deepcopy(schema)
    extension = AttributionProposals.model_json_schema()
    schema.setdefault('$defs', {}).update(extension.get('$defs', {}))
    schema['properties'].update(extension['properties'])
    schema['required'] += list(extension['properties'])
    def strict(value):
        if isinstance(value, dict):
            value.pop('default', None)
            if value.get('type') == 'object':
                value['additionalProperties'] = False
                value['required'] = list(value.get('properties', {}))
            for child in value.values():
                strict(child)
        elif isinstance(value, list):
            for child in value:
                strict(child)
    strict(schema)
    return schema


INSTRUCTIONS = load_prompt_artifact(prompt_path('memoir/skills/memoir-author-timeline/attribution'))
