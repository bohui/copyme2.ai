"""Private collector output and evidence-bound interview planning.

Model proposals are untrusted. Chat and speech receive the rendered acknowledgement
and one validated chosen question; tester traces can show validated question outputs. Photo pixels
are not supplied by this contract, so descriptions retain narrator/metadata
provenance and never claim visual inspection.
"""
from __future__ import annotations

from copy import deepcopy
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .memory_events import EvidenceRef
from .interview_questions import (QuestionResolution, resolution_schema, validate_resolutions,
    validate_question_evidence, question_evidence_schema, question_candidates, hint_evidence)
from .stage_readiness import LIFE_STAGES
from .prompt_artifact import load_prompt_artifact, prompt_path


def historical_acknowledgements(context):
    copies = json.loads(load_prompt_artifact(prompt_path('memoir/shared/historical-acknowledgements')))
    language = (context or {}).get('interview_language')
    allowed = {copies[language], copies.get(f'{language}/stop', copies[language])} if language in copies else set(copies.values())
    reflection = ((context or {}).get('interview_guidance') or {}).get('acknowledgement_guidance')
    if reflection:
        allowed.add(reflection['text'])
    return allowed


def historical_acknowledgement_allowed(value, context):
    state=(context or {}).get('historical_news') or {}
    return not (state.get('enabled') and state.get('clues')) or value in historical_acknowledgements(context)


def neutral_acknowledgement(context):
    copies = json.loads(load_prompt_artifact(prompt_path('memoir/shared/historical-acknowledgements')))
    return copies.get(context.get('interview_language'), copies['en-AU'])


def defer_prepared_acknowledgement(context):
    from .two_lane_memory import pending_confirmation
    return bool(context.get('historical_news', {}).get('clues') or pending_confirmation(context))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class QuestionContext(StrictModel):
    event_id: str | None
    photo_id: str | None
    life_stage: str | None
    year: int | None
    historical_clue_id: str | None = Field(default=None, max_length=128)
    evidence: EvidenceRef | None = Field(default=None)


class QuestionCandidate(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=800)
    context: QuestionContext
    order: int = Field(ge=0, le=100)
    bridge: str = Field(max_length=500)


class TurnWorkPlan(StrictModel):
    mode: Literal['reply_only', 'extract'] = Field(description='Extract new facts, corrections, recall/topic boundaries and profile/photo information. Reply_only is for pure greetings or stops without new facts.')
    name: str | None = Field(max_length=120,
        description='Only a preferred name explicitly stated in CURRENT narration; otherwise null. Never copy a name from profile or history.')


class InterviewPlan(StrictModel):
    @model_validator(mode='before')
    @classmethod
    def discard_retired_phase(cls, value):
        # Accept an older worker response without reviving its mode control.
        return {k:v for k,v in value.items() if k!='conversation_phase'} if isinstance(value,dict) else value

    candidates: list[QuestionCandidate] = Field(max_length=5)
    chosen_id: str | None
    active_event_id: str | None
    work: TurnWorkPlan | None = None
    resolved_questions: list[QuestionResolution] = Field(default_factory=list, max_length=5)
    deferred_questions: list[QuestionResolution] = Field(default_factory=list, max_length=5)


class PhotoAssociation(StrictModel):
    photo_id: str = Field(min_length=1, max_length=512)
    event_id: str | None
    source_id: str = Field(min_length=1, max_length=128)
    source_version: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=2000)
    description: str = Field(min_length=1, max_length=1000)
    provenance: Literal['narrator_metadata']


class CollectorResult(StrictModel):
    # First field deliberately precedes all private planning in the JSON stream.
    acknowledgement: str = Field(min_length=1, max_length=2000)
    plan: InterviewPlan
    associations: list[PhotoAssociation] = Field(max_length=20)
    response_photo_ids: list[str] = Field(max_length=5)
    stopped: bool


def constrain_acknowledgement(schema, choices):
    field = schema['properties']['acknowledgement']
    field['enum'] = choices
    # This provider can return empty incomplete output for enum plus pattern.
    field.pop('pattern', None)


