"""Bounded, resumable canonical extraction/composition workers.

A page is a complete partition, never a complete lifetime snapshot. PostgreSQL
owns coverage, evidence identity, predecessor roots and final publication.
"""
from __future__ import annotations

import copy
import json
import os
import logging
from contextlib import ExitStack
from pydantic import ValidationError
from .lifetime_memory_contracts import ContextBudget
from .composer_configuration import composer_configuration
from .model_configuration import background_model, configured_model
from .memory_events import ExtractionResult, validate_extraction
from .llm_tracing import trace_skill_execution

PROTOCOL = 'lifetime_composer_pages'
SOURCE_WINDOW = 2304


def lane_model_budget(*, composer=False, timeline_context=False):
    model = composer_configuration().model if composer else background_model()
    return ContextBudget(model=model,
        context_window=int(os.getenv('MEMOIR_LANE_CONTEXT_WINDOW','131072')),
        input_budget=int(os.getenv('MEMOIR_LANE_INPUT_BUDGET','98304' if composer or timeline_context else '65536')),
        output_headroom=int(os.getenv('MEMOIR_LANE_OUTPUT_HEADROOM','16384')),
        framing_headroom=2048)


def extraction_issue(error):
    """Report schema locations without copying narrator or model content."""
    if isinstance(error, ValidationError):
        issue = error.errors(include_input=False)[0]
        path = '.'.join(str(part) for part in issue['loc'])
        return f'{path}:{issue["type"]}'[:120]
    if isinstance(error, KeyError) and error.args and error.args[0] in {
            'events', 'place_journeys', 'prepared_questions', 'strategy_proposal'}:
        return f'missing_{error.args[0]}'
    return type(error).__name__


def validate_page(page):
    if page.get('protocol')!=PROTOCOL or page.get('schema_version')!=1:
        raise ValueError('Unsupported canonical lane page')
    if any(type(page.get(key)) is not int or page[key]<0 for key in (
        'policy_epoch','preference_revision','source_high_water','event_high_water','page_number')):
        raise ValueError('Invalid canonical lane fence')
    if page.get('skill') not in {'timeline','composer','guidance'} or type(page.get('complete')) is not bool:
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
    if len(json.dumps(page,ensure_ascii=False).encode())>(98304 if page.get('timeline_context') else 65536):
        raise ValueError('Invalid bounded canonical lane page')
    return page


def extraction_events(raw,page,original=None):
    """Validate in the transmitted window, then restore exact original offsets."""
    source=page['source']
    from .timeline_context import context_sources
    context = context_sources(page.get('timeline_context'))
    proposal=ExtractionResult.model_validate(raw)
    # This bounded page provides event identity metadata, but no authorized
    # family/person registry. Names and relationships in testimony remain prose;
    # the model cannot turn them into database identity references.
    if any(event.person_ids for event in proposal.events):
        raise ValueError('Person identities are unavailable in this bounded source page')
    updates=copy.deepcopy(raw).get('events',[])
    def absolute(value):
        if isinstance(value,dict):
            if 'source_id' in value and 'quote' in value:
                admitted = [item for item in [source,*context] if item['id'] == value['source_id']
                    and type(value['version']) is int and item['version'] == value['version'] and value['quote'] in item['text']]
                if not admitted:
                    raise ValueError('Evidence outside the claimed source page')
                start=value.get('char_start');end=value.get('char_end')
                if (start is None)!=(end is None):
                    raise ValueError('Evidence requires both exact offsets or neither')
                positions = {(item['char_start']+start,item['char_start']+end)
                    for item in admitted if type(start) is int and type(end) is int
                    and 0<=start<end<=len(item['text']) and item['text'][start:end]==value['quote']}
                if not positions:
                    for item in admitted:
                        occurrence=item['text'].find(value['quote'])
                        while occurrence>=0:
                            positions.add((item['char_start']+occurrence,item['char_start']+occurrence+len(value['quote'])))
                            occurrence=item['text'].find(value['quote'],occurrence+1)
                if len(positions)!=1:
                    raise ValueError('An ambiguous occurrence requires exact offsets')
                start,end=positions.pop()
                value.update(char_start=start,char_end=end)
            for child in value.values(): absolute(child)
        elif isinstance(value,list):
            for child in value: absolute(child)
    absolute(updates)
    if original is not None:
        if (original.get('id')!=source['id'] or original.get('version')!=source['version']
            or len(original.get('text',''))>100000
            or original['text'][source['char_start']:source['char_end']]!=source['text']):
            raise ValueError('Whole-source policy authority changed')
    admitted = [{**original,'char_start':0} if original is not None else source,*context]
    updates=validate_extraction({'events':updates},admitted,page.get('events',[]))
    core_start=page.get('core_start',source['char_start'])
    if any(ref['source_id'] != source['id'] for event in updates for ref in event['source_refs']):
        raise ValueError('Event testimony must belong to the current source')
    return [event for event in updates if any(ref['char_end']>core_start for ref in event['source_refs'])]


