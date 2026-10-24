"""Fresh bounded composer/timeline execution and atomic request admission.

A lane page is a disposable projection of one canonical partition. PostgreSQL
locks bind its immutable snapshot/page digest through actual HTTP body delivery.
Downstream provider timing is opaque; admitted work is in flight, and result commits must independently revalidate the same lane token.
"""
from __future__ import annotations

from .model_request import instruction_manifest, manifest_metadata
from .llm_tracing import trace_llm_call

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import hashlib
import re
import os
from typing import Any, Literal
from uuid import UUID, uuid4
from urllib.parse import urlsplit

import anyio
import httpx
from pydantic import Field, model_validator

from .prompt_artifact import load_prompt_artifact, prompt_path
from .prompt_composition import render_prompt_artifact
from .issue14_execution_admission import check_issue14_dispatch
from .lifetime_memory_context import serialize_packet
from .lifetime_memory_contracts import Contract, ContextBudget, PinnedContinuity
from .lifetime_memory_publication import PublicationUnavailable

# The configured memoir alias routes to the same byte-token model as the
# already supported pooled aliases; effort routing does not change token bounds.
SUPPORTED_LANE_MODELS = frozenset({'gpt-5.6-luna-pooled', 'legal2ai-luna-low',
    'memoir-luna-low', 'synthetic-byte-bpe'})
EXTRACTION_WINDOW_CONTRACT = load_prompt_artifact(prompt_path('memoir/skills/memoir-author-timeline/window'))
EXTRACTION_REJECTION_REASONS = {
    'Unsupported life stage': 'LIFE_STAGE',
    'Canonical event revision conflict': 'EVENT_REVISION',
    'Ambiguous identity must remain unresolved': 'AMBIGUOUS_IDENTITY',
    'A new event has no expected revision': 'NEW_EVENT_REVISION',
    'Unresolved candidates must be canonical scoped identities': 'CANDIDATE_SCOPE',
    'Chronology requires a canonical scoped target': 'CHRONOLOGY_SCOPE',
    'Explicit correction must cite the current original statement': 'CORRECTION_SCOPE',
    'Correction requires timeline placement fields': 'CORRECTION_SCOPE',
    'Evidence must match an authorised original source version': 'EVIDENCE_SOURCE',
    'Evidence span must match the original words': 'EVIDENCE_SPAN',
    'Stage placement requires evidence': 'STAGE_EVIDENCE',
    'Person identities are unavailable in this bounded source page': 'PERSON_SCOPE',
    'A supported year requires a date evidence basis': 'DATE_BASIS',
    'Date ranges must retain their original direction': 'DATE_RANGE',
    'Numeric date requires supported original evidence': 'DATE_NUMERIC',
    'The original date expression must be retained in its evidence': 'DATE_EXPRESSION',
    'Evidence outside the claimed source page': 'PAGE_SOURCE',
    'Evidence requires both exact offsets or neither': 'PAGE_OFFSETS',
    'An ambiguous occurrence requires exact offsets': 'PAGE_AMBIGUOUS',
    'Attribution requires an exact unambiguous span': 'PAGE_AMBIGUOUS',
    'Evidence span exceeds claimed source page': 'PAGE_SPAN',
    'Evidence quote outside claimed source page': 'PAGE_QUOTE',
    'Whole-source policy authority changed': 'POLICY_SOURCE',
}


class LaneGenerationPaused(PublicationUnavailable):
    code = 'LIFETIME_GENERATION_PAUSED'
    retryable = True


def check_lane_generation():
    from .lifetime_memory_runtime import lifetime_generation_paused
    if lifetime_generation_paused():
        raise LaneGenerationPaused('Bounded lifetime generation is paused; retry later')


@asynccontextmanager
async def _admission(publisher, fence):
    check_lane_generation()
    async with publisher.guard(fence):
        check_lane_generation()
        yield


class LaneArtifact(Contract):
    phase: Literal['prepare', 'draft', 'review', 'extract']
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class EditorialPreview(Contract):
    title: str = Field(max_length=1000)
    text: str = Field(max_length=12000)


class EditorialRequest(Contract):
    request_id: UUID
    instruction: str = Field(min_length=1, max_length=1000)
    original_preview: EditorialPreview


class TwoLaneFence(Contract):
    task_version: Literal['two-lane-v1']
    execution_generation: int = Field(ge=1, strict=True)
    phase_revision: int = Field(ge=0, strict=True)
    work_mode: Literal['extract','reply_only','pending']
    strategy_mode: Literal['shadow','active'] | None = None
    strategy_revision: int = Field(default=0,ge=0,strict=True)
    reply_contract: Literal['reply-v2'] | None = Field(default=None, exclude_if=lambda value: value is None)


