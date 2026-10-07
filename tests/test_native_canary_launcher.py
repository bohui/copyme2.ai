"""Native launcher admission tests; no Mac, containers, credentials or model."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


def test_pressure_level_two_blocks_before_resource_or_key_allocation(monkeypatch):
    from scripts.native_canary_launcher import resource_gate
    import scripts.native_canary_launcher as launcher
    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(launcher.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='2\n'))
    with pytest.raises(RuntimeError, match='pressure'):
        resource_gate()


@pytest.mark.parametrize('raw', ['0', '4', '', 'unknown', '1\n2'])
def test_unknown_or_high_pressure_is_not_capacity(raw, monkeypatch):
    from scripts.native_canary_launcher import resource_gate
    import scripts.native_canary_launcher as launcher
    monkeypatch.setattr(launcher.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(launcher.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=raw))
    with pytest.raises(RuntimeError): resource_gate()


def test_resource_lease_is_exclusive_and_retains_existing_owner(tmp_path):
    from scripts.native_canary_launcher import native_resource_lease
    lock = tmp_path / 'heavy.lock'
    with native_resource_lease('first', path=lock):
        first = lock.read_text()
        with pytest.raises(RuntimeError):
            with native_resource_lease('second', path=lock): pass
        assert lock.read_text() == first
    with native_resource_lease('third', path=lock):
        assert json.loads(lock.read_text())['run_id'] == 'third'


def test_check_command_never_prompts_or_starts_native_execution(tmp_path, monkeypatch, capsys):
    import scripts.native_canary_launcher as launcher
    monkeypatch.setattr(launcher, 'local_preflight', lambda **kwargs: {'source_revision': 'a' * 40})
    monkeypatch.setattr(launcher, 'execute_live', lambda *args, **kwargs: pytest.fail('Check must not execute'))
    monkeypatch.setattr(launcher, 'execute_controlled', lambda *args, **kwargs: pytest.fail('Check must not execute'))
    monkeypatch.setattr(sys, 'argv', ['native-canary', '--check', '--reviewed-head', 'a' * 40,
        '--output-root', str(tmp_path)])
    assert launcher.main() == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['execution_started'] is False
    assert receipt['input_read'] is False
    assert receipt['credentials_loaded'] is False
    assert receipt['gateway_auth_verified'] is False
    assert list(tmp_path.iterdir()) == []


def test_actor_staging_is_exclusive_and_only_copies_the_three_reviewed_task_files():
    from scripts.native_canary_launcher import stage_payload
    payload = stage_payload('12345678-1234-1234-1234-123456789abc')
    assert payload['directory'] == '/tmp/memoir-canary-12345678-1234-1234-1234-123456789abc'
    assert set(payload['files']) == {'canary_gateway_actor.py', 'canary_gateway_binding.py', 'canary_send_guard.py'}
    assert 'authorization' not in json.dumps(payload)


def test_live_preflight_failure_does_not_read_key_or_create_output(tmp_path, monkeypatch):
    import scripts.native_canary_launcher as launcher
    monkeypatch.setattr(launcher, 'local_preflight', lambda **kwargs: (_ for _ in ()).throw(RuntimeError('pressure')))
    monkeypatch.setattr(launcher, 'execute_live', lambda *args, **kwargs: pytest.fail('No live execution'))
    monkeypatch.setattr(sys, 'argv', ['native-canary', '--execute', '--reviewed-head', 'a' * 40,
        '--output-root', str(tmp_path)])
    assert launcher.main() == 3
    assert list(tmp_path.iterdir()) == []


def test_owned_command_deadline_reaps_only_its_started_process(tmp_path):
    import os
    from scripts.native_canary_launcher import run_owned, OwnedCommandFailed
    pid_file = tmp_path / 'owned.pid'
    program = f'import os,pathlib,time;pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()));time.sleep(30)'
    with pytest.raises(OwnedCommandFailed):
        run_owned([sys.executable, '-c', program], seconds=.5)
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError): os.kill(pid, 0)


def test_owned_failed_command_preserves_its_safe_stdout():
    from scripts.native_canary_launcher import run_owned, OwnedCommandFailed
    with pytest.raises(OwnedCommandFailed) as result:
        run_owned([sys.executable, '-c', 'print("synthetic failure receipt");raise SystemExit(3)'])
    assert b'synthetic failure receipt' in result.value.output


def test_actor_reconciliation_never_signals_an_unrelated_pid(tmp_path):
    from uuid import uuid4
    from scripts.native_canary_launcher import ACTOR_RECONCILE_PROGRAM
    process = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(20)'])
    try:
        result = subprocess.run([sys.executable, '-c', ACTOR_RECONCILE_PROGRAM],
            input=json.dumps({'run_id': str(uuid4()), 'actor_pid': process.pid}),
            capture_output=True, text=True, timeout=8, check=True)
        receipt = json.loads(result.stdout)
        assert receipt['initial_state'] == 'not_owned'
        assert receipt['signals_sent'] == []
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_actor_reconciliation_stops_only_the_exact_owned_script(tmp_path):
    import time
    from uuid import uuid4
    from scripts.native_canary_launcher import ACTOR_RECONCILE_PROGRAM
    run_id = str(uuid4())
    root = Path('/tmp') / ('memoir-canary-' + run_id)
    scripts = root / 'scripts'
    scripts.mkdir(parents=True)
    source = scripts / 'canary_gateway_actor.py'
    source.write_text('import time;time.sleep(20)')
    process = subprocess.Popen([sys.executable, str(source), '--stdio'])
    try:
        time.sleep(.1)
        result = subprocess.run([sys.executable, '-c', ACTOR_RECONCILE_PROGRAM],
            input=json.dumps({'run_id': run_id, 'actor_pid': process.pid}),
            capture_output=True, text=True, timeout=8, check=True)
        receipt = json.loads(result.stdout)
        assert receipt['initial_state'] == 'owned_actor_still_running'
        assert receipt['signals_sent'] == ['SIGTERM']
        assert receipt['final_state'] in {'absent', 'exited_unreaped'}
        process.wait(timeout=5)
    finally:
        if process.poll() is None: process.kill(); process.wait(timeout=5)
        source.unlink(); scripts.rmdir(); root.rmdir()


@pytest.fixture
def synthetic_live_run(tmp_path, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    import time
    import scripts.native_canary_launcher as launcher
    import scripts.canary_gateway_auth as auth
    import scripts.canary_app_launcher as app
    import scripts.run_codexlb_canary as manifest
    import test_shared_memory_events_postgres as fixtures
    import memoir_postgres_workflow as postgres
    import apps.api.memory_event_worker as events
    from temporalio.testing import WorkflowEnvironment

    # Simulate the full owner lifecycle. No native process, key input, SQL,
    # Temporal server or provider request is used by this regression.
    environment = {}
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(environ=environment))
    state = {'hidden_input_loaded': False, 'pressure_failure': False, 'postgres_removed': False}
    def gate():
        if state['hidden_input_loaded'] and state['pressure_failure']:
            raise launcher.NativeGateError('native_memory_pressure_elevated_or_unknown')
        return {}
    monkeypatch.setattr(launcher, 'resource_gate', gate)
    monkeypatch.setattr(launcher, 'runtime_source_preflight', lambda *args: {})
    monkeypatch.setattr(launcher, 'stage_actor', lambda *args: {'directory': 'synthetic'})
    monkeypatch.setattr(launcher, 'reconcile_postgres', lambda *args: state['postgres_removed'])
    monkeypatch.setattr(launcher, 'reconcile_actor', lambda *args: {'signals_sent': []})
    monkeypatch.setattr(launcher, 'collect_actor_evidence', lambda *args: {'actor_process_state': 'absent'})
    monkeypatch.setattr(manifest, 'build_manifest', lambda **kwargs: {'cases': [{
        'owner_id': 'synthetic-owner', 'project_id': 'synthetic-project',
        'family_enabled': False, 'language': 'en'}]})
    gateway_receipt = {'actor_pid': 123, 'guarded_send_entries': 0,
        'cleanup': {'closed': True, 'active_finished': True},
        'actor_cleanup': {'finished': True},
        'bridge_cleanup': {'child_reaped': True, 'listener_closed': True, 'actor_exit_verified': True}}
    async def gateway_stop(): return gateway_receipt
    lease = SimpleNamespace(deadline=time.monotonic() + 30, stop=gateway_stop,
        receipt=lambda: gateway_receipt)
    admission_counts = []
    @asynccontextmanager
    async def worker_scope(**kwargs):
        # Reproduce the real auth scope's callback order without reading a key.
        state['hidden_input_loaded'] = True
        kwargs['on_input_read']()
        kwargs['before_actor_start']()
        admission_counts.append(json.loads(next(tmp_path.glob('*/native-receipt.json')).read_text())[
            'provider_requests_started'])
        kwargs['on_actor_started'](gateway_receipt)
        yield SimpleNamespace(gateway_lease=lease, api_key='')
    monkeypatch.setattr(auth, 'authenticated_canary_worker', worker_scope)
    def database(**kwargs):
        kwargs['allocation'].update(attempted=True, created=True)
        kwargs['on_allocation']()
        def sql(*args): pass
        sql.command = ['container', 'exec', '--interactive', environment['MEMOIR_TEST_POSTGRES_CONTAINER_NAME']]
        yield sql
    monkeypatch.setattr(fixtures, 'database', SimpleNamespace(__wrapped__=database))
    for name in ('attachment_database', 'private_database', 'event_database'):
        monkeypatch.setattr(fixtures, name, SimpleNamespace(__wrapped__=lambda sql: sql))
    async def shutdown(): pass
    async def start_local(**kwargs): return SimpleNamespace(client=None, shutdown=shutdown)
    monkeypatch.setattr(WorkflowEnvironment, 'start_local', start_local)
    storage = SimpleNamespace(save_profile=lambda *args: None, client=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(postgres, 'PostgresRest', lambda *args, **kwargs: SimpleNamespace(
        storage=lambda: storage, handle=lambda request: None))
    monkeypatch.setattr(events, 'MemoirLaneBroker', lambda **kwargs: None)
    async def run_application(*args, **kwargs):
        gateway_receipt['guarded_send_entries'] = 1
        if state['application_outcome'] == 'failed':
            raise RuntimeError('Synthetic failure after guarded entry')
        if state['application_outcome'] == 'cancelled':
            raise asyncio.CancelledError
        return {'status': 'app_completed_evidence_pending', 'app_receipt': {'guarded_send_entries': 1}}
    monkeypatch.setattr(app, 'run_application_canary', run_application)
    args = SimpleNamespace(output_root=tmp_path, input_mode='environment',
        reviewed_head='a' * 40, docker='/unused/docker', codex='/unused/codex', codex_sha256='a' * 64)
    def run(*, application_outcome='completed', postgres_removed=True,
            pressure_failure=False, bridge_cleanup='verified'):
        state.update(application_outcome=application_outcome, postgres_removed=postgres_removed,
                     pressure_failure=pressure_failure)
        if bridge_cleanup == 'missing':
            del gateway_receipt['bridge_cleanup']
        elif bridge_cleanup != 'verified':
            gateway_receipt['bridge_cleanup'] = bridge_cleanup
        result = asyncio.run(launcher.execute_live(args, {
            'credentials_loaded': False, 'execution_started': False, 'gateway_auth_verified': False}))
        receipt = json.loads(Path(result['native_receipt']).read_text())
        return result, receipt, admission_counts
    return run


@pytest.mark.parametrize('application_outcome', ['completed', 'failed', 'cancelled'])
def test_unverified_postgres_removal_cannot_leave_live_run_complete(synthetic_live_run, application_outcome):
    result, receipt, admission_counts = synthetic_live_run(
        application_outcome=application_outcome, postgres_removed=False)
    assert receipt['cleanup']['postgres_removal_verified'] is False
    assert result['status'] == 'incomplete'
    assert receipt['provider_requests_started'] is None
    assert result['provider_requests_started'] is None
    assert receipt['guarded_send_entries'] == 1
    assert result['guarded_send_entries'] == 1
    assert admission_counts == [None]


@pytest.mark.parametrize('field', ['child_reaped', 'listener_closed', 'actor_exit_verified'])
@pytest.mark.parametrize('value', [False, None, 'missing', 1])
def test_bridge_cleanup_requires_each_verified_flag(synthetic_live_run, field, value):
    bridge_cleanup = {'child_reaped': True, 'listener_closed': True, 'actor_exit_verified': True}
    if value == 'missing':
        del bridge_cleanup[field]
    else:
        bridge_cleanup[field] = value
    result, receipt, _ = synthetic_live_run(bridge_cleanup=bridge_cleanup)
    assert result['status'] == 'incomplete'
    assert receipt['cleanup']['gateway_bridge_finished'] is False
    assert receipt['cleanup']['postgres_removal_verified'] is True


@pytest.mark.parametrize('bridge_cleanup', ['missing', None, {}])
def test_missing_bridge_cleanup_cannot_leave_live_run_complete(synthetic_live_run, bridge_cleanup):
    result, receipt, _ = synthetic_live_run(bridge_cleanup=bridge_cleanup)
    assert result['status'] == 'incomplete'
    assert receipt['cleanup']['gateway_bridge_finished'] is False


def test_verified_bridge_cleanup_preserves_application_success(synthetic_live_run):
    result, receipt, _ = synthetic_live_run()
    assert result['status'] == 'app_completed_evidence_pending'
    assert receipt['cleanup']['gateway_bridge_finished'] is True
    assert receipt['provider_requests_started'] is None
    assert receipt['guarded_send_entries'] == 1


def test_pressure_failure_after_hidden_input_records_input_without_actor_start(synthetic_live_run):
    result, receipt, admission_counts = synthetic_live_run(pressure_failure=True)
    assert result['status'] == 'incomplete'
    assert receipt['blocked_reason'] == 'native_memory_pressure_elevated_or_unknown'
    assert receipt['credentials_loaded'] is True
    assert receipt['input_read'] is True
    assert receipt['actor_start_attempted'] is False
    assert receipt['execution_started'] is False
    assert receipt['gateway_auth_verified'] is False
    assert receipt['provider_requests_started'] == result['provider_requests_started'] == 0
    assert admission_counts == []


@pytest.mark.parametrize('outcome', ['passed', 'skipped', 'missing', 'empty', 'failure'])
def test_controlled_native_success_requires_actual_application_test_receipt(tmp_path, monkeypatch, outcome):
    import scripts.native_canary_launcher as launcher
    monkeypatch.setattr(launcher, 'resource_gate', lambda: {})
    monkeypatch.setattr(launcher, 'reconcile_postgres', lambda *args: True)
    def synthetic_check(command, **kwargs):
        junit = Path(next(value.split('=', 1)[1] for value in command if value.startswith('--junitxml=')))
        if outcome != 'missing':
            case = '' if outcome == 'empty' else (
                '<testcase classname="tests.test_canary_application_native" '
                'name="test_ten_original_app_rounds_two_drafts_and_joined_single_attempt_jobs">'
                + ('' if outcome == 'passed' else '<' + outcome + '/>') + '</testcase>')
            junit.write_text('<testsuites><testsuite>' + case + '</testsuite></testsuites>')
        return b'synthetic controlled test output'
    monkeypatch.setattr(launcher, 'run_owned', synthetic_check)
    result = launcher.execute_controlled(SimpleNamespace(output_root=tmp_path), {})
    assert result['status'] == ('controlled_native_passed' if outcome == 'passed' else 'incomplete')


@pytest.mark.parametrize('scenario, input_mode, input_read, validated', [
    ('invalid', 'environment', True, False),
    ('empty', 'environment', True, False),
    ('missing', 'environment', False, False),
    ('invalid', 'prompt', True, False),
    ('empty', 'prompt', True, False),
    ('eof', 'prompt', False, False),
    ('echo_fallback', 'prompt', False, False),
    ('not_tty', 'prompt', False, False),
    ('pressure', 'environment', True, True),
    ('pressure', 'prompt', True, True),
    ('invalid_target', 'environment', False, False),
])
def test_real_auth_input_receipt_distinguishes_read_from_validated(
        tmp_path, monkeypatch, capsys, scenario, input_mode, input_read, validated):
    import asyncio
    import warnings
    import scripts.native_canary_launcher as launcher
    import scripts.canary_gateway_auth as auth
    import scripts.run_codexlb_canary as manifest
    from scripts.canary_gateway_bridge import NativeGatewayLease

    # Exercise the real auth/input contexts with an isolated synthetic source.
    # Actor creation, native commands, infrastructure and auth contact are blocked.
    reads = []
    class InputEnvironment(dict):
        def pop(self, key, default=None):
            if key == auth.TASK_KEY_NAME and key in self:
                reads.append('environment')
            return super().pop(key, default)
    raw = {'invalid': 'synthetic invalid input', 'empty': ''}.get(scenario, 'synthetic-only-input')
    environment = InputEnvironment()
    if input_mode == 'environment' and scenario != 'missing':
        environment[auth.TASK_KEY_NAME] = raw
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(environ=environment))
    monkeypatch.setattr(auth, 'os', SimpleNamespace(environ=environment))
    monkeypatch.setattr(auth.sys.stdin, 'isatty', lambda: scenario != 'not_tty')
    def prompt(**kwargs):
        if scenario == 'echo_fallback':
            warnings.warn('Synthetic hidden-input failure', auth.getpass.GetPassWarning)
            pytest.fail('Echo fallback must stop before input')
        if scenario == 'eof':
            raise EOFError
        if scenario == 'not_tty':
            pytest.fail('A non-terminal must not prompt')
        reads.append('prompt')
        return raw
    monkeypatch.setattr(auth.getpass, 'getpass', prompt)
    gates = []
    def gate():
        gates.append(True)
        if len(gates) == 2:
            raise launcher.NativeGateError('native_memory_pressure_elevated_or_unknown')
        return {}
    monkeypatch.setattr(launcher, 'resource_gate', gate)
    monkeypatch.setattr(launcher, 'runtime_source_preflight', lambda *args: {})
    monkeypatch.setattr(launcher, 'stage_actor', lambda *args: {'directory': 'synthetic'})
    monkeypatch.setattr(launcher, 'reconcile_actor', lambda *args: {'signals_sent': []})
    monkeypatch.setattr(launcher, 'collect_actor_evidence', lambda *args: {'actor_process_state': 'absent'})
    monkeypatch.setattr(manifest, 'build_manifest', lambda **kwargs: {'cases': []})
    def validate_target(**kwargs):
        if scenario == 'invalid_target':
            raise ValueError('Synthetic target validation failure')
    monkeypatch.setattr(NativeGatewayLease, 'validate_native_target', validate_target)
    async def forbidden(**kwargs): pytest.fail('Input/pressure failure must not start an actor')
    monkeypatch.setattr(NativeGatewayLease, 'start_native', forbidden)
    args = SimpleNamespace(output_root=tmp_path, input_mode=input_mode,
        reviewed_head='a' * 40, docker='/unused/docker', codex='/unused/codex', codex_sha256='a' * 64)
    result = asyncio.run(launcher.execute_live(args, {
        'credentials_loaded': False, 'execution_started': False, 'gateway_auth_verified': False}))
    receipt = json.loads(Path(result['native_receipt']).read_text())
    assert len(reads) == int(input_read)
    assert receipt['input_read'] is input_read
    assert receipt['credentials_loaded'] is validated
    assert receipt['actor_start_attempted'] is False
    assert receipt['execution_started'] is False
    assert receipt['gateway_auth_verified'] is False
    assert result['status'] == 'incomplete'
    assert receipt['provider_requests_started'] == result['provider_requests_started'] == 0
    expected_stage = 'post_input_resource_gate' if validated else (
        'gateway_input_validation' if input_read else 'gateway_auth_input')
    assert receipt['error_stage'] == expected_stage
    assert auth.TASK_KEY_NAME not in environment
    assert capsys.readouterr() == ('', '')
    for path in tmp_path.rglob('*.json'):
        assert not raw or raw not in path.read_text()


@pytest.mark.parametrize('admitted', [False, True])
def test_unrecoverable_entrypoint_error_reports_input_uncertainty(tmp_path, monkeypatch, capsys, admitted):
    from contextlib import nullcontext
    import scripts.native_canary_launcher as launcher
    def preflight(**kwargs):
        if not admitted:
            raise RuntimeError('Synthetic preflight failure')
        return {'input_read': False, 'credentials_loaded': False}
    async def failure(*args):
        raise RuntimeError('Synthetic error without recoverable receipt')
    monkeypatch.setattr(launcher, 'local_preflight', preflight)
    monkeypatch.setattr(launcher, 'native_resource_lease', lambda *args: nullcontext())
    monkeypatch.setattr(launcher, 'execute_live', failure)
    monkeypatch.setattr(sys, 'argv', ['native-canary', '--execute', '--reviewed-head', 'a' * 40,
        '--output-root', str(tmp_path)])
    assert launcher.main() == 3
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['input_read'] is (None if admitted else False)
    assert receipt['credentials_loaded'] is (None if admitted else False)
