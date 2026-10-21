"""Governed collector execution: one complete packet, one fresh bounded turn.

Canonical storage owns identity and fences. These transports validate the
server-built packet again but cannot establish that a database lease is still
current: the coordinator must gate every emission and the final commit. Engine
homes and transcripts are disposable; they are never a source of personal truth.
"""
from __future__ import annotations

from .model_request import instruction_manifest, manifest_metadata
from .llm_tracing import trace_llm_call

from copy import deepcopy
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import Field, StrictBool, model_validator

from .prompt_artifact import load_prompt_artifact, prompt_path
from .codex_agent import CodexConnection, CodexTurnIncomplete, provider_config
from .codex_worker_files import write_config
from .lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
from .interview_plan import constrain_acknowledgement
from .issue14_execution_admission import check_issue14_dispatch, issue14_connection_options
from .lifetime_memory_context import ContextCheckpoint, serialize_packet
from .lifetime_memory_contracts import (
    Contract, ContextBudget, EvidenceEnvelope, ExecutionFence, IdentityEnvelope,
    PinnedContinuity,
)
from .lifetime_memory_execution import open_execution
from .lifetime_memory_publication import ProviderPublication
from .diagnostics import configure_diagnostic_logger, log_diagnostic


diagnostic_logger = configure_diagnostic_logger(logging.getLogger('memoir.collector.diagnostics'))


# Native outputSchema also constrains commentary. Forcing a preamble required
# extra schema-shaped messages and slowed final replies in the issue 53 probes.
# Stream the acknowledgement from this single final document instead.
GOVERNED_TURN_PROMPT = load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/governed-turn'))
# The installed pooled and dedicated collector aliases route to the same byte-BPE
# model. No wildcard or arbitrary operator-defined alias is admitted.
SUPPORTED_BYTE_BOUND_MODELS = frozenset({'gpt-5.6-luna-pooled', 'gpt-5.6-luna-memoir-low',
    'gpt-5.6-luna-memoir-high', 'synthetic-byte-bpe'})
SUPPORTED_PROMPT_VERSIONS = frozenset({'lifetime-v1'})


class CollectorResponseUnavailable(RuntimeError):
    code = 'LIFETIME_RESPONSE_PENDING'


class CollectorOutputInvalid(CollectorResponseUnavailable):
    code = 'LIFETIME_COLLECTOR_OUTPUT_INVALID'

    def __init__(self, message, *, reason='OUTPUT_CONTRACT'):
        super().__init__(message)
        self.reason = reason


class _AssistantExchange(Contract):
    role: Literal['assistant']
    text: str = Field(min_length=1, max_length=100000)
    personal_testimony: Literal[False]


class _Exchange(Contract):
    sequence: int = Field(ge=1, strict=True)
    narrator: EvidenceEnvelope
    conversation_saved: StrictBool
    assistant: _AssistantExchange | None = None

    @model_validator(mode='after')
    def saved_reply(self):
        if self.conversation_saved != (self.assistant is not None):
            raise ValueError('Saved exchange requires its assistant reply')
        return self


class _Packet(Contract):
    identity: IdentityEnvelope
    fence: ExecutionFence
    policy_epoch: int = Field(ge=1, strict=True)
    model: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=100)
    instructions: str = Field(min_length=1, max_length=100000)
    pinned: PinnedContinuity
    coverage_end: int = Field(ge=0, strict=True)
    checkpoint: ContextCheckpoint | None
    current: _Exchange
    tail: list[_Exchange] = Field(max_length=256)
    retrieved: list[EvidenceEnvelope] = Field(max_length=256)
    source_ids: list[UUID] = Field(min_length=1, max_length=256)
    retrieval_complete: StrictBool
    checkpoint_required: Literal[False]
    input_tokens_upper_bound: int = Field(ge=1, strict=True)
    interview_context: dict[str, Any]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate governed packet key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('Non-finite governed packet data')


