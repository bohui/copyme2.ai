"""Generic evaluation CLI failure persistence; all provider replies are synthetic."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.run_isolated_check import offline_environment


ROOT = Path(__file__).resolve().parents[1]


def _run_cli(tmp_path, *, fail_first=False, concurrency=1, fail=True, failure_kind="exception", variants=(), failure_variant=None):
    callback = tmp_path / 'controlled_evaluation.py'
    callback.write_text('''from apps.api.evaluation_cases import run_case as app_case
async def run_case(case, correlation):
    if (case['id'] == 'controlled-error'
            and case.get('failure_variant') in (None, correlation.get('variant'))):
        failure_kind = case.get('failure_kind', 'exception')
        if failure_kind == 'missing_trajectory':
            return {'reply': 'A reply alone is not a trajectory.'}
        if failure_kind == 'invalid_result':
            return None
        if failure_kind == 'timeout':
            raise TimeoutError('private storyteller text and secret-token-must-not-leak')
        raise RuntimeError('private storyteller text and secret-token-must-not-leak')
    return await app_case(case, correlation)
''')
    payload = json.loads((ROOT / 'tests/evaluation/cases.json').read_text())
    good = payload['cases'][0]
    cases = [good, {**good, 'id': 'controlled-error', 'failure_kind': failure_kind, 'failure_variant': failure_variant}] if fail else [good]
    payload['cases'] = list(reversed(cases)) if fail_first else cases
    cases_file = tmp_path / 'cases.json'
    cases_file.write_text(json.dumps(payload))
    output = tmp_path / 'results.json'
    failure_dir = tmp_path / 'failures'
    env = offline_environment(ROOT)
    env['PYTHONPATH'] = str(tmp_path) + ':' + str(ROOT)
    command = [sys.executable, 'scripts/run_langfuse_evaluation.py',
        '--task', 'controlled_evaluation:run_case', '--cases', str(cases_file),
        '--concurrency', str(concurrency), '--run-id', 'controlled-run',
        '--output', str(output), '--failure-dir', str(failure_dir)]
    for variant in variants:
        command.extend(['--variant', variant])
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
        text=True, timeout=20)
    return completed, output, failure_dir


@pytest.mark.parametrize('fail_first,concurrency', [(False, 1), (True, 1), (False, 2)])
def test_task_exception_preserves_completed_siblings_and_failed_case(tmp_path, fail_first, concurrency):
    completed, output, failure_dir = _run_cli(tmp_path,
        fail_first=fail_first, concurrency=concurrency)
    assert completed.returncode == 1, completed.stderr
    assert output.is_file(), 'A failed case must not discard the other case results'
    results = json.loads(output.read_text())
    assert len(results) == 2
    by_id = {result['case_id']: result for result in results}
    good = by_id['place-cue-grounded']
    failed = by_id['controlled-error']
    assert good['result']['trajectory']['steps']
    assert good['acceptance']['deterministic_status'] == 'pass'
    assert good['acceptance']['status'] == 'unavailable'  # No semantic judge ran.
    assert failed['acceptance'] == {
        'status': 'error', 'deterministic_status': 'unavailable',
        'judge_status': 'not_run', 'judge_role': 'advisory'}
    assert failed['scores'] == []
    assert failed['failure_evidence'][0]['error_type'] == 'RuntimeError'
    assert failed['correlation']['run_id'] == 'controlled-run'
    assert failed['correlation']['case_id'] == 'controlled-error'
    assert failed['correlation']['application_revision']
    assert failed['correlation']['dataset_version'] == 'memoir-synthetic/2'
    assert failed['result']['trajectory'] is None  # Never invent a failed trajectory.
    assert json.loads((failure_dir / 'controlled-error-default.json').read_text()) == failed
    all_output = output.read_text() + completed.stderr + completed.stdout
    assert 'secret-token-must-not-leak' not in all_output
    assert 'private storyteller text' not in all_output


def test_successful_synthetic_cli_keeps_existing_output_contract(tmp_path):
    completed, output, failure_dir = _run_cli(tmp_path, fail=False)
    assert completed.returncode == 0, completed.stderr
    results = json.loads(output.read_text())
    assert len(results) == 1
    assert results[0]['acceptance']['deterministic_status'] == 'pass'
    assert list(failure_dir.glob('*.json')) == []


@pytest.mark.parametrize('failure_kind,error_type', [
    ('missing_trajectory', 'ValueError'), ('invalid_result', 'TypeError'),
    ('timeout', 'TimeoutError')])
def test_incomplete_task_evidence_is_persisted_without_scoring(tmp_path, failure_kind, error_type):
    completed, output, failure_dir = _run_cli(tmp_path, failure_kind=failure_kind)
    assert completed.returncode == 1, completed.stderr
    results = json.loads(output.read_text())
    failed = next(result for result in results if result['case_id'] == 'controlled-error')
    assert failed['acceptance']['status'] == 'error'
    assert failed['acceptance']['deterministic_status'] == 'unavailable'
    assert failed['scores'] == []
    assert failed['trajectory_sha256'] is None
    assert failed['failure_evidence'][0]['error_type'] == error_type
    assert (failure_dir / 'controlled-error-default.json').is_file()


def test_variant_output_and_failure_receipts_remain_separate(tmp_path):
    completed, output, failure_dir = _run_cli(tmp_path, variants=('baseline', 'candidate'))
    assert completed.returncode == 1, completed.stderr
    payload = json.loads(output.read_text())
    assert len(payload['results']) == 4
    failed = [result for result in payload['results'] if result['case_id'] == 'controlled-error']
    assert {result['correlation']['variant'] for result in failed} == {'baseline', 'candidate'}
    assert all(result['acceptance']['status'] == 'error' for result in failed)
    for result in failed:
        path = failure_dir / f"controlled-error-{result['correlation']['variant']}.json"
        assert json.loads(path.read_text()) == result


@pytest.mark.parametrize('failed_variant', ['baseline', 'candidate'])
def test_asymmetric_variant_failure_never_becomes_zero_score_baseline(tmp_path, failed_variant):
    completed, output, failure_dir = _run_cli(tmp_path, concurrency=2,
        variants=('baseline', 'candidate'), failure_variant=failed_variant)
    assert completed.returncode == 1, completed.stderr
    payload = json.loads(output.read_text())
    results = {result['correlation']['variant']: result for result in payload['results']
        if result['case_id'] == 'controlled-error'}
    assert set(results) == {'baseline', 'candidate'}
    assert results[failed_variant]['acceptance']['status'] == 'error'
    assert results[failed_variant]['scores'] == []
    successful_variant = 'candidate' if failed_variant == 'baseline' else 'baseline'
    assert results[successful_variant]['acceptance']['deterministic_status'] == 'pass'
    assert json.loads((failure_dir / f'controlled-error-{failed_variant}.json').read_text()) == results[failed_variant]
    comparisons = {row['variant']: row for row in payload['comparisons']
        if row['case_id'] == 'controlled-error'}
    candidate = comparisons['candidate']
    assert candidate['deltas'] == {}, 'Missing evidence must never become zero-valued baseline scores'
    assert candidate['comparison_status'] == 'unavailable'
    assert candidate['unavailable_metrics']
    if failed_variant == 'candidate':
        assert comparisons['baseline']['comparison_status'] == 'compared'
        assert all(delta == 0 for delta in comparisons['baseline']['deltas'].values())


def test_partial_comparison_uses_only_metrics_actually_scored_on_both_sides():
    from apps.api.trajectory_evaluation import comparison_matrix
    results = [
        {'case_id': 'partial', 'correlation': {'variant': 'baseline'},
         'scores': [{'name': 'shared', 'value': 0.25},
                    {'name': 'baseline_only', 'value': 0.75}]},
        {'case_id': 'partial', 'correlation': {'variant': 'candidate'},
         'scores': [{'name': 'shared', 'value': 0.75},
                    {'name': 'candidate_only', 'value': 0.5}]},
    ]
    rows = comparison_matrix(results, baseline_variant='baseline')
    candidate = next(row for row in rows if row['variant'] == 'candidate')
    assert candidate['deltas'] == {'shared': 0.5}
    assert candidate['comparison_status'] == 'partial'
    assert candidate['unavailable_metrics'] == ['baseline_only', 'candidate_only']


def test_error_receipt_with_partial_scores_is_not_comparable():
    from apps.api.trajectory_evaluation import comparison_matrix
    results = [
        {'case_id': 'partial-error', 'correlation': {'variant': 'baseline'},
         'acceptance': {'status': 'error'}, 'scores': [{'name': 'shared', 'value': 0.0}]},
        {'case_id': 'partial-error', 'correlation': {'variant': 'candidate'},
         'scores': [{'name': 'shared', 'value': 1.0}]},
    ]
    rows = comparison_matrix(results, baseline_variant='baseline')
    assert all(row['deltas'] == {} for row in rows)
    assert all(row['comparison_status'] == 'unavailable' for row in rows)


def test_comparison_keeps_measured_zero_but_never_supplies_missing_values():
    from apps.api.trajectory_evaluation import comparison_matrix
    results = [
        {'case_id': 'metrics', 'correlation': {'variant': 'baseline'}, 'scores': [
            {'name': 'measured_zero', 'value': 0.0}, {'name': 'missing_value'}]},
        {'case_id': 'metrics', 'correlation': {'variant': 'candidate'}, 'scores': [
            {'name': 'measured_zero', 'value': 0.5}, {'name': 'missing_value', 'value': 1.0}]},
    ]
    candidate = comparison_matrix(results, baseline_variant='baseline')[1]
    assert candidate['deltas'] == {'measured_zero': 0.5}
    assert candidate['comparison_status'] == 'partial'
    assert candidate['unavailable_metrics'] == ['missing_value']
