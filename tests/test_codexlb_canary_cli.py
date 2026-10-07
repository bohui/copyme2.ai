import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


def test_canary_plan_has_distinct_owners_original_rounds_and_honest_missing_evidence():
    from scripts.run_codexlb_canary import build_manifest
    plan = build_manifest(run_id=str(uuid4()),
        source_revision='291622826cdfb776e946dcd92b65d2fdaf4923ad')
    assert plan['live_ready'] is False
    assert plan['execution_started'] is False
    assert plan['provider_requests_started'] == 0
    assert len({c['owner_id'] for c in plan['cases']}) == 2
    assert len({c['project_id'] for c in plan['cases']}) == 2
    assert [c['family_enabled'] for c in plan['cases']] == [True, False]
    assert len(plan['round_roots']) == 10
    assert len({r['trace_id'] for r in plan['round_roots']}) == 10
    assert len(plan['checkpoints']) == 2
    assert plan['proposed_limits']['maximum_actual_requests'] == 80
    assert plan['logical_allocation_total'] == 79
    assert plan['included_semantic_repair_calls'] == 18
    assert plan['evidence']['gateway_requests'] == 'not_run'
    assert plan['evidence']['background_joins'] == 'not_run'
    assert plan['evidence']['browser'] == 'not_run'
    original = json.loads((Path(__file__).parent / 'evaluation/memoir_five_case_inputs.json').read_text())
    cases = {c['id']: c for c in original['cases']}
    assert all(c['rounds'] == cases[c['case_id']]['rounds'][:5] for c in plan['cases'])


def test_execute_flag_remains_blocked_without_authentication_or_reservation(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-B', str(root / 'scripts/run_codexlb_canary.py'),
        '--execute', '--output-root', str(tmp_path)], cwd=root, capture_output=True, text=True)
    assert result.returncode == 3
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'blocked'
    assert receipt['provider_requests_started'] == 0
    assert receipt['credentials_loaded'] is False
    assert receipt['reservation_created'] is False
    assert list(tmp_path.iterdir()) == []


def test_integrated_telemetry_source_is_distinct_from_unrun_durable_acceptance():
    from scripts.run_codexlb_canary import build_manifest
    from scripts.canary_app_launcher import CanaryRunEvidence
    root = Path(__file__).resolve().parents[1]
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    plan = build_manifest(run_id=str(uuid4()), source_revision=revision)
    dependency = plan['telemetry_dependency']
    assert dependency['status'] == 'source_integrated_durable_evidence_pending'
    assert dependency['source_revision'] == '9d337087cc865fa801b81da7e4c12d35b0ac277c'
    assert dependency['implementation_revision'] == '701032f608a7d4c35b3ad098cf3ff1ec7c705563'
    assert dependency['merge_revision'] == '6e907c64a093c0aaf76cbb9dc6380e23c16205df'
    assert dependency['durable_evidence'] == 'not_run'
    assert 'telemetry_revision_integration_pending' not in plan['blockers']
    assert 'durable_and_browser_evidence_not_run' in plan['blockers']
    result = CanaryRunEvidence(plan).finish({'status': 'incomplete', 'cases': [],
        'provider_requests_started': 0, 'evidence_mode': 'mock_only'})
    assert result['telemetry_dependency'] == dependency
    assert result['live_ready'] is False
    assert plan['integration_provenance']['exact_merged_main_acceptance'] is False
    assert all(plan['evidence'][name] == 'not_run'
        for name in ('langfuse_api', 'langfuse_database', 'browser'))


def test_telemetry_integration_remains_unverified_for_old_or_unknown_source():
    from scripts.run_codexlb_canary import build_manifest
    for revision in ('0658dfffee60694824f5ebe36a57a126756320bb', 'f' * 40):
        plan = build_manifest(run_id=str(uuid4()), source_revision=revision)
        assert plan['telemetry_dependency']['status'] == 'source_integration_unverified'
        assert plan['telemetry_dependency']['durable_evidence'] == 'not_run'
        assert 'telemetry_revision_integration_pending' in plan['blockers']
        assert plan['live_ready'] is False
