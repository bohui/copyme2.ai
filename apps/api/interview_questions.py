"""Evidence-backed retirement of question hints in the existing reply pass."""
from copy import deepcopy

from pydantic import BaseModel, ConfigDict, Field


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