class AttributionContext(Contract):
    decision: Literal['extract', 'non_story', 'unresolved', 'withheld']
    reason: Literal['new_testimony', 'conversation_control', 'profile_introduction', 'ambiguous_context', 'privacy_withheld']
    delivered_event: dict[str, Any] | None = None
    recent_dialogue: list[dict[str, Any]] | None = Field(default=None, max_length=8,
        exclude_if=lambda value: value is None)


class MemorySummaryFence(Contract):
    maintenance_id:UUID
    revision:int=Field(ge=0,strict=True)
    through_sequence:int=Field(ge=1,strict=True)
    sequence:int=Field(ge=1,strict=True)
    char_start:int=Field(ge=0,strict=True)
    char_end:int=Field(ge=0,strict=True)
    status:Literal['active','tombstone']
    work_mode:Literal['extract','reply_only']
    prior:dict[str,Any]


class LaneFence(Contract):
    protocol: Literal['lifetime_composer_pages'] = 'lifetime_composer_pages'
    lane_id: UUID
    token: UUID
    snapshot_id: UUID
    user_id: UUID
    project_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    conversation_id: UUID
    skill: Literal['timeline', 'composer']
    locale: Literal['en-AU', 'zh-CN']
    policy_epoch: int = Field(ge=1, strict=True)
    preference_revision: int = Field(ge=0, strict=True)
    source_high_water: int = Field(ge=0, strict=True)
    event_high_water: int = Field(ge=0, strict=True)
    page_number: int = Field(ge=0, strict=True)
    root_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    page_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    input_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    preferences: PinnedContinuity
    source: dict[str, Any] | None
    events: list[dict[str, Any]] = Field(max_length=8)
    partition: dict[str, Any] | None
    batch: dict[str, Any] | None = None
    coverage_round: int = Field(ge=0, strict=True)
    base_revision: int = Field(default=0, ge=0, strict=True)
    editorial_request: EditorialRequest | None = None
    two_lane: TwoLaneFence | None = None
    memory_summary:MemorySummaryFence|None=Field(default=None,exclude_if=lambda value:value is None)
    profile_context:dict[str,Any]|None=Field(default=None,exclude_if=lambda value:value is None)
    attribution_context:AttributionContext|None=Field(default=None,exclude_if=lambda value:value is None)
    attribution_coverage:dict[str,Any]|None=Field(default=None,exclude_if=lambda value:value is None)
    prior_outputs: list[LaneArtifact] = Field(default_factory=list, max_length=16)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate lane packet key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Non-finite lane packet data')


def _object(value):
    try:
        parsed = json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError):
        raise ValueError('Invalid bounded lane packet') from None
    if not isinstance(parsed, dict):
        raise ValueError('A bounded lane packet must be an object')
    return parsed


def lane_contract(phase, locale, *, batch=False, two_lane=False, strategy=False, fence=None):
    """Use server code, never client-supplied instructions or output schemas."""
    if phase == 'profile':
        from .background_profile import profile_contract
        return profile_contract(fence)
    if phase == 'summarize':
        from .lifetime_memory_summary import summary_contract
        return summary_contract(fence)
    if phase == 'extract':
        if two_lane:
            from .two_lane_memory import extraction_contract
            instructions,schema=extraction_contract(strategy=strategy, attribution=bool(fence and fence.attribution_context),
                continuity=bool(fence and fence.two_lane and fence.two_lane.reply_contract == 'reply-v2'),
                source=fence.source if fence else None)
        else:
            from .memory_events import extraction_instructions, extraction_schema
            instructions, schema = extraction_instructions(), extraction_schema()
    else:
        from .memoir_preview import composer_instructions, composer_output_schema
        instructions, schema = composer_instructions(phase), composer_output_schema(phase)
    if phase == 'extract' and fence is not None:
        from .stage_readiness import LIFE_STAGES
        evidence=schema['$defs']['EvidenceRef']['properties']
        evidence['source_id']['enum']=[fence.source['id']]
        evidence['version']['enum']=[fence.source['version']]
        identities=sorted({event['id'] for event in fence.events})
        event=schema['$defs']['EventProposal']['properties']
        event['id']={'type':'null'}
        event['existing_id']={'type':['string','null'],'enum':[None,*identities]}
        event['life_stage']={'type':['string','null'],'enum':[None,'unplaced',*LIFE_STAGES]}
        for field in ('person_ids','candidate_ids','relations'):
            for option in event[field]['anyOf']:
                if option.get('type')=='array':
                    if field=='person_ids' or not identities:option['maxItems']=0
                    elif field=='candidate_ids':option['items']['enum']=identities
        if identities:schema['$defs']['EventRelation']['properties']['event_id']['enum']=identities
    if phase == 'draft' and fence is not None:
        references = [ref for event in fence.batch['events'] for ref in event['source_refs']] if fence.batch is not None else [
            {'source_id':fence.source['id'],'version':fence.source['version'],
             'char_start':fence.source['char_start'],'char_end':fence.source['char_end']}] if fence.source else []
        choices=[]
        for identity in sorted({(ref['source_id'],str(ref['version']),ref['char_start'],ref['char_end']) for ref in references}):
            choice=deepcopy(schema['$defs']['ref'])
            for key,value in zip(('source_id','version','char_start','char_end'),identity):
                choice['properties'][key].update(type='integer' if key.startswith('char_') else 'string',enum=[value])
            choices.append(choice)
        if choices:
            schema['$defs']['ref']={'anyOf':choices}
    if batch:
        if phase == 'prepare':
            instructions += load_prompt_artifact(prompt_path('memoir/skills/memoir-composer/batch/prepare'))
        else:
            instructions += load_prompt_artifact(prompt_path('memoir/skills/memoir-composer/batch/compose'))
    locale_name = 'zh-CN' if locale == 'zh-CN' else 'en-AU'
    instructions += render_prompt_artifact(prompt_path(f'memoir/shared/bounded-context/{locale_name}'))
    if fence and fence.attribution_coverage:
        instructions += load_prompt_artifact(prompt_path('memoir/shared/place-conflicts'))
    return instructions, schema


