"""Deterministic bounded context contracts; canonical evidence remains external."""
from uuid import UUID
import pytest

from apps.api.lifetime_memory_contracts import ContextBudget, IdentityEnvelope, PinnedContinuity, SourceManifest
from apps.api.lifetime_memory_context import build_context, CheckpointRequired, InputLimitExceeded, ContextSource, ContextCheckpoint, TailCoverage

IDENTITY=IdentityEnvelope(owner_id=UUID(int=1),conversation_id=UUID(int=2),project_id='p')
BUDGET=ContextBudget(model='synthetic-byte-bpe',context_window=16000,input_budget=12000,output_headroom=2000)
PINS=PinnedContinuity(preference_revision=2,language='zh-CN',chosen_name='慧博',excluded_topics=['private'])


def source(n,text=None,**kwargs):
    return ContextSource(identity=IDENTITY,policy_epoch=1,source_id=UUID(int=100+n),version=1,sequence=n,original=text or f'第{n}个回忆 A memory in Sydney.',language='zh-CN',**kwargs)


def packet(current,tail=(),retrieved=()):
    first=min((row.sequence for row in tail),default=current.sequence)
    end=first-1
    checkpoint=ContextCheckpoint(checkpoint_id=UUID(int=30000+end),identity=IDENTITY,policy_epoch=1,
        coverage_end=end,model=BUDGET.model,prompt_version='lifetime-v1',pinned=PINS,
        manifest=SourceManifest(identity=IDENTITY,policy_epoch=1,source_revision=end,sources=[])) if end else None
    coverage=TailCoverage(identity=IDENTITY,policy_epoch=1,after_sequence=end,through_sequence=current.sequence-1,complete=True)
    return build_context(identity=IDENTITY,policy_epoch=1,pinned=PINS,instructions='Only authorized storyteller evidence is testimony.',
        current=current,tail=tail,retrieved=retrieved,budget=BUDGET,checkpoint=checkpoint,tail_coverage=coverage)


def test_current_boundary_is_included_exactly_once_and_packets_are_bounded():
    current=source(41)
    result=packet(current,tail=[source(40),current],retrieved=[source(3,'I carried a rare blue umbrella.'),source(40),current])
    assert result['source_ids'].count(str(current.source_id)) == 1
    assert len(result['source_ids']) == len(set(result['source_ids']))
    assert result['input_tokens_upper_bound'] <= BUDGET.input_budget
    assert result['pinned']['chosen_name'] == '慧博'
    assert result['pinned']['excluded_topics'] == ['private']


def test_old_facts_keep_exact_version_span_and_never_become_public_testimony():
    fact=source(3,'I carried a rare blue umbrella.')
    result=packet(source(9900),retrieved=[fact])
    item=result['retrieved'][0]
    assert item['source_id'] == str(fact.source_id) and item['version']==1
    assert item['char_start']==0 and item['char_end']==len(fact.original)
    with pytest.raises(ValueError):
        source(4,kind='public_news')


def test_oversized_current_is_rejected_before_acceptance_not_truncated():
    with pytest.raises(InputLimitExceeded):
        packet(source(1,'界'*12000))


def test_complete_tail_overflow_requires_checkpoint_instead_of_dropping_turns():
    with pytest.raises(CheckpointRequired):
        packet(source(100),tail=[source(n,'Memory '*100) for n in range(1,100)])


def test_optional_retrieval_budget_reports_incomplete_instead_of_silent_loss():
    result=packet(source(10000),retrieved=[source(n,'Memory '*100) for n in range(1,40)])
    assert result['retrieval_complete'] is False
    assert result['input_tokens_upper_bound']<=BUDGET.input_budget


def test_no_refresh_decision_depends_on_lifetime_round_number():
    for n in [39,40,41,100,10000]:
        result=packet(source(n))
        assert result['checkpoint_required'] is False


def test_missing_tail_page_or_gap_cannot_be_reported_as_complete():
    from apps.api.lifetime_memory_context import TailCoverage
    with pytest.raises(ValueError,match='coverage'):
        build_context(identity=IDENTITY,policy_epoch=1,pinned=PINS,instructions='safe',current=source(41),
            tail=[source(40)],retrieved=[],budget=BUDGET,
            tail_coverage=TailCoverage(identity=IDENTITY,policy_epoch=1,after_sequence=0,through_sequence=40,complete=True))


def test_checkpoint_payload_is_required_and_is_present_in_packet():
    result=packet(source(41),tail=[source(40)])
    assert result['checkpoint']['coverage_end']==39
    assert result['checkpoint']['pinned']['chosen_name']=='慧博'
    assert result['checkpoint']['schema_version']==1


def test_checkpoint_prompt_version_cannot_be_silently_reused():
    from apps.api.lifetime_memory_context import TailCoverage
    checkpoint=ContextCheckpoint(checkpoint_id=UUID(int=90000),identity=IDENTITY,policy_epoch=1,
        coverage_end=40,model=BUDGET.model,prompt_version='old-prompt',pinned=PINS,
        manifest=SourceManifest(identity=IDENTITY,policy_epoch=1,source_revision=40,sources=[]))
    with pytest.raises(ValueError,match='checkpoint'):
        build_context(identity=IDENTITY,policy_epoch=1,pinned=PINS,instructions='safe',current=source(41),
            tail=[],retrieved=[],budget=BUDGET,checkpoint=checkpoint,
            tail_coverage=TailCoverage(identity=IDENTITY,policy_epoch=1,after_sequence=40,through_sequence=40,complete=True))


def test_multiple_exact_spans_of_one_source_are_not_silently_discarded():
    first=source(3,'First excerpt',char_start=0)
    later=source(3,'A later excerpt',char_start=4000)
    result=packet(source(9900),retrieved=[first,later])
    assert len(result['retrieved'])==2
    assert [row['char_start'] for row in result['retrieved']]==[0,4000]
