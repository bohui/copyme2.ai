"""Bounded, resumable canonical extraction/composition workers.

A page is a complete partition, never a complete lifetime snapshot. PostgreSQL
owns coverage, evidence identity, predecessor roots and final publication.
"""
from __future__ import annotations

import copy
import json
import os
from .lifetime_memory_contracts import ContextBudget
from .memory_events import ExtractionResult, extraction_instructions, extraction_schema, validate_extraction

PROTOCOL = 'lifetime_composer_pages'
SOURCE_WINDOW = 2304


def lane_model_budget():
    return ContextBudget(model=os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL',
        os.getenv('MEMORY_SPARK_LLM_MODEL','gpt-5.6-luna-pooled')),
        context_window=int(os.getenv('MEMOIR_LANE_CONTEXT_WINDOW','131072')),
        input_budget=int(os.getenv('MEMOIR_LANE_INPUT_BUDGET','65536')),
        output_headroom=int(os.getenv('MEMOIR_LANE_OUTPUT_HEADROOM','16384')),
        framing_headroom=2048)


def check_model_packet(packet, instructions, schema):
    budget=lane_model_budget()
    serialized=json.dumps({'instructions':instructions,'schema':schema,'packet':packet},ensure_ascii=False)
    if not budget.accepts(serialized):
        raise ValueError('bounded canonical lane model budget exceeded')
    return budget.count(serialized)


def validate_page(page):
    if page.get('protocol')!=PROTOCOL or page.get('schema_version')!=1:
        raise ValueError('Unsupported canonical lane page')
    if any(type(page.get(key)) is not int or page[key]<0 for key in (
        'policy_epoch','preference_revision','source_high_water','event_high_water','page_number')):
        raise ValueError('Invalid canonical lane fence')
    if page.get('skill') not in {'timeline','composer'} or type(page.get('complete')) is not bool:
        raise ValueError('Invalid canonical lane scope')
    preferences=page.get('preferences',{})
    if preferences.get('schema_version')!=1 or preferences.get('language') not in {'en-AU','zh-CN'}:
        raise ValueError('Typed current lane preferences required')
    source=page.get('source')
    if source:
        if (not isinstance(source.get('text'),str) or len(source['text'])>SOURCE_WINDOW
            or type(source.get('char_start')) is not int or source['char_start']<0
            or source.get('char_end')!=source['char_start']+len(source['text'])
            or type(source.get('original_length')) is not int or not source['char_end']<=source['original_length']<=100000):
            raise ValueError('Invalid bounded original source window')
    if len(page.get('events',[]))>8:
        raise ValueError('Unbounded canonical event candidates')
    if len(json.dumps(page,ensure_ascii=False).encode())>65536:
        raise ValueError('Invalid bounded canonical lane page')
    return page


def extraction_events(raw,page,original=None):
    """Validate in the transmitted window, then restore exact original offsets."""
    source=page['source']
    ExtractionResult.model_validate(raw)
    updates=(copy.deepcopy(raw).get('events',[]) if original is not None else
        validate_extraction(copy.deepcopy(raw),[source],page.get('events',[])))
    def absolute(value):
        if isinstance(value,dict):
            if 'source_id' in value and 'quote' in value:
                if value['source_id']!=source['id'] or type(value['version']) is not int or value['version']!=source['version']:
                    raise ValueError('Evidence outside the claimed source page')
                start=value.get('char_start');end=value.get('char_end')
                if (start is None)!=(end is None):
                    raise ValueError('Evidence requires both exact offsets or neither')
                if start is None:
                    start=source['text'].find(value['quote'])
                    if source['text'].find(value['quote'],start+1)>=0:
                        raise ValueError('An ambiguous occurrence requires exact offsets')
                end=end if end is not None else start+len(value['quote'])
                if type(start) is not int or type(end) is not int or start<0 or end>len(source['text']) or source['text'][start:end]!=value['quote']:
                    raise ValueError('Evidence span exceeds claimed source page')
                value.update(char_start=start+source['char_start'],char_end=end+source['char_start'])
            for child in value.values(): absolute(child)
        elif isinstance(value,list):
            for child in value: absolute(child)
    absolute(updates)
    if original is not None:
        if (original.get('id')!=source['id'] or original.get('version')!=source['version']
            or len(original.get('text',''))>100000
            or original['text'][source['char_start']:source['char_end']]!=source['text']):
            raise ValueError('Whole-source policy authority changed')
        updates=validate_extraction({'events':updates},[original],page.get('events',[]))
    core_start=page.get('core_start',source['char_start'])
    return [event for event in updates if any(ref['char_end']>core_start for ref in event['source_refs'])]