def collector_schema(context=None):
    schema = CollectorResult.model_json_schema()
    schema['properties']['acknowledgement']['pattern'] = '^[^?？]*$'
    # The provider requires every wire field; legacy saved plans may omit work.
    plan = schema['$defs']['InterviewPlan']
    plan['required'] = list(plan['properties'])
    plan['properties']['work'].pop('default', None)
    question_context = schema['$defs']['QuestionContext']
    question_context['required'] = list(question_context['properties'])
    question_context['properties']['historical_clue_id'].pop('default', None)
    question_context['properties']['evidence'].pop('default', None)
    if context is not None:
        events=[e for e in context.get('events',[]) if e.get('status')=='active']
        pointers={
            'event_id':[e['id'] for e in events],
            'life_stage':[e.get('life_stage') for e in events if e.get('life_stage') in LIFE_STAGES],
            'year':[year for e in events for year in
                (e.get('temporal',{}).get('year_start'),e.get('temporal',{}).get('year_end')) if year],
        }
        for field,allowed in pointers.items():
            question_context['properties'][field]['enum']=list(dict.fromkeys([None,*allowed]))
        plan['properties']['active_event_id']['enum']=list(dict.fromkeys([None,*pointers['event_id']]))
    if (context or {}).get('historical_news', {}).get('clues'):
        constrain_acknowledgement(schema, sorted(historical_acknowledgements(context)))
    return question_evidence_schema(resolution_schema(schema, context, plan=True), context)


def collector_instructions(context):
    prefix = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/collector-plan'))
    return prefix + json.dumps(context, ensure_ascii=False, separators=(',', ':'))

def _questions(value):
    return len(re.findall(r'[?？]', value))


def _acknowledgement_has_question(value):
    if _questions(value):
        return True
    return False


def authorized_photos(context):
    photos = {}
    for photo in context.get('photo_context', []) + context.get('photos', []):
        if isinstance(photo, dict) and photo.get('photo_id'):
            photos[photo['photo_id']] = photo
    for association in context.get('associations', context.get('photo_associations', [])):
        photo = association.get('photo')
        if isinstance(photo, dict) and photo.get('photo_id'):
            photos[photo['photo_id']] = photo
    return photos


