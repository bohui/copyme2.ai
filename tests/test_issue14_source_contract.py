"""Offline source-version gate; never grants real-provider admission."""
import json
from pathlib import Path
import shutil

import pytest

from scripts.issue14_source_contract import SourceContractError, audit_source_contract


ROOT = Path(__file__).resolve().parents[1]
PROOF = Path('tests/fixtures/issue14_source_contract_v2.json')


def copy_scope(tmp_path):
    for directory in ('apps/api', 'scripts'):
        for source in (ROOT / directory).rglob('*.py'):
            target = tmp_path / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for name in ('apps/__init__.py', 'pyproject.toml', 'compose.yml', '.env.example', str(PROOF)):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def test_versioned_gate_proves_history_and_current_source_without_live_authority():
    report = audit_source_contract(ROOT)
    assert report['schema_version'] == 'memoir-issue14-source-audit/2'
    assert report['source_gate_passed'] is True
    assert report['historical_derivation_integrity_verified'] is True
    assert report['current_source_matches_reviewed_snapshot'] is True
    assert report['historical_revision'] == '3a9a339813ed06fb06ba18815bf32b880072314e'
    assert report['current_snapshot_revision'] == '1026a1b97731f098962d045d24fefa581797ca67'
    assert report['legacy_derivation_matches_current_source'] is False
    assert report['legacy_source_drift_paths'] == sorted([
        'apps/api/codex_runtime.py', 'apps/api/codex_worker_service.py',
        'apps/api/codex_agent.py', 'apps/api/canonical_composer.py'])
    assert report['live_execution_authorized'] is False
    assert report['provider_capability_verified'] is False
    assert report['hard_token_or_monetary_limit_enforced'] is False


@pytest.mark.parametrize('path', [
    'apps/api/codex_runtime.py', 'apps/api/codex_worker_service.py', 'apps/api/codex_agent.py',
    'apps/api/canonical_composer.py', 'apps/api/issue14_execution_admission.py',
    'scripts/issue14_provider_budget.py', 'scripts/issue14_provider_transport.py',
    'scripts/run_issue14_evaluation.py', 'scripts/canary_gateway_binding.py',
    'apps/api/memoir_tasks.py', 'pyproject.toml', 'scripts/fifty_round_budget_contract.py'])
def test_any_monitored_source_mutation_fails_the_new_gate(tmp_path, path):
    root = copy_scope(tmp_path)
    target = root / path
    target.write_bytes(target.read_bytes() + b'\n# unreviewed mutation\n')
    with pytest.raises(SourceContractError):
        audit_source_contract(root)


@pytest.mark.parametrize('operation', ['missing', 'extra', 'symlink', 'symlink_parent'])
def test_source_inventory_and_ordinary_file_requirements_fail_closed(tmp_path, operation):
    root = copy_scope(tmp_path)
    target = root / 'apps/api/codex_agent.py'
    if operation == 'missing':
        target.unlink()
    elif operation == 'extra':
        (root / 'apps/api/unreviewed_sender.py').write_text('pass\n')
    elif operation == 'symlink':
        target.unlink()
        target.symlink_to(ROOT / 'apps/api/codex_agent.py')
    else:
        shutil.rmtree(root / 'apps/api')
        (root / 'apps/api').symlink_to(ROOT / 'apps/api', target_is_directory=True)
    with pytest.raises(SourceContractError):
        audit_source_contract(root)


@pytest.mark.parametrize('mutation', ['version', 'snapshot', 'omit_path', 'fake_hash',
    'corrupt_object', 'missing_object', 'authorization', 'path_escape', 'invalid_object_kind',
    'boolean_size', 'oversized_object', 'trailing_compressed_data'])
