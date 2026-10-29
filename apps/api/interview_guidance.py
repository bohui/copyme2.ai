"""Evidence-backed next-turn guidance, independently executed in Lane B."""
from __future__ import annotations

from copy import deepcopy
import json

from pydantic import BaseModel, ConfigDict, Field

from .interview_questions import (PreparedQuestion, question_span, question_priority,
                                  GUIDANCE_KINDS as KINDS, GuidanceKind)
from .interview_strategy import StrategyProposal, validate_proposal
from .memory_events import EvidenceRef

MINIMUM_DETAIL_ROUNDS = 3


class GuidanceSignal(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: GuidanceKind
    source_refs: list[EvidenceRef] = Field(min_length=1, max_length=4)
    detail_question_ids: list[str] = Field(default_factory=list, max_length=8)
    recall_limit_quote: str | None = Field(default=None, min_length=1, max_length=500)


class GuidanceQuestion(PreparedQuestion):
    source_id: str = Field(min_length=1, max_length=128)
    source_version: int = Field(ge=1)
    trigger: GuidanceKind
    historical_clue_id: str | None = Field(default=None, pattern=r'^news-[a-f0-9]{24}$')
    bridge: str = Field(default='', max_length=500)


class AcknowledgementGuidance(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=700, pattern=r'^[^?？]*$')
    source_refs: list[EvidenceRef] = Field(min_length=1, max_length=4)


class GuidanceResult(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    signals: list[GuidanceSignal] = Field(max_length=6)
    prepared_questions: list[GuidanceQuestion] = Field(max_length=5)
    acknowledgement_guidance: AcknowledgementGuidance | None = None
    strategy_proposal: StrategyProposal | None = None


def _originals(page):
    windows = [*(page.get('guidance_context') or {}).get('source_windows', [])]
    if page.get('source'):
        windows.append(page['source'])
    sources = {}
    for source in windows:
        if (source.get('status') == 'active' and source.get('kind') in {'narrator_chat', 'narrator_transcript'}
                and source.get('role') != 'assistant'):
            sources.setdefault((source['id'], source['version']), []).append(source)
    return sources


def _grounded_ref(ref, sources):
    spans = set()
    for source in sources.get((ref.source_id, ref.version), []):
        try:
            spans.add(question_span(source, ref.quote, ref.char_start, ref.char_end))
        except ValueError:
            # Recount a unique exact quote, as the other derived hint validators do.
            try:
                spans.add(question_span(source, ref.quote))
            except ValueError:
                continue
    if len(spans) != 1:
        raise ValueError('Guidance evidence requires one exact authorized occurrence')
    start, end = spans.pop()
    return ref.model_copy(update={'char_start': start, 'char_end': end})


def validate_guidance_result(raw, page):
    result = GuidanceResult.model_validate(raw)
    context = page['guidance_context']
    sources = _originals(page)
    signals = {signal.kind: signal for signal in result.signals}
    if len(signals) != len(result.signals):
        raise ValueError('Guidance signals must be distinct')
    delivered = {item['question']['id'] for item in context.get('recent_dialogue', [])
                 if item.get('question', {}).get('delivered') is True}
    for signal in result.signals:
        signal.source_refs = [_grounded_ref(ref, sources) for ref in signal.source_refs]
        if signal.kind == 'conflict' and len({(ref.source_id, ref.version, ref.char_start, ref.char_end)
                                             for ref in signal.source_refs}) < 2:
            raise ValueError('A conflict requires both original assertions')
        if signal.kind == 'topic_transition':
            if signal.recall_limit_quote is not None:
                source = page['source']
                question_span(source, signal.recall_limit_quote)
            elif (len(set(signal.detail_question_ids)) < context.get('minimum_detail_rounds', MINIMUM_DETAIL_ROUNDS)
                  or len(set(signal.detail_question_ids)) != len(signal.detail_question_ids)
                  or set(signal.detail_question_ids) - delivered):
                raise ValueError('Topic transition requires delivered detail questions')
        elif signal.recall_limit_quote is not None:
            raise ValueError('Recall limits support a broader topic direction')
    news = {clue['id'] for clue in context.get('news_clues', [])}
    seen = set()
    for question in result.prepared_questions:
        if (question.source_id, question.source_version) not in sources or question.trigger not in signals:
            raise ValueError('A guidance question requires its scoped source and trigger')
        evidence = _grounded_ref(EvidenceRef(source_id=question.source_id, version=question.source_version,
            quote=question.quote, char_start=question.char_start, char_end=question.char_end), sources)
        question.char_start, question.char_end = evidence.char_start, evidence.char_end
        if question.question.count('?') + question.question.count('？') > 1:
            raise ValueError('Guidance asks one question at a time')
        confirmation = question.trigger in {'conflict', 'clarification'}
        if question.requires_confirmation != confirmation:
            raise ValueError('Only conflicts and clarifications require confirmation')
        if question.trigger in {'historical_news', 'topic_transition', 'life_essence'} and question.scope != 'broader':
            raise ValueError('A new direction requires a broader question')
        if question.trigger == 'historical_news':
            if question.historical_clue_id not in news:
                raise ValueError('Guidance requires an inspected available historical clue')
        elif question.historical_clue_id is not None:
            raise ValueError('Historical evidence belongs to a public-context question')
        identity = (question.source_id, question.source_version, question.question.strip().casefold(),
                    question.char_start, question.char_end)
        if identity in seen:
            raise ValueError('Guidance questions must be distinct')
        seen.add(identity)
    priority = next((kind for kind in KINDS if kind in signals), None)
    if priority and priority != 'life_essence' and not any(q.trigger == priority for q in result.prepared_questions):
        raise ValueError('The highest priority signal requires a question')
    if result.acknowledgement_guidance is not None:
        if 'life_essence' not in signals:
            raise ValueError('A reflection requires its grounded life-essence signal')
        acknowledgement = result.acknowledgement_guidance
        acknowledgement.source_refs = [_grounded_ref(ref, sources) for ref in acknowledgement.source_refs]
        if any(ref.attribution for ref in acknowledgement.source_refs):
            raise ValueError('A life reflection cannot adopt another speaker testimony')
    if result.strategy_proposal is not None:
        validate_proposal(result.strategy_proposal.model_dump(), page)
    output = result.model_dump(mode='json')
    output['prepared_questions'].sort(key=question_priority)
    if len(json.dumps(output, ensure_ascii=False).encode()) > 14000:
        raise ValueError('Guidance output exceeds its resource budget')
    return output


def guidance_packet(page, *, retry_reason=None):
    packet = {'source': deepcopy(page['source']), 'events': deepcopy(page['events']),
              'guidance_context': deepcopy(page['guidance_context'])}
    if retry_reason is not None:
        if retry_reason != 'OUTPUT_SCHEMA':
            raise ValueError('Unsupported guidance retry reason')
        packet['retry_reason'] = retry_reason
    return packet


def guidance_contract(fence):
    from .prompt_artifact import load_prompt_artifact, prompt_path
    instructions = load_prompt_artifact(prompt_path('memoir/skills/memoir-interview-guidance/instructions'))
    if fence.two_lane and fence.two_lane.strategy_mode:
        instructions += '\n' + load_prompt_artifact(prompt_path('memoir/agents/mira/strategy-proposal'))
    schema = GuidanceResult.model_json_schema()
    def required(value):
        if isinstance(value, dict):
            if value.get('type') == 'object' and 'properties' in value:
                value['required'] = list(value['properties'])
            value.pop('default', None)
            for child in value.values():required(child)
        elif isinstance(value, list):
            for child in value:required(child)
    required(schema)
    source_ids = list(dict.fromkeys(s['id'] for s in fence.guidance_context['source_windows']))
    if fence.source and fence.source['id'] not in source_ids:source_ids.append(fence.source['id'])
    schema['$defs']['EvidenceRef']['properties']['source_id']['enum'] = source_ids
    schema['$defs']['GuidanceQuestion']['properties']['source_id']['enum'] = source_ids
    return instructions, schema


async def _commit_guidance(page, worker, result):
    return await worker.broker.rpc('commit_lifetime_interview_guidance', p_lane_id=page['lane_id'],
        p_token=page['token'], p_page_digest=page['page_digest'], p_result=result)


async def execute_guidance_lane(page, worker):
    from .lifetime_memory_composer import lane_model_budget
    from .lifetime_memory_lane_engine import build_bounded_lane_input, send_bounded_lane_request
    if not page['guidance_context']['source_windows']:
        return await _commit_guidance(page, worker, dict(signals=[], prepared_questions=[],
            acknowledgement_guidance=None, strategy_proposal=None))
    for attempt in range(2):
        bounded = build_bounded_lane_input(page, phase='guidance',
            packet=guidance_packet(page, retry_reason='OUTPUT_SCHEMA' if attempt else None),
            budget=lane_model_budget())
        response = await send_bounded_lane_request(worker_url=worker.worker_url, worker_secret=worker.worker_secret,
            bounded_lane=bounded, worker_transport=worker.worker_transport,
            publisher=getattr(worker, 'lane_publisher', None), timeout=240)
        try:
            result = validate_guidance_result(json.loads(response['reply']), page)
            break
        except (ValueError, TypeError, KeyError):
            if attempt:raise
    return await _commit_guidance(page, worker, result)