def validate_collector_result(value, context):
    raw = json.loads(value) if isinstance(value, str) else value
    result = CollectorResult.model_validate(raw)
    if not historical_acknowledgement_allowed(result.acknowledgement, context):
        raise ValueError('Historical context cannot supply personal acknowledgement facts')
    if _acknowledgement_has_question(result.acknowledgement):
        raise ValueError('Acknowledgement cannot contain a question')
    plan = result.plan
    resolved = validate_resolutions([item.model_dump() for item in plan.resolved_questions], context)
    deferred = validate_resolutions([item.model_dump() for item in plan.deferred_questions], context, kind='deferral')
    if resolved & deferred:
        raise ValueError('A question cannot be both answered and deferred')
    if plan.chosen_id in deferred:
        raise ValueError('A deferred question cannot also be chosen')
    if plan.chosen_id in resolved:
        raise ValueError('An answered question cannot also be chosen')
    ids = [item.id for item in plan.candidates]
    if len(ids) != len(set(ids)):
        raise ValueError('Question candidates must be distinct')
    if result.stopped:
        if plan.candidates or plan.chosen_id is not None:
            raise ValueError('A finished exchange cannot force another question')
    elif not plan.candidates or plan.chosen_id not in ids:
        raise ValueError('Choose one current candidate')
    photos = authorized_photos(context)
    events = {e['id']: e for e in context.get('events', []) if e.get('status') == 'active'}
    sources = {(s['id'], int(s['version'])): s for s in context.get('sources', []) if s.get('status') == 'active'}
    source = context.get('source')
    if source and source.get('status') == 'active':
        sources[(source['id'], int(source['version']))] = source
    if plan.work:
        if plan.work.mode == 'reply_only':
            if context.get('photo_context') or result.associations or result.response_photo_ids:
                raise ValueError('Reply-only work cannot discard accepted photo context')
            if context.get('opening_turn') and len(plan.candidates) > 1:
                raise ValueError('A simple opening needs at most one candidate')
            name = plan.work.name
            if name is not None and (not name.strip() or not source or name not in source['text']):
                raise ValueError('Opening name requires exact current narrator wording')
        elif plan.work.name is not None:
            raise ValueError('Story profile clues belong to normal extraction')
    if plan.active_event_id is not None and plan.active_event_id not in events:
        raise ValueError('Unknown active event')
    # A year mentioned in a source may be a caption date or explicitly denied.
    # Only canonical temporal evidence supports a year-targeted question.
    years = {year for e in events.values() for year in
        (e.get('temporal', {}).get('year_start'), e.get('temporal', {}).get('year_end')) if year}
    stages = {e.get('life_stage') for e in events.values()}
    previous = context.get('plan') or {}
    previous_active = previous.get('active_event_id')
    chosen = None
    historical_context = None
    news_count = 0
    questions = []
    queued = {item['id']: item for item in question_candidates(context)}
    for candidate in plan.candidates:
        c = candidate.context
        expected = hint_evidence(queued[candidate.id], context) if candidate.id in queued else None
        if re.fullmatch(r'bq-[0-9a-f]{64}', candidate.id) and candidate.id not in queued:
            raise ValueError('Question candidate is outside the supplied hints')
        if c.evidence is None and expected:
            c.evidence = EvidenceRef.model_validate(expected)
        if c.evidence is not None:
            c.evidence = validate_question_evidence(c.evidence, context)
            if expected and any(getattr(c.evidence, key) != expected[key]
                    for key in ('source_id', 'version', 'quote', 'char_start', 'char_end')):
                raise ValueError('Question candidate cannot change its referenced passage')
        questions.append((candidate.question.strip().casefold(), None if c.evidence is None else
            (c.evidence.source_id, c.evidence.version, c.evidence.char_start, c.evidence.char_end)))
        if c.historical_clue_id is not None:
            from .historical_news import authorized_clue, public_clue, HISTORICAL_INVITATIONS
            clue = authorized_clue(context, c.historical_clue_id)
            safe_invitations = dict(HISTORICAL_INVITATIONS.values())
            if context.get('interview_language') in {'en-AU','zh-CN'} and (
                ('这条' in candidate.question) != (context['interview_language']=='zh-CN')):
                raise ValueError('Historical invitation must keep the interview language')
            if safe_invitations.get(candidate.question.strip()) != candidate.bridge.strip():
                raise ValueError('Historical questions require a neutral optional memory invitation')

            news_count += 1
            if news_count > 1 or any(v is not None for v in (c.year,c.life_stage,c.event_id,c.photo_id)):
                raise ValueError('Historical context cannot become personal evidence or replace the pool')
            if candidate.id == plan.chosen_id:
                if plan.active_event_id is not None:
                    raise ValueError('Continue the active memory before historical context')
                historical_context = public_clue(clue)
        if _questions(candidate.question) > 1 or _questions(candidate.bridge):
            raise ValueError('Only one visible question is allowed')
        if c.event_id is not None and c.event_id not in events:
            raise ValueError('Unknown candidate event')
        if c.photo_id is not None and c.photo_id not in photos:
            raise ValueError('Unknown candidate photo')
        if c.life_stage is not None and (c.life_stage not in LIFE_STAGES or c.life_stage not in stages):
            raise ValueError('Unsupported life stage')
        if c.year is not None and c.year not in years:
            raise ValueError('Unsupported biographical year')
        if candidate.id == plan.chosen_id:
            chosen = candidate
            if previous_active and c.event_id and c.event_id != previous_active and not candidate.bridge.strip():
                raise ValueError('Returning to another event needs a conversational bridge')
    if len(questions) != len(set(questions)):
        raise ValueError('Question candidates must be distinct')
    for association in result.associations:
        if association.photo_id not in photos:
            raise ValueError('Unknown association photo')
        s = sources.get((association.source_id, association.source_version))
        if (not source or association.source_id != source['id']
            or association.source_version != int(source['version'])
            or not s or association.quote not in s['text']):
            raise ValueError('Photo associations require exact current narrator evidence')
        # A proposed link must overlap the canonical event evidence. The SQL
        # boundary independently validates the same identity/version/span.
        if association.event_id is not None:
            event = events.get(association.event_id)
            if s['text'].count(association.quote) != 1:
                raise ValueError('Repeated photo evidence remains unresolved')
            if not event or not any(r['source_id'] == association.source_id
                and int(r['version']) == association.source_version
                and association.quote in r['quote']
                for r in event.get('source_refs', [])):
                raise ValueError('Photo evidence does not support the named event')
        EvidenceRef(source_id=association.source_id, version=association.source_version, quote=association.quote)
    if len(result.response_photo_ids) != len(set(result.response_photo_ids)) or any(id not in photos for id in result.response_photo_ids):
        raise ValueError('Unknown or duplicate response photo')
    reply = result.acknowledgement.strip()
    if chosen:
        reply += '\n\n' + (' '.join([chosen.bridge.strip(), chosen.question.strip()])).strip()
    # Always present an accepted cue, even when its topic is deferred.
    display = list(dict.fromkeys(result.response_photo_ids + [p['photo_id'] for p in context.get('photo_context', [])]))[:5]
    saved_plan = plan.model_dump()
    if not saved_plan['resolved_questions']:
        saved_plan.pop('resolved_questions')
    if not saved_plan['deferred_questions']:
        saved_plan.pop('deferred_questions')

    for candidate in saved_plan['candidates']:
        if candidate['context']['historical_clue_id'] is None:
            candidate['context'].pop('historical_clue_id')
        if candidate['context']['evidence'] is None:
            candidate['context'].pop('evidence')
    if plan.work is None:
        saved_plan.pop('work')  # Older collectors retain normal extraction behavior.
    return {'reply': reply, 'acknowledgement': result.acknowledgement,
        'plan': saved_plan, 'associations': [a.model_dump() for a in result.associations],
        'response_photos': [deepcopy(photos[id]) for id in display], 'stopped': result.stopped,
        **({'historical_context': historical_context} if historical_context else {})}


