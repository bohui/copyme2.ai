"""Public evaluation commands; external services are synthetic loopback spies."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading
import pytest

from scripts.run_isolated_check import offline_environment


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_null_cases_returns_invalid_dataset_without_allocation(tmp_path):
    path = tmp_path / 'null-cases.json'
    path.write_text('{"cases":null}')
    result = subprocess.run([sys.executable, 'scripts/run_canonical_five_case_evaluation.py',
        '--plan-only', '--inputs', str(path), '--run-id', 'null-cases',
        '--output-root', str(tmp_path)], cwd=ROOT, env=offline_environment(ROOT),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2, result.stderr
    assert json.loads(result.stdout)['status'] == 'invalid_dataset'
    assert not (tmp_path / 'null-cases').exists()


def test_canonical_fixture_zero_request_budget_refuses_service_allocation(tmp_path):
    result = subprocess.run([sys.executable, 'scripts/run_canonical_five_case_evaluation.py',
        '--execute-fixture', '--run-id', 'zero-budget-fixture', '--output-root', str(tmp_path),
        '--max-worker-requests', '0', '--max-seconds', '30'], cwd=ROOT,
        env=offline_environment(ROOT), capture_output=True, text=True, timeout=10)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'blocked'
    assert receipt['execution_started'] is False
    assert receipt['resources_allocated'] is False
    assert receipt['provider_requests_started'] == 0
    assert 'explicit_positive_fixture_limits_required' in receipt['blockers']


def test_canonical_fixture_expired_deadline_records_a_stop_before_native_allocation(tmp_path):
    result = subprocess.run([sys.executable, 'scripts/run_canonical_five_case_evaluation.py',
        '--execute-fixture', '--run-id', 'expired-native-fixture', '--output-root', str(tmp_path),
        '--max-worker-requests', '1', '--max-seconds', '0.000000001'], cwd=ROOT,
        env=offline_environment(ROOT), capture_output=True, text=True, timeout=10)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'blocked'
    assert receipt['resources_allocated'] is False
    assert receipt['provider_requests_started'] == 0
    assert receipt['provider_input_tokens'] == receipt['provider_output_tokens'] == 0
    assert receipt['blockers'] == ['fixture_time_limit_reached_before_allocation']
    persisted = json.loads((tmp_path / 'expired-native-fixture' / 'summary.json').read_text())
    assert persisted == receipt


def test_canonical_case_identifier_cannot_escape_its_run_directory(tmp_path):
    inputs = json.loads((ROOT / 'tests/evaluation/memoir_five_case_inputs.json').read_text())
    inputs['cases'][0]['id'] = '../outside-the-run'
    path = tmp_path / 'unsafe-inputs.json'
    path.write_text(json.dumps(inputs))
    result = subprocess.run([sys.executable, 'scripts/run_canonical_five_case_evaluation.py',
        '--plan-only', '--inputs', str(path), '--run-id', 'unsafe-case',
        '--output-root', str(tmp_path)], cwd=ROOT, env=offline_environment(ROOT),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert json.loads(result.stdout)['status'] == 'invalid_dataset'
    assert not (tmp_path / 'unsafe-case').exists()


@pytest.mark.parametrize('mode', ['fixture', 'pilot'])
def test_resumed_fixture_places_cannot_contact_geocoding_with_configured_credentials(tmp_path, mode):
    contacts = []
    class GeocodingSpy(BaseHTTPRequestHandler):
        def do_GET(self):
            contacts.append(self.path.split('?', 1)[0])
            data = b'{"status":"ZERO_RESULTS","results":[]}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, format, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), GeocodingSpy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        case_id = 'harbour-copper-notebook'
        run_id = 'resumed-provider-free'
        case_dir = tmp_path / run_id / 'cases' / case_id
        case_dir.mkdir(parents=True)
        (case_dir / 'storage_state.json').write_text(json.dumps({'place_history': [
            {'place': 'Perth', 'hierarchy': ['Earth', 'Australia', 'Western Australia', 'Perth'],
             'granularity': 'city'}]}))
        synthetic_env = tmp_path / 'synthetic.env'
        synthetic_env.write_text('GOOGLE_MAPS_GEOCODING_API_KEY=synthetic-only\n'
            f'GOOGLE_MAPS_GEOCODING_URL=http://127.0.0.1:{server.server_port}/geocode\n')
        process_env = offline_environment(ROOT)
        process_env.update(GOOGLE_MAPS_GEOCODING_API_KEY='synthetic-only',
            GOOGLE_MAPS_GEOCODING_URL=f'http://127.0.0.1:{server.server_port}/geocode')
        result = subprocess.run([sys.executable, 'scripts/run_memoir_five_case_evaluation.py',
            '--mode', mode, '--resume', '--skip-preflight', '--env-file', str(synthetic_env),
            '--run-id', run_id, '--output-root', str(tmp_path), '--cases', case_id,
            '--max-rounds', '1'], cwd=ROOT, env=process_env,
            capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        trace = json.loads((case_dir / 'rounds' / 'round-001.json').read_text())
        # Restored missing-coordinate places and a newly accepted place are
        # both present: absence of contact cannot be caused by no place work.
        saved = json.loads((case_dir / 'storage_state.json').read_text())
        assert {p['place'] for p in saved['place_history']} >= {'Perth', 'Hobart'}
        assert contacts == []
        assert trace['execution_mode'] == 'fixture'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_canonical_plan_keeps_250_original_inputs_and_allocates_separate_case_owners(tmp_path):
    result = subprocess.run([sys.executable, 'scripts/run_canonical_five_case_evaluation.py',
        '--plan-only', '--run-id', 'canonical-five-case-plan', '--output-root', str(tmp_path)],
        cwd=ROOT, env=offline_environment(ROOT), capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['status'] == 'planned'
    assert plan['execution_started'] is False
    assert plan['evidence_mode'] == 'mock_only'
    assert plan['provider_requests_started'] == 0
    assert len(plan['cases']) == 5
    assert len({c['owner_id'] for c in plan['cases']}) == 5
    assert len({c['project_id'] for c in plan['cases']}) == 5
    assert all(len(c['rounds']) == 50 for c in plan['cases'])
    assert plan['cases'][0]['rounds'][0] == 'I was born in Hobart, and the first family story says the harbour wind rattled the windows.'
    assert plan['cases'][1]['rounds'][0] == '我出生在成都，家里人说我还是婴儿时就喜欢听雨声。'
    assert all(c['checkpoints'] == [5, 10, 15, 20, 25, 30, 35, 40, 45, 50] for c in plan['cases'])
    assert plan['dataset']['inputs_sha256']
    assert plan['application_revision']['commit']
    assert plan['skill_manifest']
    persisted = json.loads((tmp_path / 'canonical-five-case-plan' / 'plan.json').read_text())
    assert persisted == plan


def test_skipping_preflight_cannot_start_unmetered_live_worker_calls(tmp_path):
    contacts = []
    class SyntheticWorker(BaseHTTPRequestHandler):
        def do_POST(self):
            contacts.append(self.path)
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            data = json.dumps({'reply': 'Synthetic reply.', 'thread_id': 'synthetic', 'source_paths': []}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, format, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), SyntheticWorker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f'http://127.0.0.1:{server.server_port}'
        result = subprocess.run([sys.executable, 'scripts/run_memoir_five_case_evaluation.py',
            '--mode', 'live', '--skip-preflight', '--env-file', '/dev/null',
            '--run-id', 'unmetered-live', '--output-root', str(tmp_path / 'results'),
            '--cases', 'harbour-copper-notebook', '--max-rounds', '1',
            '--worker-url', origin, '--worker-secret', 'synthetic',
            '--provider-url', origin + '/v1', '--provider-model', 'synthetic-provider',
            '--timeout', '1', '--composer-timeout', '1'], cwd=ROOT,
            env=offline_environment(ROOT), capture_output=True, text=True, timeout=20)
        assert contacts == []
        assert result.returncode == 3
        receipt = json.loads(result.stdout)
        assert receipt['status'] == 'blocked'
        assert 'verified_provider_accounting_unavailable' in receipt['blockers']
        assert receipt['provider_requests_started'] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
