"""Public evaluation commands; external services are synthetic loopback spies."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import threading

from scripts.run_isolated_check import offline_environment


ROOT = Path(__file__).resolve().parents[1]


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
