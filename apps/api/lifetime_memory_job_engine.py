"""Bounded selected-collection organisation with transactional request admission.

Original windows and derived child summaries are exact database-owned page data.
Every call starts a fresh home; global coverage/order lives in the job tree, never
an accumulated harness transcript. HTTP/pipe locks end at request admission.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .codex_agent import CodexConnection, provider_config
from .codex_worker_files import write_config
from .issue14_execution_admission import check_issue14_dispatch, issue14_connection_options
from .lifetime_memory_context import serialize_packet
from .lifetime_memory_contracts import Contract, ContextBudget, PinnedContinuity
from .prompt_composition import render_prompt_artifact
from .prompt_artifact import prompt_path
from .lifetime_memory_execution import open_execution
from .lifetime_memory_lane_engine import (
    SUPPORTED_LANE_MODELS, LaneGenerationPaused, LaneRequestBody,
    _admission, _lane_context, _object, _settle, check_lane_generation,
)
from .lifetime_memory_publication import PublicationUnavailable


class _Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class JobSource(_Strict):
    id: UUID
    project_id: str
    version: int = Field(ge=1, strict=True)
    sequence: int = Field(ge=1, strict=True)
    text: str = Field(min_length=1, max_length=2048)
    char_start: int = Field(ge=0, strict=True)
    char_end: int = Field(ge=1, strict=True)
    original_length: int = Field(ge=1, strict=True)
    kind: Literal['narrator_chat', 'narrator_transcript']
    language: Literal['en-AU', 'zh-CN']
    status: Literal['active']
    author_role: Literal['storyteller']

    @model_validator(mode='after')
    def exact_window(self):
        if self.char_end != self.char_start + len(self.text) or self.char_end > self.original_length:
            raise ValueError('Collection job source window differs from original bounds')
        return self


class ChildSection(_Strict):
    id: str = Field(pattern=r'^[a-f0-9-]{36}:[1-9][0-9]{0,2}$')
    title: str = Field(min_length=1, max_length=200)


class ChildGroup(_Strict):
    id: UUID
    digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    title: str = Field(min_length=1, max_length=200)
    sections: list[ChildSection] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def bounded_summary(self):
        if [section.id for section in self.sections] != [f'{self.id}:{n}' for n in range(1,len(self.sections)+1)]:
            raise ValueError('Child sections require stable database-owned IDs')
        if _metadata_size(self.model_dump(mode='json')) > 12000:
            raise ValueError('Collection child summary exceeds the 12KiB metadata budget')
        return self


class JobFence(Contract):
    protocol: Literal['lifetime_collection_jobs'] = 'lifetime_collection_jobs'
    job_id: UUID
    token: UUID
    snapshot_id: UUID
    user_id: UUID
    project_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    conversation_id: UUID
    kind: Literal['BuildOutline']
    phase: Literal['leaf', 'merge']
    locale: Literal['en-AU', 'zh-CN']
    policy_epoch: int = Field(ge=1, strict=True)
    preference_revision: int = Field(ge=0, strict=True)
    collection_revision: int = Field(ge=1, strict=True)
    root_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    page_number: int = Field(ge=0, strict=True)
    page_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    preferences: PinnedContinuity
    sources: list[JobSource] = Field(max_length=1)
    child_groups: list[ChildGroup] = Field(max_length=8)

    @model_validator(mode='after')
    def phase_scope(self):
        if self.phase == 'leaf':
            if len(self.sources) != 1 or self.child_groups:
                raise ValueError('A leaf job requires one exact source window and no derived children')
        elif self.sources or len(self.child_groups) < 2:
            raise ValueError('A merge job requires at least two bounded children and no original windows')
        if any(source.project_id != self.project_id for source in self.sources):
            raise ValueError('Collection source belongs to another project')
        ids = [child.id for child in self.child_groups]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate collection child identity')
        if sum(_metadata_size(child.model_dump(mode='json')) for child in self.child_groups) > 24000:
            raise ValueError('Collection merge exceeds its 24KiB child metadata budget')
        return self


def _metadata_size(value):
    # PostgreSQL jsonb::text uses separator spaces. Key order cannot alter size.
    return len(json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(', ', ': ')).encode('utf-8'))


def job_packet(fence):
    preferences=fence.preferences.model_dump(mode='json')
    _lane_context(fence,preferences)  # Shared complete-policy and pin byte bounds.
    context={key:value for key,value in fence.model_dump(mode='json').items()
        if key not in {'token','sources','child_groups'}}
    # Keep complete authority in the fence. Conversation questions/history are
    # irrelevant to organising an already selected source tree and cannot crowd
    # out mandatory privacy constraints or bounded child grouping metadata.
    context['preferences']={key:preferences[key] for key in ('schema_version',
        'preference_revision','language','chosen_name','privacy_complete',
        'excluded_topics','paused_topics','unresolved_references')}
    context.update(coverage_scope='selected_collection_partition',complete=False)
    return {'job_context':context,'sources':[source.model_dump(mode='json') for source in fence.sources],
        'child_groups':[child.model_dump(mode='json') for child in fence.child_groups]}


def job_contract(fence):
    ids=([str(source.id) for source in fence.sources] if fence.phase=='leaf' else
        [section.id for child in fence.child_groups for section in child.sections])
    field='memory_ids' if fence.phase=='leaf' else 'section_ids'
    schema={'type':'object','additionalProperties':False,'required':['title','sections'],'properties':{
        'title':{'type':'string','minLength':1,'maxLength':200},
        'sections':{'type':'array','minItems':1,'maxItems':100,'items':{'type':'object',
            'additionalProperties':False,'required':['title',field],'properties':{
                'title':{'type':'string','minLength':1,'maxLength':200},
                field:{'type':'array','minItems':1,'maxItems':len(ids),
                    'items':{'type':'string','enum':ids}}}}}}}
    instructions = render_prompt_artifact(prompt_path(f'memoir/skills/memoir-composer/outline/{fence.phase}/{fence.locale}'))
    return instructions,schema


class BoundedJobInput(Contract):
    fence: JobFence
    budget: ContextBudget
    prompt_version: Literal['lifetime-organiser-v1'] = 'lifetime-organiser-v1'
    packet: str = Field(min_length=1,max_length=65536)

    @model_validator(mode='after')
    def validate_transport(self):
        if (self.budget.model not in SUPPORTED_LANE_MODELS or self.budget.context_window>131072
                or self.budget.input_budget>65536 or self.budget.framing_headroom<2048):
            raise ValueError('Collection job budget exceeds reviewed transport limits')
        if self.packet != serialize_packet(job_packet(self.fence)):
            raise ValueError('Collection packet differs from the authoritative job page')
        if job_request_tokens(self)>self.budget.input_budget:
            raise ValueError('Collection job prompt, schema, packet and framing exceed input budget')
        return self


def job_request_tokens(bounded):
    instructions,schema=job_contract(bounded.fence)
    return (bounded.budget.count(instructions)+bounded.budget.count(bounded.packet)
        +bounded.budget.count(serialize_packet(schema))+bounded.budget.framing_headroom)


def build_bounded_job_input(page, *, budget):
    if page.get('complete') is not False:
        raise ValueError('Completed collection jobs cannot start model work')
    fence=JobFence.model_validate({key:page[key] for key in JobFence.model_fields if key in page})
    return BoundedJobInput(fence=fence,budget=budget,packet=serialize_packet(job_packet(fence)))


class JobOutputInvalid(RuntimeError):
    code='LIFETIME_JOB_OUTPUT_INVALID'
    retryable=True


def job_summary_metadata(result, node_id, digest):
    return {'id':str(UUID(str(node_id))),'digest':digest,'title':result['title'],
        'sections':[{'id':f'{node_id}:{index}','title':section['title']}
            for index,section in enumerate(result['sections'],1)]}


def validate_job_result(fence, result):
    try:
        result=_object(result) if isinstance(result,str) else _object(serialize_packet(result))
        field='memory_ids' if fence.phase=='leaf' else 'section_ids'
        expected=([str(source.id) for source in fence.sources] if fence.phase=='leaf' else
            [section.id for child in fence.child_groups for section in child.sections])
        if (set(result)!={'title','sections'} or not isinstance(result['title'],str)
                or not 1<=len(result['title'])<=200 or not isinstance(result['sections'],list)
                or not 1<=len(result['sections'])<=100):
            raise ValueError()
        actual=[]
        for section in result['sections']:
            if (not isinstance(section,dict) or set(section)!={'title',field}
                    or not isinstance(section['title'],str) or not 1<=len(section['title'])<=200
                    or not isinstance(section[field],list) or not section[field]
                    or any(not isinstance(value,str) for value in section[field])):
                raise ValueError()
            actual.extend(section[field])
        if len(actual)!=len(expected) or set(actual)!=set(expected):
            raise ValueError()
        ChildGroup.model_validate(job_summary_metadata(result,UUID(int=0),'0'*64))
    except (ValueError,TypeError,KeyError,RecursionError):
        raise JobOutputInvalid('Collection output requires bounded repair; no source coverage was committed') from None
    return result


class JobPublication:
    def __init__(self,dsn,*,authenticated_owner,send_timeout=2.0,lock_timeout=5.0):
        if not dsn:
            raise PublicationUnavailable('Collection job admission requires a transactional database connection')
        if not 0<send_timeout<=5 or not 0<lock_timeout<=5:
            raise ValueError('Invalid collection job admission timeout')
        self._dsn=dsn;self.owner=UUID(str(authenticated_owner))
        self.send_timeout=send_timeout;self.lock_timeout=lock_timeout

    @asynccontextmanager
    async def guard(self,fence):
        snapshot=JobFence.model_validate(fence).model_dump(mode='json')
        if snapshot['user_id']!=str(self.owner):raise PublicationUnavailable('Collection job owner mismatch')
        from psycopg import AsyncConnection, Error
        from psycopg.types.json import Jsonb
        connection=None
        activation_pending = False
        try:
            try:
                async with asyncio.timeout(self.lock_timeout):
                    connection=await AsyncConnection.connect(self._dsn,connect_timeout=2)
                    await connection.execute('set local role authenticated')
                    await connection.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(self.owner),))
                    await connection.execute("select set_config('lock_timeout',%s,true)",(f'{int(self.lock_timeout*1000)}ms',))
                    lease_started = asyncio.get_running_loop().time()
                    result=await connection.execute('select public.lock_lifetime_collection_job_publication(%s)',(Jsonb(snapshot),))
                    remaining=float((await result.fetchone())[0])
                    lease_deadline = lease_started + remaining
                    from .lifetime_memory_activation import require_provider_activation
                    activation_pending = True
                    await require_provider_activation(connection)
                    activation_pending = False
            except TimeoutError:
                if activation_pending:
                    from .lifetime_memory_activation import CanonicalActivationUnavailable
                    raise CanonicalActivationUnavailable() from None
                raise
            except Error as error:
                from .lifetime_memory_policy import PolicyUnavailable, is_policy_pending
                if is_policy_pending(error):
                    raise PolicyUnavailable() from None
                raise PublicationUnavailable('Collection job page is unavailable or stale') from error
            allowance=min(self.send_timeout, lease_deadline - asyncio.get_running_loop().time() - .1)
            if allowance<=0:raise PublicationUnavailable('Collection job lease expires too soon')
            async with asyncio.timeout(allowance):yield
        finally:
            if connection is not None:await _settle(asyncio.create_task(connection.close()))


class JobRequestBody(LaneRequestBody):
    fence_type = JobFence


def _publisher(bounded,publisher):
    if publisher is None:
        publisher=JobPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),authenticated_owner=bounded.fence.user_id)
    if not callable(getattr(publisher,'guard',None)):raise TypeError('Collection job requires a publication guard')
    return publisher


def _validated(value,model=None):
    bounded=BoundedJobInput.model_validate(value.model_dump(mode='json'))
    if model is not None and model!=bounded.budget.model:
        raise ValueError('Configured organiser model differs from bounded job model')
    return bounded


async def send_bounded_job_request(*,worker_url,worker_secret,bounded_job,worker_transport=None,
        publisher=None,timeout=300):
    check_lane_generation();bounded=_validated(bounded_job)
    if not worker_url or not worker_secret:raise PublicationUnavailable('Collection organiser is unavailable')
    publisher=_publisher(bounded,publisher)
    payload={'user_id':str(bounded.fence.user_id),'project_id':bounded.fence.project_id,
        'agent_role':'organiser','model':bounded.budget.model,'language':bounded.fence.locale,
        'bounded_job':bounded.model_dump(mode='json')}
    body=JobRequestBody(serialize_packet(payload).encode('utf-8'),publisher=publisher,fence=bounded.fence)
    options={'timeout':timeout}
    if worker_transport is not None:options['transport']=worker_transport
    try:
        async with httpx.AsyncClient(**options) as client:
            response=await client.post(worker_url.rstrip('/')+'/internal/codex/turn',
                headers={'X-Codex-Worker-Secret':worker_secret,'Content-Type':'application/json',
                    'Content-Length':str(len(body._content))},content=body)
            if response.status_code==503 and response.headers.get('X-Error-Code')==LaneGenerationPaused.code:
                raise LaneGenerationPaused('Bounded lifetime generation is paused; retry later')
            if response.status_code==502 and response.headers.get('X-Error-Code')==JobOutputInvalid.code:
                raise JobOutputInvalid('Collection output requires bounded repair')
            from .lifetime_memory_policy import PolicyUnavailable
            if response.status_code == 503 and response.headers.get('X-Error-Code') == PolicyUnavailable.code:
                raise PolicyUnavailable()
            from .lifetime_memory_activation import CanonicalActivationUnavailable
            if response.status_code == 503 and response.headers.get('X-Error-Code') == CanonicalActivationUnavailable.code:
                raise CanonicalActivationUnavailable()
            response.raise_for_status();result=response.json()
            if not isinstance(result,dict) or not isinstance(result.get('reply'),str):
                raise JobOutputInvalid('Invalid bounded organiser worker response')
            validate_job_result(bounded.fence,result['reply'])
            return result
    finally:
        await body.aclose()


async def run_bounded_job(*,command,home_root,base_url,api_key,model,bounded_job,publisher=None,
        timeout=240,connection_factory=None,issue14_admission=None,progress=None,
        uid=None,apply_owner=False,effort=None):
    check_lane_generation();bounded=_validated(bounded_job,model)
    check_issue14_dispatch(issue14_admission,role='organiser')
    publisher=_publisher(bounded,publisher)
    fence_json=serialize_packet(bounded.fence.model_dump(mode='json'))
    def request_admission():return _admission(publisher,json.loads(fence_json))
    instructions,schema=job_contract(bounded.fence)
    root=Path(home_root).expanduser().resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
    fence=bounded.fence
    home=root/f'job-{fence.user_id}-{fence.conversation_id}-{fence.snapshot_id}-epoch-{fence.policy_epoch}-page-{fence.page_number}-{uuid4()}'
    home.mkdir(mode=0o700)
    write_config(home,root,os.getuid() if uid is None else uid,provider_config(base_url,model,governed=True),apply_owner=apply_owner)
    async with (connection_factory or CodexConnection)(command,home,
            provider_env={'MEMORY_SPARK_LLM_API_KEY':api_key},timeout=timeout,progress=progress,
            request_admission=request_admission,**issue14_connection_options(issue14_admission)) as connection:
        opened=await open_execution(connection,thread_id=None,compatible=False,
            start_params={'cwd':str(home),'ephemeral':True,'modelProvider':'llm_provider','model':model,
                'approvalPolicy':'never','sandbox':'read-only','baseInstructions':instructions},
            identity={'owner_id':str(fence.user_id),'conversation_id':str(fence.conversation_id)})
        reply=await connection.turn(opened['thread_id'],bounded.packet,output_schema=schema,
            **({'effort':effort} if effort else {}))
        validate_job_result(fence,reply)
    return {'thread_id':opened['thread_id'],'reply':reply,'artifacts':[]}
