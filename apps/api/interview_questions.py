"""Evidence-backed retirement of question hints in the existing reply pass."""
from copy import deepcopy
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from .memory_events import EvidenceRef
from .prompt_artifact import load_prompt_artifact, prompt_path


GUIDANCE_KINDS = ('conflict', 'clarification', 'historical_news', 'topic_transition', 'life_essence', 'follow_up')
GuidanceKind = Literal['conflict', 'clarification', 'historical_news', 'topic_transition', 'life_essence', 'follow_up']


def question_priority(question):
    kind = question.get('trigger')
    return GUIDANCE_KINDS.index(kind) if kind in GUIDANCE_KINDS else 1 if question.get('requires_confirmation') else len(GUIDANCE_KINDS)


class GuidanceDependency(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    quote_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class PreparedQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1, max_length=800)
    topic: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=500)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=1)
    requires_confirmation: bool = False
    scope: Literal['detail', 'broader'] = 'detail'


def recall_question(context, hint=None):
    if hint is not None:
        if hint.get('scope') != 'broader' and not hint.get('historical_clue_id'):
            raise ValueError('Recall limits require a broader question or an unqueued fallback')
        return hint['question']
    invitations = json.loads(load_prompt_artifact(prompt_path('memoir/shared/recall-invitations')))
    return invitations.get(context.get('interview_language'), invitations['en-AU'])


def recall_hint(context, hints, selected):
    if selected is None or selected.get('scope') == 'broader' or selected.get('historical_clue_id'):
        return selected
    plan = (context.get('strategy_context') or {}).get('plan') or {}
    def source(hint):
        return (hint.get('source_id', plan.get('source_id')), hint.get('source_version', plan.get('source_version')))
    return next((hint for hint in hints if hint.get('scope') == 'broader'
                 and source(hint) == source(selected)), None)


def question_span(source, quote, start=None, end=None):
    text, offset = source['text'], source.get('char_start') or 0
    if start is None and end is None:
        position = text.find(quote)
        if position < 0 or text.find(quote, position + 1) >= 0:
            raise ValueError('Question evidence needs one exact passage or explicit offsets')
        return offset + position, offset + position + len(quote)
    if (type(start) is not int or type(end) is not int or start < offset
            or end > offset + len(text) or end - start != len(quote)
            or text[start-offset:end-offset] != quote):
        raise ValueError('Question evidence span must match the referenced passage')
    return start, end


def hint_evidence(hint, context):
    if hint.get('historical_clue_id'):
        return None
    plan = (context.get('strategy_context') or {}).get('plan') or {}
    source_id, version = hint.get('source_id', plan.get('source_id')), hint.get('source_version', plan.get('source_version'))
    if not source_id or not version or hint.get('char_start') is None or hint.get('char_end') is None:
        return None
    return {'source_id': source_id, 'version': version, 'quote': hint['quote'],
            'char_start': hint['char_start'], 'char_end': hint['char_end'], 'attribution': None}


def validate_question_evidence(value, context):
    ref = EvidenceRef.model_validate(value)
    source = context.get('source') or {}
    if (source.get('id'), source.get('version'), source.get('status')) == (ref.source_id, ref.version, 'active'):
        if source.get('kind', 'narrator_chat') not in {'narrator_chat', 'narrator_transcript'}:
            raise ValueError('Question evidence requires narrator testimony')
        start, end = question_span(source, ref.quote, ref.char_start, ref.char_end)
    else:
        authorized = [hint_evidence(hint, context) for hint in question_candidates(context)]
        matches = [item for item in authorized if item and all(item[k] == getattr(ref, k)
                   for k in ('source_id', 'version', 'quote', 'char_start', 'char_end'))]
        if not matches:
            raise ValueError('Question evidence is outside the supplied narrator passages')
        start, end = ref.char_start, ref.char_end
    return ref.model_copy(update={'char_start': start, 'char_end': end})


def question_evidence_schema(schema, context=None):
    ref = schema.get('$defs', {}).get('EvidenceRef')
    if ref:
        ref['required'] = list(ref['properties'])
        for field in ref['properties'].values():
            field.pop('default', None)
        if context is not None:
            source = context.get('source') or {}
            allowed = ([source['id']] if source.get('status') == 'active'
                and source.get('kind', 'narrator_chat') in {'narrator_chat', 'narrator_transcript'} else [])
            allowed.extend(evidence['source_id'] for hint in question_candidates(context)
                           if (evidence := hint_evidence(hint, context)) is not None)
            if allowed:
                ref['properties']['source_id']['enum'] = list(dict.fromkeys(allowed))
            else:
                schema['$defs']['EvidenceRef'] = {'type': 'null'}
    return schema


class QuestionResolution(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    source_version: int = Field(ge=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=512)


def question_candidates(context):
    return [*context.get('prepared_questions', []),
            *((context.get('strategy_context') or {}).get('plan') or {}).get('candidates', [])]


def resolution_sources(context):
    sources = {(r['id'], r['version']): r for item in context.get('recent_dialogue', [])
               if (r := item.get('response')) and r.get('complete') is True and r.get('role') == 'user'
               and r.get('kind') in {'narrator_chat', 'narrator_transcript'}}
    current = context.get('source')
    if (current and current.get('status') == 'active' and current.get('role') != 'assistant'
            and current.get('kind', 'narrator_chat') in {'narrator_chat', 'narrator_transcript'}):
        sources[(current['id'], current['version'])] = current
    return sources


def resolution_schema(schema, context, *, plan=False):
    """Offer semantic retirement only when the request supplies answer evidence."""
    schema = deepcopy(schema)
    container = schema['$defs']['InterviewPlan'] if plan else schema
    candidates = question_candidates(context or {})
    for name in ('resolved_questions', 'deferred_questions'):
        if not candidates or not resolution_sources(context or {}):
            container['properties'].pop(name, None)
            container['required'] = [key for key in container['required'] if key != name]
        elif name in container['properties']:
            container['properties'][name].pop('default', None)
    if not candidates or not resolution_sources(context or {}):
        return schema
    schema['$defs']['QuestionResolution']['properties']['question_id']['enum'] = list(dict.fromkeys(
        candidate['id'] for candidate in candidates))
    return schema


def validate_resolutions(values, context, *, kind='resolution'):
    candidates = {candidate['id'] for candidate in question_candidates(context)}
    sources = resolution_sources(context)
    if kind == 'deferral':
        current = context.get('source') or {}
        sources = {key: value for key, value in sources.items() if key == (current.get('id'), current.get('version'))}
    seen = set()
    for value in values:
        item = QuestionResolution.model_validate(value)
        source = sources.get((item.source_id, item.source_version))
        if item.question_id not in candidates or item.question_id in seen:
            raise ValueError(f'Question {kind} requires one current queued question')
        if (not source or item.char_end > len(source['text'])
                or source['text'][item.char_start:item.char_end] != item.quote):
            raise ValueError(f'Question {kind} requires an exact narrator answer span')
        seen.add(item.question_id)
    return seen