class BoundedLaneInput(Contract):
    fence: LaneFence
    budget: ContextBudget
    prompt_version: Literal['lifetime-lane-v1'] = 'lifetime-lane-v1'
    phase: Literal['extract', 'summarize', 'profile', 'prepare', 'draft', 'review']
    packet: str = Field(min_length=1, max_length=10_000_000)

    @model_validator(mode='after')
    def validate_transport(self):
        if (self.fence.skill == 'timeline') != (self.phase in {'extract','summarize','profile'}):
            raise ValueError('Bounded lane phase does not match skill')
        maximum_input = 98304 if self.phase in {'prepare', 'draft', 'review'} else 65536
        if (self.budget.context_window > 131072 or self.budget.input_budget > maximum_input
                or self.budget.framing_headroom < 2048):
            raise ValueError('Bounded lane budget exceeds the reviewed transport limits')
        if self.budget.model not in SUPPORTED_LANE_MODELS:
            raise ValueError('No reviewed byte-token bound for lane model')
        packet = _object(self.packet)
        if serialize_packet(packet) != self.packet or set(packet) != {'lane_context', 'payload'}:
            raise ValueError('Bounded lane packet must use the canonical context envelope')
        if not isinstance(packet['payload'], dict):
            raise ValueError('Invalid bounded lane payload')
        context = packet['lane_context']
        expected = _lane_context(self.fence, context.get('preferences') if isinstance(context, dict) else None)
        if context != expected:
            raise ValueError('Bounded lane context differs from its immutable fence')
        _validate_phase_packet(self.fence,self.phase,packet['payload'])
        if lane_request_tokens(self) > self.budget.input_budget:
            raise ValueError('Bounded lane instructions, packet, schema and framing exceed budget')
        return self


def _lane_context(fence, preferences):
    if not isinstance(preferences,dict) or preferences.get('privacy_complete') is not True:
        raise ValueError('Bounded lane privacy policy is incomplete')
    try:
        pins = PinnedContinuity.model_validate(preferences)
    except ValueError:
        raise ValueError('Bounded lane requires current typed preferences') from None
    if pins != fence.preferences or pins.preference_revision != fence.preference_revision:
        raise ValueError('Bounded lane preferences differ from the authoritative fence')
    privacy = {key:preferences.get(key,[]) for key in ('paused_topics','excluded_topics','unresolved_references')}
    if (len(serialize_packet(privacy).encode('utf-8')) > 16384
            or len(serialize_packet(preferences.get('known_continuity',[])).encode('utf-8')) > 8192
            or len(serialize_packet(preferences).encode('utf-8')) > 32768):
        raise ValueError('Bounded lane preferences exceed the policy resource budget')
    return {'schema_version':1, 'snapshot_id':str(fence.snapshot_id), 'page_number':fence.page_number,
        'page_digest':fence.page_digest, 'policy_epoch':fence.policy_epoch,
        'preference_revision':fence.preference_revision, 'preferences':preferences,
        'coverage_scope':'bounded_partition', 'complete':False}



