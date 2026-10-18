"""Logical Lane B policy over existing runners; never a second scheduler."""
from dataclasses import asdict, dataclass
import asyncio
import hashlib
import json
import logging
import os


@dataclass(frozen=True)
class Skill:
    name: str
    runner: str | None
    execution: str
    trigger: str
    status: str = 'implemented'
    modes: tuple[str, ...] = ('comfort', 'explore', 'shape')
    cadence_owner: str | None = None
    gates: tuple[str, ...] = ()
    recovery: str = 'none'


SKILLS = {item.name: item for item in (
    Skill('memoir-author-timeline', 'timeline', 'model', 'accepted_source',
        gates=('canonical_activation','source_policy_fence','A_work_decision'),recovery='durable_lane'),
    Skill('memoir-family-tree', None, 'model', 'relationship_evidence', 'unwired',
        gates=('family_entitlement','relationship_evidence','integration_required')),
    Skill('memoir-place-groups', 'grouping', 'deterministic', 'place_change',
        gates=('owned_project','public_places','request_deduplication'),recovery='request'),
    Skill('memoir-story-game', None, 'model', 'game_button', 'unavailable', ('shape',),
        gates=('current_delivered_A_shape','explicit_button','completion','adaptation_consent','entitlement','evidence','integration_required')),
    Skill('historical-news-research', 'historical', 'provider', 'delivered_context',
        gates=('rollout_flag','user_settings','public_time_place','reply_delivered','A_lease_released','persisted_claim','source_verification'),recovery='research_claim'),
    Skill('memoir-composer', 'composer', 'model', 'periodic', cadence_owner='private_draft_cadence',
        gates=('SQL_due_milestone','extraction_complete_snapshot','composition_opt_in','canonical_publication'),recovery='durable_lane'),
    Skill('memoir-memory-context', 'timeline', 'model', 'periodic', cadence_owner='lifetime_profile_due_round',
        gates=('SQL_due_interval','manual_field_exclusions','automatic_profile_enabled','remaining_targets','source_policy_fence'),recovery='durable_lane'),
    Skill('memoir-place-journey', 'timeline', 'embedded', 'place_evidence',
        gates=('same_timeline_pass','source_grounded_geography','canonical_publication'),recovery='durable_lane'),
    Skill('place-photo-research', 'photos', 'provider', 'place_selection',
        gates=('owned_project','public_query','cursor_scope','cache','bounded_photo_capacity','optional_model_flag'),recovery='process_local_job_public_cache'),
)}


def execution_map():
    from .recall import private_draft_cadence
    return [{**asdict(item), 'lane':'B' if item.runner or item.status in {'unwired','unavailable'} else None,
        'mode_independent':item.name != 'memoir-story-game',
        'cadence':{'every_completed_rounds':private_draft_cadence()} if item.name=='memoir-composer' else
            {'default_rounds':'1, 5, 10, 20, 30, ...; SQL-owned'} if item.name=='memoir-memory-context' else None,
        'compatibility':'flag_off_place_in_A' if item.name == 'memoir-place-journey' else None}
        for item in SKILLS.values()]


class SkillUnavailable(ValueError):
    pass


async def action_turn(storage,project_id,reference):
    """An optional UI correlation reference is not permission or source evidence."""
    if not reference:return None
    from uuid import UUID
    from fastapi import HTTPException
    try:
        turn=str(UUID(str(reference)))
    except (TypeError,ValueError):
        raise HTTPException(422,'Invalid progress turn reference') from None
    if not await asyncio.to_thread(storage.interview_turn_by_id,project_id,turn):
        raise HTTPException(422,'Owned progress turn required')
    return turn


def admit(name, trigger):
    """One logical owner. Domain writers still validate evidence/claims/cadence.

    Callers supply an authenticated source/action reference, never a requested
    mode or a round. Only the existing SQL schedulers can admit periodic pages.
    Optional runners retain their separate capacity, caches and recovery.
    """
    skill = SKILLS[name]
    if skill.status != 'implemented' or skill.trigger != trigger:
        raise SkillUnavailable(skill.status if skill.status != 'implemented' else 'trigger_required')
    if name == 'historical-news-research' and os.getenv('MEMORY_SPARK_HISTORICAL_NEWS','').lower() not in {'1','true','yes'}:
        raise SkillUnavailable('feature_disabled')
    return skill