def _parse_packet(value):
    try:
        raw = json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        packet = _Packet.model_validate(raw)
    except (ValueError, TypeError, RecursionError):
        # Pydantic errors can include a whole private source. Never expose it.
        raise ValueError('Invalid governed packet contract') from None
    if serialize_packet(raw) != value:
        raise ValueError('Governed packet must use canonical serialization')
    return packet


class GovernedCollectorInput(Contract):
    """Internal-only transport; no user-wide profile, legacy memory or secrets."""
    packet: str = Field(min_length=1, max_length=10_000_000)
    fence: ExecutionFence
    budget: ContextBudget
    prompt_version: str = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_packet(self):
        packet = _parse_packet(self.packet)
        if (self.budget.context_window > 131072 or self.budget.input_budget > 65536
                or (self.budget.model != 'synthetic-byte-bpe' and self.budget.framing_headroom < 2048)):
            raise ValueError('Governed collector budget exceeds the reviewed transport limits')
        if self.budget.model not in SUPPORTED_BYTE_BOUND_MODELS:
            raise ValueError('No reviewed tokenizer bound for governed model')
        if self.prompt_version not in SUPPORTED_PROMPT_VERSIONS:
            raise ValueError('Unsupported governed prompt version')
        if packet.model != self.budget.model or packet.prompt_version != self.prompt_version:
            raise ValueError('Governed model or prompt is incompatible')
        if packet.fence != self.fence or packet.identity != self.fence.identity or packet.policy_epoch != self.fence.policy_epoch:
            raise ValueError('Governed packet fence does not match')
        if not packet.pinned.privacy_complete:
            raise ValueError('Governed privacy constraints are incomplete')
        if packet.pinned.preference_revision != self.fence.preference_revision:
            raise ValueError('Governed preferences are stale')
        count = self.budget.count(self.packet)
        if count != packet.input_tokens_upper_bound or count > self.budget.input_budget:
            raise ValueError('Governed packet exceeds or misstates its input budget')
        if packet.current.conversation_saved or packet.current.sequence <= packet.coverage_end:
            raise ValueError('Governed current turn must be unsaved and uncovered')
        source_ids = [packet.current.narrator.source_id] + [row.narrator.source_id for row in packet.tail]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError('Duplicate current or tail narrator evidence')
        previous = packet.coverage_end
        claims = [packet.current.narrator]
        for row in packet.tail:
            if not previous < row.sequence < packet.current.sequence:
                raise ValueError('Governed tail must be ordered before current source')
            previous = row.sequence
            claims.append(row.narrator)
        spans = set()
        covered = set(source_ids)
        for claim in packet.retrieved:
            span = (claim.source_id, claim.version, claim.char_start, claim.char_end)
            if claim.source_id in covered or span in spans:
                raise ValueError('Duplicate current, tail or retrieved narrator evidence')
            spans.add(span)
            claims.append(claim)
            if claim.source_id not in source_ids:
                source_ids.append(claim.source_id)
        if packet.source_ids != source_ids:
            raise ValueError('Governed source identity manifest is inconsistent')
        checkpoint = packet.checkpoint
        if checkpoint:
            if (checkpoint.identity != packet.identity or checkpoint.policy_epoch != packet.policy_epoch
                    or checkpoint.model != packet.model or checkpoint.prompt_version != packet.prompt_version
                    or checkpoint.pinned != packet.pinned or checkpoint.coverage_end != packet.coverage_end
                    or checkpoint.manifest.identity != packet.identity
                    or checkpoint.manifest.policy_epoch != packet.policy_epoch
                    or checkpoint.manifest.source_revision > self.fence.source_revision):
                raise ValueError('Governed checkpoint is incompatible')
            versions = {ref.source_id:ref.version for ref in checkpoint.manifest.sources}
            for claim in checkpoint.evidence:
                if (claim.source_id == packet.current.narrator.source_id
                        or versions.get(claim.source_id) != claim.version):
                    raise ValueError('Governed checkpoint evidence is inconsistent')
            if checkpoint.memory_summary:
                if checkpoint.memory_summary.processed_through!=checkpoint.coverage_end:
                    raise ValueError('Governed summary watermark is inconsistent')
                for item in checkpoint.memory_summary.items:
                    for ref in item.source_refs:
                        if versions.get(UUID(ref.source_id))!=ref.version or UUID(ref.source_id)==packet.current.narrator.source_id:
                            raise ValueError('Governed summary citation is inconsistent')
            claims.extend(checkpoint.evidence)
        elif packet.coverage_end:
            raise ValueError('Governed coverage requires its checkpoint')
        versions = {}
        for claim in claims:
            if claim.policy_epoch != packet.policy_epoch or 'conversation' not in claim.allowed_use:
                raise ValueError('Governed evidence has stale or unauthorized policy')
            if claim.source_id in versions and versions[claim.source_id] != claim.version:
                raise ValueError('Governed evidence has conflicting source versions')
            versions[claim.source_id] = claim.version
        if checkpoint and checkpoint.memory_summary:
            for item in checkpoint.memory_summary.items:
                for ref in item.source_refs:
                    source_id=UUID(ref.source_id)
                    if source_id in versions and versions[source_id]!=ref.version:
                        raise ValueError('Governed summary has conflicting source versions')
                    versions[source_id]=ref.version
        if {'source', 'sources'} & packet.interview_context.keys():
            raise ValueError('Governed interview context cannot duplicate narrator evidence')
        return self


