"""Optional derived hints on the canonical timeline lane; no delivery authority."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import os

from pydantic import BaseModel, ConfigDict, Field
from .lifetime_memory_continuity import _Places


def two_lanes_enabled():
    return os.getenv('MEMOIR_TWO_LANES', '').lower() in {'1', 'true', 'yes'}


CONVERSATION_INSTRUCTIONS = '''
Optional place extraction belongs to the asynchronous memory lane. Do not return
place_journeys. Use this single collector pass for the whole current message,
reply, one appropriate chosen question and reply_only/extract work decision.
Prioritize the current request, correction or boundary, then a useful follow-up
to the latest answer, then a valid prepared_questions hint, then a grounded safe
fallback. Prepared questions are optional derived suggestions, never delivered
questions or testimony. Adapt or discard them against the current answer. Answer
explicit questions; a pause needs zero candidates. A normal pool is 2–5, a
name-only opening at most one; never pad a pool. If an upload is unprocessed,
state that it is pending; do not claim to have inspected it.
'''


class PreparedQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1, max_length=800)
    topic: str = Field(min_length=1, max_length=120)
    quote: str = Field(min_length=1, max_length=500)


class DerivedHints(_Places):
    prepared_questions: list[PreparedQuestion] = Field(max_length=5)


def extraction_contract(*, strategy=False):
    from .memory_events import extraction_instructions, extraction_schema
    schema=extraction_schema()
    extension=DerivedHints.model_json_schema()
    extension['$defs']['_PlaceJourney']['required']=list(extension['$defs']['_PlaceJourney']['properties'])
    for field in ('latitude','longitude'):
        extension['$defs']['_PlaceJourney']['properties'][field].pop('default',None)
    schema.setdefault('$defs',{}).update(extension['$defs'])
    schema['properties'].update(extension['properties'])
    schema['required']+=list(extension['properties'])
    instructions=extraction_instructions()+'''
In this same bounded extraction pass also return place_journeys and at most five
prepared_questions. Empty arrays are valid. Places must be coarse public
administrative places literally named in this source window, hierarchy from
Earth to the exact source-script place; no private address, building or inferred
place. Omit uncertain coordinates. Each prepared question needs a topic and an
exact contiguous quote from this source window. It is an optional next-turn hint,
not a delivered question. Prepared questions use lane_context.preferences.language,
independently of the memoir edition locale. Respect current privacy/topics. Never infer
preferences, grant access, publish, charge or claim an upload was processed.
'''
    if strategy:
        from .interview_strategy import StrategyProposal
        proposal=StrategyProposal.model_json_schema()
        schema.setdefault('$defs',{}).update(proposal.get('$defs',{}))
        schema['properties']['strategy_proposal']={k:v for k,v in proposal.items() if k!='$defs'}
        schema['required'].append('strategy_proposal')
        instructions+='\nPropose the next internal comfort/explore/shape strategy and objective. Shape clarifies chronology/identity/links, never composition. Rich first narratives can explore immediately; no turn gates. Corrections preserve continuity; short answers alone imply no discomfort. Respect legacy pacing and current exclusions. A normal grounded pool is 2–5 when supported, with no filler minimum. Focus IDs must be active events in this page or []. This proposal changes no preferences, permissions or actual delivered questions.'
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
        questions.append(item.model_dump())
    return {'place_journeys':places,'prepared_questions':questions}


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
