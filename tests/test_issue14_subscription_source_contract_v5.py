"""Current PR45 integration, with all older source/publication evidence frozen."""
from pathlib import Path
import json
import pytest
from scripts.issue14_subscription_source_contract_v5 import (
    audit_subscription_source_v5, historical_v4_files, historical_test_files, SourceContractError,
)
ROOT = Path(__file__).resolve().parents[1]
PROOF = 'tests/fixtures/issue14_subscription_source_v5.json'


def copy_scope(tmp_path):
    names = set(json.loads((ROOT / PROOF).read_text())['current_snapshot']['files']) | {
        PROOF, 'scripts/issue14_source_contract.py', 'scripts/issue14_subscription_source_contract.py',
        'scripts/issue14_subscription_source_contract_v4.py', 'scripts/issue14_subscription_source_contract_v5.py',
        'tests/fixtures/issue14_source_contract_v2.json', 'tests/fixtures/issue14_subscription_source_v3.json',
        'tests/fixtures/issue14_subscription_source_v4.json'}
    for name in names:
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    return tmp_path


def test_current_source_and_all_history_without_provider_authority():
    result = audit_subscription_source_v5(ROOT)
    assert result['source_gate_passed'] is True
    assert result['historical_derivation_integrity_verified'] is True
    assert result['historical_v2_integrity_verified'] is True
    assert result['historical_v3_integrity_verified'] is True
    assert result['historical_v4_integrity_verified'] is True
    assert result['current_source_file_count'] == 291
    assert len(result['historical_v4_drift_paths']) == 12
    assert result['newly_monitored_source_paths'] == ['Mira_Memoir_Journalist_System_Prompt_v1.0.md', 'apps/api/interview_photos.py',
        'apps/api/interview_plan.py', 'supabase/migrations/202610090001_interview_photos_plan.sql']
    assert result['live_execution_authorized'] is result['provider_capability_verified'] is False
    assert result['hard_token_or_monetary_limit_enforced'] is False


def test_v4_archive_and_original_publication_tests_have_exact_identity(tmp_path):
    from scripts.issue14_subscription_source_contract_v4 import audit_subscription_source_v4
    for name, raw in historical_v4_files(ROOT).items():
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
    result = audit_subscription_source_v4(tmp_path)
    assert result['source_gate_passed'] is True and result['current_source_file_count'] == 287
    assert result['current_snapshot_revision'] == 'e39195b5595de57791398727d8c0ebb9e88de3f7'
    tests = historical_test_files(ROOT)
    assert set(tests) == {'tests/test_issue6_langfuse_publication.py'}
    assert b'def test_export_preserves_reviewed_synthetic_cases_and_exact_runtime_prompts' in next(iter(tests.values()))


@pytest.mark.parametrize('path', ['scripts/issue14_subscription_session.py', 'apps/api/interview_plan.py',
    'apps/api/interview_photos.py', 'apps/api/memory_events.py', 'apps/api/memoir_preview.py',
    'supabase/migrations/202610090001_interview_photos_plan.sql', 'tests/memoir_postgres_workflow.py'])
def test_current_runtime_drift_fails(tmp_path, path):
    root = copy_scope(tmp_path); target = root / path; target.write_bytes(target.read_bytes()+b'\n# mutation\n')
    with pytest.raises(SourceContractError): audit_subscription_source_v5(root)


@pytest.mark.parametrize('path', ['scripts/__pycache__/new.py', 'skills/memoir-composer/extra.pyc',
    'supabase/__pycache__/new.sql', 'apps/api/extra.py'])
def test_added_runtime_inputs_fail(tmp_path, path):
    root=copy_scope(tmp_path);target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('extra')
    with pytest.raises(SourceContractError): audit_subscription_source_v5(root)


@pytest.mark.parametrize('mutation', ['version','revision','omit_current','omit_archive','omit_test',
    'fake_test','corrupt_test','authority','v4_module','v4_proof','duplicate_json','boolean_size'])
def test_proof_and_frozen_v4_and_publication_test_cannot_be_relabelled(tmp_path, mutation):
    root=copy_scope(tmp_path);assert audit_subscription_source_v5(root)['source_gate_passed']
    p=root/PROOF;raw=p.read_text();v=json.loads(raw);snap=v['current_snapshot'];first=next(iter(snap['files']))
    if mutation=='version':v['schema_version']='unknown'
    elif mutation=='revision':snap['revision']='0'*40
    elif mutation=='omit_current':snap['files'].pop(first)
    elif mutation=='omit_archive':
        old=json.loads((root/'tests/fixtures/issue14_subscription_source_v4.json').read_text())
        v['objects'].pop(old['current_snapshot']['files']['scripts/issue14_subscription_session.py']['blob'])
    elif mutation=='omit_test':v['historical_support'].clear()
    elif mutation=='fake_test':v['historical_support']['tests/forged.py']=next(iter(v['historical_support'].values()))
    elif mutation=='corrupt_test':next(iter(v['historical_support'].values()))['sha256']='0'*64
    elif mutation=='authority':v['live_execution_authorized']=True
    elif mutation=='boolean_size':next(iter(v['objects'].values()))['size']=True
    elif mutation=='duplicate_json':
        p.write_text('{"schema_version":"forged",'+raw.lstrip()[1:])
        with pytest.raises(SourceContractError):audit_subscription_source_v5(root)
        return
    else:(root/('scripts/issue14_subscription_source_contract_v4.py' if mutation=='v4_module' else 'tests/fixtures/issue14_subscription_source_v4.json')).write_text('{}')
    p.write_text(json.dumps(v))
    with pytest.raises(SourceContractError):audit_subscription_source_v5(root)