def lane_artifact_digest(phase, value):
    """Bind derived prose, allowing only the host's deterministic metadata pins."""
    from .memoir_preview import normalize_composer_refs, normalize_canonical_actions, normalize_canonical_event_dispositions
    value = normalize_composer_refs(deepcopy(_object(value) if isinstance(value,str) else value))
    if not isinstance(value,dict):
        raise ValueError('A lane artifact must be a JSON object')
    if phase == 'draft':
        normalize_canonical_actions(value)
        normalize_canonical_event_dispositions(value)
        for key in ('input_snapshot_id','input_fingerprint','expected_manuscript_revision','counter'):
            value.pop(key,None)
    return hashlib.sha256(serialize_packet(value).encode('utf-8')).hexdigest()


def _required_artifacts(phase, payload):
    if not isinstance(payload, dict):
        raise ValueError('A bounded lane payload must be an object')
    request = payload.get('request', {})
    if not isinstance(request, dict) or not isinstance(request.get('context', {}), dict):
        raise ValueError('Invalid canonical lane context')
    prepared = request.get('context', {}).get('prepared_partitions', [])
    if not isinstance(prepared, list) or len(prepared) > 8:
        raise ValueError('Invalid prepared lane artifact list')
    values = [('prepare', value) for value in prepared]
    for key, kind in (('candidate', 'draft'), ('review', 'review')):
        if phase in {'draft', 'review'} and payload.get(key) is not None:
            values.append((kind, payload[key]))
    result = []
    for kind, value in values:
        ref = LaneArtifact(phase=kind, digest=lane_artifact_digest(kind, value))
        if ref not in result:
            result.append(ref)
    return result


def lane_extraction_packet(fence):
    return {'schema_version':1,'sources':[deepcopy(fence.source)],'events':deepcopy(fence.events),
        'interview_context':fence.attribution_context.model_dump(mode='json') if fence.attribution_context else {},
        'preferences':fence.preferences.model_dump(mode='json'),
        'coverage':{'scope':'source_window','snapshot_id':str(fence.snapshot_id),
            'source_high_water':fence.source_high_water,'complete':False},
        'window_contract':EXTRACTION_WINDOW_CONTRACT}


def canonical_lane_request(fence):
    from .canonical_composer import composer_request
    if fence.batch is not None:
        from .progressive_composer import batch_job
        from .canonical_composer import composition_request
        request, _ = composition_request(batch_job(fence.model_dump(mode='json')))
        request['context']['prepared_partitions'] = []
        return request
    if not fence.source or not fence.partition or fence.partition.get('status')!='active':
        raise ValueError('Composer page lacks authoritative active evidence')
    source,event=deepcopy(fence.source),deepcopy(fence.partition)
    job={**fence.model_dump(mode='json'),'governed_page':True,'sources':[source],'events':[event],
        'source_manifest':[{'id':source['id'],'version':source['version']}],
        'event_manifest':[{'id':event['id'],'revision':event['revision']}],
        'previous':None,'base_revision':0,'source_windows':{source['id']:{
            'char_start':source['char_start'],'char_end':source['char_end'],'original_length':source['original_length']}}}
    request=composer_request(job)
    request['context'].update(projection_invalidated_chapter_ids=[],preserved_sections=[],prepared_partitions=[])
    return request


