"""Small reply proposals; host-owned evidence and saved-plan compatibility."""
from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field

from .interview_plan import (PhotoAssociation, TurnWorkPlan, authorized_photos,
                             constrain_acknowledgement, historical_acknowledgements)
from .interview_questions import (QuestionResolution, hint_evidence, question_candidates,
                                 resolution_schema, validate_question_evidence)
from .interview_strategy import SelectionReason, selection_candidates
from .prompt_artifact import load_prompt_artifact, prompt_path

REPLY_VERSION = 'reply-v2'


class ReplyProposal(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    acknowledgement: str = Field(min_length=1, max_length=2000)
    question: str | None = Field(min_length=1, max_length=800)
    reason: SelectionReason
    hint: int | None = Field(ge=0)
    quote: str | None = Field(min_length=1, max_length=500)
    work: TurnWorkPlan
    resolved_questions: list[QuestionResolution] = Field(default_factory=list, max_length=5)
    associations: list[PhotoAssociation] = Field(default_factory=list, max_length=20)
    response_photo_ids: list[str] = Field(default_factory=list, max_length=5)


def reply_candidates(context):
    return selection_candidates(context) if context.get('strategy_selector') else question_candidates(context)


def reply_instructions():
    core = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/reply'))
    dispatch = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/governed-turn'))
    if len(core + '\n' + dispatch) >= 2000:
        raise ValueError('Compiled reply instructions exceed the 2000 character budget')
    return core


def reply_schema(context):
    schema = ReplyProposal.model_json_schema()
    schema['required'] = list(schema['properties'])
    schema['properties']['acknowledgement']['pattern'] = '^[^?？]*$'
    schema['properties']['hint']['enum'] = [None, *range(len(reply_candidates(context)))]
    photos = authorized_photos(context)
    if photos:
        schema['properties']['response_photo_ids']['items']['enum'] = list(photos)
    else:
        for field in ('associations', 'response_photo_ids'):
            schema['properties'].pop(field)
            schema['required'].remove(field)
        schema['$defs'].pop('PhotoAssociation')
    if context.get('historical_news', {}).get('clues'):
        constrain_acknowledgement(schema, sorted(historical_acknowledgements(context)))
    schema = resolution_schema(schema, context)
    def compact(value):
        if isinstance(value, dict):
            return {key: compact(child) for key, child in value.items() if key not in {'title', 'default'}}
        return [compact(child) for child in value] if isinstance(value, list) else value
    return compact(schema)


def adapt_reply(raw, context):
    item = ReplyProposal.model_validate(raw)
    if not authorized_photos(context) and {'associations', 'response_photo_ids'} & raw.keys():
        raise ValueError('Unavailable photo fields must be omitted')
    name = item.work.name
    source = context.get('source') or {}
    if name is not None and (not name.strip() or name not in source.get('text', '')):
        raise ValueError('Opening name requires exact current narrator wording')
    if (item.question is None) != (item.reason in {'pause', 'direct_answer'}):
        raise ValueError('No-question outcome requires an explicit reason')
    candidates = reply_candidates(context)
    hint = None
    if item.hint is not None:
        if item.hint >= len(candidates):
            raise ValueError('Candidate is stale, asked or outside this project')
        hint = candidates[item.hint]
        if item.reason not in {'prepared_candidate', 'adapted_candidate'} or item.question is None:
            raise ValueError('Candidate use requires its recorded reason')
        if item.reason == 'prepared_candidate' and item.question.strip() != hint['question'].strip():
            raise ValueError('Prepared candidate text changed')
        evidence = hint_evidence(hint, context)
        if item.quote is not None and (not evidence or item.quote != evidence['quote']):
            raise ValueError('Question candidate cannot change its referenced passage')
    else:
        if item.reason in {'prepared_candidate', 'adapted_candidate'}:
            raise ValueError('Candidate identity required')
        evidence = None
        if item.quote is not None:
            source = context.get('source') or {}
            evidence = validate_question_evidence(dict(source_id=source.get('id'),
                version=source.get('version'), quote=item.quote, char_start=None,
                char_end=None, attribution=None), context).model_dump()
    if item.question is None and evidence is not None:
        raise ValueError('No question cannot deliver question evidence')
    identity = hint['id'] if hint else 'immediate-' + (context.get('source') or {}).get('id', 'fallback')
    questions = [] if item.question is None else [dict(id=identity, question=item.question,
        context=dict(event_id=None, photo_id=None, life_stage=None, year=None, evidence=evidence),
        order=0, bridge='')]
    legacy = dict(acknowledgement=item.acknowledgement,
        plan=dict(candidates=questions, chosen_id=identity if questions else None,
                  active_event_id=None, work=dict(mode=item.work.mode,
                      name=name if item.work.mode == 'reply_only' else None),
                  resolved_questions=[value.model_dump() for value in item.resolved_questions]),
        associations=[value.model_dump() for value in item.associations],
        response_photo_ids=item.response_photo_ids, stopped=item.question is None, continuity_updates=[])
    state = context.get('strategy_context') or {}
    plan = state.get('plan') or {}
    outcome = dict(schema_version=1,
        plan_revision_seen=plan.get('plan_revision', state.get('invalid_plan_revision')),
        selected_candidate_id=hint['id'] if hint else None, selection_reason=item.reason,
        used_strategy=context.get('active_strategy') or plan.get('strategy') or 'explore',
        question_delivered=item.question, work_hint=item.work.mode) if context.get('strategy_selector') else None
    return legacy, item.reason, outcome, item.reason == 'pause', name


def reply_packet(packet):
    """Project an already validated governed packet; preserve its complete raw tail."""
    context = packet.interview_context
    checkpoint = packet.checkpoint
    summary = checkpoint.memory_summary if checkpoint else None
    state = context.get('strategy_context') or {}
    hints = reply_candidates(context)
    selectable_ids = {hint['id'] for hint in hints}
    resolution_only = {hint['id']: dict(id=hint['id'], question=hint['question'])
                       for hint in question_candidates(context) if hint['id'] not in selectable_ids}
    return dict(reply_contract=REPLY_VERSION, instructions=packet.instructions, reply_language=context.get('interview_language'),
        current=packet.current.model_dump(mode='json'),
        dialogue=[entry.model_dump(mode='json') for entry in packet.tail],
        preferences=packet.pinned.model_dump(mode='json'),
        original_evidence=[ref.model_dump(mode='json') for ref in packet.retrieved],
        brief=dict(covered_through_sequence=packet.coverage_end,
                   items=[item.model_dump() for item in summary.items] if summary else [],
                   last_delivered_question=deepcopy(state.get('prior_delivered_question')),
                   hints=[dict(index=index, **deepcopy(hint))
                          for index, hint in enumerate(hints)],
                   resolution_only_questions=list(resolution_only.values())),
        context={key: deepcopy(context[key]) for key in (
            'opening_turn', 'active_strategy', 'breadth_checkpoint', 'recent_dialogue',
            'events', 'photos', 'photo_context', 'historical_news', 'reviewed_acknowledgement') if key in context})
