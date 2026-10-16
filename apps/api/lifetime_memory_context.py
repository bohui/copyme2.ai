"""One deterministic bounded packet builder for worker and in-process execution.

Callers supply already paginated canonical rows, never an all-lifetime collection.
Ownership/status/epoch are checked again here before selection, not after ranking.
"""
from __future__ import annotations
import json
from typing import Literal
from uuid import UUID
from pydantic import Field

from .lifetime_memory_summary import AcceptedMemorySummary
from .lifetime_memory_contracts import Contract, IdentityEnvelope, PinnedContinuity, EvidenceEnvelope, ContextBudget, SourceManifest


class InputLimitExceeded(ValueError):
    """Reject this request before durable acceptance; preserve the full input."""


class CheckpointRequired(ValueError):
    """Publish a validated checkpoint before retrying; never drop the raw tail."""


class ContextSource(Contract):
    identity: IdentityEnvelope
    source_id: UUID
    version: int = Field(ge=1, strict=True)
    sequence: int = Field(ge=1, strict=True)
    original: str = Field(min_length=1,max_length=100000)
    char_start: int = Field(default=0,ge=0,strict=True)
    language: Literal['en-AU','zh-CN']
    kind: Literal['narrator_chat','narrator_transcript'] = 'narrator_chat'
    status: Literal['active'] = 'active'
    policy_epoch: int = Field(ge=1,strict=True)
    conversation_saved: bool = False
    assistant_reply: str | None = Field(default=None,max_length=100000)
    reply_policy_epoch: int | None = Field(default=None,ge=1,strict=True)



class ContextCheckpoint(Contract):
    checkpoint_id: UUID
    predecessor_id: UUID | None = None
    identity: IdentityEnvelope
    policy_epoch: int = Field(ge=1, strict=True)
    coverage_end: int = Field(ge=1, strict=True)
    model: str = Field(min_length=1,max_length=200)
    prompt_version: str = Field(min_length=1,max_length=100)
    pinned: PinnedContinuity
    manifest: SourceManifest
    evidence: list[EvidenceEnvelope] = Field(default_factory=list,max_length=16)
    memory_summary: AcceptedMemorySummary | None = Field(default=None,exclude_if=lambda value:value is None)


class TailCoverage(Contract):
    identity: IdentityEnvelope
    policy_epoch: int = Field(ge=1, strict=True)
    after_sequence: int = Field(ge=0, strict=True)
    through_sequence: int = Field(ge=0, strict=True)
    complete: bool
    tombstones: list[int] = Field(default_factory=list,max_length=256)

def serialize_packet(packet):
    return json.dumps(packet,ensure_ascii=False,separators=(',',':'),sort_keys=True)


def _measure(packet,budget):
    # Include the self-describing counter itself, not only evidence text.
    packet['input_tokens_upper_bound']=0
    for _ in range(8):
        count=budget.count(serialize_packet(packet))
        if count==packet['input_tokens_upper_bound']:
            return count
        packet['input_tokens_upper_bound']=count
    raise ValueError('context counter did not stabilize')


