"""Canonical lifetime conversation orchestration shared by API execution modes.

Narration, including transcribed microphone input, uses bounded model requests
and transactional publication fences. There is no legacy conversation fallback.
"""
from contextlib import AsyncExitStack
import asyncio
import json
from pathlib import Path
import time
from uuid import uuid4
from fastapi import HTTPException

from .lifetime_memory_contracts import ContextBudget, IdentityEnvelope
from .lifetime_memory_context import ContextSource, TailCoverage, InputLimitExceeded, serialize_packet
from .lifetime_memory_service import LifetimeMemoryService,MaintenancePending
from .lifetime_memory_transport import GovernedResult
from .prompt_artifact import load_prompt_artifact, prompt_path


class MappingRequired(RuntimeError):
    pass


class GenerationPaused(RuntimeError):
    pass


class PolicyMaintenancePending(MaintenancePending):
    """Metadata-only recovery; never imply the current request was accepted."""
    pass


class AcceptedResponsePending(MaintenancePending):
    code = 'LIFETIME_RESPONSE_PENDING'


def place_workspace_update(project_id, journeys):
    return {'project_id':project_id,'source_sequence':max(place.get('source_sequence',0) for place in journeys),
        'place_journey':journeys[-1],'place_journeys':journeys,
        'place_journey_change':{'changed':True,'mentioned':True}}


class LifetimePublicationContext:
    def __init__(self, emitter=None):
        self.emitter=emitter;self.fence=None;self.scope=None
        self.historical_research=None
        self.optional_tasks=[]
        self.strategy_delivery=None;self.strategy_metrics=None;self.strategy_outcome=None;self.strategy_timings={}

    def set_fence(self,fence):
        self.fence=json.loads(json.dumps(fence))
        if self.emitter:self.emitter.set_fence(self.fence)

    async def flush(self):
        if self.emitter:await self.emitter.flush()

    def queue_historical_research(self,runtime,storage,project_id):
        from .background_skills import queue_research
        queue_research(self,runtime,storage,project_id)

    def observe_delivery(self,event):
        if self.strategy_metrics is not None:
            if event.get('type')=='text_delta' and event.get('text','').strip():self.strategy_metrics.text()
            if event.get('type') in {'reply_complete','result'}:
                self.strategy_metrics.text()
                if (self.strategy_outcome or {}).get('question_delivered') is not None:
                    self.strategy_timings.setdefault('full_question_ms',self.strategy_metrics.elapsed())

    async def close(self, *, delivered=False):
        delivery,self.strategy_delivery=self.strategy_delivery,None
        if delivered and delivery is not None:
            try:await delivery()
            except Exception as error:
                # A disconnect/late fence cannot invent a delivery receipt. Saved
                # reply replay can recover this idempotently under a fresh fence.
                import logging
                logging.getLogger(__name__).warning('Conversation delivery receipt unavailable: %s',type(error).__name__)
        if self.strategy_metrics is not None and self.strategy_outcome is not None:
            self.strategy_metrics.record(self.strategy_outcome,delivered=delivered,**self.strategy_timings)
            self.strategy_metrics=None
        for task in self.optional_tasks:
            if not task.done():task.cancel()
        if self.optional_tasks:
            await asyncio.gather(*self.optional_tasks,return_exceptions=True)
            self.optional_tasks=[]
        if self.scope is not None:
            scope,self.scope=self.scope,None
            await scope.aclose()
        research,self.historical_research=self.historical_research,None
        if delivered and research is not None:
            from .historical_news import enrich
            storage,project_id,engine=research
            try:
                await enrich(storage,project_id,engine)
            except Exception as error:
                import logging
                logging.getLogger(__name__).warning('Historical research unavailable: %s',type(error).__name__)


def lifetime_enabled():
    """The canonical engine is the sole conversation implementation."""
    return True


def lifetime_generation_paused():
    import os
    return os.getenv('MEMOIR_LIFETIME_GENERATION_PAUSED', '').lower() in {'1', 'true', 'yes'}


