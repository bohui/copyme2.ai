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
import re
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .prompt_artifact import load_prompt_artifact, prompt_path
from .interview_plan import collector_schema, validate_collector_result
from .place_journey import grounded_place_journeys, validate_place_journey


MAX_CONTINUITY_UPDATES = 8


class LiteralContinuityInputError(ValueError):
    """An explicit policy cannot be completely represented without truncation."""


GOVERNED_CONTINUITY_INSTRUCTIONS = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/governed-continuity'))


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


class _Places(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    place_journeys: list[_PlaceJourney] = Field(max_length=8)


def governed_collector_schema(context=None):
    """Add the governed wire field without modifying the legacy schema.

    The provider requires every wire property; old responses may still omit the
    extension when validated. The caller budgets these full schema bytes.
    """
    if (context or {}).get('strategy_selector'):
        from .interview_strategy import selector_schema
        schema=selector_schema(context)
    else:
        schema = deepcopy(collector_schema(context))
    extension = _Updates.model_json_schema()
    schema.setdefault('$defs', {}).update(extension['$defs'])
    item = schema['$defs']['_ContinuityUpdate']['properties']
    for field in ('char_start', 'char_end'):
        item[field] = {'anyOf': [item[field], {'type': 'null'}]}
    source = (context or {}).get('source')
    if source:
        item['source_id']['const'] = source['id']
        item['source_version']['const'] = source['version']
        direct_kinds = {directive.kind for directive in _literal_directives(source)}
        item['kind']['enum'] = [kind for kind in item['kind']['enum']
                               if kind not in _DIRECT_KINDS or kind in direct_kinds]
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


# Freeze whitespace and English word-boundary behavior independently of Python
# Unicode versions and the PostgreSQL database locale. SQL uses this explicit
# whitespace class and C collation; English word markers are ASCII in both.
_SPACE_CLASS = r'[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]'
_SPACE_CHARS = ''.join(chr(code) for code in (
    *range(0x9, 0xe), *range(0x1c, 0x21), 0x85, 0xa0, 0x1680,
    *range(0x2000, 0x200b), 0x2028, 0x2029, 0x202f, 0x205f, 0x3000))
_SENTENCE_PATTERN = r'[^.!?。！？\r\n\u2028\u2029]+[.!?。！？]?'

# Whole direct sentences only. This is a deliberately small literal fallback,
# not an intent classifier. Reported/quoted text anywhere makes control scope
# ambiguous, including speech continued across a newline or sentence boundary.
_REPORTED = re.compile(
    r'''["“”‘「」『』`：:]|(?<!\w)['’]|['’](?!\w)|\b(?:said|says|told|asked|replied|wrote|written|whispered|shouted|reported|quoted|quote|caption|script|example|hypothetical|suppose|imagine)\b|(?:说|說|告诉|告訴|写道|寫道|写着|寫著|例如|假如|如果)''',
    re.IGNORECASE | re.ASCII,
)
_CONDITIONAL = re.compile(
    r'\b(?:if|unless|until|when|because|but|except|maybe|perhaps|whether)\b|(?:除非|如果|假如|也许|也許|可能|但是|不过|不過)',
    re.IGNORECASE | re.ASCII,
)
_LITERAL_PATTERNS = (
    ('excluded_topic', r"(?:please\s+)?(?:do not|don't|don’t|never)\s+(?:discuss|mention|ask (?:me )?about|bring up)\s+.+"),
    ('excluded_topic', r"I\s+(?:do not|don't|don’t)\s+want to\s+(?:discuss|talk about)\s+.+"),
    ('excluded_topic', r'(?:请|我)?(?:不要|别|不想)(?:再)?(?:讨论|谈|聊|提)(?:到|起)?[^，,：:；;]+'),
    ('paused_topic', r"(?:(?:please|let's|let’s)\s+)?(?:set aside|pause discussing|pause talking about)\s+.+?(?:\s+for now)?"),
    ('paused_topic', r'(?:我们|咱们)?先(?:不聊|不谈|暂停讨论)[^，,：:；;]+'),
    ('commitment', r"I(?:'ll|’ll| will| promise to)\s+.+"),
    ('commitment', r'我(?:下次会|稍后会|之后会|以后会|会|将|打算)[^，,：:；;]+'),
)
_LITERAL_PATTERNS = tuple((kind, pattern.replace(' ', r'\s+').replace(r'\s', _SPACE_CLASS))
                          for kind, pattern in _LITERAL_PATTERNS)
_PRIVACY_KINDS = {'excluded_topic', 'paused_topic'}
_DIRECT_KINDS = _PRIVACY_KINDS | {'commitment'}


def _literal_phrases(text):
    if _REPORTED.search(text):
        return []
    result = []
    for match in re.finditer(_SENTENCE_PATTERN, text):
        segment = match.group()
        start = match.start() + len(segment) - len(segment.lstrip(_SPACE_CHARS))
        phrase = segment.strip(_SPACE_CHARS)
        # Question-shaped wording is not a literal instruction or promise.
        if phrase.endswith(('?', '？')):
            continue
        phrase = phrase.rstrip('.!。！').rstrip(_SPACE_CHARS)
        if not phrase or _CONDITIONAL.search(phrase):
            continue
        for kind, pattern in _LITERAL_PATTERNS:
            if re.fullmatch(pattern, phrase, re.IGNORECASE | re.ASCII):
                if len(phrase) > 500:
                    if kind in _PRIVACY_KINDS:
                        raise LiteralContinuityInputError('Explicit privacy controls must fit 500 characters without truncation')
                    break
                result.append({'kind': kind, 'text': phrase, 'char_start': start,
                    'char_end': start + len(phrase)})
                break
    return result


def _validate_policy_count(phrases):
    if sum(item['kind'] in _PRIVACY_KINDS for item in phrases) > MAX_CONTINUITY_UPDATES:
        raise LiteralContinuityInputError('Too many explicit privacy controls for one continuity turn; no controls were truncated')


def validate_literal_continuity_input(text, *, source_kind='narrator_chat'):
    """Pure preaccept validation, using the identical postaccept literal parser.

    This is an early request check, not a trusted completeness claim. Atomic
    persistence independently establishes current-source policy completeness.
    For already accepted replays, callers must report maintenance rather than
    claim the source was not accepted when this validation rejects the text.
    """
    if not isinstance(text, str) or source_kind not in {'narrator_chat', 'narrator_transcript'}:
        raise LiteralContinuityInputError('Original narrator text and kind are required')
    _validate_policy_count(_literal_phrases(text))


def _literal_directives(source):
    phrases = _literal_phrases(source['text'])
    _validate_policy_count(phrases)
    return [_ContinuityUpdate(**item, assertion='asserted', uncertainty=(
        'Literal statement of future intent; completion is unconfirmed.'
        if item['kind'] == 'commitment' else
        'Literal current-source request; scope is limited to the quoted wording.'),
        source_id=source['id'], source_version=source['version'], quote=item['text'])
        for item in phrases]


def _same_literal(proposal, literal):
    """Allow punctuation in a model quote without widening its control span."""
    return (proposal.kind == literal.kind and proposal.char_start == literal.char_start
            and proposal.quote.rstrip('.!。！').rstrip(_SPACE_CHARS) == literal.quote)


def validate_governed_collector_result(raw, context):
    """Validate existing planning first, then return server-owned continuity rows."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise ValueError('Collector result must be an object')
    outcome=None
    if context.get('strategy_selector'):
        from .interview_strategy import adapt_selection
        value,outcome,stopped=adapt_selection(value,context)
    ordinary = {key: item for key, item in value.items() if key not in {'continuity_updates', 'place_journeys'}}
    result = validate_collector_result(ordinary, context)
    if outcome is not None:result.update(strategy_outcome=outcome,stopped=stopped)
    source = _current_source(context)
    updates = value.get('continuity_updates', [])
    if isinstance(updates, list):
        updates = [dict(item) if isinstance(item, dict) else item for item in updates]
        for item in updates:
            if not source or not isinstance(item, dict):
                continue
            start, end, quote = item.get('char_start'), item.get('char_end'), item.get('quote')
            locate = ('char_start' in item and 'char_end' in item and start is None and end is None)
            explicit = type(start) is int and start >= 0 and type(end) is int and end >= 1
            if (not (locate or explicit)
                    or not isinstance(quote, str) or not 0 < len(quote) <= 500
                    or item.get('source_id') != source['id']
                    or type(item.get('source_version')) is not int or item['source_version'] != source['version']):
                continue
            if locate or source['text'][start:end] != quote:
                original_start = source['text'].find(quote)
                if original_start >= 0 and source['text'].find(quote, original_start + 1) < 0:
                    # Resolve a unique exact quote before typed span validation.
                    item['char_start'] = original_start
                    item['char_end'] = original_start + len(quote)
    proposed = _Updates.model_validate({'continuity_updates': updates}).continuity_updates
    if proposed and source is None:
        raise ValueError('Continuity requires exact current narrator evidence')
    literal = _literal_directives(source) if source else []
    seen = set()
    for item in proposed:
        if (item.source_id != source['id'] or item.source_version != source['version']
                or item.char_end > len(source['text'])
                or source['text'][item.char_start:item.char_end] != item.quote):
            raise ValueError('Continuity requires exact current narrator evidence')
        key = (item.kind, item.char_start, item.char_end)
        if key in seen:
            raise ValueError('Duplicate continuity update')
        seen.add(key)
        if item.kind == 'person' and item.assertion == 'asserted':
            from .interview_strategy import current_constraints
            prefix = source['text'][:item.char_start].rstrip()
            if (current_constraints(source['text']).get('override') == 'current_correction'
                    and re.search(r'\bnot(?:\s+(?:my|our|the|his|her|their|your))?\s*$|(?:不是|并非|並非)(?:我|我的|他|他的|她|她的)?$', prefix, re.I)):
                raise ValueError('A superseded person cannot become asserted continuity')
        if item.kind in _DIRECT_KINDS and (item.assertion != 'asserted'
                or not any(_same_literal(item, direct) for direct in literal)):
            raise ValueError('Privacy and commitment continuity require asserted direct narrator wording')

    places = _Places.model_validate({'place_journeys': [] if context.get('two_lane_memory') is True
        else value.get('place_journeys', [])}).place_journeys
    candidates = [validate_place_journey(place.model_dump()) for place in places
                  if place.hierarchy[-1] == place.place]
    journeys = grounded_place_journeys([place for place in candidates if place is not None],
                                      source['text']) if source else []
    return {**result, 'continuity_updates': _rows(_select_updates(literal, proposed)),
            'place_journeys': journeys}


def literal_continuity_updates(context):
    """Return deterministic literal rows before generation, without model input.

    Only the enumerated English/Chinese sentence forms are recognized. Mixed
    quoted/reported language is conservatively ignored, not intent-classified.
    The coordinator can persist excluded/paused rows under the existing lease
    before capturing the provider/publication fence. It remains responsible for
    policy revision and idempotency. This helper neither writes nor changes phase.
    """
    source = _current_source(context)
    return _rows(_select_updates(_literal_directives(source) if source else [], []))


def _select_updates(literal, proposed):
    # Every literal control has priority, including controls already proposed at
    # the end of a full model array. Canonicalize ALL direct kinds so early and
    # final persistence use identical quote spans, uncertainty and record IDs.
    controls = [item for item in literal if item.kind in _PRIVACY_KINDS]
    if len(controls) > MAX_CONTINUITY_UPDATES:
        raise LiteralContinuityInputError('Too many explicit privacy controls for one continuity turn; no controls were truncated')
    commitments = [item for item in literal if item.kind == 'commitment']
    other = [item for item in proposed if item.kind not in _DIRECT_KINDS]
    return [*controls, *commitments, *other][:MAX_CONTINUITY_UPDATES]


def _rows(selected):
    # A source-span index stays stable if another proposal is omitted or reordered.
    selected.sort(key=lambda item: (item.char_start, item.char_end, item.kind))
    rows = []
    for item in selected:
        seed = f'memoir:continuity:{item.source_id}:{item.source_version}:{item.kind}:{item.char_start}:{item.char_end}'
        record_id = ('literal-v1:' + sha256(seed.encode('utf-8')).hexdigest()
                     if item.kind in _PRIVACY_KINDS else str(uuid5(NAMESPACE_URL, seed)))
        rows.append({'record_id': record_id, 'kind': item.kind, 'data': {
            'text': item.text, 'assertion': item.assertion, 'uncertainty': item.uncertainty,
            'source_refs': [{'source_id': item.source_id, 'version': item.source_version,
                'char_start': item.char_start, 'char_end': item.char_end, 'quote': item.quote}],
        }})
    return rows