def test_proof_cannot_be_relabelled_or_weakened(tmp_path, mutation):
    root = copy_scope(tmp_path)
    path = root / PROOF
    proof = json.loads(path.read_text())
    current = proof['snapshots']['issue14-inactive-v2']
    if mutation == 'version':
        proof['schema_version'] = 'memoir-source-proof/999'
    elif mutation == 'snapshot':
        current['revision'] = '0' * 40
    elif mutation == 'omit_path':
        del current['files']['apps/api/codex_agent.py']
    elif mutation == 'fake_hash':
        current['files']['apps/api/codex_agent.py']['sha256'] = '0' * 64
    elif mutation == 'corrupt_object':
        key = next(iter(proof['objects']))
        proof['objects'][key]['data'] = 'AAAA'
    elif mutation == 'missing_object':
        del proof['objects'][proof['snapshots']['historical-v1']['revision']]
    elif mutation == 'authorization':
        proof['live_execution_authorized'] = True
    elif mutation == 'path_escape':
        current['files']['../../outside.py'] = current['files'].pop('apps/api/codex_agent.py')
    else:
        import base64
        entry = proof['objects'][next(iter(proof['objects']))]
        if mutation == 'invalid_object_kind':
            entry['kind'] = []
        elif mutation == 'boolean_size':
            entry['size'] = True
        elif mutation == 'oversized_object':
            entry['size'] = 1_000_000_000
        else:
            entry['data'] = base64.b64encode(base64.b64decode(entry['data']) + b'trailing').decode()
    path.write_text(json.dumps(proof))
    with pytest.raises(SourceContractError):
        audit_source_contract(root)


def test_updating_a_hash_to_match_unreviewed_code_cannot_forge_git_membership(tmp_path):
    import hashlib
    root = copy_scope(tmp_path)
    target = root / 'apps/api/codex_agent.py'
    raw = target.read_bytes() + b'\n# changed\n'
    target.write_bytes(raw)
    path = root / PROOF
    proof = json.loads(path.read_text())
    entry = proof['snapshots']['issue14-inactive-v2']['files']['apps/api/codex_agent.py']
    entry['sha256'] = hashlib.sha256(raw).hexdigest()
    entry['blob'] = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    path.write_text(json.dumps(proof))
    with pytest.raises(SourceContractError):
        audit_source_contract(root)


def test_legacy_planner_remains_historical_and_blocked():
    from scripts.single_fifty_campaign import build_campaign_plan
    value = build_campaign_plan(case_id='harbour-copper-notebook', family_enabled=False)
    assert value['budget']['schema_version'] == 'memoir-fifty-budget-proposal/1'
    assert value['budget']['derivation_source_revision'] == '3a9a339813ed06fb06ba18815bf32b880072314e'
    assert value['budget_source_audit']['derivation_matches_current_files'] is False
    assert 'budget_call_graph_source_drift' in value['blockers']
    assert value['live_ready'] is False
    assert value['budget']['live_execution_authorized'] is False


def test_proof_symlink_cannot_read_outside_the_source_root(tmp_path):
    root = copy_scope(tmp_path)
    (root / PROOF).unlink()
    (root / PROOF).symlink_to(ROOT / PROOF)
    with pytest.raises(SourceContractError, match='source_file_unavailable'):
        audit_source_contract(root)


def test_source_audit_is_read_only_and_repeatable(tmp_path):
    import hashlib
    root = copy_scope(tmp_path)
    before = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file()}
    assert audit_source_contract(root) == audit_source_contract(root)
    after = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize('prefix', ['apps/api', 'scripts'])
def test_unreadable_inventory_subdirectory_cannot_hide_source(tmp_path, monkeypatch, prefix):
    import os
    root = copy_scope(tmp_path)
    hidden = root / prefix / 'hidden'
    hidden.mkdir()
    (hidden / 'unreviewed_sender.py').write_text('pass\n')
    original = os.scandir
    def denied(path):
        if Path(path) == hidden:
            raise PermissionError('synthetic traversal failure')
        return original(path)
    monkeypatch.setattr(os, 'scandir', denied)
    with pytest.raises(SourceContractError, match='source_inventory_unavailable'):
        audit_source_contract(root)


@pytest.mark.parametrize('relative', [str(PROOF), 'apps/api/codex_agent.py'])
def test_fifo_proof_or_source_fails_without_waiting_for_a_writer(tmp_path, relative):
    import os
    import subprocess
    import sys
    root = copy_scope(tmp_path)
    target = root / relative
    target.unlink()
    os.mkfifo(target)
    program = '''
import sys
sys.path.insert(0, sys.argv[1])
from scripts.issue14_source_contract import SourceContractError, audit_source_contract
try:
    audit_source_contract(sys.argv[2])
except SourceContractError:
    raise SystemExit(0)
raise SystemExit(2)
'''
    result = subprocess.run([sys.executable, '-c', program, str(ROOT), str(root)],
        capture_output=True, timeout=2)
    assert result.returncode == 0