async def run_lifetime_turn(runtime,storage,text,*,publication,project_id=None,language='en-AU',
        client_turn_id=None,source_kind='narrator_chat',uploaded_photo_ids=None,photo_selection=None,recording_ids=None,
        user_response=True,on_delta=None,on_event=None,workspace_focus=None,evaluation=None,trajectory=None,**unused):
    turn_started=time.monotonic()
    from .collector_configuration import collector_configuration
    from .interview_strategy import strategy_enabled,strategy_instructions,InterviewStrategyPlan,StrategyMetrics
    from .two_lane_memory import two_lanes_enabled, CONVERSATION_INSTRUCTIONS
    two_lane=two_lanes_enabled()
    from .conversation_locale import detect_reply_locale,explicit_request
    from .interview_plan import CollectorVisibleStream,collector_instructions,public_interview_fields
    from .lifetime_memory_continuity import (GOVERNED_CONTINUITY_INSTRUCTIONS,LiteralContinuityInputError,validate_literal_continuity_input,validate_governed_collector_result)
    from .lifetime_memory_engine import (CollectorResponseUnavailable,GovernedCollectorInput,
        governed_request_overhead,run_governed_collector)
    from .lifetime_memory_outbox import LifetimeMemoryOutbox
    from .recall import storage_recall_status
    from .turn_progress import TurnProgress, thinking_steps_enabled
    # Explicit request resource bound, before accepting any narrator bytes.
    if len(text.encode('utf-8'))>16000:
        raise InputLimitExceeded('This message exceeds the governed request budget; the original was not accepted or truncated')
    from .lifetime_memory_activation import CanonicalActivationUnavailable
    from .lifetime_memory_policy import PolicyUnavailable,is_policy_pending
    import httpx
    identity_raw=await asyncio.to_thread(storage.lifetime_rpc,'resolve_lifetime_conversation',p_project_id=project_id)
    if identity_raw.get('outcome')!='resolved':raise MappingRequired('Existing memoir projects require explicit identity mapping')
    identity=IdentityEnvelope.model_validate({k:v for k,v in identity_raw.items() if k!='outcome'})
    project_id=identity.project_id
    scope=AsyncExitStack();await scope.__aenter__()
    try:
        await scope.enter_async_context(runtime._lock(storage.user_id))
        lease=await scope.enter_async_context(runtime._storage_lease(storage,timeout=5))
        accepted_source_id=None
        async def policy_pending(status=None):
            status=status or await lease.io(storage.lifetime_rpc,'read_lifetime_policy_status',p_conversation_id=str(identity.conversation_id))
            error=PolicyMaintenancePending('Accepted conversation policy requires maintenance before private content can be used')
            error.pending_source_id=status.get('pending_source_id')
            error.pending_source_version=status.get('pending_source_version')
            error.pending_client_turn_id=status.get('pending_client_turn_id')
            if accepted_source_id is not None:
                error.accepted_source_id=accepted_source_id
                error.client_turn_id=client_turn_id
            return error
        async def call(name,**args):
            try:
                return await lease.io(storage.lifetime_rpc,name,**args)
            except httpx.HTTPStatusError as error:
                if is_policy_pending(error):
                    raise await policy_pending() from None
                raise
        entitlement=await lease.io(storage.story_entitlement)
        access=await lease.io(storage_recall_status,storage,entitlement)
        fence=await call('capture_lifetime_fence',p_conversation_id=str(identity.conversation_id),p_lease_token=lease.lease_token)
        publication.set_fence(fence)
        client_turn_id=client_turn_id or str(uuid4())
        replay=None
        already_accepted=False
        if user_response:
            already_accepted=await call('validate_lifetime_replay_input',p_conversation_id=str(identity.conversation_id),p_client_turn_id=client_turn_id,p_text=text,p_kind=source_kind,**({'p_recording_ids':recording_ids} if recording_ids else {}))
            replay=await call('read_lifetime_two_lane_reply' if two_lane else 'read_lifetime_reply',p_conversation_id=str(identity.conversation_id),p_client_turn_id=client_turn_id)
        policy_status=await call('read_lifetime_policy_status',p_conversation_id=str(identity.conversation_id))
        if policy_status.get('pending'):
            raise await policy_pending(policy_status)
        if user_response and replay is None:
            try:
                validate_literal_continuity_input(text,source_kind=source_kind)
            except LiteralContinuityInputError:
                if already_accepted:
                    raise await policy_pending() from None
                raise InputLimitExceeded('This message exceeds the explicit privacy-control request limit; the original was not accepted or truncated') from None
        if replay is not None:
            response={**replay,'cached':True,'recall_status':access}
            response['recordings']=await lease.io(storage.source_recordings,project_id,replay['accepted_source_id']) if callable(getattr(storage,'source_recordings',None)) else []
            if replay.get('reply'):
                journeys=await call('read_lifetime_place_journeys',p_project_id=project_id,p_source_id=replay['accepted_source_id'])
                progress=TurnProgress(on_event,client_turn_id,project_id,language,enabled=thinking_steps_enabled())
                if journeys:
                    await progress.update('place-journey',
                        'Restored saved place cues · ' + ' · '.join(place['place'] for place in journeys),
                        '已恢复保存的地点线索 · ' + ' · '.join(place['place'] for place in journeys),
                        status='cached',skill='memoir-place-journey')
                    workspace=place_workspace_update(project_id,journeys)
                    response.update(workspace)
                    if on_event:await on_event({'type':'workspace_update','data':workspace})
                interview=await lease.io(storage.interview_turn_by_id,project_id,client_turn_id)
                if isinstance((interview or {}).get('historical_context'),dict):
                    response['historical_context']=public_interview_fields(interview)['historical_context']
                if (interview or {}).get('plan'):
                    await progress.record_question_pool(interview['plan'])
                    if (interview['plan'].get('candidates')
                        and (interview.get('source') or {}).get('sequence')==fence['source_revision']):
                        # A successful retry can recover work skipped after failed delivery.
                        # The current owned durable claim deduplicates completed/running jobs.
                        publication.queue_historical_research(runtime,storage,project_id)
                response.update(trace=list(progress.steps),trace_mode='live')
        elif access and access['payment_required']:
            response={'project_id':project_id,'recall_status':access,'reply':None,'conversation_saved':False}
        elif not user_response:
            # Assistant-only onboarding is not testimony or a consumed round.
            pins=await call('read_lifetime_pinned',p_conversation_id=str(identity.conversation_id))
            greeting=('您想从哪里开始，或者继续哪段回忆？' if pins['language']=='zh-CN'
                else 'Where would you like to begin, or which memory would you like to continue?')
            response={'project_id':project_id,'conversation_saved':False,'accepted_source_id':None,
                'reply':greeting}
        elif lifetime_generation_paused():
            raise GenerationPaused('Conversation generation is paused; saved history and receipts remain available')
        else:
            if workspace_focus and not already_accepted:
                from .workspace_memory_actions import read_workspace_focus
                await lease.io(read_workspace_focus, storage, project_id, workspace_focus)
            accepted_start=time.monotonic()
            accepted=await lease.io(storage.accept_interview_turn,project_id,client_turn_id,text,kind=source_kind,
                language=detect_reply_locale(text) or language,uploaded_photo_ids=uploaded_photo_ids,photo_selection=photo_selection,
                **({'recording_ids':recording_ids} if recording_ids else {}),
                **({'two_lane':True} if two_lane else {}))
            source=accepted.get('source')
            if not source:raise ValueError('Governed narrator turn requires a canonical source')
            accepted_source_id=source['id']
            profile=await lease.io(storage.profile)
            selected_language=explicit_request(text) or profile.get('preferred_language') or language or detect_reply_locale(text)
            if selected_language not in {'en-AU','zh-CN'}:selected_language='en-AU'
            if profile.get('preferred_language')!=selected_language:
                language_fence=await call('capture_lifetime_fence',p_conversation_id=str(identity.conversation_id),p_lease_token=lease.lease_token)
                selected_language=await call('set_lifetime_language',p_fence=language_fence,p_language=selected_language,p_explicit=bool(explicit_request(text)))
            fence=await call('capture_lifetime_fence',p_conversation_id=str(identity.conversation_id),p_lease_token=lease.lease_token)
            # Source acceptance atomically persists the complete literal policy.
            publication.set_fence(fence)
            progress=TurnProgress(on_event,client_turn_id,project_id,selected_language,enabled=thinking_steps_enabled())
            if on_event:await on_event({'type':'source_accepted','data':{'client_turn_id':client_turn_id,'project_id':project_id,
                'accepted_source_id':source['id'],'recordings':accepted.get('recordings',[]),**public_interview_fields(accepted)}})
            await progress.update('memory-context','Loading saved profile and memory context','正在加载个人资料和回忆背景')
            context=await call('read_lifetime_interview_context',p_conversation_id=str(identity.conversation_id))
            if workspace_focus:
                from .workspace_memory_actions import read_workspace_focus, apply_workspace_focus
                try:
                    focus = await lease.io(read_workspace_focus, storage, project_id, workspace_focus)
                except HTTPException as error:
                    if error.status_code != 409: raise
                    # The original is accepted. A changed optional workspace task
                    # must not prevent this source or a lost reply from completing.
                    focus = None
                apply_workspace_focus(context, focus)
            from .historical_news import accepted_hypothesis,ready_projection
            import os
            context['historical_news']=ready_projection(context['historical_news'],enabled=os.getenv('MEMORY_SPARK_HISTORICAL_NEWS','').lower() in {'1','true','yes'})
            news=context['historical_news']
            needs_revalidation=news.pop('needs_revalidation',False)
            if news.get('enabled') and needs_revalidation:
                # Reuse inspected evidence only after checking the latest accepted basis.
                # This local preparation never starts or awaits external research.
                try:
                    basis=await lease.io(storage.historical_news_basis,project_id)
                    hypothesis=accepted_hypothesis(basis) if basis else None
                    if hypothesis:
                        refreshed=await lease.io(storage.revalidate_historical_news,project_id,hypothesis,basis['news_snapshot'])
                        if refreshed:
                            refreshed.pop('needs_revalidation',None)
                            context['historical_news']=refreshed
                except Exception:
                    pass  # Optional stale clues remain excluded on read/validation failure.
            context.pop('conversation_phase',None)
            context.update(source=source,sources=[source],photo_context=accepted.get('photo_context',[]),
                interview_language=selected_language,opening_turn=accepted.get('sequence')==1)
            if two_lane:
                context['two_lane_memory']=True
                context['prepared_questions']=await call('read_lifetime_prepared_questions',p_conversation_id=str(identity.conversation_id))
            collector=collector_configuration(runtime.model)
            if two_lane and strategy_enabled() and collector.prompt_version=='two-lane-v1':
                state=await call('read_lifetime_strategy_context',p_conversation_id=str(identity.conversation_id))
                if state['mode']=='active':
                    if state.get('plan') is not None:InterviewStrategyPlan.model_validate(state['plan'])
                    context.pop('prepared_questions',None)
                    context.update(strategy_selector=True,strategy_context=state,
                        active_strategy=(state.get('plan') or {}).get('strategy') or state.get('planned_strategy_hint') or
                            ('explore' if context['has_accepted_narration'] else 'comfort'))
                    publication.strategy_metrics=StrategyMetrics(client_turn_id,source['sequence'],context,start=turn_started)
            overall=ContextBudget(model=collector.model,context_window=131072,input_budget=65536,output_headroom=8192,framing_headroom=2048)
            overhead=governed_request_overhead(context,overall)
            packet_budget=overall.model_copy(update={'input_budget':overall.input_budget-overhead})
            saved=await call('read_lifetime_checkpoint_before' if two_lane else 'read_lifetime_checkpoint',p_conversation_id=str(identity.conversation_id),p_policy_epoch=fence['policy_epoch'],p_model=collector.model,p_prompt_version='lifetime-v1',
                **({'p_before_sequence':source['sequence'],'p_require_accepted':True} if two_lane else {}))
            if saved and saved['coverage_end']>=source['sequence']:
                saved=await call('read_lifetime_checkpoint_before',p_conversation_id=str(identity.conversation_id),p_policy_epoch=fence['policy_epoch'],
                    p_model=collector.model,p_prompt_version='lifetime-v1',p_before_sequence=source['sequence'],p_require_accepted=False)
            after=saved['coverage_end'] if saved else 0
            tail=await call('read_lifetime_two_lane_tail' if two_lane else 'read_lifetime_tail',p_conversation_id=str(identity.conversation_id),p_policy_epoch=fence['policy_epoch'],p_after_sequence=after,p_through_sequence=source['sequence']-1)
            def row(value):return ContextSource(identity=identity,policy_epoch=fence['policy_epoch'],source_id=value['id'],version=value['version'],sequence=value['sequence'],original=value['text'],language=value['language'],kind=value['kind'],conversation_saved=value.get('conversation_saved',False),assistant_reply=value.get('assistant_reply'),reply_policy_epoch=value.get('reply_policy_epoch'))
            coverage=TailCoverage(identity=identity,policy_epoch=fence['policy_epoch'],after_sequence=after,through_sequence=source['sequence']-1,complete=tail['complete'],tombstones=tail['tombstones'])
            service=LifetimeMemoryService(storage.lifetime_rpc,budget=packet_budget)
            from .collector_prompt import COMPACT_COLLECTOR_PROMPT
            from .codex_runtime import conversation_language_instruction
            privacy_guard = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/privacy-guard'))
            instructions=COMPACT_COLLECTOR_PROMPT+'\n'+conversation_language_instruction(selected_language)+'\n'+privacy_guard+collector_instructions({})+GOVERNED_CONTINUITY_INSTRUCTIONS
            if context.get('strategy_selector'):
                instructions=strategy_instructions(context['active_strategy'])+'\n'+conversation_language_instruction(selected_language)+GOVERNED_CONTINUITY_INSTRUCTIONS
                # Places are optional B work, so omit that extension from A.
                instructions=instructions[:instructions.index('Return place_journeys')]
            elif two_lane:
                instructions+=CONVERSATION_INSTRUCTIONS
            try:
                packet=await lease.io(service.assemble,fence=fence,current=row(source),instructions=instructions,
                tail=[row(value) for value in tail['records']],tail_coverage=coverage,interview_context=context,accepted_checkpoint=saved)
            except InputLimitExceeded as error:
                pending=MaintenancePending('The source is accepted; required current context exceeds this request budget')
                pending.accepted_source_id=source['id'];pending.client_turn_id=client_turn_id
                raise pending from error
            except MaintenancePending as error:
                error.accepted_source_id=source['id'];error.client_turn_id=client_turn_id
                raise
            # Reject changed preparation; transport also fences actual prompt admission.
            current_fence=await call('capture_lifetime_fence',p_conversation_id=str(identity.conversation_id),p_lease_token=lease.lease_token)
            if current_fence!=fence:raise RuntimeError('Context changed during preparation; retry the accepted turn')
            await progress.update('memory-context','Saved profile and memory context loaded','个人资料和回忆背景已加载',status='completed')
            governed=GovernedCollectorInput(packet=serialize_packet(packet),fence=fence,budget=overall,prompt_version='lifetime-v1')
            visible=CollectorVisibleStream()
            async def delta(chunk):
                value=visible.feed(chunk)
                if value and on_delta:await on_delta(value)
            await progress.update('collector-call','LLM call · Generating reply and question pool','LLM 调用 · 正在生成回复和问题池')
            model_started=time.monotonic()
            if publication.strategy_metrics is not None:
                publication.strategy_timings.update(context_preparation_ms=round((model_started-turn_started)*1000,3),
                    input_bytes=len(governed.packet.encode()),prompt_version='two-lane-v1')
            try:
                if runtime.worker_url:
                    result=await runtime._worker_turn(user_id=storage.user_id,prior=None,memories=[],profile={},place_journey={},
                        family_enabled=False,family_context={},project_id=project_id,text='',language=selected_language,
                        interview_context=context,governed=governed.model_dump(mode='json'),on_delta=delta if on_delta else None,
                        on_event=None if two_lane else progress.harness_event,evaluation=evaluation,trajectory=trajectory)
                    if trajectory is not None:
                        trajectory.append_trajectory(result.get('trajectory'),source='canonical-worker')
                else:
                    result=await run_governed_collector(command=runtime.command,home_root=runtime.home_root,base_url=runtime.base_url,
                        api_key=runtime.api_key,model=collector.model,governed=governed,interview_context=context,
                        timeout=runtime.timeout,on_delta=delta if on_delta else None,on_event=None if two_lane else progress.harness_event,
                        effort=collector.effort,issue14_admission=runtime._issue14_admission,trajectory=trajectory,
                        responsesapi_client_metadata=evaluation)
            except PolicyUnavailable:
                raise await policy_pending() from None
            except CanonicalActivationUnavailable as error:
                pending=MaintenancePending('The source is accepted; conversation provider authority is unavailable')
                pending.accepted_source_id=source['id'];pending.client_turn_id=client_turn_id
                raise pending from error
            except (CollectorResponseUnavailable,TimeoutError):
                pending=AcceptedResponsePending('Your message is saved. Please retry the response.')
                pending.accepted_source_id=source['id'];pending.client_turn_id=client_turn_id
                raise pending from None
            if result.get('_artifact_task') is not None:
                if two_lane:
                    publication.optional_tasks.append(result['_artifact_task'])
                else:
                    await result['_artifact_task']
            validated=validate_governed_collector_result(result['reply'],context)
            if publication.strategy_metrics is not None:
                publication.strategy_timings['model_ms']=round((time.monotonic()-model_started)*1000,3)
                publication.strategy_outcome=validated['strategy_outcome']
            journeys=[{**place,'source_sequence':source['sequence'],'status':'active',
                'revision':source['version'],'updated_at':source['created_at']} for place in validated['place_journeys']]
            if journeys:
                places=' · '.join(place['place'] for place in journeys)
                await progress.update('place-journey','Validating and saving place cues · '+places,
                    '正在核实并保存地点线索 · '+places,skill='memoir-place-journey')
                try:
                    await call('persist_lifetime_place_journeys',p_fence=fence,p_source_id=source['id'],p_source_version=source['version'],
                        p_journeys=validated['place_journeys'])
                except Exception:
                    await progress.update('place-journey','Place cues could not be saved','地点线索未能保存',
                        status='failed',skill='memoir-place-journey')
                    raise
                await progress.update('place-journey','Validated and saved place cues · '+places,
                    '已核实并保存地点线索 · '+places,status='completed',skill='memoir-place-journey')
            await progress.update('collector-call','LLM call · Reply and question pool generated','LLM 调用 · 回复和问题池已生成',status='completed')
            await progress.update('save','Saving conversation memory','正在保存对话记忆')
            await publication.flush()  # no old queued chunk can be relabeled by our phase commit
            save_started=time.monotonic()
            try:
                committed=await call('commit_lifetime_strategy_turn' if context.get('strategy_selector') else 'commit_lifetime_turn',p_fence=fence,p_client_turn_id=client_turn_id,p_plan=validated['plan'],
                    p_associations=validated['associations'],p_reply=validated['reply'],p_response_photo_ids=[p['photo_id'] for p in validated['response_photos']],
                    p_thread_id=result['thread_id'],p_prompt_version='lifetime-v1',p_model=collector.model,p_continuity_updates=validated['continuity_updates'],
                    **({'p_outcome':validated['strategy_outcome']} if context.get('strategy_selector') else {}))
            except PolicyMaintenancePending:
                raise
            except Exception:
                if not two_lane:raise
                pending=AcceptedResponsePending('Your message is saved. Please retry the response.')
                pending.accepted_source_id=source['id'];pending.client_turn_id=client_turn_id
                raise pending from None
            fence=committed['fence'];publication.set_fence(fence)
            if publication.strategy_metrics is not None:
                publication.strategy_timings.update(save_ms=round((time.monotonic()-save_started)*1000,3),
                    **committed.get('strategy_metrics',{}))
            await progress.update('save','Conversation memory saved','对话记忆已保存',status='completed')
            await progress.record_question_pool(validated['plan'])
            has_question=validated['plan']['chosen_id'] is not None
            milestone_identity={'project_id':project_id,'client_turn_id':client_turn_id,'accepted_source_id':source['id']}
            if on_event and has_question:
                await on_event({'type':'question_validated','data':{**milestone_identity,'has_question':True}})
            if on_delta:
                prefix=validated.get('acknowledgement','') if visible.emitted else ''
                await on_delta(validated['reply'][len(prefix):] if prefix and validated['reply'].startswith(prefix) else validated['reply'])
            access=await lease.io(storage_recall_status,storage,entitlement)
            response={'project_id':project_id,'client_turn_id':client_turn_id,'accepted_source_id':source['id'],'recordings':accepted.get('recordings',[]),
                'conversation_saved':True,'reply':validated['reply'],'recall_status':access,**public_interview_fields(committed['interview']),
                'trace':list(progress.steps),'trace_mode':'live'}
            if two_lane:
                response['reply_id']=committed['memory'][0]['id']
            if on_event:
                completion={**milestone_identity,'reply':validated['reply'],'cached':False,'has_question':has_question}
                if two_lane:completion={**response,**completion}  # Preserve the existing public two-lane envelope.
                await on_event({'type':'reply_complete','data':completion})
            if on_event:await on_event({'type':'conversation_saved','data':response})
            if journeys:
                workspace=place_workspace_update(project_id,journeys)
                response.update(workspace)
                if on_event:await on_event({'type':'workspace_update','data':workspace})
            if two_lane:
                # Acceptance/reply transactions already own the durable intents.
                # The worker drains them independently, including after disconnect.
                response['required_memory_work']={'pending':True,'backup_complete':False}
            else:
                response['required_memory_work']=await lease.io(LifetimeMemoryOutbox(storage.lifetime_rpc).drain,fence,limit=4)
            if context['historical_news'].get('enabled') is True and not validated['stopped']:
                # Response cleanup runs after final publication and lease release.
                publication.queue_historical_research(runtime,storage,project_id)
        # Keep both cross-replica renewal and the local lock alive through actual
        # final ASGI send. The response cleanup is their sole release owner.
        if two_lane and response.get('reply_id') and response.get('reply'):
            async def strategy_delivery():
                await call('commit_lifetime_attribution_delivery',p_fence=publication.fence,
                    p_client_turn_id=client_turn_id,p_reply_id=response['reply_id'])
                if strategy_enabled():
                    return await call('commit_lifetime_strategy_delivery',p_fence=publication.fence,
                        p_client_turn_id=client_turn_id,p_reply_id=response['reply_id'])
            publication.strategy_delivery=strategy_delivery
        publication.scope=scope;scope=None
        return GovernedResult(response,fence) if publication.emitter else response
    finally:
        if scope is not None:await scope.aclose()