async def _summarize(page,worker):
    from .lifetime_memory_summary import summary_packet,summary_rejection_reason,validate_summary
    state=page['memory_summary']
    if state['work_mode']=='reply_only' or page['source'] is None:
        return copy.deepcopy(state['prior'])
    from .lifetime_memory_activation import CanonicalActivationUnavailable
    if not getattr(worker,'worker_url',None) or not getattr(worker,'worker_secret',None):
        raise CanonicalActivationUnavailable()
    from .lifetime_memory_lane_engine import build_bounded_lane_input,send_bounded_lane_request
    packet=summary_packet(page)
    for attempt in range(3):
        bounded=build_bounded_lane_input(page,phase='summarize',packet=packet,budget=lane_model_budget())
        response=await send_bounded_lane_request(worker_url=worker.worker_url,worker_secret=worker.worker_secret,
            bounded_lane=bounded,worker_transport=getattr(worker,'worker_transport',None),
            publisher=getattr(worker,'lane_publisher',None),timeout=240)
        try:return validate_summary(json.loads(response['reply']),page)
        except (ValueError,TypeError,KeyError) as error:
            packet['retry_reason']=summary_rejection_reason(error)
            logging.getLogger(__name__).warning('canonical_summary rejected lane_id=%s attempt=%d reason=%s',
                page['lane_id'],attempt+1,packet['retry_reason'])
            if attempt==2:raise ValueError('Semantic summary output failed validation') from None


async def _extract(page,worker):
    from .lifetime_memory_lane_engine import EXTRACTION_WINDOW_CONTRACT, EXTRACTION_REJECTION_REASONS
    if (page.get('two_lane') or {}).get('work_mode')=='reply_only':
        result={'events':[],'place_journeys':[]}
        if (page.get('two_lane') or {}).get('reply_contract') == 'reply-v2':
            result['continuity_updates'] = []
        return result
    original=await worker.broker.rpc('read_lifetime_lane_policy_source',p_lane_id=page['lane_id'],p_token=page['token'])
    packet={'schema_version':1,'sources':[page['source']],
        'events':page['events'],'interview_context':{},'preferences':page['preferences'],
        'coverage':{'scope':'source_window','snapshot_id':page['snapshot_id'],
            'source_high_water':page['source_high_water'],'complete':False},
        'window_contract':EXTRACTION_WINDOW_CONTRACT}
    if page.get('attribution_context'):
        packet['interview_context'] = page['attribution_context']
    if page.get('timeline_context') is not None:
        packet.update(copy.deepcopy(page['timeline_context']))
    from .lifetime_memory_lane_engine import build_bounded_lane_input, send_bounded_lane_request
    for attempt in range(3):
        bounded=build_bounded_lane_input(page,phase='extract',packet=packet,budget=lane_model_budget(timeline_context=bool(page.get('timeline_context'))))
        response=await send_bounded_lane_request(worker_url=worker.worker_url,worker_secret=worker.worker_secret,
            bounded_lane=bounded,worker_transport=worker.worker_transport,
            publisher=getattr(worker,'lane_publisher',None),timeout=240)
        try:
            raw=json.loads(response['reply'])
            selected = (page.get('two_lane') or {}).get('selected_skills')
            if selected is not None:
                if 'memoir-author-timeline' not in selected and any(raw.get(field) for field in ('events','continuity_updates','event_places')):
                    raise ValueError('Unselected timeline output')
                if 'memoir-place-journey' not in selected and raw.get('place_journeys'):
                    raise ValueError('Unselected place output')
            if (page.get('two_lane') or {}).get('reply_contract') == 'reply-v2':
                allowed = {'events', 'place_journeys', 'continuity_updates'}
                if page.get('attribution_context'):
                    allowed.update({'event_places', 'passage_dispositions'})
                if not isinstance(raw, dict) or set(raw) - allowed:
                    raise ValueError('Unexpected background reply fields')
            result={'events':extraction_events({'events':raw['events']},page,original)}
            if page.get('two_lane'):
                from .two_lane_memory import derived_hints
                if page.get('attribution_context'):
                    from .conversation_attribution import validate_attribution, policy_dispositions
                    result.update(validate_attribution(raw, page, result['events']))
                    from .timeline_context import placement_links
                    for link in placement_links(result['events']):
                        if not any(item['event_index'] == link['event_index'] and item['role'] == link['role']
                                and item['place']['hierarchy'][:len(link['place']['hierarchy'])] == link['place']['hierarchy']
                                for item in result['event_places']):
                            result['event_places'].append(link)
                    result['passage_dispositions'].extend(policy_dispositions(page, original))
                result.update(derived_hints(raw, page, attribution=result if page.get('attribution_context') else None))
                if (page.get('two_lane') or {}).get('reply_contract') == 'reply-v2':
                    from .lifetime_memory_continuity import validate_continuity_updates
                    result['continuity_updates'] = validate_continuity_updates(
                        raw['continuity_updates'], page['source'], background=True)
            return result
        except (ValueError,TypeError,KeyError) as error:
            # Only fixed validator messages cross the logging boundary.
            packet['retry_reason']=EXTRACTION_REJECTION_REASONS.get(str(error),'OUTPUT_SCHEMA')
            logging.getLogger(__name__).warning(
                'canonical_extraction rejected lane_id=%s page_number=%d attempt=%d reason=%s issue=%s',
                page['lane_id'], page['page_number'], attempt + 1,
                packet['retry_reason'], extraction_issue(error))
            if attempt==2:raise



