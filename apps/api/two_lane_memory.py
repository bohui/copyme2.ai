"""Optional derived hints on the canonical timeline lane; no delivery authority."""
from __future__ import annotations

from pathlib import Path

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import os

from pydantic import BaseModel, ConfigDict, Field
from .prompt_artifact import load_prompt_artifact, prompt_path
from .lifetime_memory_continuity import _Places


def two_lanes_enabled():
    return os.getenv('MEMOIR_TWO_LANES', '').lower() in {'1', 'true', 'yes'}


CONVERSATION_INSTRUCTIONS = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/background-memory'))


class PreparedQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1, max_length=800)
    topic: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=500)
    requires_confirmation: bool = Field(default=False,
        description='Whether this question needs narrator confirmation before continuing the interview.')


class DerivedHints(_Places):
    prepared_questions: list[PreparedQuestion] = Field(max_length=5)


def extraction_contract(*, strategy=False, attribution=False):
    from .memory_events import extraction_instructions, extraction_schema
    schema=extraction_schema()
    extension=DerivedHints.model_json_schema()
    question = extension['$defs']['PreparedQuestion']
    question['required'] = list(question['properties'])
    question['properties']['requires_confirmation'].pop('default', None)
    extension['$defs']['_PlaceJourney']['required']=list(extension['$defs']['_PlaceJourney']['properties'])
    for field in ('latitude','longitude'):
        extension['$defs']['_PlaceJourney']['properties'][field].pop('default',None)
    schema.setdefault('$defs',{}).update(extension['$defs'])
    schema['properties'].update(extension['properties'])
    schema['required']+=list(extension['properties'])
    place_skill = load_prompt_artifact(Path(__file__).resolve().parents[2] / 'skills/memoir-place-journey/references/two-lane.md')
    # The versioned timeline text also describes its standalone events-only
    # transport. Replace that one sentence when composing the wider two-lane
    # schema so the worker receives one consistent output contract.
    timeline_instructions = extraction_instructions(derived_hints=True).replace(
        'Return only schema-bound\nJSON `{"events": [...]}` to the private worker.',
        'Return schema-bound JSON matching the supplied combined schema to the private worker.',
    )
    instructions=timeline_instructions+'\n'+place_skill+load_prompt_artifact(
        prompt_path('memoir/skills/memoir-author-timeline/derived-hints'))
    if strategy:
        from .interview_strategy import StrategyProposal
        proposal=StrategyProposal.model_json_schema()
        schema.setdefault('$defs',{}).update(proposal.get('$defs',{}))
        schema['properties']['strategy_proposal']={k:v for k,v in proposal.items() if k!='$defs'}
        schema['required'].append('strategy_proposal')
        instructions+=load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/strategy/proposal'))
    if attribution:
        from .conversation_attribution import attribution_schema, INSTRUCTIONS
        instructions += INSTRUCTIONS
        schema = attribution_schema(schema)
    return instructions,schema


def derived_hints(raw, page):
    from .place_journey import validate_place_journey, grounded_place_journeys
    hints=DerivedHints.model_validate({key:raw[key] for key in ('place_journeys','prepared_questions')})
    places=[validate_place_journey(place.model_dump()) for place in hints.place_journeys
            if place.hierarchy[-1]==place.place]
    places=grounded_place_journeys([place for place in places if place],page['source']['text'])
    questions=[]
    for item in hints.prepared_questions:
        if item.quote not in page['source']['text']:
            raise ValueError('Prepared question lacks exact source evidence')
        if item.question.count('?')+item.question.count('？')>1:
            raise ValueError('Prepared hint contains multiple questions')
        if item.question.casefold() in {q['question'].casefold() for q in questions}:
            raise ValueError('Prepared questions must be distinct')
        questions.append(item.model_dump(exclude_defaults=True))
    return {'place_journeys':places,'prepared_questions':questions}


def pending_confirmation(context):
    from .interview_strategy import current_constraints
    if current_constraints((context.get('source') or {}).get('text', '')):
        return None
    return next((q for q in context.get('prepared_questions', [])
                 if q.get('requires_confirmation') is True), None)


def prioritize_confirmation(value, context):
    """The persisted B queue owns the next question; narrator controls still win."""
    question = pending_confirmation(context)
    if not question or value.get('stopped') or (context.get('strategy_selector') and value.get('question') is None):
        return value
    if context.get('strategy_selector'):
        return {**value, 'question': question['question'], 'selected_candidate_id': question['id'],
                'selection_reason': 'prepared_candidate'}
    return {**value, 'plan': {**value['plan'], 'chosen_id': question['id'], 'active_event_id': None,
        'candidates': [{'id': question['id'], 'question': question['question'], 'order': 0, 'bridge': '',
                        'context': {'event_id': None, 'photo_id': None, 'life_stage': None, 'year': None}}]}}


class RuntimeCapacity:
    """Bound one worker's requests with a reserved interactive slot.

    Background callers acquire their smaller allowance before total capacity,
    so they cannot occupy the interactive reserve while waiting. PostgreSQL's
    existing project lane token remains the distributed ownership authority.
    """
    def __init__(self, *, total=4, background=2, queue_limit=8):
        if not 1<=background<total<=32 or not 0<=queue_limit<=128:
            raise ValueError('Invalid runtime capacity')
        self._total=asyncio.Semaphore(total)
        self._background=asyncio.Semaphore(background)
        self.queue_limit=queue_limit
        self.waiting=0

    @asynccontextmanager
    async def slot(self, *, interactive, serial_lock=None):
        from .agent_lock import AgentTurnBusyError
        key='_interactive_waiting' if interactive else '_background_waiting'
        count=getattr(self,key,0)
        blocked=(self._total.locked() or (not interactive and self._background.locked())
                 or (serial_lock is not None and serial_lock.locked()))
        if count>=self.queue_limit and blocked:
            raise AgentTurnBusyError('Runtime capacity queue is full')
        setattr(self,key,count+1);self.waiting+=1
        queued=True
        try:
            async with AsyncExitStack() as admitted:
                async with asyncio.timeout(5):
                    # Repeated work for one principal cannot occupy the
                    # interactive reserve while waiting on its serial writer.
                    if serial_lock is not None:
                        await admitted.enter_async_context(serial_lock)
                    if not interactive:
                        await admitted.enter_async_context(self._background)
                    await admitted.enter_async_context(self._total)
                setattr(self,key,getattr(self,key)-1);self.waiting-=1;queued=False
                yield
        finally:
            if queued:
                setattr(self,key,getattr(self,key)-1);self.waiting-=1