def governed_request_overhead(interview_context, budget: ContextBudget, *, output_schema=None,
        prompt=GOVERNED_TURN_PROMPT) -> int:
    """Reserve the actual schema, fixed input and conservative protocol framing."""
    return (budget.count(prompt)
        + budget.count(serialize_packet(output_schema if output_schema is not None
            else governed_collector_schema(interview_context))) + budget.framing_headroom)


def governed_request_tokens(packet: str, interview_context, budget: ContextBudget) -> int:
    return budget.count(packet) + governed_request_overhead(interview_context, budget)


def validate_governed_context(governed: GovernedCollectorInput, interview_context, *, model=None):
    """Validate even model_copy()/mutable dictionaries at the actual send seam."""
    governed = GovernedCollectorInput.model_validate(governed.model_dump(mode='json'))
    packet = _parse_packet(governed.packet)
    if model is not None and model != governed.budget.model:
        raise ValueError('Configured collector model differs from governed budget')
    if not isinstance(interview_context, dict):
        raise ValueError('Governed collector requires its bounded interview context')
    try:
        serialized = serialize_packet(interview_context)
    except (TypeError, ValueError, RecursionError):
        raise ValueError('Invalid governed interview context') from None
    if governed.budget.count(serialized) > governed.budget.input_budget:
        raise ValueError('Governed interview context exceeds the input budget')
    projection = {key:value for key,value in interview_context.items() if key not in {'source','sources'}}
    if projection != packet.interview_context:
        raise ValueError('Governed interview context differs from packet')
    if interview_context.get('interview_language') != packet.pinned.language:
        raise ValueError('Governed context language differs from pinned language')
    source = interview_context.get('source')
    current = packet.current.narrator
    if (not isinstance(source, dict) or source.get('id') != str(current.source_id)
            or type(source.get('version')) is not int or source['version'] != current.version
            or source.get('text') != current.original or source.get('status') != 'active'):
        raise ValueError('Governed interview context current source differs from packet')
    # This validation-only reconstruction cannot introduce extra evidence. Exact
    # spans remain distinct; never concatenate excerpts into invented testimony.
    allowed = {(str(row.source_id), row.version, row.original)
        for row in [current, *[exchange.narrator for exchange in packet.tail], *packet.retrieved]}
    sources = interview_context.get('sources', [])
    if not isinstance(sources, list) or len(sources) > 256:
        raise ValueError('Invalid governed context source list')
    for row in sources:
        if (not isinstance(row, dict) or row.get('status') != 'active'
                or type(row.get('version')) is not int
                or (row.get('id'), row.get('version'), row.get('text')) not in allowed):
            raise ValueError('Governed interview context has unsupported source evidence')
    if governed_request_tokens(governed.packet, interview_context, governed.budget) > governed.budget.input_budget:
        raise ValueError('Governed packet, schema, prompt and framing exceed the input budget')
    return packet