class CollectorVisibleStream:
    """Incrementally expose only the first complete acknowledgement string.

    Keeping a string buffered until its closing quote allows validation before
    display, handles escaped quotes/Unicode, and never leaks partial JSON keys.
    The chosen question is emitted only after full result validation.
    """
    def __init__(self):
        self.buffer = ''
        self.emitted = False
        self.rejected = False

    def feed(self, chunk, *, final=False):
        if self.emitted or self.rejected:
            return ''
        self.buffer += chunk
        prefix = re.match(r'^\s*\{\s*"acknowledgement"\s*:\s*', self.buffer)
        if not prefix:
            if len(self.buffer) > 80 or final:
                self.rejected = True
            return ''
        try:
            value, _ = json.JSONDecoder().raw_decode(self.buffer[prefix.end():])
        except json.JSONDecodeError:
            return ''
        if not isinstance(value, str) or not value or len(value) > 2000 or _acknowledgement_has_question(value):
            self.rejected = True
            return ''
        self.emitted = True
        return value


def public_interview_fields(turn):
    """Project only current authorized cards and the immutable acceptance cue."""
    if not isinstance(turn, dict):
        return {'photo_cue': None, 'response_photos': []}
    photos = turn.get('response_photos')
    if not isinstance(photos, list) or not photos and not turn.get('plan'):
        photos = turn.get('photo_context') or []
    safe = []
    allowed = {'photo_id','kind','id','title','description','image_url','original_url','source_url',
               'attribution','date_expression','place','period','content_type','width','height'}
    for photo in photos:
        if not isinstance(photo, dict):
            continue
        projected = {key:value for key,value in photo.items() if key in allowed}
        if photo.get('kind') == 'private_upload':
            for key in ('image_url','original_url','source_url'):
                projected.pop(key, None)
        safe.append(projected)
    from .historical_news import public_clue
    key = turn.get('consumed_photo_key')
    revision = turn.get('consumed_photo_revision')
    return {**({'recordings':turn['recordings']} if 'recordings' in turn else {}), 'photo_cue': {'consumed': bool(key or turn.get('photo_context')), 'key': key, 'revision': revision}, 'response_photos': safe,
        **({'historical_context': public_clue(turn['historical_context'])}
           if isinstance(turn.get('historical_context'), dict) else {})}