def _validate_phase_packet(fence,phase,payload):
    if phase == 'profile':
        from .background_profile import RETRY_CODES, profile_packet
        if fence.memory_summary is not None or fence.batch is not None or fence.prior_outputs:
            raise ValueError('Profile requires its canonical source page')
        actual = deepcopy(payload)
        if 'retry_reason' in actual and actual.pop('retry_reason') not in RETRY_CODES:
            raise ValueError('Unsupported profile retry reason')
        if actual != profile_packet(fence):
            raise ValueError('Profile payload differs from authoritative page evidence')
        return
    if fence.profile_context is not None:
        raise ValueError('Profile window cannot run another lane phase')
    if phase=='summarize':
        from .lifetime_memory_summary import SUMMARY_RETRY_CODES,SummaryProposal,summary_packet
        if fence.memory_summary is None or fence.batch is not None or fence.prior_outputs:
            raise ValueError('Summary requires its canonical compaction page')
        SummaryProposal.model_validate(fence.memory_summary.prior)
        state=fence.memory_summary;source=fence.source
        if state.through_sequence!=fence.source_high_water-1 or state.sequence>state.through_sequence:
            raise ValueError('Summary window exceeds its covered snapshot')
        if state.status=='active':
            if (not isinstance(source,dict) or source.get('project_id')!=fence.project_id or source.get('status')!='active'
                or source.get('kind') not in {'narrator_chat','narrator_transcript'}
                or not isinstance(source.get('text'),str) or not 0<len(source['text'])<=2000
                or source.get('sequence')!=state.sequence or source.get('char_start')!=state.char_start
                or source.get('char_end')!=state.char_end or state.char_end-state.char_start!=len(source['text'])
                or type(source.get('original_length')) is not int or not state.char_end<=source['original_length']<=100000):
                raise ValueError('Invalid bounded summary source window')
        elif source is not None or state.work_mode!='reply_only':
            raise ValueError('A tombstone cannot supply narrator text')
        actual=deepcopy(payload)
        if 'retry_reason' in actual:
            reason=actual.pop('retry_reason')
            if not isinstance(reason,str) or reason not in SUMMARY_RETRY_CODES:
                raise ValueError('Unsupported summary retry reason')
        if actual!=summary_packet(fence.model_dump(mode='json')):
            raise ValueError('Summary payload differs from its canonical window')
        return
    if fence.memory_summary is not None:
        raise ValueError('Semantic window cannot run another lane phase')
    if fence.batch is not None:
        from .progressive_composer import summary_packet, validate_batch, validate_summary
        validate_batch(fence.batch, fence.project_id)
        if fence.skill != 'composer' or phase == 'extract':
            raise ValueError('Progressive batches are background composition only')
        if phase == 'prepare':
            if (not isinstance(payload.get('preparation_id'), str)
                or re.fullmatch('[a-f0-9]{64}', payload['preparation_id']) is None
                or payload != summary_packet(fence.model_dump(mode='json'), payload.get('preparation_id'))):
                raise ValueError('Summary packet differs from the new original messages')
        else:
            expected = canonical_lane_request(fence)
            actual = payload.get('request')
            if not isinstance(actual, dict):
                raise ValueError('Progressive phase requires its canonical request')
            prepared = actual.get('context', {}).get('prepared_partitions', [])
            if len(prepared) != int(bool(fence.batch['new_messages'])):
                raise ValueError('A new message batch requires its grounded summary')
            for value in prepared:
                validate_summary(value, fence.model_dump(mode='json'))
            expected['context']['prepared_partitions'] = deepcopy(prepared)
            # Stored unchanged sections and configuration invalidations are computed
            # by the shared composer, not supplied by the model.
            from .memoir_preview import incremental_model_request
            if actual != expected and actual != incremental_model_request(expected):
                raise ValueError('Progressive request differs from its authoritative batch')
            if phase == 'draft' and (set(payload) - {'request', 'plan', 'candidate', 'validation', 'review'} or not isinstance(payload.get('plan'), dict)):
                raise ValueError('Unsupported progressive draft context')
            if phase == 'review' and set(payload) != {'request', 'candidate', 'validation'}:
                raise ValueError('Unsupported progressive review context')
        if fence.prior_outputs != _required_artifacts(phase, payload):
            raise ValueError('Progressive bytes lack their same-batch artifact proofs')
        return
    if not isinstance(fence.source,dict) or len(serialize_packet({
            'source':fence.source,'events':fence.events,'partition':fence.partition}).encode('utf-8'))>45000:
        raise ValueError('Invalid bounded authoritative lane evidence scope')
    source=fence.source
    if (source.get('project_id')!=fence.project_id or source.get('status')!='active'
            or source.get('kind') not in {'narrator_chat','narrator_transcript'}
            or not isinstance(source.get('text'),str) or not 0<len(source['text'])<=2304
            or type(source.get('char_start')) is not int or source['char_start']<0
            or source.get('char_end')!=source['char_start']+len(source['text'])):
        raise ValueError('Invalid canonical source window')
    if phase=='extract':
        if 'retry_reason' in payload and (not isinstance(payload['retry_reason'],str)
                or payload['retry_reason'] not in {*EXTRACTION_REJECTION_REASONS.values(),'OUTPUT_SCHEMA'}):
            raise ValueError('Unsupported extraction retry reason')
        if {key:value for key,value in payload.items() if key!='retry_reason'}!=lane_extraction_packet(fence):
            raise ValueError('Extraction payload differs from authoritative page evidence')
    elif phase=='prepare':
        if (set(payload)!={'preparation_id','partition','sources'}
                or not isinstance(payload['preparation_id'],str)
                or re.fullmatch('[a-f0-9]{64}',payload['preparation_id']) is None
                or payload['partition']!=fence.partition or payload['sources']!=[fence.source]):
            raise ValueError('Preparation payload differs from authoritative page evidence')
    else:
        expected=canonical_lane_request(fence)
        actual=payload.get('request')
        if not isinstance(actual,dict):raise ValueError('Canonical phase request is required')
        context=actual.get('context')
        if not isinstance(context,dict):raise ValueError('Invalid canonical lane context')
        prepared=context.get('prepared_partitions',[])
        if not isinstance(prepared,list) or len(prepared)>8:raise ValueError('Invalid prepared lane artifact list')
        from .memory_events import EvidenceRef
        expected_refs = [EvidenceRef.model_validate(ref).model_dump(exclude_none=True)
            for ref in fence.partition.get('source_refs',[])]
        for item in prepared:
            if (not isinstance(item,dict) or set(item)!={'event_id','context','source_refs'}
                    or item['event_id']!=fence.partition['id'] or not isinstance(item['context'],str)
                    or len(item['context'])>10000 or not isinstance(item['source_refs'],list)
                    or [EvidenceRef.model_validate(ref).model_dump(exclude_none=True) for ref in item['source_refs']]!=expected_refs):
                raise ValueError('Prepared artifact has unsupported page evidence')
        expected['context']['prepared_partitions']=deepcopy(prepared)
        if actual!=expected:
            raise ValueError('Composer request differs from authoritative page evidence')
        if phase=='draft':
            if set(payload)-{'request','plan','candidate','validation','review'} or not isinstance(payload.get('plan'),dict):
                raise ValueError('Unsupported draft phase context')
        elif phase=='review' and set(payload)!={'request','candidate','validation'}:
            raise ValueError('Unsupported review phase context')
    if fence.prior_outputs!=_required_artifacts(phase,payload):
        raise ValueError('Derived lane bytes lack their exact same-page artifact proofs')


