"""Five-case/fifty-input source integrity leaves older evidence frozen."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts import issue14_subscription_source_contract_v5 as v5
from scripts import issue14_subscription_source_contract_v6 as v6


ROOT = Path(__file__).resolve().parents[1]
PROOF = v6.PROOF_PATH


def copy_scope(tmp_path):
    names = set(json.loads((ROOT / PROOF).read_text())['current_snapshot']['files'])
    names.update(v6.TOOLING_PATHS)
    names.update({PROOF, v5.PROOF_PATH, v5.v4.PROOF_PATH, v5.v3.PROOF_PATH, v5.v2.PROOF_PATH})
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    return tmp_path


def test_current_fifty_source_preserves_all_history_without_execution_authority():
    result = v6.audit_subscription_source_v6(ROOT)
    assert result['schema_version'] == 'memoir-subscription-source-audit/6'
    assert result['source_gate_passed'] is True
    for version in ('derivation', 'v2', 'v3', 'v4', 'v5'):
        assert result[f'historical_{version}_integrity_verified'] is True
    assert result['current_snapshot_revision'] == v6.CURRENT_REVISION
    assert result['current_snapshot_tree'] == v6.CURRENT_TREE
    assert result['current_source_file_count'] == 302
    assert result['historical_v5_snapshot_revision'] == '3d0e157f0835a72c3fb3aa9ec6766f8c2aaaa67b'
    assert result['historical_v5_matches_current_source'] is False
    assert result['newly_monitored_source_paths'] == [
        'apps/api/codex_progress.py',
        'apps/api/codex_timeout_policy.py',
        'scripts/issue14_response_observation.py',
        'scripts/memoir_fifty_browser.py', 'scripts/memoir_fifty_browser_runner.py',
        'scripts/memoir_fifty_coverage.py',
        'scripts/memoir_fifty_photo.py',
        'scripts/memoir_fifty_readback.py',
        'scripts/memoir_subscription_profiles.py',
        'tests/evaluation/memoir_five_case_expected.json', 'tests/evaluation/memoir_five_case_inputs.json']
    assert result['original_five_case_inputs_integrity_verified'] is True
    assert result['original_five_case_expected_integrity_verified'] is True
    assert result['historical_publication_test_source_verified'] is True
    assert result['current_source_matches_reviewed_snapshot'] is True
    assert result['live_execution_authorized'] is False
    assert result['provider_capability_verified'] is False
    assert result['hard_token_or_monetary_limit_enforced'] is False


def test_frozen_v5_identity_is_the_canonical_merged_proof():
    assert v5.CURRENT_REVISION == '3d0e157f0835a72c3fb3aa9ec6766f8c2aaaa67b'
    assert v5.CURRENT_TREE == 'fda1225d8cde3c00d81d4168e7d7a1a68c4d4b4a'
    assert v6.V5_AUDITOR_SHA256 == '294db5d8aef39d9595a42fe52b2746734059e5124c73f13f66660448ea1826db'
    assert v6.V5_PROOF_SHA256 == '94070f30ef19b7de626eac54ba1052656d16bf588a0151ddcd90cf5f5d29f78a'
    assert hashlib.sha256((ROOT / v5.AUDIT_PATH).read_bytes()).hexdigest() == v6.V5_AUDITOR_SHA256
    assert hashlib.sha256((ROOT / v5.PROOF_PATH).read_bytes()).hexdigest() == v6.V5_PROOF_SHA256


def test_v5_archive_retains_exact_identity_and_original_assertions(tmp_path):
    archive = v6.historical_v5_files(ROOT)
    for name, raw in archive.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    result = v5.audit_subscription_source_v5(tmp_path)
    assert result['source_gate_passed'] is True
    assert result['current_source_file_count'] == 291
    assert len(result['historical_v4_drift_paths']) == 12
    assert result['current_snapshot_revision'] == v5.CURRENT_REVISION
    assert result['current_snapshot_tree'] == v5.CURRENT_TREE
    assert archive[v5.AUDIT_PATH] == (ROOT / v5.AUDIT_PATH).read_bytes()
    assert archive[v5.PROOF_PATH] == (ROOT / v5.PROOF_PATH).read_bytes()
    assert v6.AUDIT_PATH not in archive
    assert v6.DATASET_PATH not in archive
    assert v6.EXPECTED_PATH not in archive


@pytest.mark.parametrize('path', [
    'scripts/memoir_fifty_browser.py', 'scripts/memoir_fifty_browser_runner.py',
    'scripts/memoir_fifty_coverage.py',
    'scripts/memoir_fifty_photo.py',
    'scripts/memoir_fifty_readback.py',
    'scripts/memoir_subscription_profiles.py',
    'scripts/issue14_progressive_readback.py', 'scripts/issue14_subscription_session.py',
    'scripts/issue14_subscription_runner.py', 'scripts/issue14_subscription_transport.py',
    'scripts/run_issue14_subscription_evaluation.py', v6.DATASET_PATH, v6.EXPECTED_PATH, v5.PROMPT_PATH,
    'tests/evaluation/issue6_semantic_datasets.json', 'tests/memoir_postgres_workflow.py',
    'tests/test_agent_commit_postgres.py', 'tests/test_private_rounds_postgres.py',
    'tests/test_shared_memory_events_postgres.py', 'tests/test_guest_conversation_transfer.py',
    'supabase/migrations/202610090001_interview_photos_plan.sql'])
def test_runtime_dataset_native_and_sql_mutation_fails(tmp_path, path):
    root = copy_scope(tmp_path)
    target = root / path
    target.write_bytes(target.read_bytes() + b'\n# unreviewed mutation\n')
    with pytest.raises(v6.SourceContractError):
        v6.audit_subscription_source_v6(root)


@pytest.mark.parametrize('path', [
    'scripts/__pycache__/new.py', 'apps/api/extra.py',
    'skills/memoir-composer/extra.pyc', 'supabase/__pycache__/extra.sql'])
def test_extra_runtime_input_fails(tmp_path, path):
    root = copy_scope(tmp_path)
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('extra')
    with pytest.raises(v6.SourceContractError, match='source_inventory_invalid'):
        v6.audit_subscription_source_v6(root)


@pytest.mark.parametrize('dataset_path', [v6.DATASET_PATH, v6.EXPECTED_PATH])
@pytest.mark.parametrize('failure', ['missing', 'symlink', 'directory', 'fifo', 'oversized'])
def test_required_dataset_read_fails_closed(tmp_path, failure, dataset_path):
    root = copy_scope(tmp_path)
    target = root / dataset_path
    target.unlink()
    if failure == 'symlink':
        target.symlink_to(ROOT / dataset_path)
    elif failure == 'directory':
        target.mkdir()
    elif failure == 'fifo':
        os.mkfifo(target)
    elif failure == 'oversized':
        target.write_bytes(b'x' * (v5.v2._MAX_OBJECT_BYTES + 1))
    with pytest.raises(v6.SourceContractError, match='source_file_(unavailable|invalid)'):
        v6.audit_subscription_source_v6(root)


@pytest.mark.parametrize('mutation', [
    'version', 'revision', 'tree', 'omit_current', 'omit_dataset', 'omit_expected', 'hash', 'blob',
    'omit_archive', 'corrupt_archive', 'boolean_size', 'duplicate_json', 'authority',
    'v5_module', 'v5_proof', 'v4_module', 'v4_proof', 'v3_module', 'v3_proof',
    'v2_module', 'v2_proof'])
def test_proof_and_all_frozen_history_fail_closed(tmp_path, mutation):
    root = copy_scope(tmp_path)
    assert v6.audit_subscription_source_v6(root)['source_gate_passed']
    path = root / PROOF
    raw = path.read_text()
    data = json.loads(raw)
    snapshot = data['current_snapshot']
    first = next(iter(snapshot['files']))
    if mutation == 'version':
        data['schema_version'] = 'unknown'
    elif mutation == 'revision':
        snapshot['revision'] = '0' * 40
    elif mutation == 'tree':
        snapshot['tree'] = '0' * 40
    elif mutation == 'omit_current':
        snapshot['files'].pop(first)
    elif mutation == 'omit_dataset':
        snapshot['files'].pop(v6.DATASET_PATH)
    elif mutation == 'omit_expected':
        snapshot['files'].pop(v6.EXPECTED_PATH)
    elif mutation == 'hash':
        snapshot['files'][first]['sha256'] = '0' * 64
    elif mutation == 'blob':
        snapshot['files'][first]['blob'] = '0' * 40
    elif mutation == 'omit_archive':
        old = json.loads((root / v5.PROOF_PATH).read_text())
        data['objects'].pop(old['current_snapshot']['files']['scripts/run_issue14_subscription_evaluation.py']['blob'])
    elif mutation == 'corrupt_archive':
        next(iter(data['objects'].values()))['data'] = 'AAAA'
    elif mutation == 'boolean_size':
        next(iter(data['objects'].values()))['size'] = True
    elif mutation == 'authority':
        data['live_execution_authorized'] = True
    elif mutation == 'duplicate_json':
        path.write_text('{"schema_version":"forged",' + raw.lstrip()[1:])
        with pytest.raises(v6.SourceContractError):
            v6.audit_subscription_source_v6(root)
        return
    else:
        version, kind = mutation.split('_')
        module = {'v5': v5, 'v4': v5.v4, 'v3': v5.v3, 'v2': v5.v2}[version]
        (root / (module.AUDIT_PATH if kind == 'module' else module.PROOF_PATH)).write_text('{}')
    path.write_text(json.dumps(data))
    with pytest.raises(v6.SourceContractError):
        v6.audit_subscription_source_v6(root)


def test_archived_v5_helper_rejects_missing_authenticated_blob(tmp_path):
    root = copy_scope(tmp_path)
    path = root / PROOF
    data = json.loads(path.read_text())
    prior = json.loads((root / v5.PROOF_PATH).read_text())
    data['objects'].pop(prior['current_snapshot']['files']['scripts/run_issue14_subscription_evaluation.py']['blob'])
    path.write_text(json.dumps(data))
    with pytest.raises(v6.SourceContractError):
        v6.historical_v5_files(root)


@pytest.mark.parametrize('path, expected', [(v6.DATASET_PATH, v6.DATASET_SHA256),
                                          (v6.EXPECTED_PATH, v6.EXPECTED_SHA256)])
def test_original_fifty_datasets_are_explicitly_bound(path, expected):
    proof = json.loads((ROOT / PROOF).read_text())
    entry = proof['current_snapshot']['files'][path]
    raw = (ROOT / path).read_bytes()
    assert entry['sha256'] == expected == hashlib.sha256(raw).hexdigest()
    assert entry['blob'] == v5.v2._git_hash('blob', raw)


def test_inventory_traversal_failure_fails_closed(tmp_path, monkeypatch):
    root = copy_scope(tmp_path)
    def unreadable(_path, *, followlinks, onerror):
        onerror(PermissionError('unreadable source directory'))
        return iter(())
    monkeypatch.setattr(v5.v3.os, 'walk', unreadable)
    with pytest.raises(v6.SourceContractError, match='source_inventory_unavailable'):
        v6.audit_subscription_source_v6(root)
