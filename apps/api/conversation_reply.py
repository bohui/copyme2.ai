"""Small reply proposals; host-owned evidence and saved-plan compatibility."""
from copy import deepcopy
from pydantic import BaseModel, ConfigDict, Field

from .interview_plan import PhotoAssociation, TurnWorkPlan, authorized_photos
from .interview_questions import (QuestionResolution, hint_evidence, question_candidates,
                                 resolution_schema, validate_question_evidence, recall_question, recall_hint, question_span)
from .interview_strategy import SelectionReason, selection_candidates, prioritized_candidates
from .prompt_artifact import load_prompt_artifact, prompt_path

REPLY_VERSION = 'reply-v2'


class ReplyProposal(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    acknowledgement: str = Field(min_length=1, max_length=2000,
        description='Grounded statement only. Leave facts awaiting clarification unresolved.')
    recall_limit_quote: str | None = Field(default=None, min_length=1, max_length=500,
        description='Exact unique CURRENT narrator wording that they cannot recall a requested detail, even when other details follow; otherwise null. Not another speaker, ordinary uncertainty or a short answer.')
    reason: SelectionReason = Field(description='pause and direct_answer require question=null. Use latest_story for an optional next question, including public context; recall_limit for recall difficulty. With a hint: prepared_candidate for copy, adapted_candidate for rewording. Mere continuation is return_context.')
    quote: str | None = Field(min_length=1, max_length=500,
        description='Null with a hint or historical_clue_id. Otherwise, for recall_limit cite exact unique CURRENT wording about unavailable detail; for other reasons use an exact unique CURRENT-source passage or null.')
    hint: int | None = Field(ge=0,
        description='First relevant hint index. Recall_limit uses a scope=broader hint; null when none is relevant. Current intent overrides priority.')
    deferred_hints: list[int] = Field(default_factory=list, max_length=5,
        description='Unavailable detail indices in brief.hints. Only defer questions seeking the detail the narrator cannot recall; quote cites CURRENT recall-limit wording. Never include the chosen hint.')
    question: str | None = Field(min_length=1, max_length=800,
        description='One useful next question, including a connected broader direction after a recall limit; null for a stop or direct answer.')
    historical_clue_id: str | None = Field(default=None, max_length=128,
        description='Optional supplied public clue ID used in this question; null when irrelevant. When set, hint and quote must be null. Public history is separate from personal testimony.')
    work: TurnWorkPlan
    resolved_questions: list[QuestionResolution] = Field(default_factory=list, max_length=5)
    associations: list[PhotoAssociation] = Field(default_factory=list, max_length=20)
    response_photo_ids: list[str] = Field(default_factory=list, max_length=5)


def reply_candidates(context):
    return selection_candidates(context) if context.get('strategy_selector') else prioritized_candidates(context, question_candidates(context))


def reply_instructions():
    core = load_prompt_artifact(prompt_path('memoir/agents/mira/system'))
    if len(core) >= 2000:
        raise ValueError('Compiled reply instructions exceed the 2000 character budget')
    return core


def reply_schema(context):
    schema = ReplyProposal.model_json_schema()
    schema['required'] = list(schema['properties'])
    schema['properties']['acknowledgement']['pattern'] = '^[^?？]*$'
    schema['properties']['hint']['enum'] = [None, *range(len(reply_candidates(context)))]
    deferred = [i for i, hint in enumerate(reply_candidates(context))
                if hint.get('scope') != 'broader' and not hint.get('historical_clue_id')]
    if deferred:
        schema['properties']['deferred_hints']['items']['enum'] = deferred
    else:
        schema['properties'].pop('deferred_hints')
        schema['required'].remove('deferred_hints')
    photos = authorized_photos(context)
    if photos:
        schema['properties']['response_photo_ids']['items']['enum'] = list(photos)
    else:
        for field in ('associations', 'response_photo_ids'):
            schema['properties'].pop(field)
            schema['required'].remove(field)
        schema['$defs'].pop('PhotoAssociation')
    from .historical_news import ready_clues
    clues = [clue['id'] for clue in ready_clues(context)]
    if clues:
        schema['properties']['historical_clue_id']['enum'] = [None, *clues]
    else:
        schema['properties'].pop('historical_clue_id')
        schema['required'].remove('historical_clue_id')
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
    candidates = reply_candidates(context)
    if item.hint is not None and item.hint >= len(candidates):
        raise ValueError('Candidate is stale, asked or outside this project')
    if item.recall_limit_quote is not None:
        validate_question_evidence(dict(source_id=source.get('id'), version=source.get('version'),
            quote=item.recall_limit_quote, char_start=None, char_end=None, attribution=None), context)
        if item.reason not in {'pause', 'direct_answer', 'current_correction', 'user_redirect', 'pacing'}:
            item.reason = 'recall_limit'
            item.quote = item.recall_limit_quote
    if item.reason == 'recall_limit':
        had_hint = item.hint is not None
        selected = recall_hint(context, candidates, candidates[item.hint] if item.hint is not None else None)
        item.hint = next((i for i, hint in enumerate(candidates) if selected and hint['id'] == selected['id']), None)
        if selected is not None or had_hint or item.question is None:
            item.question = recall_question(context, selected)
        item.work.mode = 'extract'
    deferrals = []
    if item.deferred_hints:
        if item.reason != 'recall_limit' or item.quote is None or len(set(item.deferred_hints)) != len(item.deferred_hints):
            raise ValueError('Question deferral requires current recall-limit evidence and distinct hints')
        validate_question_evidence(dict(source_id=source.get('id'), version=source.get('version'),
            quote=item.quote, char_start=None, char_end=None, attribution=None), context)
        start, end = question_span(source, item.quote)
        for index in item.deferred_hints:
            if (index < 0 or index >= len(candidates) or index == item.hint
                    or candidates[index].get('scope') == 'broader' or candidates[index].get('historical_clue_id')):
                raise ValueError('Question deferral requires an unchosen detail hint')
            deferrals.append(dict(question_id=candidates[index]['id'], source_id=source['id'],
                source_version=source['version'], char_start=start, char_end=end, quote=item.quote))
    if ((item.question is None and item.reason not in {'pause', 'direct_answer', 'current_correction'})
            or (item.question is not None and item.reason in {'pause', 'direct_answer'})):
        raise ValueError('No-question outcome requires an explicit reason')
    if item.historical_clue_id is not None:
        from .historical_news import authorized_clue
        authorized_clue(context, item.historical_clue_id)
        if item.question is None or item.hint is not None or (item.quote is not None and item.reason!='recall_limit'):
            raise ValueError('Public context requires one optional question without personal evidence or a prepared hint')
    hint = None
    if item.hint is not None:
        hint = candidates[item.hint]
        if item.reason not in {'prepared_candidate', 'adapted_candidate', 'recall_limit'} or item.question is None:
            raise ValueError('Candidate use requires its recorded reason')
        if hint.get('historical_clue_id'):
            # Public clues use the host's optional invitation, never model-written biography.
            item.question = hint['question']
            if item.reason != 'recall_limit':
                item.reason = 'prepared_candidate'
        if item.reason == 'prepared_candidate' and item.question.strip() != hint['question'].strip():
            raise ValueError('Prepared candidate text changed')
        evidence = None if hint.get('historical_clue_id') else hint_evidence(hint, context)
        if item.quote is not None:
            if item.reason == 'recall_limit':
                validate_question_evidence(dict(source_id=source.get('id'), version=source.get('version'),
                    quote=item.quote, char_start=None, char_end=None, attribution=None), context)
            elif not evidence or item.quote != evidence['quote']:
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
            if item.historical_clue_id is not None:
                evidence = None  # Recall control is not evidence of attending a public event.
    identity = hint['id'] if hint else 'immediate-' + (context.get('source') or {}).get('id', 'fallback')
    questions = [] if item.question is None else [dict(id=identity, question=item.question,
        context=dict(event_id=None, photo_id=None, life_stage=None, year=None, evidence=evidence),
        order=0, bridge='')]
    if questions and hint and hint.get('historical_clue_id'):
        questions[0]['context']['historical_clue_id'] = hint['historical_clue_id']
        questions[0]['bridge'] = hint['bridge']
    if questions and item.historical_clue_id is not None:
        questions[0]['context']['historical_clue_id'] = item.historical_clue_id
    legacy = dict(acknowledgement=item.acknowledgement,
        plan=dict(candidates=questions, chosen_id=identity if questions else None,
                  active_event_id=None, work=dict(mode=item.work.mode,
                      name=name if item.work.mode == 'reply_only' else None),
                  resolved_questions=[value.model_dump() for value in item.resolved_questions],
                  deferred_questions=deferrals),
        associations=[value.model_dump() for value in item.associations],
        response_photo_ids=item.response_photo_ids, stopped=item.question is None, continuity_updates=[])
    state = context.get('strategy_context') or {}
    plan = state.get('plan') or {}
    outcome = dict(schema_version=1,
        plan_revision_seen=plan.get('plan_revision', state.get('invalid_plan_revision')),
        selected_candidate_id=hint['id'] if hint else None, selection_reason=item.reason,
        used_strategy=context.get('active_strategy') or plan.get('strategy') or 'explore',
        question_delivered=item.question, work_hint=item.work.mode) if context.get('strategy_selector') else None
    return legacy, item.reason, outcome, item.question is None and item.reason != 'direct_answer', name


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
    deliveries = deepcopy(context.get('background_deliveries', []))
    if summary and summary.items:
        deliveries.append(dict(skill='memoir-memory-context',
            covered_through_sequence=packet.coverage_end, items=[item.model_dump() for item in summary.items]))
    if context.get('events'):
        deliveries.append(dict(skill='memoir-author-timeline', events=deepcopy(context['events'])))
    from .historical_news import ready_clues, public_clue
    clues = [public_clue(clue) for clue in ready_clues(context)]
    if clues:
        deliveries.append(dict(skill='memoir-historical-news-research', clues=clues))
    return dict(reply_contract=REPLY_VERSION, instructions=packet.instructions, reply_language=context.get('interview_language'),
        current=packet.current.model_dump(mode='json'),
        dialogue=[entry.model_dump(mode='json') for entry in packet.tail],
        preferences=packet.pinned.model_dump(mode='json'),
        original_evidence=[ref.model_dump(mode='json') for ref in packet.retrieved],
        brief=dict(covered_through_sequence=packet.coverage_end,
                   hint_order='highest_priority_first',
                   objective=(state.get('plan') or {}).get('objective'),
                   last_delivered_question=deepcopy(state.get('prior_delivered_question')),
                   hints=[dict(index=index, **deepcopy(hint))
                          for index, hint in enumerate(hints)],
                   resolution_only_questions=list(resolution_only.values())),
        background_deliveries=deliveries,
        context={key: deepcopy(context[key]) for key in (
            'opening_turn', 'active_strategy', 'breadth_checkpoint', 'recent_dialogue',
            'photos', 'photo_context', 'reviewed_acknowledgement') if key in context})
