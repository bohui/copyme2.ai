"""Versioned MemoryEvent proposals at the external extraction boundary.

PostgreSQL owns identities/revisions and original source versions. This module
validates a proposal; it never manufactures testimony or performs fuzzy merges.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .stage_readiness import LIFE_STAGES
from .prompt_composition import render_prompt_artifact
from .prompt_artifact import prompt_path
from .place_journey import CoarsePlace, validate_place_journey


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=2000)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    attribution: str | None = Field(default=None, max_length=200)


class TemporalPlacement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expression: str = Field(min_length=1, max_length=500)
    precision: Literal['unknown', 'day', 'month', 'year', 'range', 'approximate', 'age', 'season'] = 'unknown'
    year_start: int | None = Field(default=None, ge=1, le=9999)
    year_end: int | None = Field(default=None, ge=1, le=9999)
    basis: list[EvidenceRef] = Field(default_factory=list, max_length=100)


class TemporalEstimate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    year_start: int | None = Field(default=None, ge=1, le=9999, strict=True)
    year_end: int | None = Field(default=None, ge=1, le=9999, strict=True)
    age_start: int | None = Field(default=None, ge=0, le=130, strict=True)
    age_end: int | None = Field(default=None, ge=0, le=130, strict=True)
    confidence: float = Field(gt=0, lt=1, strict=True)
    reference_year: int | None = Field(default=None, ge=1, le=9999, strict=True)
    rationale: str = Field(min_length=1, max_length=1000)
    basis: list[EvidenceRef] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def ordered_ranges(self):
        for start, end in ((self.year_start,self.year_end),(self.age_start,self.age_end)):
            if (start is None) != (end is None) or start is not None and end < start:
                raise ValueError('Estimated timing requires increasing complete ranges')
        if self.year_start is None and self.age_start is None:
            raise ValueError('An estimate requires a year or age range')
        return self


class EventRelation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['before', 'after']
    event_id: str = Field(min_length=1, max_length=128)
    source_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)


class EventProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str | None = Field(default=None, max_length=128)
    existing_id: str | None = Field(default=None, max_length=128)
    expected_revision: int | None = Field(default=None, ge=1)
    kind: Literal['event', 'period']
    title: str = Field(min_length=1, max_length=300)
    life_stage: str | None = None
    temporal: TemporalPlacement | None = None
    temporal_estimate: TemporalEstimate | None = None
    stage_evidence: list[EvidenceRef] | None = Field(default=None, max_length=100)
    source_refs: list[EvidenceRef] = Field(min_length=1, max_length=100)
    uncertainty: str | None = Field(default=None, max_length=2000)
    location: CoarsePlace | None = None
    location_basis: list[EvidenceRef] | None = Field(default=None, max_length=20)
    locationConfidenceScore: float | None = Field(default=None, ge=0, le=1, strict=True)
    yearConfidenceScore: float | None = Field(default=None, ge=0, le=1, strict=True)
    person_ids: list[str] | None = Field(default=None, max_length=100)
    visibility: Literal['private', 'family', 'public'] | None = None
    include_in_print: bool | None = None
    attribution: str | None = Field(default=None, max_length=200)
    candidate_ids: list[str] | None = Field(default=None, max_length=100)
    relations: list[EventRelation] | None = Field(default=None, max_length=100)
    correction: EvidenceRef | None = Field(default=None, description=(
        'Only for a current explicit correction using correct, actually, year was, I meant, should be, '
        '更正, 纠正, 应该, 其实 or 不是. Quote the complete current original. '
        'New stage/date evidence for an existing event uses correction=null.'))

    @model_validator(mode='before')
    @classmethod
    def confidence_values(cls, value):
        if isinstance(value, dict) and any(field in value and value[field] is None
                for field in ('locationConfidenceScore','yearConfidenceScore')):
            raise ValueError('Confidence scores use zero for unknown placement')
        return value


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    events: list[EventProposal] = Field(max_length=100)


_AGE_WORDS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14,
    'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18,
    'nineteen': 19,
}
_AGE_TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
             'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90}
_CN_AGE = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7,
           '八': 8, '九': 9, '十': 10, '两': 2}
_CN_YEAR_DIGITS = {'0': ('零', '〇'), '1': ('一',), '2': ('二',), '3': ('三',),
                   '4': ('四',), '5': ('五',), '6': ('六',), '7': ('七',),
                   '8': ('八',), '9': ('九',)}


def _memory_age_number(text):
    match = re.search(r'(?:at age |aged |age |when I was )([0-9]{1,3})', text, re.I)
    if not match:
        match = re.search(r'([0-9]{1,3})\s*(?:years old|岁)', text, re.I)
    if match:
        return int(match.group(1))
    match = re.search(r'(?:at age|aged|age|at|when I was)\s+([a-z]+)(?:[-\s]+([a-z]+))?', text, re.I)
    if match:
        first, second = match.group(1).lower(), (match.group(2) or '').lower()
        if first in _AGE_WORDS:
            return _AGE_WORDS[first]
        if first in _AGE_TENS:
            return _AGE_TENS[first] + (_AGE_WORDS.get(second, 0) if second else 0)
    match = re.search(r'([一二三四五六七八九十两]{1,3})岁', text)
    if match:
        word = match.group(1).replace('两', '二')
        if '十' in word:
            left, right = word.split('十', 1)
            return (_CN_AGE.get(left, 1) if left else 1) * 10 + _CN_AGE.get(right, 0)
        if len(word) == 1:
            return _CN_AGE.get(word)
    return None


def _memory_birth_year(text):
    patterns = (
        r'\bI\s+(?:was\s+)?born\s+(?:in\s+)?([0-9]{4})',
        r'\bmy\s+(?:birth year|year of birth)\s+(?:was|is)?\s*([0-9]{4})',
        r'我(?:是|于|在)?([0-9]{4})年?(?:出生|生于)',
        r'我(?:是)?(?:出生|生于)(?:于|在)?([0-9]{4})',
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def _year_is_present(target, text):
    if re.search(rf'(?<![0-9]){target}(?![0-9])', text):
        return True
    # Chinese memoir inputs commonly preserve years as digit-by-digit words,
    # for example 一九八八, 一九九三, or 二〇〇二. Match only the exact four
    # digit rendering; do not interpret a partial number as a supported year.
    digits = str(target)
    if len(digits) != 4:
        return False
    forms = ['']
    for digit in digits:
        forms = [prefix + glyph for prefix in forms for glyph in _CN_YEAR_DIGITS[digit]]
    return any(form in text for form in forms)


def _numeric_temporal_evidence_is_supported(timing):
    basis = timing.basis
    targets = [value for value in (timing.year_start, timing.year_end) if value is not None]
    if timing.precision == 'age' and len(targets) > 1:
        # The contract permits a one-year uncertainty interval when only a
        # birth year and an age are known. PostgreSQL validates the anchored
        # lower bound; the upper bound records the narrator's uncertainty.
        if targets[1] not in (targets[0], targets[0] + 1):
            return False
        targets = targets[:1]
    for target in targets:
        if timing.precision == 'age':
            supported = any(
                _memory_age_number(age.quote) is not None
                and (age.attribution is None or age.attribution.casefold() in {'narrator', 'storyteller', 'self', '我', '本人'})
                and (birth.attribution is None or birth.attribution.casefold() in {'narrator', 'storyteller', 'self', '我', '本人'})
                and re.match(r'^(?:actually[,\s]+)?(?:I\s+(?:was\s+)?born|my\s+(?:birth year|year of birth)|我(?:是|于|在)?[0-9]{4}年?(?:出生|生于)|我(?:是)?(?:出生|生于))', birth.quote, re.I)
                and _memory_birth_year(birth.quote) is not None
                and _memory_birth_year(birth.quote) + _memory_age_number(age.quote) == target
                for age in basis for birth in basis
            )
        else:
            supported = any(_year_is_present(target, ref.quote) for ref in basis)
        if not supported:
            return False
    return True


def _source_ref_is_vetoed(ref: EvidenceRef, original: dict) -> bool:
    """Apply recording boundaries using exact evidence, never title similarity.

    Legacy workspace items receive private cN IDs; canonical proposals already
    carry stronger source IDs, versions and exact quotes/spans. Resolve those
    references privately against the same clause-level veto contract. Repeated
    quotes without an explicit span conservatively cover every occurrence.
    No source-claim metadata enters the canonical schema or durable payload.
    """
    from .codex_runtime import _timeline_source_spans, _timeline_veto_scope

    text = original['text']
    spans = _timeline_source_spans(text)
    previous = None
    blocked = set()
    for index, (clause, _start, _end) in enumerate(spans):
        scope = _timeline_veto_scope(clause)
        if scope == 'all':
            return True
        if scope:
            # Canonical evidence may be an attributed recollection, not a
            # first-person assertion. The preceding claim owns "this event";
            # legacy author heuristics must not move it to another event.
            if previous is not None:
                blocked.add(previous)
        else:
            previous = index
    for index in blocked:
        _clause, start, end = spans[index]
        if ref.char_start is not None:
            offset = original.get('char_start', 0)
            if ref.char_start - offset < end and ref.char_end - offset > start:
                return True
        else:
            # Search only potential overlapping occurrences. Avoid building a
            # cross product of every repeated quote and every source clause.
            match = text.find(ref.quote, max(0, start - len(ref.quote) + 1))
            if 0 <= match < end:
                return True
    return False


def validate_extraction(raw, sources, saved_events):
    result = ExtractionResult.model_validate(raw)
    originals = {}
    for source in sources:
        if source.get('status', 'active') == 'active':
            originals.setdefault((source['id'], source['version']), []).append(source)
    events = {e['id']: e for e in saved_events}
    updates = []
    for event in result.events:
        if event.life_stage is not None and event.life_stage not in (*LIFE_STAGES, 'unplaced'):
            raise ValueError('Unsupported life stage')
        if event.existing_id:
            saved = events.get(event.existing_id)
            if not saved or saved['revision'] != event.expected_revision or saved['kind'] != event.kind:
                raise ValueError('Canonical event revision conflict')
            if event.candidate_ids:
                raise ValueError('Ambiguous identity must remain unresolved')
        elif event.expected_revision is not None:
            raise ValueError('A new event has no expected revision')
        if event.candidate_ids and not set(event.candidate_ids).issubset(events):
            raise ValueError('Unresolved candidates must be canonical scoped identities')
        for relation in event.relations or []:
            if relation.event_id not in events:
                raise ValueError('Chronology requires a canonical scoped target')
        if event.location:
            normalized = validate_place_journey(event.location.model_dump())
            if (not normalized or event.location.hierarchy[-1] != event.location.place
                    or not any(event.location.place in ref.quote for ref in event.location_basis or [])):
                raise ValueError('Location requires a named coarse place in its evidence')
            if event.locationConfidenceScore is None:
                raise ValueError('Location requires its confidence score')
        refs = [*event.source_refs, *(event.location_basis or []), *(event.stage_evidence or []), *(event.temporal.basis if event.temporal else []),
                *(event.temporal_estimate.basis if event.temporal_estimate else []),
                *(ref for relation in event.relations or [] for ref in relation.source_refs),
                *([event.correction] if event.correction else [])]
        if event.correction and (not event.existing_id or event.correction.source_id != sources[0]['id']
                or sources[0].get('text') != event.correction.quote):
            raise ValueError('Explicit correction must cite the current original statement')
        # Match the canonical SQL writer before returning a proposal, so the
        # bounded retry can repair intent instead of repeating a failed commit.
        if event.correction and not re.search(r'(correct|actually|year was|i meant|should be|更正|纠正|应该|其实|不是)', event.correction.quote, re.I):
            raise ValueError('Correction requires explicit correction wording')
        location_correction = bool(event.correction and event.life_stage is None and event.temporal is None
            and 'location' in event.model_fields_set and event.locationConfidenceScore is not None)
        if event.correction and event.life_stage is None and event.temporal is None and not location_correction:
            raise ValueError('Correction requires timeline placement fields')
        admitted = {}
        for ref in refs:
            candidates = originals.get((ref.source_id, ref.version), [])
            candidates = [original for original in candidates if ref.quote in original['text']]
            if not candidates:
                raise ValueError('Evidence must match an authorised original source version')
            if ref.char_start is not None or ref.char_end is not None:
                candidates = [original for original in candidates if ref.char_start is not None and ref.char_end is not None
                    and ref.char_start >= original.get('char_start', 0)
                    and ref.char_end <= original.get('char_start', 0) + len(original['text'])
                    and original['text'][ref.char_start-original.get('char_start',0):ref.char_end-original.get('char_start',0)] == ref.quote]
                if not candidates:
                    raise ValueError('Evidence span must match the original words')
            admitted[id(ref)] = candidates[0]
        if event.life_stage not in {None, 'unplaced'} and not event.stage_evidence:
            raise ValueError('Stage placement requires evidence')
        if event.temporal_estimate and event.temporal_estimate.reference_year is not None:
            estimate = event.temporal_estimate
            if not any(str(admitted[id(ref)].get('created_at',''))[:4] == str(estimate.reference_year)
                       for ref in estimate.basis):
                raise ValueError('Estimated timing anchor must match an original source capture year')
        if event.temporal:
            timing = event.temporal
            if timing.year_start is not None or timing.year_end is not None:
                if not timing.basis or timing.precision == 'unknown':
                    raise ValueError('A supported year requires a date evidence basis')
                if timing.year_start is not None and timing.year_end is not None and timing.year_start > timing.year_end:
                    raise ValueError('Date ranges must retain their original direction')
                if not _numeric_temporal_evidence_is_supported(timing):
                    raise ValueError('Numeric date requires supported original evidence')
            if timing.expression != 'unknown' and not any(timing.expression in r.quote for r in timing.basis):
                raise ValueError('The original date expression must be retained in its evidence')
        # Withhold only the affected proposal. Independent allowed events in
        # the same input still advance the canonical lane successfully.
        if any(_source_ref_is_vetoed(ref, admitted[id(ref)])
               for ref in refs):
            continue
        normalized = event.model_dump(exclude_none=True)
        if location_correction:
            # The explicit correction writer owns stage/date overrides. Location
            # clarification follows ordinary, current-source event enrichment.
            normalized.pop('correction')
        if 'location' in event.model_fields_set:
            normalized['location'] = event.location.model_dump() if event.location else None
        if 'location_basis' in event.model_fields_set:
            normalized['location_basis'] = [ref.model_dump(exclude_none=True) for ref in event.location_basis or []]
        if 'temporal_estimate' in event.model_fields_set:
            normalized['temporal_estimate'] = event.temporal_estimate.model_dump(exclude_none=True) if event.temporal_estimate else None
        updates.append(normalized)
    return updates


def extraction_schema():
    schema = ExtractionResult.model_json_schema()
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
    for field in ('locationConfidenceScore', 'yearConfidenceScore'):
        schema['$defs']['EventProposal']['properties'][field] = {'type':'number','minimum':0,'maximum':1}
    return schema


def extraction_instructions(*, derived_hints: bool = False):
    name = 'extract-with-hints' if derived_hints else 'extract'
    return render_prompt_artifact(prompt_path(f'memoir/skills/memoir-author-timeline/{name}'))