async def validate_lane_payload(bounded):
    """Recompute static host plan/errors; arbitrary free-form context is rejected."""
    if bounded.phase not in {'draft','review'}:return
    from .memoir_preview import skill_operation
    from .canonical_composer import validate_canonical_candidate
    payload=_object(bounded.packet)['payload'];request=payload['request']
    if bounded.fence.batch is not None:
        request = canonical_lane_request(bounded.fence)
        request['context']['prepared_partitions'] = deepcopy(payload['request']['context'].get('prepared_partitions', []))
    plan=await skill_operation('plan',request)
    if bounded.phase=='draft' and payload['plan']!=plan:
        raise ValueError('Draft plan differs from the canonical page plan')
    candidate=payload.get('candidate')
    if candidate is None:
        if bounded.phase=='review':raise ValueError('Review requires a same-page candidate')
        if payload.get('validation') is not None or payload.get('review') is not None:
            raise ValueError('Repair context requires its same-page candidate')
        return
    pins={'input_snapshot_id':request['snapshot']['id'],'input_fingerprint':plan.get('input_fingerprint'),
        'expected_manuscript_revision':request['prior_state']['revision'],'counter':plan.get('counter')}
    if any(key in candidate and candidate[key]!=value for key,value in pins.items()):
        raise ValueError('Candidate metadata differs from the canonical page plan')
    validation=await validate_canonical_candidate(request,candidate)
    if payload.get('validation')!=validation:
        raise ValueError('Candidate validation differs from the canonical page proof')

def lane_request_tokens(bounded_lane: BoundedLaneInput) -> int:
    instructions, schema = lane_contract(bounded_lane.phase, bounded_lane.fence.locale, batch=bounded_lane.fence.batch is not None, two_lane=bounded_lane.fence.two_lane is not None, strategy=bool(bounded_lane.fence.two_lane and bounded_lane.fence.two_lane.strategy_mode), fence=bounded_lane.fence)
    return (bounded_lane.budget.count(instructions) + bounded_lane.budget.count(bounded_lane.packet)
        + bounded_lane.budget.count(serialize_packet(schema)) + bounded_lane.budget.framing_headroom)


def build_bounded_lane_input(page, *, phase, packet, budget):
    if page.get('complete') is not False:
        raise ValueError('A completed lane page cannot start new model work')
    fence = LaneFence.model_validate({key:page[key] for key in LaneFence.model_fields if key in page})
    payload = _object(packet) if isinstance(packet, str) else deepcopy(packet)
    if not isinstance(payload, dict):
        raise ValueError('A bounded lane payload must be an object')
    proofs = _required_artifacts(phase,payload)
    fence = fence.model_copy(update={'prior_outputs':proofs})
    return BoundedLaneInput(fence=fence, budget=budget, phase=phase,
        packet=serialize_packet({'lane_context':_lane_context(fence,deepcopy(page.get('preferences'))),
            'payload':payload}))


