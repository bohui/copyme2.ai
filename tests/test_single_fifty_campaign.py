"""Plan and receipt-shape contracts only; no runtime, service or provider imports."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]


def plan(family_enabled=True):
    from scripts.single_fifty_campaign import build_campaign_plan
    return build_campaign_plan(case_id='harbour-copper-notebook', family_enabled=family_enabled,
                               run_id=str(uuid4()))


def test_one_selected_case_keeps_fifty_originals_and_ten_distinct_checkpoints():
    p = plan()
    original = json.loads((ROOT / 'tests/evaluation/memoir_five_case_inputs.json').read_text())
    expected = next(c for c in original['cases'] if c['id'] == 'harbour-copper-notebook')
    assert len(p['cases']) == 1
    case = p['cases'][0]
    assert case['rounds'] == expected['rounds'] and len(case['rounds']) == 50
    assert case['language'] == 'en-AU' and case['family_enabled'] is True
    assert len(p['round_roots']) == len({r['trace_id'] for r in p['round_roots']}) == 50
    assert [r['round'] for r in p['round_roots']] == list(range(1, 51))
    assert [c['milestone'] for c in p['checkpoints']] == list(range(5, 51, 5))
    assert len({c['checkpoint_id'] for c in p['checkpoints']}) == 10
    for checkpoint in p['checkpoints']:
        root = p['round_roots'][checkpoint['milestone'] - 1]
        assert checkpoint['trace_id'] == root['trace_id']
        assert checkpoint['checkpoint_id'] == case['case_id'] + ':' + str(root['round'])
    assert [r['original_input_sha256'] for r in p['round_roots']] == [
        hashlib.sha256(text.encode()).hexdigest() for text in case['rounds']]


def test_plan_cannot_convert_historical_canary_permission_or_change_real_entitlement():
    p = plan(False)
    assert p['live_ready'] is False and p['execution_started'] is False
    assert p['provider_requests_started'] == 0 and p['credentials_loaded'] is False
    assert p['budget']['approval_status'] == 'unapproved' and p['budget']['live_execution_authorized'] is False
    assert p['historical_canary'] == {'rounds': 10, 'checkpoints': 2, 'actual_request_cap': 80,
        'wall_seconds': 900, 'request_seconds': 60, 'applies_to_this_campaign': False}
    assert p['entitlement']['mode'] == 'isolated_synthetic_backend'
    assert p['entitlement']['normal_free_account_round_limit'] == 20
    assert p['entitlement']['real_subscription_or_billing_change'] is False
    assert p['coverage']['free_account_20_round_gate'] == 'separate_required_test'
    assert p['coverage']['browser_login_recovery'] == 'not_covered'
    assert p['configuration']['policy'] == 'preserve_actual_role_routing'
    assert p['configuration']['installed_role_configuration'] == 'not_verified'
    assert p['configuration']['role_model_overrides'] == {}
    assert {'security_hotfix_review_required', 'campaign_execution_path_not_implemented',
            'new_campaign_budget_approval_required', 'consumer_account_binding_not_verified'} <= set(p['blockers'])


@pytest.mark.parametrize('case_id,family', [('unknown', True), ('harbour-copper-notebook', 1)])
def test_invalid_scope_is_rejected(case_id, family):
    from scripts.single_fifty_campaign import build_campaign_plan
    with pytest.raises(ValueError):
        build_campaign_plan(case_id=case_id, family_enabled=family, run_id=str(uuid4()))


def receipt_for(p):
    case = p['cases'][0]
    rounds = []
    for ordinal, text in enumerate(case['rounds'], 1):
        sources = [{'id': f'source-{i}', 'sequence': i, 'version': 1, 'text': original}
                   for i, original in enumerate(case['rounds'][:ordinal], 1)]
        rounds.append({'round': ordinal, 'status': 'completed', 'background_settled': True,
            'accepted_source_id': f'source-{ordinal}', 'canonical_state': {'sources': sources,
                'completed_rounds': ordinal, 'processing': {'extracted_through': ordinal}}})
    from scripts.single_fifty_campaign import REQUIRED_CLEANUP
    return {'run_id': p['run_id'], 'source_revision': p['source_revision'], 'source_tree': p['source_tree'],
        'status': 'completed', 'execution_started': True, 'evidence_mode': 'mock_only',
        'provider_requests_started': 0, 'guarded_send_entries': 0,
        'cases': [{key: case[key] for key in ('case_id', 'owner_id', 'project_id', 'language', 'family_enabled')} | {
            'status': 'completed', 'rounds': rounds, 'checkpoints': [
                {'milestone': n, 'draft': {'revision': 1, 'covered_round': n}}
                for n in range(5, 51, 5)]}],
        'cleanup': {name: True for name in REQUIRED_CLEANUP}}


def test_complete_controlled_receipt_shape_never_claims_live_or_model_quality():
    from scripts.single_fifty_campaign import assess_campaign_receipt
    p = plan()
    result = assess_campaign_receipt(p, receipt_for(p))
    assert result['receipt_shape_complete'] is True
    assert result['completed_rounds'] == 50 and result['saved_checkpoints'] == 10
    assert result['live_ready'] is False and result['acceptance_status'] == 'not_established'
    assert result['model_quality'] == 'not_graded'
    assert result['provider_requests_started'] == 0


@pytest.mark.parametrize('terminal', ['failed', 'cancelled', 'incomplete'])
def test_failure_and_cancellation_keep_partial_counts_and_unknown_provider_usage(terminal):
    from scripts.single_fifty_campaign import assess_campaign_receipt
    p = plan()
    receipt = receipt_for(p)
    receipt.update(status=terminal, provider_requests_started=None, guarded_send_entries=17)
    case = receipt['cases'][0]
    case.update(status=terminal, rounds=case['rounds'][:12], checkpoints=case['checkpoints'][:2])
    result = assess_campaign_receipt(p, receipt)
    assert result['receipt_shape_complete'] is False
    assert result['completed_rounds'] == 12 and result['saved_checkpoints'] == 2
    assert result['provider_requests_started'] is None and result['guarded_send_entries'] == 17
    assert result['acceptance_status'] == 'not_established'


@pytest.mark.parametrize('mutation', ['missing_round', 'duplicate_round', 'extra_round', 'wrong_source',
    'wrong_original', 'stale_extraction', 'missing_checkpoint', 'duplicate_checkpoint',
    'unsaved_checkpoint', 'bad_cleanup', 'wrong_owner', 'wrong_revision', 'fake_actual_count'])
def test_receipt_contract_rejects_missing_duplicate_foreign_or_unverified_evidence(mutation):
    from scripts.single_fifty_campaign import assess_campaign_receipt
    p = plan()
    receipt = receipt_for(p)
    case = receipt['cases'][0]
    if mutation == 'missing_round': case['rounds'].pop()
    if mutation == 'duplicate_round': case['rounds'][1] = deepcopy(case['rounds'][0])
    if mutation == 'extra_round': case['rounds'].append(deepcopy(case['rounds'][-1]))
    if mutation == 'wrong_source': case['rounds'][-1]['accepted_source_id'] = 'foreign'
    if mutation == 'wrong_original': case['rounds'][-1]['canonical_state']['sources'][-1]['text'] = 'Changed input'
    if mutation == 'stale_extraction': case['rounds'][-1]['canonical_state']['processing']['extracted_through'] = 49
    if mutation == 'missing_checkpoint': case['checkpoints'].pop()
    if mutation == 'duplicate_checkpoint': case['checkpoints'][1] = deepcopy(case['checkpoints'][0])
    if mutation == 'unsaved_checkpoint': case['checkpoints'][-1]['draft']['revision'] = 0
    if mutation == 'bad_cleanup': receipt['cleanup']['gateway_bridge_finished'] = False
    if mutation == 'wrong_owner': case['owner_id'] = str(uuid4())
    if mutation == 'wrong_revision': receipt['source_revision'] = 'f' * 40
    if mutation == 'fake_actual_count': receipt['provider_requests_started'] = True
    result = assess_campaign_receipt(p, receipt)
    assert result['receipt_shape_complete'] is False
    assert result['errors']
    assert result['live_ready'] is False


def test_execute_is_blocked_before_creating_output_or_importing_application(tmp_path):
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/single_fifty_campaign.py'),
        '--execute', '--output-root', str(tmp_path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 3
    receipt = json.loads(result.stdout)
    assert receipt['execution_started'] is False and receipt['credentials_loaded'] is False
    assert receipt['provider_requests_started'] == 0
    assert list(tmp_path.iterdir()) == []


def test_plan_cli_uses_explicit_case_and_family_scope_and_retains_reused_run_evidence(tmp_path):
    run_id = str(uuid4())
    command = [sys.executable, '-B', str(ROOT / 'scripts/single_fifty_campaign.py'), '--plan-only',
        '--case-id', 'chengdu-tea-ledger', '--family-mode', 'disabled', '--run-id', run_id,
        '--output-root', str(tmp_path)]
    first = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert first.returncode == 0, first.stderr
    path = Path(json.loads(first.stdout)['manifest'])
    original = path.read_bytes()
    p = json.loads(original)
    assert p['cases'][0]['language'] == 'zh-CN' and p['cases'][0]['family_enabled'] is False
    assert p['live_ready'] is False
    second = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert second.returncode != 0 and path.read_bytes() == original


@pytest.mark.parametrize('mutation', ['missing_version', 'duplicate_prior_source', 'unknown_actual'])
def test_source_versions_and_request_uncertainty_cannot_be_promoted(mutation):
    from scripts.single_fifty_campaign import assess_campaign_receipt
    p = plan()
    receipt = receipt_for(p)
    records = receipt['cases'][0]['rounds']
    if mutation == 'missing_version': records[-1]['canonical_state']['sources'][0].pop('version')
    if mutation == 'duplicate_prior_source': records[-1]['canonical_state']['sources'][0]['id'] = 'source-2'
    if mutation == 'unknown_actual': receipt['provider_requests_started'] = None
    result = assess_campaign_receipt(p, receipt)
    assert result['receipt_shape_complete'] is False
    assert result['live_ready'] is False
    if mutation == 'unknown_actual': assert result['provider_requests_started'] is None


def test_plan_imports_no_application_or_authentication_modules(monkeypatch):
    import builtins
    original = builtins.__import__
    def import_only_offline(name, *args, **kwargs):
        assert not name.startswith('apps.'), 'Planning must not import application/auth startup'
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', import_only_offline)
    assert plan()['execution_started'] is False


def test_changed_call_graph_bytes_keep_budget_derivation_unverified(monkeypatch):
    import scripts.single_fifty_campaign as campaign
    original_sha = campaign._sha
    def altered(path, root):
        return '0' * 64 if path == root / 'apps/api/codex_runtime.py' else original_sha(path, root)
    monkeypatch.setattr(campaign, '_sha', altered)
    p = plan()
    assert p['budget_source_audit']['derivation_matches_current_files'] is False
    assert 'apps/api/codex_runtime.py' in p['budget_source_audit']['mismatched_paths']
    assert 'budget_call_graph_source_drift' in p['blockers']
    assert p['live_ready'] is False


def test_mistaken_credential_option_is_not_echoed_or_consumed(tmp_path):
    marker = 'synthetic-cli-secret-must-not-echo'
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/single_fifty_campaign.py'),
        '--execute', '--output-root', str(tmp_path), '--api-key', marker],
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
    assert marker not in result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('mutation', ['future_cursor', 'boolean_round_count', 'boolean_sequence'])
def test_receipt_rejects_impossible_or_boolean_canonical_counters(mutation):
    from scripts.single_fifty_campaign import assess_campaign_receipt
    p = plan()
    receipt = receipt_for(p)
    first = receipt['cases'][0]['rounds'][0]['canonical_state']
    if mutation == 'future_cursor': first['processing']['extracted_through'] = 50
    if mutation == 'boolean_round_count': first['completed_rounds'] = True
    if mutation == 'boolean_sequence': first['sources'][0]['sequence'] = True
    assert assess_campaign_receipt(p, receipt)['receipt_shape_complete'] is False


@pytest.mark.parametrize('mutation', ['different_family', 'missing_family', 'numeric_family',
    'float_covered_round', 'malformed_evidence_mode'])
def test_reviewed_scope_and_counter_types_fail_closed(mutation):
    from scripts.single_fifty_campaign import assess_campaign_receipt
    p = plan()
    receipt = receipt_for(p)
    case = receipt['cases'][0]
    if mutation == 'different_family': case['family_enabled'] = False
    if mutation == 'missing_family': case.pop('family_enabled')
    if mutation == 'numeric_family': case['family_enabled'] = 1
    if mutation == 'float_covered_round': case['checkpoints'][0]['draft']['covered_round'] = 5.0
    if mutation == 'malformed_evidence_mode': receipt['evidence_mode'] = []
    result = assess_campaign_receipt(p, receipt)
    assert result['receipt_shape_complete'] is False
    assert result['errors']
    assert result['live_ready'] is False
