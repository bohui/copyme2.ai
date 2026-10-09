"""Historical v3 source proof; its original audit and mutations retain meaning."""
from pathlib import Path
import pytest

from scripts.issue14_subscription_source_contract import (
    audit_subscription_source, historical_v2_files, SourceContractError,
)

ROOT=Path(__file__).resolve().parents[1]


def copy_current(tmp_path):
    # V3 is immutable history after the separately reviewed recovery. Materialize
    # its verified original inputs, not current files that would make negatives
    # pass merely because the entire checkout has already drifted.
    from scripts.issue14_subscription_source_contract_v4 import historical_v3_files
    for path, raw in historical_v3_files(ROOT).items():
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    return tmp_path


def test_current_proof_and_both_historical_versions_are_independent(tmp_path):
    report=audit_subscription_source(copy_current(tmp_path))
    assert report['source_gate_passed'] is True
    assert report['historical_derivation_integrity_verified'] is True
    assert report['historical_v2_integrity_verified'] is True
    assert report['current_source_matches_reviewed_snapshot'] is True
    assert report['current_source_file_count']==287
    assert report['historical_v2_matches_current_source'] is False
    assert report['live_execution_authorized'] is report['provider_capability_verified'] is False


def test_old_v2_audit_runs_against_exact_archived_blobs(tmp_path):
    from scripts.issue14_source_contract import audit_source_contract
    for path,raw in historical_v2_files(ROOT).items():
        target=tmp_path/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    report=audit_source_contract(tmp_path)
    assert report['source_gate_passed'] is True
    assert report['current_snapshot_revision']=='1026a1b97731f098962d045d24fefa581797ca67'


@pytest.mark.parametrize('path',['apps/api/codex_runtime.py','scripts/issue14_subscription_session.py',
    'scripts/run_issue14_subscription_evaluation.py','tests/test_agent_commit_postgres.py',
    'tests/evaluation/issue6_semantic_datasets.json','skills/memoir-composer/SKILL.md',
    'supabase/migrations/202610040002_memoir_skill_lanes.sql'])
def test_runtime_native_fixture_dataset_skills_and_sql_drift_fail(tmp_path,path):
    root=copy_current(tmp_path);target=root/path;target.write_bytes(target.read_bytes()+b'\n# changed\n')
    with pytest.raises(SourceContractError):audit_subscription_source(root)


@pytest.mark.parametrize('kind',['extra','missing','symlink','fifo','v2_proof','v2_auditor'])
def test_source_and_historical_boundaries_fail_closed(tmp_path,kind):
    import os
    root=copy_current(tmp_path);target=root/'scripts/issue14_subscription_session.py'
    if kind=='extra':(root/'skills/unreviewed.md').write_text('unreviewed')
    elif kind=='missing':target.unlink()
    elif kind=='symlink':target.unlink();target.symlink_to(ROOT/'scripts/issue14_subscription_session.py')
    elif kind=='fifo':target.unlink();os.mkfifo(target)
    elif kind=='v2_proof':(root/'tests/fixtures/issue14_source_contract_v2.json').write_text('{}')
    else:(root/'scripts/issue14_source_contract.py').write_text('pass\n')
    with pytest.raises(SourceContractError):audit_subscription_source(root)


@pytest.mark.parametrize('kind',['version','revision','tree','omit','hash','blob','extra_authority',
    'missing_archive','corrupt_archive','duplicate_json','boolean_size','trailing_compressed'])
def test_current_proof_and_archived_v2_cannot_be_forged(tmp_path,kind):
    import json,base64
    root=copy_current(tmp_path)
    assert audit_subscription_source(root)['source_gate_passed'] is True
    path=root/'tests/fixtures/issue14_subscription_source_v3.json';raw=path.read_text();proof=json.loads(raw)
    current=proof['current_snapshot'];first=next(iter(current['files']))
    if kind=='version':proof['schema_version']='future'
    elif kind=='revision':current['revision']='0'*40
    elif kind=='tree':current['tree']='0'*40
    elif kind=='omit':current['files'].pop(first)
    elif kind=='hash':current['files'][first]['sha256']='0'*64
    elif kind=='blob':current['files'][first]['blob']='0'*40
    elif kind=='extra_authority':proof['live_execution_authorized']=True
    elif kind=='missing_archive':
        legacy=json.loads((root/'tests/fixtures/issue14_source_contract_v2.json').read_text())
        sha=legacy['snapshots']['issue14-inactive-v2']['files']['apps/api/codex_runtime.py']['blob']
        proof['objects'].pop(sha)
    elif kind=='duplicate_json':
        path.write_text('{"schema_version":"duplicate",'+raw.lstrip()[1:])
        with pytest.raises(SourceContractError):audit_subscription_source(root)
        return
    else:
        entry=next(iter(proof['objects'].values()))
        if kind=='corrupt_archive':entry['data']='AAAA'
        elif kind=='boolean_size':entry['size']=True
        else:entry['data']=base64.b64encode(base64.b64decode(entry['data'])+b'trailing').decode()
    path.write_text(json.dumps(proof))
    with pytest.raises(SourceContractError):audit_subscription_source(root)


@pytest.mark.parametrize('path',['skills/memoir-composer/__pycache__/unreviewed.md',
    'skills/memoir-composer/unreviewed.pyc','scripts/__pycache__/unreviewed_sender.py'])
def test_cache_names_cannot_hide_runtime_inputs(tmp_path,path):
    root=copy_current(tmp_path)
    target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('unreviewed')
    with pytest.raises(SourceContractError):audit_subscription_source(root)
