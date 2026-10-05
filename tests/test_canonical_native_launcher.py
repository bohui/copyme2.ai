"""Full public native fixture command; requires the shared resource window.

This test is deliberately outside the lightweight CLI suite. It starts one
disposable PostgreSQL and one Temporal server and controls only the external
provider protocol. Do not treat its mock output as live model acceptance.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

from scripts.run_isolated_check import offline_environment


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which('container') is None,
    reason='Canonical native launcher requires the supported Apple Container fixture')
def test_five_native_case_owners_preserve_all_250_originals_and_50_checkpoints(tmp_path):
    result = subprocess.run([sys.executable, 'scripts/run_canonical_five_case_evaluation.py',
        '--execute-fixture', '--run-id', 'native-five-case-fixture', '--output-root', str(tmp_path),
        '--max-worker-requests', '2000', '--max-seconds', '1500'], cwd=ROOT,
        env=offline_environment(ROOT), capture_output=True, text=True, timeout=1560)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'completed'
    assert receipt['evidence_mode'] == 'mock_only'
    assert receipt['model_output_quality'] == 'unavailable'
    assert receipt['provider_requests_started'] == 0
    assert receipt['provider_input_tokens'] == receipt['provider_output_tokens'] == 0
    assert receipt['private_worker_requests_started'] == receipt['fixture_protocol_calls']
    assert 0 < receipt['private_worker_requests_started'] <= 2000
    assert len(receipt['cases']) == 5
    assert len({case['owner_id'] for case in receipt['cases']}) == 5
    assert len({case['project_id'] for case in receipt['cases']}) == 5
    originals = json.loads((ROOT / 'tests/evaluation/memoir_five_case_inputs.json').read_text())
    inputs = {case['id']: case['rounds'] for case in originals['cases']}
    for case in receipt['cases']:
        assert case['status'] == 'completed'
        assert len(case['rounds']) == 50
        assert all(round['background_settled'] for round in case['rounds'])
        assert [c['milestone'] for c in case['checkpoints']] == [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
        view = case['canonical_state']
        assert view['completed_rounds'] == view['processing']['extracted_through'] == 50
        assert [s['text'] for s in view['sources']] == inputs[case['case_id']]
        persisted = json.loads((tmp_path / 'native-five-case-fixture' / 'cases' /
                                case['case_id'] / 'receipt.json').read_text())
        assert persisted == case
    assert receipt['cleanup'] == {'temporal_closed': True, 'readiness_closed': True,
        'worker_transport_closed': True, 'postgres_fixture_closed': True,
        'postgres_removal_verified': True, 'workspace_removed': True}
    # Inspect only the exact task UUID; no inventory of unrelated containers.
    stopped = subprocess.run(['container', 'inspect', receipt['postgres_container']],
        capture_output=True, text=True, timeout=15)
    assert stopped.returncode != 0
    assert f"container not found: {receipt['postgres_container']}" in stopped.stderr.lower()
