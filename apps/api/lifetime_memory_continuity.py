"""Governed-only, evidence-bound continuity for the visible collector turn.

This extension does not own conversation phase, language or chosen-name policy.
It delegates the original interview result to its existing validator and emits
only data suitable for the existing transactional continuity writer. Model text
is kept verbatim: an authentic quote cannot license an invented paraphrase.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .interview_plan import collector_schema, validate_collector_result


MAX_CONTINUITY_UPDATES = 8
GOVERNED_CONTINUITY_INSTRUCTIONS = """
Private governed continuity contract:
Return continuity_updates as an array, empty when there is nothing supported.
Identify current-source people (person), unresolved references
(unresolved_reference), explicit pending commitments (commitment), direct topic
exclusions (excluded_topic), and direct topic pauses (paused_topic). Include at
most eight updates. These are attributed continuity, never independent facts or
new language, phase, ownership, access, publication or sharing permissions.
For every update, text must equal quote verbatim in the original source language,
with at most 500 characters. Preserve narrator uncertainty and remembered speech;
never turn another speaker's words into the narrator's preference or commitment.
assertion is asserted or inferred; inferred requires a nonempty uncertainty.
Cite only the CURRENT active narrator source_id and source_version. char_start
and char_end are zero-based Unicode character offsets, with an exclusive end,
and must identify quote exactly in that original source. Public news, photo
metadata, old sources and generated assistant text cannot supply these updates.
Do not translate quotes or invent a paraphrase, person, relationship, promise or
restriction. No owner, epoch, record ID or revision belongs in a proposal.
Privacy exclusions and pauses must be asserted direct literal narrator commands,
not inferred preferences, conditional examples, quoted or reported speech. Keep
their exact scope and wording. Explicit commitments describe future intent, never
completed work. For initial literal controls use complete direct sentences such
as "Don't discuss my school", "Let's set aside my school for now", or
"I'll return to the garden later"; do not promote another person's quotation.
The application continues to own all phase transitions and validates the existing
plan; this extension cannot override a pause or change language or chosen name.
"""


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


def governed_collector_schema(context=None):
    """Add the governed wire field without modifying the legacy schema.

    The provider requires every wire property; old responses may still omit the
    extension when validated. The caller budgets these full schema bytes.
    """
    schema = deepcopy(collector_schema(context))
    extension = _Updates.model_json_schema()
    schema.setdefault('$defs', {}).update(extension['$defs'])
    item = schema['$defs']['_ContinuityUpdate']['properties']
    source = (context or {}).get('source')
    if source:
        item['source_id']['const'] = source['id']
        item['source_version']['const'] = source['version']
    schema['properties']['continuity_updates'] = extension['properties']['continuity_updates']
    schema['required'].append('continuity_updates')
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


# Whole direct sentences only. This is a deliberately small literal fallback,
# not an intent classifier. Reported/quoted text anywhere makes control scope
# ambiguous, including speech continued across a newline or sentence boundary.
_REPORTED = re.compile(
    r'''["“”‘「」『』`：:]|(?<!\w)['’]|['’](?!\w)|\b(?:said|says|told|asked|replied|wrote|written|whispered|shouted|reported|quoted|quote|caption|script|example|hypothetical|suppose|imagine)\b|(?:说|說|告诉|告訴|写道|寫道|写着|寫著|例如|假如|如果)''',
    re.IGNORECASE,
)
_CONDITIONAL = re.compile(
    r'\b(?:if|unless|until|when|because|but|except|maybe|perhaps|whether)\b|(?:除非|如果|假如|也许|也許|可能|但是|不过|不過)',
    re.IGNORECASE,
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
_PRIVACY_KINDS = {'excluded_topic', 'paused_topic'}
_DIRECT_KINDS = _PRIVACY_KINDS | {'commitment'}


def _literal_directives(source):
    text = source['text']
    if _REPORTED.search(text):
        return []
    result = []
    for match in re.finditer(r'[^.!?。！？\n]+[.!?。！？]?', text):
        segment = match.group()
        start = match.start() + len(segment) - len(segment.lstrip())
        phrase = segment.strip()
        # Question-shaped wording is not a literal instruction or promise.
        if phrase.endswith(('?', '？')):
            continue
        phrase = phrase.rstrip('.!。！').rstrip()
        if not phrase or len(phrase) > 500 or _CONDITIONAL.search(phrase):
            continue
        for kind, pattern in _LITERAL_PATTERNS:
            if re.fullmatch(pattern, phrase, re.IGNORECASE):
                result.append(_ContinuityUpdate(kind=kind, text=phrase,
                    assertion='asserted', uncertainty=(
                        'Literal statement of future intent; completion is unconfirmed.'
                        if kind == 'commitment' else
                        'Literal current-source request; scope is limited to the quoted wording.'),
                    source_id=source['id'], source_version=source['version'],
                    char_start=start, char_end=start + len(phrase), quote=phrase))
                break
    return result


def _same_literal(proposal, literal):
    """Allow punctuation in a model quote without widening its control span."""
    return (proposal.kind == literal.kind and proposal.char_start == literal.char_start
            and proposal.quote.rstrip('.!。！').rstrip() == literal.quote)


def validate_governed_collector_result(raw, context):
    """Validate existing planning first, then return server-owned continuity rows."""
    value = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(value, dict):
        raise ValueError('Collector result must be an object')
    ordinary = {key: item for key, item in value.items() if key != 'continuity_updates'}
    result = validate_collector_result(ordinary, context)
    proposed = _Updates.model_validate({'continuity_updates': value.get('continuity_updates', [])}).continuity_updates
    source = _current_source(context)
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
        if item.kind in _DIRECT_KINDS and (item.assertion != 'asserted'
                or not any(_same_literal(item, direct) for direct in literal)):
            raise ValueError('Privacy and commitment continuity require asserted direct narrator wording')

    return {**result, 'continuity_updates': _rows(_select_updates(literal, proposed))}


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
        raise ValueError('Too many explicit privacy controls for one continuity turn')
    commitments = [item for item in literal if item.kind == 'commitment']
    other = [item for item in proposed if item.kind not in _DIRECT_KINDS]
    return [*controls, *commitments, *other][:MAX_CONTINUITY_UPDATES]


def _rows(selected):
    # A source-span index stays stable if another proposal is omitted or reordered.
    selected.sort(key=lambda item: (item.char_start, item.char_end, item.kind))
    rows = []
    for item in selected:
        record_id = str(uuid5(NAMESPACE_URL,
            f'memoir:continuity:{item.source_id}:{item.source_version}:{item.kind}:{item.char_start}:{item.char_end}'))
        rows.append({'record_id': record_id, 'kind': item.kind, 'data': {
            'text': item.text, 'assertion': item.assertion, 'uncertainty': item.uncertainty,
            'source_refs': [{'source_id': item.source_id, 'version': item.source_version,
                'char_start': item.char_start, 'char_end': item.char_end, 'quote': item.quote}],
        }})
    return rows
