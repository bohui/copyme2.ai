"""W0 transport invariants; no provider, database, or real-user inputs."""
from copy import deepcopy
from uuid import UUID

import pytest
from pydantic import ValidationError
from apps.api.lifetime_memory_contracts import (
    ContextBudget, EvidenceEnvelope, ExecutionFence, IdentityEnvelope,
    ReceiptEnvelope, inventory_accounts,
)

OWNER = '11111111-1111-4111-8111-111111111111'
CONVERSATION = '22222222-2222-4222-8222-222222222222'


def test_identity_requires_server_resolved_owner_and_version():
    identity = IdentityEnvelope(owner_id=OWNER, conversation_id=CONVERSATION, project_id='original')
    assert identity.schema_version == 1
    assert str(identity.owner_id) == OWNER
    with pytest.raises(ValidationError):
        IdentityEnvelope(owner_id=OWNER, conversation_id=CONVERSATION, project_id='original', schema_version=2)


@pytest.mark.parametrize('changes', [{'context_window': 0}, {'output_headroom': 0},
    {'input_budget': 4097}, {'input_budget': 4096, 'output_headroom': 4096},
    {'input_budget': True}])
def test_budget_rejects_invalid_or_unbounded_configuration(changes):
    settings = dict(model='fixture-byte-bound-v1', context_window=8192, input_budget=4096, output_headroom=1024)
    settings.update(changes)
    # A valid 4097-token input is allowed if it fits the window.
    if changes == {'input_budget': 4097}:
        settings['context_window'] = 4096
    with pytest.raises(ValidationError):
        ContextBudget(**settings)


def test_budget_counts_serialized_utf8_conservatively():
    budget = ContextBudget(model='fixture-byte-bound-v1', context_window=8192, input_budget=4096, output_headroom=1024)
    assert budget.count('我叫慧博') == len('我叫慧博'.encode('utf-8'))
    assert budget.count('hello') == 5
    assert budget.accepts('x' * 4096)
    assert not budget.accepts('x' * 4097)


def test_evidence_preserves_attribution_spans_uncertainty_and_contradictions():
    claim = EvidenceEnvelope(source_id=CONVERSATION, version=3, char_start=2, char_end=5,
        original='我记得', language='zh-CN', assertion='asserted', uncertainty='date uncertain',
        allowed_use=['conversation'], policy_epoch=7, contradicts=['other-claim'])
    assert claim.original == '我记得'
    assert claim.contradicts == ['other-claim']
    with pytest.raises(ValidationError):
        EvidenceEnvelope(**{**claim.model_dump(), 'char_end': 4})
    with pytest.raises(ValidationError):
        EvidenceEnvelope(**{**claim.model_dump(), 'role': 'public_news'})


def test_fence_preserves_phase_and_preference_revision_and_lease_identity():
    fence = ExecutionFence(identity=IdentityEnvelope(owner_id=OWNER, conversation_id=CONVERSATION, project_id='original'),
        policy_epoch=1, source_revision=5, execution_generation=2,
        phase_revision=8, preference_revision=9, lease_token=OWNER)
    assert fence.phase_revision == 8 and fence.preference_revision == 9
    assert fence.lease_token == UUID(OWNER)


def test_receipts_cannot_claim_saved_before_acceptance():
    with pytest.raises(ValidationError):
        ReceiptEnvelope(client_turn_id=OWNER, source_accepted=False, conversation_saved=True)


def test_inventory_is_read_only_preserves_ids_and_refuses_ambiguous_mapping():
    rows = [dict(owner_id=OWNER, projects=[], source_ids=[], turn_ids=[], thread_pointer=None),
        dict(owner_id=CONVERSATION, projects=['old'], source_ids=['s1'], turn_ids=['t1'], thread_pointer='engine-old'),
        dict(owner_id='33333333-3333-4333-8333-333333333333', projects=['old','new'], source_ids=['s2'], turn_ids=['t2'], thread_pointer='engine-new')]
    before = deepcopy(rows)
    result = inventory_accounts(rows)
    assert [row['outcome'] for row in result] == ['new_account', 'mapping_required', 'mapping_required']
    assert result[1]['candidate_project_ids'] == ['old']
    assert result[2]['candidate_project_ids'] == ['old','new']
    assert rows == before
    assert result[2]['source_ids'] == ['s2']


def test_inventory_reports_collision_without_selecting_a_winner():
    result = inventory_accounts([dict(owner_id=OWNER, projects=['p','p'], source_ids=['s','s'], turn_ids=['t','t'], thread_pointer='x')])[0]
    assert result['outcome'] == 'collision'
    assert set(result['collisions']) == {'project_ids', 'source_ids', 'turn_ids'}


def test_source_manifest_is_versioned_scoped_and_rejects_duplicate_source_ids():
    from apps.api.lifetime_memory_contracts import SourceManifest
    identity = IdentityEnvelope(owner_id=OWNER, conversation_id=CONVERSATION, project_id='original')
    manifest = SourceManifest(identity=identity, policy_epoch=3, source_revision=8,
        sources=[{'source_id':OWNER, 'version':2}])
    assert manifest.schema_version == 1 and manifest.sources[0].version == 2
    with pytest.raises(ValidationError):
        SourceManifest(**{**manifest.model_dump(), 'sources':manifest.sources * 2})


@pytest.mark.parametrize('fields', [dict(source_accepted=True, conversation_saved=False),
    dict(source_accepted=True, source_id=OWNER, conversation_saved=True)])
def test_narrator_receipt_requires_durable_ids(fields):
    with pytest.raises(ValidationError):
        ReceiptEnvelope(client_turn_id=OWNER, **fields)


def test_assistant_only_receipt_is_explicit_and_never_counts_as_narrator_acceptance():
    receipt = ReceiptEnvelope(kind='assistant_only', client_turn_id=OWNER,
        source_accepted=False, conversation_saved=True, reply_id=CONVERSATION)
    assert receipt.kind == 'assistant_only'
    with pytest.raises(ValidationError):
        ReceiptEnvelope(**{**receipt.model_dump(), 'source_accepted':True, 'source_id':OWNER})


def test_budget_reserves_declared_framing_and_requires_compatible_tokenizer():
    with pytest.raises(ValidationError):
        ContextBudget(model='fixture', context_window=8192, input_budget=4096, output_headroom=1024, framing_headroom=3073)
    with pytest.raises(ValidationError):
        ContextBudget(model='fixture', context_window=8192, input_budget=4096, output_headroom=1024, tokenizer='unknown')


def test_inventory_retains_project_scoped_source_turn_associations():
    associations = [{'project_id':'old', 'source_id':'same', 'client_turn_id':'same'},
                    {'project_id':'new', 'source_id':'same', 'client_turn_id':'same'}]
    result = inventory_accounts([dict(owner_id=OWNER, projects=['old','new'], evidence=associations)])[0]
    assert result['evidence'] == associations
    assert result['collisions'] == []
    assert result['outcome'] == 'mapping_required'


def test_old_checkpoint_phase_is_discarded_without_changing_other_pins():
    from apps.api.lifetime_memory_contracts import PinnedContinuity
    phase = dict(schema_version=1, phase='shape', selection='explicit', preferred_phase='shape',
        revision=7, reason='narrator_choice', source_turn_id=None)
    pinned = PinnedContinuity(preference_revision=9, language='zh-CN', conversation_phase=phase,
        chosen_name='慧博', active_question='What happened next?', excluded_topics=['private'])
    assert 'conversation_phase' not in pinned.model_dump(mode='json')
    assert pinned.chosen_name=='慧博' and pinned.excluded_topics==['private']