async def _extract(page,worker):
    original=await worker.broker.rpc('read_lifetime_lane_policy_source',p_lane_id=page['lane_id'],p_token=page['token'])
    packet={'schema_version':1,'sources':[page['source']],
        'events':page['events'],'interview_context':{},'preferences':page['preferences'],
        'coverage':{'scope':'source_window','snapshot_id':page['snapshot_id'],
            'source_high_water':page['source_high_water'],'complete':False},
        'window_contract':'Offsets in proposals are relative to this exact original window. The host restores absolute offsets. Candidate event metadata is derived identity context, never testimony. Unlisted history is not absent. Preserve uncertain identity rather than guessing.'}
    check_model_packet(packet,extraction_instructions(),extraction_schema())
    from .lifetime_memory_lane_engine import build_bounded_lane_input, send_bounded_lane_request
    bounded=build_bounded_lane_input(page,phase='extract',packet=packet,budget=lane_model_budget())
    response=await send_bounded_lane_request(worker_url=worker.worker_url,worker_secret=worker.worker_secret,
        bounded_lane=bounded,worker_transport=worker.worker_transport,
        publisher=getattr(worker,'lane_publisher',None),timeout=240)
    return {'events':extraction_events(json.loads(response['reply']),page,original)}



async def _compose(page,worker):
    if page.get('reuse'):
        return {'reuse':True}
    if not page.get('partition') or page['partition'].get('status')!='active' or not page.get('source'):
        return {'status':'no_authorized_evidence'}
    from .canonical_composer import compose_shared_snapshot
    source=page['source'];event=page['partition']
    job={**page,'authoritative_page':copy.deepcopy(page),'governed_page':True,'sources':[source],'events':[event],
        'source_manifest':[{'id':source['id'],'version':source['version']}],
        'event_manifest':[{'id':event['id'],'revision':event['revision']}],
        'previous':None,'base_revision':0,'source_windows':{
            source['id']:{'char_start':source['char_start'],'char_end':source['char_end'],'original_length':source['original_length']}}}
    return await compose_shared_snapshot(job,worker)


async def execute_lifetime_lane(job,worker,*,page_quantum=8):
    """Bound each lease's work; completed pages survive yielding and crashes."""
    if not 1<=page_quantum<=32: raise ValueError('Invalid lane page quantum')
    from .lifetime_memory_lane_engine import LaneGenerationPaused
    page=job
    for _ in range(page_quantum):
        validate_page(page)
        if page['preferences'].get('privacy_complete') is not True:
            return await worker.broker.rpc('defer_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'],
                p_reason='LIFETIME_PRIVACY_MAINTENANCE_REQUIRED')
        if page['complete']:
            return await worker.broker.rpc('complete_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'])
        try:
            result=await (_extract(page,worker) if page['skill']=='timeline' else _compose(page,worker))
        except LaneGenerationPaused:
            return await worker.broker.rpc('defer_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'],
                p_reason='LIFETIME_GENERATION_PAUSED')
        except ValueError as error:
            if 'budget' not in str(error).lower():
                raise
            return await worker.broker.rpc('defer_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'],
                p_reason='LIFETIME_MODEL_BUDGET_REQUIRED')
        result=await worker.broker.rpc('commit_lifetime_memoir_lane_page',p_lane_id=job['lane_id'],p_token=job['token'],
            p_page_number=page['page_number'],p_result=result,p_page_digest=page['page_digest'])
        if result.get('status')!='page_saved': return result
        page=await worker.broker.rpc('read_lifetime_memoir_lane_page',p_lane_id=job['lane_id'],p_token=job['token'])
        if not page: return {'status':'stale'}
    return await worker.broker.rpc('yield_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'])
