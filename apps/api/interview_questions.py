"""Evidence-backed retirement of question hints in the existing reply pass."""
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field
from .memory_events import EvidenceRef


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
        for name in ('char_start','char_end'):
            ref['properties'][name]['description']=(
                'For a current-source quote occurring exactly once, use null for BOTH offsets; '
                'the application finds and validates its exact span. For repeated wording, supply '
                'exact absolute Unicode character offsets. For a queued hint, copy its supplied offsets.')
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
    field = container['properties']['resolved_questions']
    candidates = question_candidates(context or {})
    if not candidates or not resolution_sources(context or {}):
        container['properties'].pop('resolved_questions')
        container['required'] = [key for key in container['required'] if key != 'resolved_questions']
        return schema
    field.pop('default', None)
    field['description'] = (
        'Queued questions already answered by current narrator text or recent_dialogue, including paraphrases. '
        'Exclude these before choosing the next question; cite exact narrator answer spans. '
        'An assistant question alone, a skip, an uncertain answer, '
        'or an unrelated reply does not resolve a fact. Keep unresolved confirmations; [] when none are answered.')
    schema['$defs']['QuestionResolution']['properties']['question_id']['enum'] = list(dict.fromkeys(
        candidate['id'] for candidate in candidates))
    return schema


def validate_resolutions(values, context):
    candidates = {candidate['id'] for candidate in question_candidates(context)}
    sources = resolution_sources(context)
    seen = set()
    for value in values:
        item = QuestionResolution.model_validate(value)
        source = sources.get((item.source_id, item.source_version))
        if item.question_id not in candidates or item.question_id in seen:
            raise ValueError('Question resolution requires one current queued question')
        if (not source or item.char_end > len(source['text'])
                or source['text'][item.char_start:item.char_end] != item.quote):
            raise ValueError('Question resolution requires an exact narrator answer span')
        seen.add(item.question_id)
    return seen
