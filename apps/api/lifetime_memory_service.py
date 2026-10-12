"""Canonical retrieval/checkpoint coordinator with explicit bounded work.

Transport-neutral RPC adapter shared by worker and in-process preparation. No
provider calls, lifetime-sized collections, commercial counters or source writes.
"""
from __future__ import annotations
import re
from .lifetime_memory_contracts import IdentityEnvelope, PinnedContinuity, EvidenceEnvelope
from .lifetime_memory_context import ContextSource, ContextCheckpoint, TailCoverage, build_context, CheckpointRequired


STOP_WORDS={'about','what','when','where','which','that','this','tell','remember','memory','please','could','would','have','with','from','your','mine','more','there','were','then'}


def lexical_terms(text):
    words=[word.lower() for word in re.findall(r'[A-Za-z]{3,}|[\u3400-\u9fff]{2,}',text)]
    terms=[]
    for word in words:
        candidates=[word] if word.isascii() else [word[i:i+2] for i in range(len(word)-1)]
        for candidate in candidates:
            if candidate not in STOP_WORDS and candidate not in terms:
                terms.append(candidate)
    return terms[:8]


class MaintenancePending(RuntimeError):
    """Canonical interval needs complete durable maintenance before compaction."""


class LifetimeMemoryService:
    def __init__(self,rpc,*,budget,prompt_version='lifetime-v1'):
        self.rpc=rpc;self.budget=budget;self.prompt_version=prompt_version

    def assemble(self,*,fence,current,instructions,tail,tail_coverage,interview_context=None):
        """Tail must be a complete bounded canonical page result, not a guess."""
        identity=IdentityEnvelope.model_validate(fence['identity']);epoch=fence['policy_epoch']
        pins=PinnedContinuity.model_validate(self.rpc('read_lifetime_pinned',p_conversation_id=str(identity.conversation_id)))
        if not pins.privacy_complete:
            raise MaintenancePending('The source is accepted; active privacy constraints need maintenance before another model request')
        saved=self.rpc('read_lifetime_checkpoint',p_conversation_id=str(identity.conversation_id),p_policy_epoch=epoch,
            p_model=self.budget.model,p_prompt_version=self.prompt_version)
        checkpoint=ContextCheckpoint.model_validate(saved) if saved else None
        retrieved=[];seen=set();complete=True
        terms=lexical_terms(current.original)
        for term in terms or ['']:
            # At most eight lexical pages, or one honest bounded canonical fallback.
            page=self.rpc('read_lifetime_source_page',p_conversation_id=str(identity.conversation_id),p_policy_epoch=epoch,
                p_limit=8,p_query=term)
            complete=complete and page['complete']
            for row in page['records']:
                if row['status']!='active' or (row['source_id'],row['version'],row['char_start'],row['char_end']) in seen:continue
                seen.add((row['source_id'],row['version'],row['char_start'],row['char_end']))
                retrieved.append(ContextSource(identity=identity,policy_epoch=epoch,source_id=row['source_id'],
                    version=row['version'],sequence=row['sequence'],original=row['text'],char_start=row['char_start'],language=row['language'],kind=row['kind']))
        if terms and not retrieved:
            complete=False
            page=self.rpc('read_lifetime_source_page',p_conversation_id=str(identity.conversation_id),p_policy_epoch=epoch,p_limit=8)
            for row in page['records']:
                if row['status']=='active':
                    retrieved.append(ContextSource(identity=identity,policy_epoch=epoch,source_id=row['source_id'],version=row['version'],
                        sequence=row['sequence'],original=row['text'],char_start=row['char_start'],language=row['language'],kind=row['kind']))
        args=dict(identity=identity,policy_epoch=epoch,pinned=pins,instructions=instructions,current=current,
            retrieved=retrieved,budget=self.budget,prompt_version=self.prompt_version,retrieval_complete=complete,fence=fence,interview_context=interview_context)
        try:
            if not tail_coverage.complete:raise CheckpointRequired('Incomplete local tail requires a complete canonical maintenance proof')
            return build_context(**args,tail=tail,tail_coverage=tail_coverage,checkpoint=checkpoint)
        except CheckpointRequired:
            if current.sequence<=1:raise
            proof=self.rpc('begin_lifetime_compaction',p_fence=fence,p_through_sequence=current.sequence-1)
            for _ in range(8):
                if proof['complete']:break
                proof=self.rpc('step_lifetime_compaction',p_id=proof['id'],p_fence=fence,p_expected_revision=proof['revision'])
            if not proof['complete']:
                raise MaintenancePending('Canonical coverage maintenance remains pending; the durable cursor is resumable')
            selected=[]
            for row in [*retrieved,*list(tail)[-1:]]:
                if row.sequence>=current.sequence or len(selected)>=2:continue
                quote=row.original[:2000]
                claim=EvidenceEnvelope(source_id=row.source_id,version=row.version,char_start=row.char_start,
                    char_end=row.char_start+len(quote),original=quote,language=row.language,assertion='asserted',
                    allowed_use=['conversation'],policy_epoch=epoch).model_dump(mode='json')
                if claim not in selected:selected.append(claim)
            candidate=self.rpc('create_lifetime_checkpoint',p_fence=fence,p_coverage_end=current.sequence-1,
                p_model=self.budget.model,p_prompt_version=self.prompt_version,p_evidence=selected,p_coverage_proof=proof['id'])
            self.rpc('publish_lifetime_checkpoint',p_id=candidate,p_fence=fence)
            saved=self.rpc('read_lifetime_checkpoint',p_conversation_id=str(identity.conversation_id),p_policy_epoch=epoch,
                p_model=self.budget.model,p_prompt_version=self.prompt_version)
            checkpoint=ContextCheckpoint.model_validate(saved)
            covered=TailCoverage(identity=identity,policy_epoch=epoch,after_sequence=checkpoint.coverage_end,
                through_sequence=current.sequence-1,complete=True)
            return build_context(**args,tail=[],tail_coverage=covered,checkpoint=checkpoint)