async def run_governed_collector(**options):
    """Retry rejected output in fresh bounded homes within the original timeout."""
    options={**options,'interview_context':deepcopy(options['interview_context']),
        'governed':GovernedCollectorInput.model_validate(options['governed'].model_dump(mode='json'))}
    acknowledgement = options['interview_context'].get('reviewed_acknowledgement')
    original_delta = options.get('on_delta')
    if original_delta:
        async def observed_delta(text):
            nonlocal acknowledgement
            if text:
                value = json.loads(text)['acknowledgement']
                if acknowledgement is None:
                    acknowledgement = value
                    await original_delta(text)
        options['on_delta'] = observed_delta
    attempts=3
    repair_reason=None
    invalid_attempts=0
    incomplete_retry_used=False
    async with asyncio.timeout(options.get('timeout',120)):
        # One incomplete provider document can be replaced without consuming a validation attempt.
        for _ in range(attempts+1):
            try:
                return await _run_governed_collector_once(**options, acknowledgement=acknowledgement,
                    repair_reason=repair_reason)
            except CollectorOutputInvalid as error:
                repair_reason=error.reason
                invalid_attempts+=1
                if invalid_attempts==attempts:
                    raise
            except CodexTurnIncomplete:
                repair_reason='INCOMPLETE_PROVIDER_OUTPUT'
                if incomplete_retry_used:
                    raise CollectorResponseUnavailable('The saved message needs another response attempt') from None
                incomplete_retry_used=True