def admit_lane(fence, phase):
    """Admit only canonical bounded phases, not a catalog-selected model call."""
    if fence.skill == 'timeline':
        if phase not in {'extract','summarize','profile'}:
            raise SkillUnavailable('phase_required')
        name = 'memoir-memory-context' if phase == 'profile' else 'memoir-author-timeline'
        if phase == 'extract' and fence.two_lane is not None and fence.two_lane.work_mode != 'extract':
            raise SkillUnavailable('reply_only')
        if phase == 'profile' and (not fence.profile_context or fence.profile_context.get('work_mode') != 'extract'
                or not fence.profile_context.get('targets')):
            raise SkillUnavailable('manual_or_no_targets')
    else:
        if fence.skill != 'composer' or phase not in {'prepare','draft','review','index'}:
            raise SkillUnavailable('phase_required')
        name = 'memoir-composer'
    return admit(name, SKILLS[name].trigger)


async def _record(function, arguments, *, owner=None):
    """Best-effort metadata, never a new personal-data writer or execution gate."""
    if not os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'):
        return
    from psycopg import AsyncConnection
    from psycopg.types.json import Jsonb
    try:
        async with asyncio.timeout(2):
            async with await AsyncConnection.connect(os.environ['MEMOIR_PUBLICATION_DATABASE_URL'],connect_timeout=1) as connection:
                await connection.execute('set local role service_role')
                if owner:
                    await connection.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(owner),))
                await connection.execute("set local lock_timeout='250ms'")
                await connection.execute('select public.'+function+'('+','.join(['%s']*len(arguments))+')',
                    tuple(Jsonb(value) if isinstance(value,dict) else value for value in arguments))
    except Exception as error:
        logging.getLogger(__name__).warning('Background progress unavailable: %s',type(error).__name__)


class ServiceWork:
    """Request/claim-scoped progress, not durable resumption for optional jobs."""
    def __init__(self, name, trigger, owner, project_id, reference, *, client_turn_id=None, research_job_id=None):
        self.skill = admit(name,trigger)
        self.owner,self.project_id = owner,project_id
        self.client_turn_id = str(client_turn_id) if client_turn_id else None
        self.research_job_id = research_job_id
        self.id = hashlib.sha256(json.dumps([name,reference,self.client_turn_id],sort_keys=True).encode()).hexdigest()
        self.previous = None

    async def update(self,status,*,cached=False):
        step = {'id':self.id,'skill':self.skill.name,'lane':'B','phase':self.skill.runner,
            'execution':'cache' if cached else self.skill.execution,'status':status,
            'model_invoked':False if cached or self.skill.execution=='deterministic' else None,
            'coverage_start':0,'coverage_end':0,'project_id':self.project_id,'client_turn_id':self.client_turn_id}
        if step != self.previous:
            metadata={**step,**({'research_job_id':self.research_job_id} if self.research_job_id else {})}
            await _record('record_background_service_work',(str(self.owner),self.project_id,metadata))
            self.previous = step
        return step


async def group_places(owner,project_id,places,*,client_turn_id=None):
    from .place_groups import resolve_place_groups
    work = ServiceWork('memoir-place-groups','place_change',owner,project_id,places,client_turn_id=client_turn_id)
    await work.update('running')
    try:
        result = await asyncio.to_thread(resolve_place_groups,places)
    except BaseException:
        await work.update('failed')
        raise
    return {**result,'skill_progress':await work.update('completed')}


async def photo_step(owner,project_id,result,*,client_turn_id=None):
    """PhotoPages proves job identity/cache state; transport proves no more."""
    if not result.get('job_id'):
        return result
    work=ServiceWork('place-photo-research','place_selection',owner,project_id,result['job_id'],client_turn_id=client_turn_id)
    cached=bool(result.get('cached'))
    status='running' if result.get('searching') else 'failed' if result.get('status')=='UNAVAILABLE' else 'cached' if cached else 'completed'
    return {**result,'skill_progress':await work.update(status,cached=cached)}


def queue_research(publication,runtime,storage,project_id):
    """The sole after-delivery registration point; no launch while A holds a lease."""
    try:
        admit('historical-news-research','delivered_context')
    except SkillUnavailable:
        return
    from .historical_news import HistoricalResearch
    from .historical_news_provider import GatewayHistoricalProvider
    if runtime._news_engine is None:
        runtime._news_engine = HistoricalResearch(GatewayHistoricalProvider())
    publication.historical_research = (storage,project_id,runtime._news_engine)


async def observe_lane(fence, phase, status, invocation_id):
    """Optional metadata only; provider and canonical publication guards still own truth."""
    from .two_lane_memory import two_lanes_enabled
    if not two_lanes_enabled() or not os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'):
        return
    await _record('record_lifetime_skill_phase',(fence.model_dump(mode='json'),phase,status,invocation_id),owner=fence.user_id)