def _validated(value, model=None):
    # Revalidate model_copy() and nested mutation at each actual transport seam.
    bounded = BoundedLaneInput.model_validate(value.model_dump(mode='json'))
    if model is not None and model != bounded.budget.model:
        raise ValueError('Configured lane model differs from the bounded budget')
    return bounded


async def _settle(task):
    with anyio.CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()


class LanePublication:
    def __init__(self, dsn, *, authenticated_owner, send_timeout=2.0, lock_timeout=5.0):
        if not dsn:
            raise PublicationUnavailable('Bounded lane admission requires a transactional database connection')
        if not 0 < send_timeout <= 5 or not 0 < lock_timeout <= 5:
            raise ValueError('Invalid bounded lane admission timeout')
        self._dsn = dsn
        self.owner = UUID(str(authenticated_owner))
        self.send_timeout = send_timeout
        self.lock_timeout = lock_timeout

    @asynccontextmanager
    async def guard(self, fence):
        snapshot = LaneFence.model_validate(fence).model_dump(mode='json')
        if snapshot['user_id'] != str(self.owner):
            raise PublicationUnavailable('Bounded lane admission owner mismatch')
        from psycopg import AsyncConnection, Error
        from psycopg.types.json import Jsonb
        connection = None
        try:
            try:
                async with asyncio.timeout(self.lock_timeout):
                    connection = await AsyncConnection.connect(self._dsn,connect_timeout=2)
                    await connection.execute('set local role authenticated')
                    await connection.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(self.owner),))
                    await connection.execute("select set_config('lock_timeout',%s,true)",(f'{int(self.lock_timeout*1000)}ms',))
                    lease_started = asyncio.get_running_loop().time()
                    result = await connection.execute('select public.lock_lifetime_memoir_lane_publication(%s)',(Jsonb(snapshot),))
                    remaining = float((await result.fetchone())[0])
                    lease_deadline = lease_started + remaining
                    from .lifetime_memory_activation import require_provider_activation
                    await require_provider_activation(connection)
            except TimeoutError:
                from .lifetime_memory_activation import CanonicalActivationUnavailable
                raise CanonicalActivationUnavailable() from None
            except Error as error:
                from .lifetime_memory_policy import PolicyUnavailable, is_policy_pending
                if is_policy_pending(error):
                    raise PolicyUnavailable() from None
                if error.sqlstate == '55P03':
                    from .lifetime_memory_activation import CanonicalActivationUnavailable
                    raise CanonicalActivationUnavailable() from None
                raise PublicationUnavailable('Bounded lane page is unavailable or stale') from error
            allowance = min(self.send_timeout, lease_deadline - asyncio.get_running_loop().time() - .1)
            if allowance <= 0:
                raise PublicationUnavailable('Bounded lane lease expires too soon')
            async with asyncio.timeout(allowance):
                yield
        finally:
            if connection is not None:
                await _settle(asyncio.create_task(connection.close()))


def _publisher(bounded, publisher):
    if publisher is None:
        publisher = LanePublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),
            authenticated_owner=bounded.fence.user_id)
    if not callable(getattr(publisher,'guard',None)):
        raise TypeError('Bounded lane execution requires a publication guard')
    return publisher


class LaneRequestBody:
    """Immutable single-use HTTP body, locked through transport consumption."""
    fence_type = LaneFence

    def __init__(self, content, *, publisher, fence, after_send=None, before_send=None):
        self._content = bytes(content)
        self._fence_json = serialize_packet(self.fence_type.model_validate(fence).model_dump(mode='json'))
        self._publisher = publisher
        self._iterator = None
        self._after_send = after_send
        self._before_send = before_send

    async def _chunks(self):
        content = self._content
        snapshot = json.loads(self._fence_json)
        async with _admission(self._publisher,snapshot):
            if self._before_send:
                self._before_send()
            yield content
        if self._after_send:
            await self._after_send()

    def __aiter__(self):
        if self._iterator is not None:
            raise RuntimeError('Bounded lane bodies cannot be replayed')
        self._iterator = self._chunks()
        return self._iterator

    async def aclose(self):
        if self._iterator is not None:
            await _settle(asyncio.create_task(self._iterator.aclose()))