async def _run_governed_collector_once(*, command, home_root, base_url, api_key, model,
        governed: GovernedCollectorInput, interview_context, thread_id=None,
        timeout=120, on_delta=None, on_event=None, effort=None,
        responsesapi_client_metadata=None, connection_factory=None,
        issue14_admission=None, trajectory=None, progress=None, uid=None, apply_owner=False, publisher=None,
        acknowledgement=None,repair_reason=None):
    """Generate once from canonical evidence, returning an uncommitted pointer.

    No resume is currently admitted because harness transcript size is not
    independently measurable. A missing/corrupt/old home therefore needs no
    backup restore. Provider/auth/timeouts propagate rather than becoming a
    false missing-state recovery. The caller keeps the same product turn and
    publishes this candidate only after its database fence revalidation.
    The admission guard covers delivery into app-server, not opaque downstream
    provider HTTP timing. Admitted work is in flight; output stays separately fenced.
    """
    from .lifetime_memory_lane_engine import check_lane_generation, _admission
    check_lane_generation()
    packet = validate_governed_context(governed, interview_context, model=model)
    output_schema = governed_collector_schema(interview_context)
    prompt=GOVERNED_TURN_PROMPT
    if repair_reason is not None:
        prompt += load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/governed-repair/codes'))
    if repair_reason is not None:
        prompt+=(load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/governed-repair/prefix'))
            +json.dumps({'error_code': repair_reason},ensure_ascii=False)+load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/governed-repair/suffix')))
    if acknowledgement is not None:
        # A fresh-home repair must preserve the acknowledgement already shown.
        constrain_acknowledgement(output_schema, [acknowledgement])
        prompt+=load_prompt_artifact(prompt_path('memoir/skills/memoir-interviewer/governed-repair/acknowledgement'))+json.dumps(acknowledgement,ensure_ascii=False)+'.'
    if (governed.budget.count(governed.packet) + governed_request_overhead(
            interview_context, governed.budget, output_schema=output_schema,prompt=prompt) > governed.budget.input_budget):
        raise CollectorResponseUnavailable('The acknowledged reply exceeds the request budget')
    check_issue14_dispatch(issue14_admission, role='collector', correlation=responsesapi_client_metadata)
    if publisher is None:
        # Server-only configuration, never accepted in WorkerTurnInput. No
        # fallback to a prior RPC check: it cannot fence actual pipe admission.
        publisher = ProviderPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),
            authenticated_owner=packet.identity.owner_id)
    if not callable(getattr(publisher, 'guard', None)):
        raise TypeError('Governed execution requires a publication guard')
    fence_snapshot = serialize_packet(packet.fence.model_dump(mode='json'))
    def request_admission():
        # Each guard gets a fresh detached copy of the original exact fence.
        # A later publication-phase setter cannot relabel this packet.
        return _admission(publisher, json.loads(fence_snapshot))
    # Snapshot validation-only data before awaiting provider work.
    interview_context = deepcopy(interview_context)
    from .interview_plan import CollectorVisibleStream, historical_acknowledgement_allowed
    visible = CollectorVisibleStream()
    streamed_acknowledgement = None

    async def model_delta(chunk):
        nonlocal streamed_acknowledgement
        value = visible.feed(chunk)
        if (value and historical_acknowledgement_allowed(value, interview_context)
            and (acknowledgement is None or value == acknowledgement)):
            streamed_acknowledgement = value
            # Only the complete validated acknowledgement crosses this boundary.
            await on_delta(json.dumps({'acknowledgement': value}, ensure_ascii=False))
    root = Path(home_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    identity = packet.identity
    home = root / (f'governed-{identity.owner_id}-{identity.conversation_id}'
        f'-epoch-{packet.policy_epoch}-generation-{packet.fence.execution_generation}-{uuid4()}')
    home.mkdir(mode=0o700)
    write_config(home, root, os.getuid() if uid is None else uid,
        provider_config(base_url, model, governed=True), apply_owner=apply_owner)
    factory = connection_factory or CodexConnection
    async with factory(command, home, provider_env={'MEMORY_SPARK_LLM_API_KEY':api_key},
            timeout=timeout, trajectory=trajectory, progress=progress, request_admission=request_admission,
            **issue14_connection_options(issue14_admission)) as connection:
        opened = await open_execution(connection, thread_id=None, compatible=False,
            start_params={'cwd':str(home), 'ephemeral':True, 'modelProvider':'llm_provider',
                'model':model, 'approvalPolicy':'never', 'sandbox':'read-only',
                'baseInstructions':governed.packet}, identity=identity.model_dump(mode='json'))
        candidate = opened['thread_id']
        static_parts = [packet.instructions, GOVERNED_TURN_PROMPT]
        if repair_reason:
            static_parts.extend(load_prompt_artifact(prompt_path(
                'memoir/skills/memoir-interviewer/governed-repair/' + part))
                for part in ('codes', 'prefix', 'suffix'))
        if acknowledgement is not None:
            static_parts.append(load_prompt_artifact(prompt_path(
                'memoir/skills/memoir-interviewer/governed-repair/acknowledgement')))
        manifest = instruction_manifest('\n'.join(static_parts), output_schema,
            variant='collector-repair' if repair_reason else 'collector',
            extra_names=['memoir/shared/historical-acknowledgements']
                if interview_context.get('historical_news',{}).get('clues') else [])
        with trace_llm_call('memoir.' + str('collector-repair' if repair_reason else 'collector'), model, metadata={'contract_version': 'lifetime-v1', 'prompt_manifest': manifest}):
            reply = await connection.turn(candidate, prompt,
                output_schema=output_schema,
                **({'on_delta':model_delta} if on_delta else {}),
                **({'on_event':on_event} if on_event else {}),
                **({'effort':effort} if effort else {}),
                responsesapi_client_metadata={**manifest_metadata(manifest),
                    **(responsesapi_client_metadata or {}),
                    'generation_name': 'memoir-interviewer',
                    'trace_name': 'memoir-interviewer',
                })
        try:
            validated = validate_governed_collector_result(reply, interview_context)
            expected = acknowledgement if acknowledgement is not None else streamed_acknowledgement
            if expected is not None and validated['acknowledgement'] != expected:
                raise ValueError('Correction cannot replace the streamed acknowledgement')
        except (ValueError, TypeError, KeyError) as error:
            reasons = {'A stop cannot force a question': 'CONTRACT_01',
             'Acknowledgement cannot contain a question': 'CONTRACT_02',
             'Candidate identity required': 'CONTRACT_03',
             'Candidate is stale, asked or outside this project': 'CONTRACT_04',
             'Candidate use requires its recorded reason': 'CONTRACT_05',
             'Choose one current candidate': 'CONTRACT_06',
             'Continuity requires exact current narrator evidence': 'CONTRACT_07',
             'Continuity span must cover exact original characters': 'CONTRACT_08',
             'Continuity text must preserve the exact attributed quote': 'CONTRACT_09',
             'Correction cannot replace the streamed acknowledgement': 'CONTRACT_10',
             'Current intent overrides prepared candidates': 'CONTRACT_11',
             'Current intent requires one appropriate follow-up question': 'CONTRACT_12',
             'Current pause requires no question': 'CONTRACT_13',
             'Duplicate continuity update': 'CONTRACT_14',
             'Inferred continuity requires explicit uncertainty': 'CONTRACT_15',
             'No-question outcome requires an explicit reason': 'CONTRACT_16',
             'Only one immediate question is allowed': 'CONTRACT_17',
             'Only one visible question is allowed': 'CONTRACT_18',
             'Prepared candidate text changed': 'CONTRACT_19',
             'Privacy and commitment continuity require asserted direct narrator wording': 'CONTRACT_20',
             'Question candidates must be distinct': 'CONTRACT_21',
             'Question evidence is outside the supplied narrator passages': 'CONTRACT_22',
             'Question evidence needs one exact passage or explicit offsets': 'CONTRACT_23',
             'Question evidence span must match the referenced passage': 'CONTRACT_24',
             'Returning to another event needs a conversational bridge': 'CONTRACT_25',
             'Unknown active event': 'CONTRACT_26',
             'Unknown candidate event': 'CONTRACT_27',
             'Unsupported biographical year': 'CONTRACT_28',
             'Unsupported life stage': 'CONTRACT_29'}
            reason = reasons[str(error)] if str(error) in reasons else 'SCHEMA_OR_OTHER_CONTRACT'
            if isinstance(error,json.JSONDecodeError):reason='INVALID_JSON'
            from pydantic import ValidationError
            if isinstance(error, ValidationError):
                for detail in error.errors(include_input=False, include_url=False):
                    field=detail['loc'][0] if detail['loc'] else None
                    if reason=='SCHEMA_OR_OTHER_CONTRACT' and field in output_schema['properties']:
                        reason='SCHEMA_FIELD_'+field
                    cause = str((detail.get('ctx') or {}).get('error', ''))
                    if cause in reasons:
                        reason = reasons[cause]
                        break
            log_diagnostic(diagnostic_logger, 'collector_output_rejected',
                (responsesapi_client_metadata or {}).get('request_id'),
                component='memoir.collector', agent_role='collector', model=model,
                requested_effort=effort, status='rejected', error_code=reason)
            # A legacy repair appends the invalid answer and another prompt to
            # the same transcript. That would invalidate this request budget.
            raise CollectorOutputInvalid('The interview response could not be validated; please retry the accepted turn',reason=reason) from None
    if on_delta and streamed_acknowledgement is None:
        await on_delta(reply)
    result = {'thread_id':candidate, 'reply':reply, 'artifacts':[],
        'cold_resume_reason':'unvalidated_transcript' if thread_id else 'missing'}
    if trajectory is not None:
        trajectory.finish(result,status='completed',stop_reason='canonical.collector.completed')
        result['trajectory']=trajectory.payload()
    if on_event:
        await on_event({'type':'provider_complete', 'data':{'thread_id':candidate, 'reply':reply,
            'trajectory':result.get('trajectory')}})
    return result
