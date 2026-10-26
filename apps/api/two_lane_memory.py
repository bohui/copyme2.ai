"""Optional derived hints on the canonical timeline lane; no delivery authority."""
from __future__ import annotations

from pathlib import Path

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import os

from .prompt_artifact import load_prompt_artifact, prompt_path
from .lifetime_memory_continuity import _Places
from .interview_questions import PreparedQuestion, hint_evidence, question_candidates, question_priority


def two_lanes_enabled():
    return os.getenv('MEMOIR_TWO_LANES', '').lower() in {'1', 'true', 'yes'}


CONVERSATION_INSTRUCTIONS = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/background-memory'))


class DerivedHints(_Places):
    """Timeline-owned geography only; interviewing belongs to the guidance skill."""


def extraction_contract(*, strategy=False, attribution=False, continuity=False, source=None):
    from .memory_events import extraction_instructions, extraction_schema
    schema=extraction_schema()
    extension=DerivedHints.model_json_schema()
    extension['$defs']['_PlaceJourney']['required']=list(extension['$defs']['_PlaceJourney']['properties'])
    for field in ('latitude','longitude'):
        extension['$defs']['_PlaceJourney']['properties'][field].pop('default',None)
    schema.setdefault('$defs',{}).update(extension['$defs'])
    schema['properties'].update(extension['properties'])
    schema['required']+=list(extension['properties'])
    place_skill = load_prompt_artifact(Path(__file__).resolve().parents[2] / 'skills/memoir-place-journey/references/two-lane.md')
    instructions=extraction_instructions(derived_hints=True)+'\n'+place_skill+load_prompt_artifact(
        prompt_path('memoir/skills/memoir-author-timeline/derived-hints'))
    if attribution:
        from .conversation_attribution import attribution_schema, INSTRUCTIONS
        instructions += INSTRUCTIONS
        schema = attribution_schema(schema)
    if continuity:
        from .lifetime_memory_continuity import continuity_schema
        extension = continuity_schema(source, background=True)
        schema['$defs'].update(extension['$defs'])
        schema['properties'].update(extension['properties'])
        schema['required'].append('continuity_updates')
        instructions += load_prompt_artifact(prompt_path('memoir/skills/memoir-author-timeline/continuity'))
    return instructions,schema


def derived_hints(raw, page, *, attribution=None):
    from .place_journey import validate_place_journey, grounded_place_journeys
    hints=DerivedHints.model_validate({key:raw[key] for key in ('place_journeys',)},
        context={'derived_source':page['source']})
    places=[validate_place_journey(place.model_dump()) for place in hints.place_journeys
            if place.hierarchy[-1]==place.place]
    source = page['source']
    text = source['text']
    if attribution is not None:
        blocked = [item['source_ref'] for item in attribution['passage_dispositions']
            if item['disposition'] != 'non_story' or item['reason'] != 'profile_introduction']
        narrator = {'narrator', 'storyteller', 'self', '我', '本人', page['user_id']}
        blocked.extend(ref for event in attribution['events'] for ref in event['source_refs']
            if any(label and label.casefold() not in narrator
                for label in (ref.get('attribution'), event.get('attribution'))))
        characters = list(text)
        for ref in blocked:
            if ref['source_id'] == source['id'] and ref['version'] == source['version']:
                lo = max(0, ref['char_start'] - source['char_start'])
                hi = min(len(text), ref['char_end'] - source['char_start'])
                # Preserve offsets and keep another narrator occurrence of the same place.
                characters[lo:hi] = ' ' * max(0, hi - lo)
        text = ''.join(characters)
    places=grounded_place_journeys([place for place in places if place],text,
        source_offset=source.get('char_start') or 0, source_text=source['text'])
    if attribution is not None:
        restricted = [item['source_ref'] for item in attribution['passage_dispositions']
            if item['disposition'] in {'withheld', 'unresolved'}
            and item['source_ref']['source_id'] == source['id']
            and item['source_ref']['version'] == source['version']]
        for place in places:
            evidence = place.get('research')
            if evidence and any(ref['char_start'] < evidence['char_end']
                    and evidence['char_start'] < ref['char_end'] for ref in restricted):
                # An exact quote still cannot carry restricted prose into research.
                place.pop('research')
    return {'place_journeys':places}


def pending_confirmation(context, *, exclude_ids=()):
    return next((q for q in sorted(question_candidates(context), key=question_priority)
                 if q.get('requires_confirmation') is True and q['id'] not in exclude_ids), None)


def prioritize_question(value, context, *, selection_reason):
    """Prioritize B only after validating the original plan and current intent."""
    resolved = {item['question_id'] for name in ('resolved_questions', 'deferred_questions')
                for item in value['plan'].get(name, [])}
    question = pending_confirmation(context, exclude_ids=resolved)
    if (question is None and context.get('reply_contract') == 'reply-v2'
            and selection_reason in {'prepared_candidate', 'adapted_candidate', 'return_context', 'latest_story'}):
        from .conversation_reply import reply_candidates
        question = next((item for item in reply_candidates(context) if item['id'] not in resolved
                         and (selection_reason != 'latest_story' or item.get('trigger') in
                              {'historical_news', 'topic_transition', 'life_essence'})), None)
    # The independent skill supplies next-turn options, not a guardrail that
    # rewrites a reply already chosen or streamed by Lane A.
    if question and question.get('trigger'):
        return value
    if not question or value['stopped'] or selection_reason in {'current_correction', 'user_redirect', 'pacing', 'recall_limit'}:
        return value
    if value['plan']['chosen_id'] == question['id'] and not question.get('requires_confirmation'):
        return value
    evidence = None if question.get('historical_clue_id') else hint_evidence(question, context)
    return {**value, 'plan': {**value['plan'], 'chosen_id': question['id'], 'active_event_id': None,
        'candidates': [{'id': question['id'], 'question': question['question'], 'order': 0,
                        'bridge': question.get('bridge', ''),
                        'context': {'event_id': None, 'photo_id': None, 'life_stage': None, 'year': None,
                                    **({'historical_clue_id': question['historical_clue_id']}
                                       if question.get('historical_clue_id') else {}),
                                    **({'evidence': evidence} if evidence else {})}}]}}


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