async def lifetime_http_turn(runtime,storage,text,*,accept,options,close_storage=True):
    import os
    from fastapi import HTTPException
    from .lifetime_memory_publication import TransactionalPublication,PublicationUnavailable
    from .lifetime_memory_activation import CanonicalActivationUnavailable
    from .lifetime_memory_transport import governed_turn_events,GovernedStreamingResponse,GovernedJSONResponse
    publication=LifetimePublicationContext()
    response=None
    async def cleanup():
        try:await publication.close(delivered=response is not None and response.delivered)
        finally:
            if close_storage:await asyncio.to_thread(storage.client.close)
    try:
        publisher=TransactionalPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),authenticated_owner=storage.user_id)
        if 'application/x-ndjson' in accept:
            async def run(emit):
                publication.emitter=emit
                return await runtime.turn(storage,text,**options,lifetime_context=publication,on_delta=emit,on_event=emit.event)
            response=GovernedStreamingResponse(governed_turn_events(run,cleanup=cleanup),publisher=publisher,on_delivered=publication.observe_delivery)
            return response
        result=await runtime.turn(storage,text,**options,lifetime_context=publication)
        response=GovernedJSONResponse(result,publisher=publisher,fence=publication.fence,cleanup=cleanup,on_delivered=publication.observe_delivery)
        return response
    except BaseException as error:
        await cleanup()
        if isinstance(error,CanonicalActivationUnavailable):
            raise HTTPException(503,'Conversation provider authority is unavailable',headers={'X-Error-Code':CanonicalActivationUnavailable.code,'Retry-After':'60'}) from None
        if isinstance(error,PublicationUnavailable):raise HTTPException(503,'Governed publication is not configured') from None
        if isinstance(error,GenerationPaused):raise HTTPException(503,str(error),headers={'X-Error-Code':'LIFETIME_GENERATION_PAUSED'}) from None
        if isinstance(error,MappingRequired):raise HTTPException(409,str(error),headers={'X-Error-Code':'LIFETIME_MAPPING_REQUIRED'}) from None
        if isinstance(error,InputLimitExceeded):raise HTTPException(413,str(error)) from None
        import httpx
        if isinstance(error,httpx.HTTPStatusError) and error.response.status_code==413:
            raise HTTPException(413,'The combined recordings exceed five minutes; your answer was not accepted',headers={'X-Error-Code':'AUDIO_DURATION_EXCEEDED'}) from None
        if isinstance(error,httpx.HTTPStatusError):raise HTTPException(409 if error.response.status_code in {400,409} else 503,'The accepted conversation state changed; reconcile the saved receipt before retrying') from None
        if isinstance(error,PolicyMaintenancePending):
            raise HTTPException(503,{'state':'policy_maintenance_pending','message':str(error),
                'pending_source_id':getattr(error,'pending_source_id',None),
                'pending_source_version':getattr(error,'pending_source_version',None),
                'pending_client_turn_id':getattr(error,'pending_client_turn_id',None),
                **({'accepted_source_id':error.accepted_source_id,'client_turn_id':error.client_turn_id}
                   if getattr(error,'accepted_source_id',None) is not None else {})},
                headers={'X-Error-Code':'LIFETIME_POLICY_PENDING','Retry-After':'60'}) from None
        if isinstance(error,AcceptedResponsePending):
            raise HTTPException(503,{'state':'source_accepted','message':str(error),
                'accepted_source_id':error.accepted_source_id,'client_turn_id':error.client_turn_id},
                headers={'X-Error-Code':error.code,'Retry-After':'1'}) from None
        if isinstance(error,MaintenancePending):raise HTTPException(503,{'state':'source_accepted','message':str(error),'accepted_source_id':getattr(error,'accepted_source_id',None),'client_turn_id':getattr(error,'client_turn_id',None)},headers={'X-Error-Code':'LIFETIME_MAINTENANCE_PENDING'}) from None
        raise
