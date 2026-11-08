"""Mira owns the next reply; Atlas supplies evidence through context only."""
from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from .interview_plan import PhotoAssociation, authorized_photos, constrain_acknowledgement
from .interview_questions import validate_question_evidence, recall_question, question_span
from .interview_strategy import Strategy
from .prompt_artifact import load_prompt_artifact, prompt_path

REPLY_VERSION = 'reply-v2'
ReplyReason = Literal['latest_story', 'user_redirect', 'current_correction', 'pacing',
                      'recall_limit', 'pause', 'direct_answer', 'return_context']


class WorkspaceFocus(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    place: str = Field(min_length=1, max_length=120, description='One coarse city/place, using its exact narrator wording. No hospital, address or invented location.')
    quote: str = Field(min_length=1, max_length=500, description='Exact unique narrator passage containing this place and grounding the memory your question follows.')
    source_id: str | None = Field(default=None, min_length=1, max_length=128,
        description='Null for CURRENT narration; otherwise the supplied original narrator source ID for quote.')


class ReplyProposal(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    acknowledgement: str = Field(min_length=1, max_length=2000,
        description='Grounded statement only. Leave facts awaiting clarification unresolved.')
    recall_limit_quote: str | None = Field(default=None, min_length=1, max_length=500,
        description='Exact unique CURRENT narrator wording that they cannot recall a requested detail, even when other details follow; otherwise null. Not another speaker, ordinary uncertainty or a short answer.')
    reason: ReplyReason = Field(description='pause and direct_answer require question=null. Use latest_story for an optional next question, including public context; recall_limit for recall difficulty. Mere continuation is return_context.')
    strategy: Strategy = Field(default='explore',
        description='Your current interviewing approach: comfort for gentle support, explore for memory details, shape for arranging or connecting established memories. This does not authorize game or book actions.')
    quote: str | None = Field(min_length=1, max_length=500,
        description='With a public clue, use null except for recall_limit: cite exact unique CURRENT wording about unavailable detail. For other reasons, use an exact unique CURRENT-source passage or null.')
    question: str | None = Field(min_length=1, max_length=800,
        description='One useful next question, including a connected broader direction after a recall limit; null for a stop or direct answer.')
    workspace_focus: WorkspaceFocus | None = Field(default=None,
        description='City of the memory your NEXT QUESTION explores, including an implicit continuation. Choose that city when acknowledgement mentions several. Example: living in Sydney but born in Chengde, followed by a childhood question -> Chengde. Null when no question or its place is unresolved. This selects the map, photos and event list; it asserts no new biography.')
    historical_clue_id: str | None = Field(default=None, max_length=128,
        description='Supplied public clue ID used in an optional next question; null when question is null or the clue is irrelevant. With a clue, use latest_story or recall_limit; quote is null except an exact recall-limit quote. Public history is separate from personal testimony.')
    associations: list[PhotoAssociation] = Field(default_factory=list, max_length=20)
    response_photo_ids: list[str] = Field(default_factory=list, max_length=5)


def reply_instructions():
    core = load_prompt_artifact(prompt_path('memoir/agents/mira/reply'))
    if len(core) >= 2000:
        raise ValueError('Compiled reply instructions exceed the 2000 character budget')
    return core


def reply_schema(context):
    schema = ReplyProposal.model_json_schema()
    schema['properties']['acknowledgement']['pattern'] = '^[^?？]*$'
    if context.get('reviewed_acknowledgement') is not None:
        constrain_acknowledgement(schema, [context['reviewed_acknowledgement']])
    def compact(value):
        if isinstance(value, dict):
            result = {key: compact(child) for key, child in value.items() if key not in {'title', 'default'}}
            if result.get('type') == 'object' and 'properties' in result:
                result['required'] = list(result['properties'])
            return result
        return [compact(child) for child in value] if isinstance(value, list) else value
    return compact(schema)


def adapt_reply(raw, context):
    item = ReplyProposal.model_validate(raw)
    if not authorized_photos(context) and (item.associations or item.response_photo_ids):
        raise ValueError('Unavailable photo fields must be omitted')
    name = None
    source = context.get('source') or {}
    if item.recall_limit_quote is not None:
        validate_question_evidence(dict(source_id=source.get('id'), version=source.get('version'),
            quote=item.recall_limit_quote, char_start=None, char_end=None, attribution=None), context)
        if item.reason not in {'pause', 'direct_answer', 'current_correction', 'user_redirect', 'pacing'}:
            item.reason = 'recall_limit'
            item.quote = item.recall_limit_quote
    if item.reason == 'recall_limit':
        if item.question is None:
            item.question = recall_question(context)
    if ((item.question is None and item.reason not in {'pause', 'direct_answer', 'current_correction'})
            or (item.question is not None and item.reason in {'pause', 'direct_answer'})):
        raise ValueError('No-question outcome requires an explicit reason')
    if item.historical_clue_id is not None:
        from .historical_news import authorized_clue
        authorized_clue(context, item.historical_clue_id)
        if item.question is None or (item.quote is not None and item.reason!='recall_limit'):
            raise ValueError('Public context requires one optional question without personal evidence')
    evidence = None
    if item.quote is not None:
        evidence = validate_question_evidence(dict(source_id=source.get('id'),
            version=source.get('version'), quote=item.quote, char_start=None,
            char_end=None, attribution=None), context).model_dump()
        if item.historical_clue_id is not None:
            evidence = None  # Recall control is not evidence of attending a public event.
    identity = 'immediate-' + (context.get('source') or {}).get('id', 'fallback')
    questions = [] if item.question is None else [dict(id=identity, question=item.question,
        context=dict(event_id=None, photo_id=None, life_stage=None, year=None, evidence=evidence),
        order=0, bridge='')]
    if questions and item.historical_clue_id is not None:
        questions[0]['context']['historical_clue_id'] = item.historical_clue_id
    saved = dict(acknowledgement=item.acknowledgement,
        plan=dict(candidates=questions, chosen_id=identity if questions else None,
                  active_event_id=None, work=dict(mode='extract', name=None)),
        associations=[value.model_dump() for value in item.associations],
        response_photo_ids=item.response_photo_ids, stopped=item.question is None, continuity_updates=[])
    focus = None
    if item.workspace_focus is not None:
        from .interview_questions import resolution_sources
        from .place_journey import validate_place_journey
        proposed = item.workspace_focus
        sources = resolution_sources(context)
        original = next((s for (source_id, _), s in sources.items()
            if source_id == (proposed.source_id or source.get('id'))), None)
        coarse = validate_place_journey(dict(place=proposed.place, hierarchy=['Earth', proposed.place], granularity='city'))
        if item.question is None or not original or not coarse or proposed.place not in proposed.quote:
            raise ValueError('Workspace focus requires a question and an original coarse place')
        try:
            start, end = question_span(original, proposed.quote)
        except ValueError:
            raise ValueError('Workspace focus quote must match one original passage in its selected source') from None
        focus = dict(place=proposed.place, evidence=dict(source_id=original['id'], version=original['version'],
            quote=proposed.quote, char_start=start, char_end=end))
    saved['workspace_focus'] = focus
    outcome = dict(schema_version=1,
        plan_revision_seen=None,
        selected_candidate_id=None, selection_reason=item.reason,
        used_strategy=item.strategy,
        question_delivered=item.question, work_hint='extract')
    return saved, item.reason, outcome, item.question is None and item.reason != 'direct_answer', name


def reply_packet(packet):
    """Project an already validated governed packet; preserve its complete raw tail."""
    context = packet.interview_context
    checkpoint = packet.checkpoint
    summary = checkpoint.memory_summary if checkpoint else None
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
        original_evidence=[ref.model_dump(mode='json') for ref in
            [*(checkpoint.evidence if checkpoint else []), *packet.retrieved]],
        brief=dict(covered_through_sequence=packet.coverage_end),
        background_deliveries=deliveries,
        context={key: deepcopy(context[key]) for key in (
            'opening_turn', 'breadth_checkpoint', 'recent_dialogue',
            'photos', 'photo_context', 'reviewed_acknowledgement') if key in context})
