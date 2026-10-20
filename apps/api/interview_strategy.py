"""Internal next-turn interviewing strategy, separate from preferences/permissions.

B proposes plans; application transactions validate them. A selects one immediate
question and records a deviation without changing the planned strategy.
"""
from __future__ import annotations
import json
import logging
import os
import re
import time
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field
from .interview_plan import PhotoAssociation,TurnWorkPlan
from .two_lane_memory import PreparedQuestion, pending_confirmation
from .interview_questions import QuestionResolution, resolution_schema
from .interview_questions import hint_evidence, question_evidence_schema
from .memory_events import EvidenceRef
from .prompt_composition import render_prompt_artifact
from .prompt_artifact import prompt_path
from .stage_readiness import LIFE_STAGES

Strategy=Literal['comfort','explore','shape']
SelectionReason=Literal['prepared_candidate','adapted_candidate','latest_story','user_redirect','current_correction',
    'pacing','pause','direct_answer','safe_fallback','stale_plan','no_plan','return_context']


class StrategyProposal(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    strategy:Strategy
    objective:Literal['gentle_entry','follow_story','clarify_order','clarify_identity','link_stories']
    focus_event_ids:list[str]=Field(max_length=8)


class StrategyCandidate(PreparedQuestion):
    id:str=Field(pattern=r"^bq-[0-9a-f]{64}$")


class InterviewStrategyPlan(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    schema_version:Literal[1]=1
    plan_revision:int=Field(ge=1)
    project_id:str
    based_on_sequence:int=Field(ge=1)
    source_id:str
    source_version:int=Field(ge=1)
    source_revision:int=Field(ge=1)
    policy_epoch:int=Field(ge=1)
    preference_revision:int=Field(ge=0)
    execution_generation:int=Field(ge=1)
    phase_revision:int=Field(ge=0)
    snapshot_id:str
    checkpoint_id:str|None
    strategy:Strategy
    objective:str
    focus_event_ids:list[str]=Field(max_length=8)
    candidates:list[StrategyCandidate]=Field(max_length=5)
    background_lag_ms:int=Field(ge=0)


class ImmediateSelection(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    acknowledgement:str=Field(min_length=1,max_length=2000)
    question:str|None=Field(max_length=800)
    selected_candidate_id:str|None=Field(max_length=128)
    selection_reason:SelectionReason
    used_strategy:Strategy
    work:TurnWorkPlan
    associations:list[PhotoAssociation]=Field(max_length=20)
    response_photo_ids:list[str]=Field(max_length=5)
    stopped:bool
    question_evidence:EvidenceRef|None=Field(default=None, description=(
        'Exact current narrator passage the immediate question refers to; null offsets are allowed for a unique quote. '
        'Distinguish separate groups within one message; for a queued candidate its recorded evidence is retained. '
        'Null only for a question without referenced narrator evidence.'))
    resolved_questions:list[QuestionResolution]=Field(default_factory=list,max_length=5)


def strategy_enabled():
    return os.getenv('MEMOIR_INTERVIEW_STRATEGY','').lower() in {'1','true','yes'}


STRATEGY_MODULES = frozenset({'comfort', 'explore', 'shape'})


def stage_breadth_checkpoint(coverage):
    """Three distinct grounded events permit an invitation, never completion."""
    stages = {row['life_stage']: row for row in coverage or [] if row['life_stage'] in LIFE_STAGES
              and row['grounded_events'] > 0}
    if not stages:
        return None
    current = max(stages, key=lambda stage: (stages[stage]['last_source_sequence'], LIFE_STAGES.index(stage)))
    if stages[current]['grounded_events'] < 3:
        return None
    other_stages = LIFE_STAGES[LIFE_STAGES.index(current) + 1:] + LIFE_STAGES[:LIFE_STAGES.index(current)]
    next_stage = next((stage for stage in other_stages
                       if stages.get(stage, {}).get('grounded_events', 0) < 3), None)
    if next_stage is None:
        return None
    return dict(current_stage=current, suggested_stage=next_stage,
                grounded_events=stages[current]['grounded_events'], minimum_grounded_events=3)


def strategy_instructions(strategy):
    if strategy not in STRATEGY_MODULES:
        raise ValueError('Unknown internal strategy')
    return render_prompt_artifact(prompt_path(f'memoir/skills/memoir-interviewer/strategy/{strategy}'))

def selector_schema(context=None):
    schema=ImmediateSelection.model_json_schema()
    schema['required']=list(schema['properties'])
    for prop in schema['properties'].values():prop.pop('default',None)
    schema['properties']['acknowledgement']['pattern']='^[^?？]*$'
    context=context or {}
    constraints=current_constraints((context.get('source') or {}).get('text',''))
    candidates=((context.get('strategy_context') or {}).get('plan') or {}).get('candidates',[])
    confirmation = pending_confirmation(context)
    if confirmation:
        candidates = [confirmation, *candidates]
    identities=[] if constraints else list(dict.fromkeys(candidate['id'] for candidate in candidates))
    schema['properties']['selected_candidate_id']['enum']=[None,*identities]
    schema['properties']['question']['description']=(
        'One immediate question, or null. Null requires selection_reason pause or direct_answer '
        'and selected_candidate_id null.')
    schema['properties']['selection_reason']['description']=(
        'Use pause or direct_answer only when question is null. A direct acknowledgement of a narrator '
        'instruction without a follow-up uses direct_answer. Prepared/adapted requires a current candidate ID.')
    if not identities:
        schema['properties']['selection_reason']['enum']=[reason for reason in
            schema['properties']['selection_reason']['enum'] if reason not in {'prepared_candidate','adapted_candidate'}]
    if constraints.get('no_question'):
        schema['properties']['question']={'type':'null'}
        schema['properties']['selection_reason']['enum']=['pause']
    elif constraints.get('override') and not direct_question(context):
        # Literal intent matching cannot enumerate every natural request to stop.
        schema['properties']['selection_reason']['enum']=[constraints['override'], 'pause']
    return question_evidence_schema(resolution_schema(schema, context))


def direct_question(context):
    return bool(re.search(r'[?？]', _direct_narrator_text((context.get('source') or {}).get('text', ''))))


def _direct_narrator_text(text):
    # Bound reported speech to its own clause. Mask whole quotes first, keeping
    # a sentence boundary so later direct narrator requests remain authoritative.
    from .conversation_attribution import QUOTED_SENTENCE_PATTERN,QUOTED_PATTERN,ATTRIBUTION_PATTERN
    value=re.sub(QUOTED_SENTENCE_PATTERN,' [quoted]. ',text or '')
    value=re.sub(QUOTED_PATTERN,' [quoted] ',value)
    direct=[];reported_continuation=False
    for part in re.finditer(r'([^.!?。！？;；,，\r\n]+)([.!?。！？;；,，\r\n]*|$)',value):
        clause=part.group(1).strip();boundary=part.group(2)
        if not clause:continue
        if reported_continuation:
            if re.search(r'[.!?。！？;；]',boundary) or '[quoted]' in clause:reported_continuation=False
            continue
        # "我说错了" is an explicit narrator correction, not attribution to
        # another speaker. Do not promote "他说错了" or a quoted correction.
        correction=bool(re.match(r'^(?:刚才|剛才|刚刚|剛剛|之前)?我(?:说|說)错',clause))
        attributed=list(re.finditer(ATTRIBUTION_PATTERN,clause,re.I))
        if attributed and not correction:
            tail=clause[attributed[-1].end():].strip().strip(':：')
            # A bare report introduction can include its indirect object. It
            # continues through comma-separated speech until a strong boundary.
            introduction=not tail or bool(re.fullmatch(r'(?:me|us|him|her|them|you|我|我们|我們|对我|對我)',tail,re.I))
            reported_continuation=introduction
            # A complete sentence closes an unquoted reported clause. An
            # introduction followed only by a newline continues to the next one.
            if re.search(r'[.!?。！？;；]',boundary):reported_continuation=False
            continue
        direct.append(clause + boundary)
    return '\n'.join(direct)


def current_constraints(text):
    value = _direct_narrator_text(text)
    if re.search(r'\b(?:not today|stop here|pause here|finished today)\b|今天不聊|今天先到这里|先停一停',value,re.I):return {'no_question':True}
    if re.search(r'(?m)^\s*(?:(?:please\s+)?stop(?:\s+(?:now|the interview|asking questions))?|no more questions(?:\s+(?:please|today|for now))?|(?:请|請)?(?:停一下|停止提问|停止提問|不要再问了|不要再問了|别再问了|別再問了))\s*[.!?。！？;；]*\s*$',value,re.I):
        return {'no_question':True}
    if re.search(r"let[’']s (?:talk|discuss)|change (?:the )?(?:subject|topic)|换个话题|想聊",value,re.I):return {'override':'user_redirect'}
    if re.search(r'\b(?:I meant|got that wrong|correction)\b|(?:我(?:说|說)错)|更正',value,re.I):return {'override':'current_correction'}
    if re.search(r'\b(?:lighter question|keep it gentle|take it slowly)\b|轻松|慢慢聊',value,re.I):return {'override':'pacing'}
    return {}


def adapt_selection(raw,context):
    item=ImmediateSelection.model_validate({k:v for k,v in raw.items() if k!='continuity_updates'})
    state=context.get('strategy_context') or {};plan=state.get('plan') or {}
    constraints=current_constraints((context.get('source') or {}).get('text',''))
    available={c['id']:c for c in plan.get('candidates',[])}
    confirmation = pending_confirmation(context)
    if confirmation:
        available[confirmation['id']] = confirmation
    if item.question is not None and (not item.question.strip() or item.question.count('?')+item.question.count('？')>1):
        raise ValueError('Only one immediate question is allowed')
    if item.stopped and item.question is not None:raise ValueError('A stop cannot force a question')
    if item.selection_reason in {'pause','direct_answer'} and item.question is not None:
        raise ValueError('A pause or direct answer requires no question')
    if constraints.get('no_question') and item.question is not None:raise ValueError('Current pause requires no question')
    if constraints.get('override') and not direct_question(context) and not item.stopped:
        if item.question is None or item.selection_reason != constraints['override']:
            raise ValueError('Current intent requires one appropriate follow-up question')
    if item.question is None and item.selection_reason not in {'pause','direct_answer'}:raise ValueError('No-question outcome requires an explicit reason')
    if item.selected_candidate_id is not None:
        if item.selected_candidate_id not in available:raise ValueError('Candidate is stale, asked or outside this project')
        if constraints:raise ValueError('Current intent overrides prepared candidates')
        if item.selection_reason not in {'prepared_candidate','adapted_candidate'}:raise ValueError('Candidate use requires its recorded reason')
        if item.question is None:raise ValueError('No question cannot deliver a candidate')
        if item.selection_reason=='prepared_candidate' and item.question.strip()!=available[item.selected_candidate_id]['question'].strip():
            raise ValueError('Prepared candidate text changed')
    elif item.selection_reason in {'prepared_candidate','adapted_candidate'}:raise ValueError('Candidate identity required')
    candidate_id=item.selected_candidate_id or 'immediate-'+(context.get('source') or {}).get('id','fallback')
    candidates=[] if item.question is None else [{'id':candidate_id,'question':item.question,
        'context':{'event_id':None,'photo_id':None,'life_stage':None,'year':None},'order':0,'bridge':''}]
    if candidates:
        evidence = hint_evidence(available[item.selected_candidate_id], context) if item.selected_candidate_id else item.question_evidence
        if evidence is not None:
            candidates[0]['context']['evidence'] = evidence.model_dump() if hasattr(evidence, 'model_dump') else evidence
    legacy={'acknowledgement':item.acknowledgement,'plan':{'candidates':candidates,
        'chosen_id':candidate_id if candidates else None,'active_event_id':None,'work':item.work.model_dump()},
        'associations':[a.model_dump() for a in item.associations],'response_photo_ids':item.response_photo_ids,
        'stopped':item.question is None,'continuity_updates':raw.get('continuity_updates',[])}
    if item.resolved_questions:
        legacy['plan']['resolved_questions']=[resolution.model_dump() for resolution in item.resolved_questions]
    outcome={'schema_version':1,'plan_revision_seen':plan.get('plan_revision',state.get('invalid_plan_revision')),
        'selected_candidate_id':item.selected_candidate_id,'selection_reason':item.selection_reason,
        'used_strategy':item.used_strategy,'question_delivered':item.question,'work_hint':item.work.mode}
    return legacy,outcome,item.stopped


def validate_proposal(raw,page):
    proposal=StrategyProposal.model_validate(raw)
    allowed={e['id'] for e in page.get('events',[]) if e.get('status')=='active'}
    if len(set(proposal.focus_event_ids))!=len(proposal.focus_event_ids) or set(proposal.focus_event_ids)-allowed:
        raise ValueError('Strategy focus is outside the canonical page')
    if proposal.strategy=='shape' and proposal.objective not in {'clarify_order','clarify_identity','link_stories'}:
        raise ValueError('Internal shape needs a clarification objective')
    return proposal.model_dump()


class StrategyMetrics:
    """Redacted observable timings; no source, question, name, image or reasoning."""
    def __init__(self,turn_id,sequence,context,*,start=None):
        self.start=time.monotonic() if start is None else start;self.turn_id=turn_id;self.sequence=sequence;self.first_text=None
        state=context.get('strategy_context') or {};self.plan=state.get('plan') or {}
    def elapsed(self):return round((time.monotonic()-self.start)*1000,3)
    def text(self):
        if self.first_text is None:self.first_text=round((time.monotonic()-self.start)*1000,3)
    def record(self,outcome,**timings):
        data={'event':'interview_strategy_outcome','client_turn_id':self.turn_id,'source_sequence':self.sequence,
            'plan_revision_seen':outcome['plan_revision_seen'],'planned_strategy':self.plan.get('strategy'),
            'used_strategy':outcome['used_strategy'],
            'selection_reason':outcome['selection_reason'],'correction':outcome['selection_reason']=='current_correction',
            'override':outcome['used_strategy']!=self.plan.get('strategy') if self.plan else False,'candidate_used':outcome['selected_candidate_id'] is not None,
            'plan_age_turns':max(0,self.sequence-self.plan['based_on_sequence']) if self.plan else None,
            'time_to_first_meaningful_text_ms':self.first_text,'background_lag_ms':self.plan.get('background_lag_ms'),
            'actual_usage':None,'actual_cost':None,'time_to_first_audio_ms':None,'full_question_ms':None,**timings}
        logging.getLogger('memoir.strategy.metrics').info(json.dumps(data,sort_keys=True))
        return data