async def _compose(page,worker):
    if page.get('batch') is not None:
        from .progressive_composer import batch_job
        from .canonical_composer import compose_shared_snapshot
        return await compose_shared_snapshot(batch_job(page), worker)
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
    """Policy maintenance releases only metadata authority, never stale prose."""
    from .lifetime_memory_policy import is_policy_pending
    try:
        return await _execute_lifetime_lane(job,worker,page_quantum=page_quantum)
    except Exception as error:
        if not is_policy_pending(error):
            raise
        return await worker.broker.rpc('defer_lifetime_memoir_lane_policy',
            p_lane_id=job['lane_id'],p_token=job['token'],p_user_id=job['user_id'],
            p_project_id=job['project_id'],p_conversation_id=job['conversation_id'])


async def _execute_lifetime_lane(job,worker,*,page_quantum=8):
    """Bound each lease's work; completed pages survive yielding and crashes."""
    if not 1<=page_quantum<=32: raise ValueError('Invalid lane page quantum')
    from .lifetime_memory_lane_engine import LaneGenerationPaused
    from .lifetime_memory_activation import CanonicalActivationUnavailable
    page=job
    attribution_pages = []
    def receipt(result):
        return {**result, 'attribution_pages': attribution_pages} if attribution_pages else result
    for _ in range(page_quantum):
        validate_page(page)
        if (page.get('two_lane') or {}).get('work_mode')=='pending':
            # A new original window needs its own Lane B skill choice.
            return receipt(await worker.broker.rpc('yield_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token']))
        if page['preferences'].get('privacy_complete') is not True:
            return await worker.broker.rpc('defer_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'],
                p_reason='LIFETIME_PRIVACY_MAINTENANCE_REQUIRED')
        selected = (page.get('two_lane') or {}).get('selected_skills')
        if (page['skill'] == 'timeline' and (page.get('two_lane') or page.get('two_lane_maintenance_required'))
                and (selected is None or 'memoir-memory-context' in selected)
                and (page.get('two_lane') or {}).get('profile_complete') is not True):
            with trace_skill_execution('memoir-memory-context','profile') as attempt:
                profile_page = await worker.broker.rpc('read_lifetime_profile_page',
                    p_lane_id=job['lane_id'], p_token=job['token'])
                if profile_page is not None:
                    from .background_profile import extract_profile
                    try:
                        profile_result = await extract_profile(profile_page, worker)
                    except (LaneGenerationPaused, CanonicalActivationUnavailable) as deferred:
                        attempt['status']='blocked'
                        return await worker.broker.rpc('defer_lifetime_memoir_lane',
                            p_lane_id=job['lane_id'], p_token=job['token'], p_reason=deferred.code)
                    except ValueError as error:
                        if 'budget' not in str(error).lower():
                            raise
                        attempt['status']='blocked'
                        return await worker.broker.rpc('defer_lifetime_memoir_lane',
                            p_lane_id=job['lane_id'], p_token=job['token'], p_reason='LIFETIME_MODEL_BUDGET_REQUIRED')
                    saved = await worker.broker.rpc('commit_lifetime_profile_page',
                        p_lane_id=job['lane_id'], p_token=job['token'],
                        p_page_digest=profile_page['page_digest'], p_result=profile_result)
                    if saved.get('status') != 'page_saved':
                        attempt['status']='blocked'
                        return saved
                    if profile_result.get('skipped'):
                        attempt['status']='skipped'
                    page = await worker.broker.rpc('read_lifetime_memoir_lane_page',
                        p_lane_id=job['lane_id'], p_token=job['token'])
                    if not page:
                        return {'status': 'stale'}
                    continue
                if selected is not None and 'memoir-memory-context' in selected:
                    attempt['status']='blocked'
                    return receipt(await worker.broker.rpc('yield_lifetime_memoir_lane',
                        p_lane_id=job['lane_id'],p_token=job['token']))
                attempt['status']='skipped'
        if page['complete']:
            if page['skill']=='timeline' and page.get('two_lane_maintenance_required') is True:
                from .collector_configuration import collector_configuration
                model=collector_configuration(configured_model()).model
                checkpoint=await worker.broker.rpc('advance_two_lane_checkpoint',p_lane_id=job['lane_id'],p_token=job['token'],p_steps=1,p_model=model)
                if not checkpoint['complete']:
                    return await worker.broker.rpc('yield_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'])
                if checkpoint.get('summary_pending'):
                    page=await worker.broker.rpc('read_lifetime_memoir_lane_page',p_lane_id=job['lane_id'],p_token=job['token'])
                    if page.get('memory_summary') is None:
                        return await worker.broker.rpc('yield_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'])
                    continue
            return receipt(await worker.broker.rpc('complete_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token']))
        phase='summarize' if page.get('memory_summary') is not None else 'extract' if page['skill']=='timeline' else page['skill']
        names=['memoir-'+('author-timeline' if page['skill']=='timeline' else
            'interview-guidance' if page['skill']=='guidance' else 'composer')]
        if phase=='extract' and selected is not None:
            names=[name for name in ('memoir-author-timeline','memoir-place-journey') if name in selected]
        with ExitStack() as spans:
            attempts=[spans.enter_context(trace_skill_execution(name,phase,
                embedded=name=='memoir-place-journey' and 'memoir-author-timeline' in names)) for name in names]
            try:
                if page['skill']=='guidance':
                    from .interview_guidance import execute_guidance_lane
                    result=await execute_guidance_lane(page,worker)
                else:
                    result=await (_summarize(page,worker) if page.get('memory_summary') is not None else
                        _extract(page,worker) if page['skill']=='timeline' else _compose(page,worker))
            except (LaneGenerationPaused, CanonicalActivationUnavailable) as deferred:
                for attempt in attempts:attempt['status']='blocked'
                return await worker.broker.rpc('defer_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'],
                    p_reason=deferred.code)
            except ValueError as error:
                if 'budget' not in str(error).lower():
                    raise
                for attempt in attempts:attempt['status']='blocked'
                return await worker.broker.rpc('defer_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token'],
                    p_reason='LIFETIME_MODEL_BUDGET_REQUIRED')
            if page['skill']=='guidance':
                return result
            if page.get('memory_summary') is not None:
                result=await worker.broker.rpc('commit_lifetime_memory_summary_page',p_lane_id=job['lane_id'],p_token=job['token'],
                    p_revision=page['memory_summary']['revision'],p_result=result,p_page_digest=page['page_digest'])
            else:
                result=await worker.broker.rpc('commit_lifetime_memoir_lane_page',p_lane_id=job['lane_id'],p_token=job['token'],
                    p_page_number=page['page_number'],p_result=result,p_page_digest=page['page_digest'])
            if result.get('status')!='page_saved':
                for attempt in attempts:attempt['status']='blocked'
        if result.get('attribution'):
            attribution_pages.append(result['attribution'])
        if result.get('policy_changed'):
            return await worker.broker.rpc('yield_lifetime_memoir_lane_metadata',p_lane_id=job['lane_id'],p_token=job['token'],
                p_user_id=job['user_id'],p_project_id=job['project_id'],p_conversation_id=job['conversation_id'])
        if result.get('status')!='page_saved': return result
        page=await worker.broker.rpc('read_lifetime_memoir_lane_page',p_lane_id=job['lane_id'],p_token=job['token'])
        if not page: return {'status':'stale'}
    return receipt(await worker.broker.rpc('yield_lifetime_memoir_lane',p_lane_id=job['lane_id'],p_token=job['token']))
