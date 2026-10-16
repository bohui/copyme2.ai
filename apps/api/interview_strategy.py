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
from .two_lane_memory import PreparedQuestion

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


def strategy_enabled():
    return os.getenv('MEMOIR_INTERVIEW_STRATEGY','').lower() in {'1','true','yes'}


def legacy_strategy(phase,*,has_narration=False):
    phase=phase or {}
    return {'strategy':phase.get('preferred_phase') or phase.get('phase') or ('explore' if has_narration else 'comfort'),
        'legacy_pacing':phase.get('preferred_phase') if phase.get('selection')=='explicit' else None,
        'legacy_revision':phase.get('revision',0)}


STRATEGY_MODULES={
 'comfort':'Offer low-pressure entry when there is no volunteered story. A concrete first detail can immediately use explore. Short answers alone do not imply discomfort. Do not force a life-history form.',
 'explore':'Follow one unanswered detail in the volunteered story, including a rich first reply. Keep uncertainty and follow redirects or gentler pacing. Never require a turn-count threshold.',
 'shape':'Clarify supported chronology, identities or links in existing stories. Automatic internal shape is allowed. It cannot start an organiser/composer or confer draft, purchase, access, publishing or printing rights.'}


def strategy_instructions(strategy):
    from .collector_prompt import COMPACT_COLLECTOR_PROMPT
    if strategy not in STRATEGY_MODULES:raise ValueError('Unknown internal strategy')
    core=COMPACT_COLLECTOR_PROMPT
    start=core.index('Comfort, explore and shape are soft')
    end=core.index('Conversation is a continuing flow',start)
    core=core[:start]+core[end:]
    core=core.replace('This pass produces the conversational response and private interview plan only.',
        'This pass produces one immediate response/question and one small work hint only.')
    return core+'\nActive internal strategy: '+strategy+'\n'+STRATEGY_MODULES[strategy]+'''
The stored B strategy is a planning hint, not a user preference or permission.
Read the entire latest accepted message first. strategy_context.prior_delivered_question
is the actual asked-question receipt. A saved assistant entry in the raw tail
can be undelivered; it is not proof that a question was asked. Current redirect, correction,
exclusion, lighter pacing, stop or direct question takes priority over a prepared
candidate. You may deviate for this one turn, recording a bounded reason, without
changing the stored plan. Preserve explicit legacy pacing preferences. Resume
returning stories; a correction does not restart onboarding. Do not infer feelings.
Return acknowledgement, zero or one immediate question, selected_candidate_id or
null, selection_reason, used_strategy and work.mode/work.name.
Choose work.mode from the ENTIRE current narrator message. Use "reply_only" only
for a name-only introduction, greeting, farewell or similarly minimal reply with
no new memory details or workspace actions. Use "extract" when the message adds
a birthplace, residence, date, person, activity or event, even in one brief opening
sentence. Corrections, privacy requests and photo discussion also need "extract".
This hint routes background memory/place work; keeping extraction out of this
foreground response does not mean choosing "reply_only" for a story. Do not use
message length, strategy or turn count as an extraction gate. For "reply_only",
set work.name to the exact preferred name stated in the current source, or null
when unknown. For "extract", set work.name=null.
Do not generate a future candidate pool. B owns reusable future planning. No
question is required for a stop or direct answer. Do not claim an unprocessed
upload or unavailable draft is ready. Quoted composition requests and ambiguous
"I'm done" grant no action. Formal composition uses separate application gates.
No private plan, strategy label, tool log or reasoning belongs in visible text.
'''


def selector_schema():
    schema=ImmediateSelection.model_json_schema()
    schema['required']=list(schema['properties'])
    for prop in schema['properties'].values():prop.pop('default',None)
    schema['properties']['acknowledgement']['pattern']='^[^?？]*$'
    return schema


def current_constraints(text):
    # Bound reported speech to its own clause. Mask whole quotes first, keeping
    # a sentence boundary so later direct narrator requests remain authoritative.
    from .conversation_phase import QUOTED_SENTENCE_PATTERN,QUOTED_PATTERN,ATTRIBUTION_PATTERN
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
        direct.append(clause)
    value='\n'.join(direct)
    if re.search(r'\b(?:not today|stop here|pause here|finished today)\b|今天不聊|今天先到这里|先停一停',value,re.I):return {'no_question':True}
    if re.search(r"let[’']s (?:talk|discuss)|change (?:the )?(?:subject|topic)|换个话题|想聊",value,re.I):return {'override':'user_redirect'}
    if re.search(r'\b(?:I meant|got that wrong|correction)\b|(?:我(?:说|說)错)|更正',value,re.I):return {'override':'current_correction'}
    if re.search(r'\b(?:lighter question|keep it gentle|take it slowly)\b|轻松|慢慢聊',value,re.I):return {'override':'pacing'}
    return {}


def adapt_selection(raw,context):
    item=ImmediateSelection.model_validate({k:v for k,v in raw.items() if k!='continuity_updates'})
    state=context.get('strategy_context') or {};plan=state.get('plan') or {}
    constraints=current_constraints((context.get('source') or {}).get('text',''))
    available={c['id']:c for c in plan.get('candidates',[])}
    if item.question is not None and (not item.question.strip() or item.question.count('?')+item.question.count('？')>1):
        raise ValueError('Only one immediate question is allowed')
    if item.stopped and item.question is not None:raise ValueError('A stop cannot force a question')
    if constraints.get('no_question') and item.question is not None:raise ValueError('Current pause requires no question')
    if item.question is None and item.selection_reason not in {'pause','direct_answer'}:raise ValueError('No-question outcome requires an explicit reason')
    if item.selected_candidate_id is not None:
        if item.selected_candidate_id not in available:raise ValueError('Candidate is stale, asked or outside this project')
        if constraints:raise ValueError('Current intent overrides prepared candidates')
        if item.selection_reason not in {'prepared_candidate','adapted_candidate'}:raise ValueError('Candidate use requires its recorded reason')
        if item.question is None:raise ValueError('No question cannot deliver a candidate')
        if item.selection_reason=='prepared_candidate' and item.question!=available[item.selected_candidate_id]['question']:
            raise ValueError('Prepared candidate text changed')
    elif item.selection_reason in {'prepared_candidate','adapted_candidate'}:raise ValueError('Candidate identity required')
    candidate_id=item.selected_candidate_id or 'immediate-'+(context.get('source') or {}).get('id','fallback')
    candidates=[] if item.question is None else [{'id':candidate_id,'question':item.question,
        'context':{'event_id':None,'photo_id':None,'life_stage':None,'year':None},'order':0,'bridge':''}]
    legacy={'acknowledgement':item.acknowledgement,'plan':{'candidates':candidates,
        'chosen_id':candidate_id if candidates else None,'active_event_id':None,'work':item.work.model_dump(),'conversation_phase':None},
        'associations':[a.model_dump() for a in item.associations],'response_photo_ids':item.response_photo_ids,
        'stopped':item.question is None,'continuity_updates':raw.get('continuity_updates',[])}
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
