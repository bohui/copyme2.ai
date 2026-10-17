"""Versioned, strict transports for disposable lifetime-memory projections.

These contracts neither resolve identity in the browser nor manufacture claims.
The database remains authoritative for ownership, versions, policy and leases.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    schema_version: Literal[1] = 1


class IdentityEnvelope(Contract):
    owner_id: UUID
    conversation_id: UUID
    product: Literal['memoir'] = 'memoir'
    project_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class ExecutionFence(Contract):
    identity: IdentityEnvelope
    policy_epoch: int = Field(ge=1, strict=True)
    source_revision: int = Field(ge=0, strict=True)
    execution_generation: int = Field(ge=1, strict=True)
    phase_revision: int = Field(ge=0, strict=True)  # Current SQL emits zero; retained for wire compatibility.
    preference_revision: int = Field(ge=0, strict=True)
    lease_token: UUID


class EvidenceEnvelope(Contract):
    source_id: UUID
    version: int = Field(ge=1, strict=True)
    char_start: int = Field(ge=0, strict=True)
    char_end: int = Field(ge=1, strict=True)
    original: str = Field(min_length=1, max_length=100000)
    language: Literal['en-AU', 'zh-CN']
    role: Literal['storyteller'] = 'storyteller'
    assertion: Literal['asserted', 'inferred']
    uncertainty: str | None = Field(default=None, max_length=2000)
    time_meaning: str | None = Field(default=None, max_length=500)
    translation: str | None = Field(default=None, max_length=100000)
    translation_attribution: str | None = Field(default=None, max_length=200)
    supersedes: list[str] = Field(default_factory=list, max_length=100)
    contradicts: list[str] = Field(default_factory=list, max_length=100)
    allowed_use: list[Literal['conversation', 'extraction', 'composition']] = Field(min_length=1, max_length=3)
    policy_epoch: int = Field(ge=1, strict=True)

    @model_validator(mode='after')
    def validate_span(self):
        if self.char_end - self.char_start != len(self.original):
            raise ValueError('evidence span must cover exact original characters')
        if (self.translation is None) != (self.translation_attribution is None):
            raise ValueError('translation requires attribution')
        return self


class SourceVersion(Contract):
    source_id: UUID
    version: int = Field(ge=1, strict=True)


class SourceManifest(Contract):
    identity: IdentityEnvelope
    policy_epoch: int = Field(ge=1, strict=True)
    source_revision: int = Field(ge=0, strict=True)
    sources: list[SourceVersion] = Field(max_length=256)

    @model_validator(mode='after')
    def unique_sources(self):
        if len({source.source_id for source in self.sources}) != len(self.sources):
            raise ValueError('manifest has duplicate source identities')
        return self


class ContextBudget(Contract):
    model: str = Field(min_length=1, max_length=200)
    context_window: int = Field(ge=1, le=10_000_000, strict=True)
    input_budget: int = Field(ge=1, le=10_000_000, strict=True)
    output_headroom: int = Field(ge=1, le=10_000_000, strict=True)
    framing_headroom: int = Field(default=1024, ge=1, le=10_000_000, strict=True)
    tokenizer: Literal['utf8-byte-upper-bound-v1'] = 'utf8-byte-upper-bound-v1'

    @model_validator(mode='after')
    def validate_window(self):
        if self.input_budget + self.output_headroom + self.framing_headroom > self.context_window:
            raise ValueError('input plus output must leave framing headroom in context window')
        return self

    def count(self, serialized_packet: str) -> int:
        # UTF-8 bytes conservatively upper-bound ordinary byte-level tokenizer
        # text tokens. Caller must include all serialized instructions/metadata;
        # model-specific framing is separately reserved in context_window.
        return len(serialized_packet.encode('utf-8'))

    def accepts(self, serialized_packet: str) -> bool:
        return self.count(serialized_packet) <= self.input_budget


class ReceiptEnvelope(Contract):
    kind: Literal['narrator', 'assistant_only'] = 'narrator'
    client_turn_id: UUID
    source_accepted: bool
    conversation_saved: bool
    source_id: UUID | None = None
    reply_id: UUID | None = None

    @model_validator(mode='after')
    def validate_saved(self):
        if self.kind == 'assistant_only' and (self.source_accepted or self.source_id is not None):
            raise ValueError('assistant-only receipt cannot claim narrator acceptance')
        if self.source_accepted != (self.source_id is not None):
            raise ValueError('source acceptance requires its durable source identity')
        if self.conversation_saved != (self.reply_id is not None):
            raise ValueError('saved reply requires its durable reply identity')
        if self.kind == 'narrator' and self.conversation_saved and not self.source_accepted:
            raise ValueError('a saved narrator reply requires durable source acceptance')
        return self


def inventory_accounts(accounts: list[dict]) -> list[dict]:
    """Inspect an explicitly supplied synthetic/export inventory without writes.

    Even a sole historical project requires an approved mapping. This function
    has no database connection, default input, selection heuristic or side effect.
    """
    result = []
    for account in accounts:
        owner = str(UUID(account['owner_id']))
        projects = list(account.get('projects', []))
        sources = list(account.get('source_ids', []))
        turns = list(account.get('turn_ids', []))
        collisions = [name for name, values in [('project_ids', projects), ('source_ids', sources), ('turn_ids', turns)]
                      if any(count > 1 for count in Counter(values).values())]
        evidence = deepcopy(account.get('evidence', []))
        for key in ('source_id', 'client_turn_id'):
            scoped = [(row['project_id'], row[key]) for row in evidence]
            if any(count > 1 for count in Counter(scoped).values()):
                collisions.append('scoped_' + key)
        if any(row['project_id'] not in projects for row in evidence):
            collisions.append('unmapped_evidence_project')
        result.append(dict(evidence=evidence, owner_id=owner, outcome='collision' if collisions else
            'mapping_required' if projects else 'new_account', candidate_project_ids=projects,
            source_ids=sources, turn_ids=turns, collisions=collisions,
            thread_pointer=account.get('thread_pointer'),
            preference_revision=account.get('preference_revision')))
    return result


class ContinuityRecord(Contract):
    """Evidence-backed continuity, separate from authoritative user preferences.

    Phase and language decisions remain owned by their existing modules/tables.
    These records never silently make an inferred or conflicting assertion true.
    """
    record_id: str = Field(min_length=1, max_length=128)
    kind: Literal['chosen_name', 'language', 'active_question', 'unresolved_reference',
                  'paused_topic', 'excluded_topic', 'commitment', 'person']
    revision: int = Field(ge=1, strict=True)
    policy_epoch: int = Field(ge=1, strict=True)
    text: str = Field(min_length=1, max_length=2000)
    assertion: Literal['asserted', 'inferred']
    uncertainty: str | None = Field(default=None, max_length=2000)
    evidence: list[EvidenceEnvelope] = Field(min_length=1, max_length=32)


class ContinuityQuote(Contract):
    source_id: UUID
    version: int = Field(ge=1,strict=True)
    char_start: int = Field(ge=0,strict=True)
    char_end: int = Field(ge=1,strict=True)
    quote: str = Field(min_length=1,max_length=100000)


class ContinuityData(Contract):
    text: str = Field(min_length=1,max_length=2000)
    assertion: Literal['asserted','inferred']
    uncertainty: str | None = Field(default=None,max_length=2000)
    source_refs: list[ContinuityQuote] = Field(min_length=1,max_length=32)


class ContinuityState(Contract):
    record_id: str = Field(min_length=1,max_length=128)
    kind: Literal['chosen_name','language','active_question','unresolved_reference','paused_topic','excluded_topic','commitment','person']
    revision: int = Field(ge=1,strict=True)
    policy_epoch: int = Field(ge=1,strict=True)
    data: ContinuityData


class PinnedContinuity(Contract):
    @model_validator(mode='before')
    @classmethod
    def discard_retired_phase(cls, value):
        # Old checkpoints remain readable without restoring a mode preference.
        return {k:v for k,v in value.items() if k!='conversation_phase'} if isinstance(value,dict) else value

    known_continuity: list[ContinuityState] = Field(default_factory=list,max_length=8)
    known_continuity_complete: bool = True
    continuity_retrieval: str = 'read_lifetime_continuity'
    preference_revision: int = Field(ge=0, strict=True)
    chosen_name: str | None = Field(default=None, max_length=200)
    language: Literal['en-AU', 'zh-CN']
    active_question: str | None = Field(default=None, max_length=2000)
    privacy_complete: bool = True
    unresolved_references: list[str] = Field(default_factory=list)
    paused_topics: list[str] = Field(default_factory=list)
    excluded_topics: list[str] = Field(default_factory=list)