async def send_bounded_lane_request(*, worker_url, worker_secret, bounded_lane,
        worker_transport=None, publisher=None, timeout=None):
    check_lane_generation()
    bounded = _validated(bounded_lane)
    await validate_lane_payload(bounded)
    if not worker_url or not worker_secret:
        raise PublicationUnavailable('Bounded lane worker is unavailable')
    publisher = _publisher(bounded,publisher)
    payload = {'user_id':str(bounded.fence.user_id), 'project_id':bounded.fence.project_id,
        'agent_role':('memory_context' if bounded.phase == 'profile' else
            'author_timeline' if bounded.phase in {'extract','summarize'} else 'composer'),
        'model':bounded.budget.model, 'language':bounded.fence.locale,
        'bounded_lane':bounded.model_dump(mode='json')}
    if bounded.phase not in {'extract','summarize','profile'}:
        payload['composer_phase'] = bounded.phase
    from .background_skills import admit_lane, observe_lane
    admit_lane(bounded.fence,bounded.phase)
    invocation_id = uuid4()
    async def observe(status):
        await observe_lane(bounded.fence,bounded.phase,status,invocation_id)
    body = LaneRequestBody(serialize_packet(payload).encode('utf-8'),publisher=publisher,fence=bounded.fence,
        after_send=lambda: observe('running'))
    options = {'timeout':timeout or 300}
    if worker_transport is not None:
        options['transport'] = worker_transport
    try:
        async with httpx.AsyncClient(**options) as client:
            response = await client.post(worker_url.rstrip('/')+'/internal/codex/turn',
                headers={'X-Codex-Worker-Secret':worker_secret,'Content-Type':'application/json',
                    'Content-Length':str(len(body._content))},content=body)
            if response.status_code == 503 and response.headers.get('X-Error-Code') == LaneGenerationPaused.code:
                raise LaneGenerationPaused('Bounded lifetime generation is paused; retry later')
            from .lifetime_memory_policy import PolicyUnavailable
            if response.status_code == 503 and response.headers.get('X-Error-Code') == PolicyUnavailable.code:
                raise PolicyUnavailable()
            from .lifetime_memory_activation import CanonicalActivationUnavailable
            if response.status_code == 503 and response.headers.get('X-Error-Code') == CanonicalActivationUnavailable.code:
                raise CanonicalActivationUnavailable()
            response.raise_for_status()
            result = response.json()
            if not isinstance(result,dict) or not isinstance(result.get('reply'),str):
                raise RuntimeError('Invalid bounded lane worker response')
            await observe('completed')
            return result
    except BaseException:
        await observe('failed')
        raise
    finally:
        await body.aclose()


async def run_bounded_lane(*, command, home_root, base_url, api_key, model,
        bounded_lane, publisher=None, timeout=240, connection_factory=None,
        issue14_admission=None, progress=None, uid=None, apply_owner=False, effort=None,
        provider_transport=None):
    check_lane_generation()
    bounded = _validated(bounded_lane,model)
    await validate_lane_payload(bounded)
    role = ('memory_context' if bounded.phase == 'profile' else
        'author_timeline' if bounded.phase in {'extract','summarize'} else 'composer')
    skill_name = {'memory_context': 'memoir-memory-context',
        'author_timeline': 'memoir-author-timeline', 'composer': 'memoir-composer'}[role]
    check_issue14_dispatch(issue14_admission,role=role)
    publisher = _publisher(bounded,publisher)
    instructions,schema = lane_contract(bounded.phase,bounded.fence.locale,batch=bounded.fence.batch is not None, two_lane=bounded.fence.two_lane is not None, strategy=bool(bounded.fence.two_lane and bounded.fence.two_lane.strategy_mode), fence=bounded.fence)
    from .conversation_reply_transport import stream_document
    endpoint = urlsplit(base_url)
    if (not api_key or endpoint.scheme not in {'http', 'https'} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('Lane provider is not configured')
    manifest = instruction_manifest(instructions, schema, variant=bounded.phase)
    payload = dict(model=model, instructions=instructions, input=bounded.packet,
        store=False, stream=True, tools=[], tool_choice='none', parallel_tool_calls=False,
        reasoning={'effort': effort or 'low', 'summary': 'auto'},
        max_output_tokens=bounded.budget.output_headroom,
        metadata={**manifest_metadata(manifest), 'generation_name':skill_name, 'trace_name':skill_name},
        text={'format':{'type':'json_schema', 'name':'codex_output_schema', 'strict':True, 'schema':schema}})
    encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    request = LaneRequestBody(encoded, publisher=publisher, fence=bounded.fence,
        before_send=lambda: check_issue14_dispatch(issue14_admission, role=role))
    with trace_llm_call('memoir.' + bounded.phase, model,
            metadata={'contract_version':'lifetime-lane-v1', 'prompt_manifest':manifest}):
        reply, receipt = await stream_document(request=request, content_length=len(encoded),
            base_url=base_url, api_key=api_key, timeout=timeout, transport=provider_transport,
            max_response_bytes=2_000_000)
    _object(reply)
    return {'thread_id':receipt['response_id'], 'reply':reply, 'artifacts':[]}