def build_context(*,identity:IdentityEnvelope,policy_epoch:int,pinned:PinnedContinuity,
                  instructions:str,current:ContextSource,tail,retrieved,budget:ContextBudget,
                  checkpoint:ContextCheckpoint | None=None,tail_coverage:TailCoverage,
                  retrieval_complete:bool=True,prompt_version:str='lifetime-v1',fence=None,interview_context=None):
    """Mandatory pins/current/tail fit first; optional retrieval may be incomplete.

    coverage_end is from a separately validated published checkpoint. Lifetime
    round count is neither supplied nor used. All emitted source spans are exact.
    """
    if not pinned.privacy_complete:
        raise InputLimitExceeded('Active privacy constraints do not fit the request; no partial policy can be used')
    coverage_end=checkpoint.coverage_end if checkpoint else 0
    if coverage_end>=current.sequence:
        raise ValueError('checkpoint must precede current accepted source')
    if checkpoint and (checkpoint.identity!=identity or checkpoint.policy_epoch!=policy_epoch
       or checkpoint.pinned!=pinned or checkpoint.model!=budget.model or checkpoint.prompt_version!=prompt_version
       or checkpoint.manifest.identity!=identity or checkpoint.manifest.policy_epoch!=policy_epoch):
        raise ValueError('stale checkpoint identity/policy/preferences/model')
    if checkpoint:
        versions={ref.source_id:ref.version for ref in checkpoint.manifest.sources}
        for claim in checkpoint.evidence:
            if (versions.get(claim.source_id)!=claim.version or claim.policy_epoch!=policy_epoch
                or 'conversation' not in claim.allowed_use):
                raise ValueError('checkpoint evidence is outside its authorized manifest')
        if checkpoint.memory_summary:
            if checkpoint.memory_summary.processed_through!=checkpoint.coverage_end:
                raise ValueError('Summary processing watermark differs from checkpoint')
            for item in checkpoint.memory_summary.items:
                for ref in item.source_refs:
                    if versions.get(UUID(ref.source_id))!=ref.version:
                        raise ValueError('Summary citation is outside its authorized manifest')
    if (tail_coverage.identity!=identity or tail_coverage.policy_epoch!=policy_epoch
       or not tail_coverage.complete or tail_coverage.after_sequence!=coverage_end
       or tail_coverage.through_sequence!=current.sequence-1):
        raise ValueError('incomplete or mismatched tail coverage')
    tail=list(tail)
    uncovered=[row for row in tail if row.source_id!=current.source_id]
    sequences=[row.sequence for row in uncovered]+tail_coverage.tombstones
    if len(sequences)!=len(set(sequences)) or sorted(sequences)!=list(range(coverage_end+1,current.sequence)):
        raise ValueError('uncovered tail coverage has gaps or duplicates')
    if any(row.source_id==current.source_id and row!=current for row in tail):
        raise ValueError('conflicting current source duplicate')
    if len({row.source_id for row in uncovered})!=len(uncovered):
        raise ValueError('conflicting source sequence coverage')
    def evidence(source):
        if source.identity!=identity or source.policy_epoch!=policy_epoch:
            raise ValueError('source owner/conversation/policy mismatch')
        return EvidenceEnvelope(source_id=source.source_id,version=source.version,char_start=source.char_start,
            char_end=source.char_start+len(source.original),original=source.original,language=source.language,
            assertion='asserted',allowed_use=['conversation'],policy_epoch=policy_epoch).model_dump(mode='json')
    def exchange(source):
        item={'sequence':source.sequence,'narrator':evidence(source),'conversation_saved':source.conversation_saved}
        if source.assistant_reply is not None:
            if source.reply_policy_epoch!=policy_epoch:
                raise ValueError('assistant repetition has stale or absent provenance')
            item.update(assistant={'role':'assistant','text':source.assistant_reply,'personal_testimony':False},conversation_saved=True)
        return item
    packet={'schema_version':1,'model':budget.model,'prompt_version':prompt_version,
            **({'fence':fence} if fence is not None else {}),
            **({'interview_context':{k:v for k,v in interview_context.items() if k not in {'source','sources'}}} if interview_context is not None else {}),
            'identity':identity.model_dump(mode='json'),'policy_epoch':policy_epoch,
        'instructions':instructions,'pinned':pinned.model_dump(mode='json'),'coverage_end':coverage_end,
        'checkpoint':checkpoint.model_dump(mode='json') if checkpoint else None,
        'current':exchange(current),'tail':[],'retrieved':[],'source_ids':[str(current.source_id)],
        'retrieval_complete':retrieval_complete,'checkpoint_required':False,'input_tokens_upper_bound':0}
    if _measure(packet,budget)>budget.input_budget:
        raise InputLimitExceeded('Current input and mandatory instructions/preferences exceed the declared input budget')
    seen={current.source_id:current.version}
    previous=coverage_end
    for source in tail:
        evidence(source)  # Never silently ignore a foreign or stale duplicate.
        if source.sequence<=coverage_end:
            continue
        if source.source_id in seen:
            if source.version!=seen[source.source_id]:
                raise ValueError('conflicting source versions')
            continue
        if source.sequence<=previous or source.sequence>=current.sequence:
            raise ValueError('uncovered tail must be ordered before the current turn')
        previous=source.sequence
        packet['tail'].append(exchange(source));packet['source_ids'].append(str(source.source_id))
        seen[source.source_id]=source.version
        if _measure(packet,budget)>budget.input_budget:
            raise CheckpointRequired('Complete uncovered tail requires an occupancy-triggered checkpoint')
    covered_source_ids=set(seen)
    seen_spans=set()
    for source in retrieved:
        item=evidence(source)
        if source.source_id in seen and source.version!=seen[source.source_id]:
            raise ValueError('conflicting source versions')
        span=(source.source_id,source.version,source.char_start,source.char_start+len(source.original))
        if source.source_id in covered_source_ids or span in seen_spans:
            continue
        new_id=source.source_id not in seen
        packet['retrieved'].append(item)
        if new_id:packet['source_ids'].append(str(source.source_id))
        original_complete=packet['retrieval_complete'];packet['retrieval_complete']=False
        if _measure(packet,budget)>budget.input_budget:
            packet['retrieved'].pop()
            if new_id:packet['source_ids'].pop()
            _measure(packet,budget)
            break
        packet['retrieval_complete']=original_complete
        seen[source.source_id]=source.version;seen_spans.add(span)
    _measure(packet,budget)
    return packet
