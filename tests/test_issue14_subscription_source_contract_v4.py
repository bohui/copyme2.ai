"""Recovery source integrity remains separate from prior run/protocol evidence."""
from pathlib import Path
import json
import pytest
from scripts.issue14_subscription_source_contract_v4 import (
    audit_subscription_source_v4, historical_v3_files, SourceContractError,
)
ROOT = Path(__file__).resolve().parents[1]
PROOF = 'tests/fixtures/issue14_subscription_source_v4.json'


def copy_scope(tmp_path):
    # Execute the frozen v4 contract against its independently verified original
    # inputs. Current source is checked by v5, not relabelled as old evidence.
    from scripts.issue14_subscription_source_contract_v5 import historical_v4_files
    for name, raw in historical_v4_files(ROOT).items():
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return tmp_path


def test_new_current_and_immutable_history_pass_without_live_authority(tmp_path):
    result = audit_subscription_source_v4(copy_scope(tmp_path))
    assert result['source_gate_passed'] is True
    assert result['historical_derivation_integrity_verified'] is True
    assert result['historical_v2_integrity_verified'] is True
    assert result['historical_v3_integrity_verified'] is True
    assert result['current_source_file_count'] == 287
    assert result['historical_v3_drift_paths'] == [
        'scripts/issue14_subscription_runner.py', 'scripts/issue14_subscription_session.py']
    assert result['live_execution_authorized'] is result['provider_capability_verified'] is False
    assert result['hard_token_or_monetary_limit_enforced'] is False


def test_v3_runs_on_its_exact_verified_archived_snapshot(tmp_path):
    from scripts.issue14_subscription_source_contract import audit_subscription_source
    for name, raw in historical_v3_files(ROOT).items():
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    result = audit_subscription_source(tmp_path)
    assert result['source_gate_passed'] is True and result['current_source_file_count'] == 287
    assert result['current_snapshot_revision'] == 'bbf35488e37d7a83f9542a8b09ba2b7a81e2ca05'


@pytest.mark.parametrize('path', ['scripts/issue14_subscription_runner.py',
    'scripts/issue14_subscription_session.py', 'apps/api/codex_runtime.py',
    'skills/memoir-composer/SKILL.md', 'supabase/migrations/202610040002_memoir_skill_lanes.sql',
    'tests/evaluation/issue6_semantic_datasets.json', 'tests/test_agent_commit_postgres.py'])
def test_current_monitored_changes_fail(tmp_path, path):
    root = copy_scope(tmp_path); target = root / path
    target.write_bytes(target.read_bytes() + b'\n# unreviewed\n')
    with pytest.raises(SourceContractError): audit_subscription_source_v4(root)


@pytest.mark.parametrize('path', ['scripts/__pycache__/new.py', 'skills/memoir-composer/new.pyc',
    'skills/memoir-composer/__pycache__/new.md', 'supabase/new.sql'])
def test_all_extra_runtime_inputs_fail(tmp_path, path):
    root = copy_scope(tmp_path); target = root / path
    target.parent.mkdir(parents=True, exist_ok=True); target.write_text('extra')
    with pytest.raises(SourceContractError): audit_subscription_source_v4(root)


@pytest.mark.parametrize('mutation', ['version', 'revision', 'tree', 'omit', 'hash',
    'missing_archive', 'corrupt_archive', 'duplicate_json', 'boolean_size', 'extra_authority',
    'v2_module', 'v2_proof', 'v3_module', 'v3_proof'])
def test_proof_and_frozen_history_fail_closed(tmp_path, mutation):
    root = copy_scope(tmp_path)
    assert audit_subscription_source_v4(root)['source_gate_passed'] is True
    path = root / PROOF; raw = path.read_text(); data = json.loads(raw)
    snapshot = data['current_snapshot']; first = next(iter(snapshot['files']))
    if mutation == 'version': data['schema_version'] = 'unknown'
    elif mutation == 'revision': snapshot['revision'] = '0' * 40
    elif mutation == 'tree': snapshot['tree'] = '0' * 40
    elif mutation == 'omit': snapshot['files'].pop(first)
    elif mutation == 'hash': snapshot['files'][first]['sha256'] = '0' * 64
    elif mutation == 'missing_archive':
        old = json.loads((root / 'tests/fixtures/issue14_subscription_source_v3.json').read_text())
        data['objects'].pop(old['current_snapshot']['files']['scripts/issue14_subscription_session.py']['blob'])
    elif mutation == 'corrupt_archive': next(iter(data['objects'].values()))['data'] = 'AAAA'
    elif mutation == 'boolean_size': next(iter(data['objects'].values()))['size'] = True
    elif mutation == 'extra_authority': data['live_execution_authorized'] = True
    elif mutation == 'duplicate_json':
        path.write_text('{"schema_version":"forged",' + raw.lstrip()[1:])
        with pytest.raises(SourceContractError): audit_subscription_source_v4(root)
        return
    else:
        target = {'v2_module':'scripts/issue14_source_contract.py',
            'v2_proof':'tests/fixtures/issue14_source_contract_v2.json',
            'v3_module':'scripts/issue14_subscription_source_contract.py',
            'v3_proof':'tests/fixtures/issue14_subscription_source_v3.json'}[mutation]
        (root / target).write_text('{}')
    path.write_text(json.dumps(data))
    with pytest.raises(SourceContractError): audit_subscription_source_v4(root)
