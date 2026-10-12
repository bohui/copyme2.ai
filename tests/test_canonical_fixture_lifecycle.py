"""Public fixture CLI failures using only controlled external process boundaries."""
import json
import asyncio
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time
from types import SimpleNamespace

import pytest

from scripts.run_isolated_check import offline_environment


ROOT = Path(__file__).resolve().parents[1]

# External PostgreSQL-driver stub paired with fake_container's psql transport.
# No application authority guard or classification is replaced.
PUBLICATION_CONNECTION_STUB = '''import psycopg
class ExternalConnection:
    @classmethod
    async def connect(cls, dsn, **kwargs):
        assert dsn.startswith('host=127.0.0.1 port=')
        assert kwargs['options'] == '-c default_transaction_read_only=on -c statement_timeout=2000'
        return cls()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def execute(self, query):
        assert query == 'select system_identifier::text from pg_control_system()'
        return self
    async def fetchone(self): return ('987654321',)
psycopg.AsyncConnection = ExternalConnection
'''


def fake_container(tmp_path, *, slow_stage=None, malformed_logs=False, stop_fails=False, eof_delay=None):
    """An external command stub: no Apple Container or PostgreSQL is launched."""
    binary = tmp_path / 'bin'
    binary.mkdir()
    state = tmp_path / 'container-alive'
    commands = tmp_path / 'container-commands.jsonl'
    executable = binary / 'container'
    executable.write_text(f'''#!{sys.executable}
import json, os, pathlib, sys, time
state = pathlib.Path({str(state)!r})
with pathlib.Path({str(commands)!r}).open('a') as log:
    log.write(json.dumps(sys.argv[1:]) + '\\n')
action = sys.argv[1]
if action == 'run':
    state.write_text(sys.argv[sys.argv.index('--name') + 1])
    if '--publish' in sys.argv:
        pathlib.Path({str(tmp_path / 'published-port')!r}).write_text(sys.argv[sys.argv.index('--publish') + 1])
    if {slow_stage!r} == 'startup': time.sleep(8)
elif action == 'logs':
    if {malformed_logs!r}:
        sys.stdout.buffer.write(b'\\xff')
    else: print('PostgreSQL init process complete; ready for start up.')
elif action == 'exec' and 'pg_isready' in sys.argv:
    pass
elif action == 'exec' and 'sh' in sys.argv:
    receipt = json.loads(pathlib.Path({str(tmp_path / 'external-lifecycle/summary.json')!r}).read_text())
    assert receipt['postgres_publication_endpoint']['binding_verified'] is True
    assert receipt['postgres_publication_endpoint']['guest_address'] == sys.argv[-1]
elif action == 'exec' and 'psql' in sys.argv:
    pathlib.Path({str(tmp_path / 'sql-process.pid')!r}).write_text(str(os.getpid()))
    if {eof_delay!r} is not None:
        os.close(1)
        time.sleep({eof_delay!r})
        os.write(2, b'Synthetic SQL failure\\n')
        os._exit(1)
    for line in sys.stdin:
        if {slow_stage!r} == 'migration': time.sleep(8)
        if line.startswith('select system_identifier::text'): print('987654321', flush=True)
        if line.startswith('\\\\echo '):
            print(line.split(' ', 1)[1].strip(), flush=True)
elif action == 'stop':
    if {stop_fails!r}: sys.exit(1)
    state.unlink(missing_ok=True)
elif action == 'inspect':
    if state.exists():
        inspection = pathlib.Path({str(tmp_path / 'inspection-started')!r})
        if {slow_stage!r} == 'inspection' and not inspection.exists():
            inspection.touch()
            time.sleep(8)
        port = int(pathlib.Path({str(tmp_path / 'published-port')!r}).read_text().split(':')[1])
        print(json.dumps([{{'configuration': {{'id': state.read_text(), 'publishedPorts': [{{
            'hostAddress': '127.0.0.1', 'hostPort': port, 'containerPort': 5432, 'proto': 'tcp', 'count': 1}}]}},
            'status': {{'state': 'running', 'networks': [{{'ipv4Address': '192.168.64.2/24'}}]}}}}]))
    else:
        print('Error: container not found: ' + sys.argv[-1], file=sys.stderr)
        sys.exit(1)
else: sys.exit(2)
''')
    executable.chmod(0o755)
    environment = offline_environment(ROOT)
    environment['PATH'] = str(binary) + ':' + environment.get('PATH', '')
    return environment, state, commands


def fixture_command(tmp_path, *, seconds=3):
    return [sys.executable, 'scripts/run_canonical_five_case_evaluation.py',
        '--execute-fixture', '--fixture-publication-tcp', '--run-id', 'external-lifecycle', '--output-root', str(tmp_path),
        '--max-worker-requests', '1', '--max-seconds', str(seconds)]


def test_sql_stdout_eof_waits_for_delayed_exit_within_remaining_fixture_budget(tmp_path):
    environment, state, _ = fake_container(tmp_path, eof_delay=.35)
    result = subprocess.run(fixture_command(tmp_path, seconds=5), cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    # A genuine SQL failure remains the outcome, rather than a spurious
    # process-wait timeout while the execution budget still has headroom.
    assert receipt['error_class'] == 'AssertionError'
    assert receipt['cleanup']['postgres_fixture_closed'] is True
    assert not state.exists()
    pid = int((tmp_path / 'sql-process.pid').read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_sql_stdout_eof_exhausted_deadline_closes_process_before_later_cleanup(tmp_path):
    environment, state, _ = fake_container(tmp_path, eof_delay=10)
    started = time.monotonic()
    result = subprocess.run(fixture_command(tmp_path, seconds=3), cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=15)
    assert time.monotonic() - started < 6, 'Expired SQL exit wait must kill its owned process promptly'
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['error_class'] == 'TimeoutError'
    assert receipt['cleanup']['postgres_fixture_closed'] is True
    assert not state.exists()
    pid = int((tmp_path / 'sql-process.pid').read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_successful_removal_preserves_uncertain_historical_container_allocation(tmp_path):
    environment, state, _ = fake_container(tmp_path, slow_stage='startup')
    result = subprocess.run(fixture_command(tmp_path, seconds=3), cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['postgres_allocation'] == {'attempted': True, 'created': False}
    # The container command created its external resource before stalling,
    # but never confirmed success. Final absence cannot prove no allocation.
    assert receipt['resources_allocated'] is None
    assert receipt['cleanup']['postgres_fixture_closed'] is True
    assert receipt['cleanup']['postgres_removal_verified'] is True
    assert not state.exists()


@pytest.mark.parametrize('stage', ['startup', 'inspection', 'migration'])
def test_fixture_deadline_bounds_native_startup_and_migrations(tmp_path, stage):
    environment, state, commands = fake_container(tmp_path, slow_stage=stage)
    started = time.monotonic()
    result = subprocess.run(fixture_command(tmp_path), cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=20)
    assert time.monotonic() - started < 6, 'Setup ignored the three-second fixture deadline'
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'incomplete'
    assert receipt['cleanup']['postgres_fixture_closed'] is True
    assert not state.exists()
    if stage == 'inspection':
        calls = [json.loads(line) for line in commands.read_text().splitlines()]
        assert not any(any('mv /tmp/memoir-publication-address.tmp' in part for part in call) for call in calls)
        assert receipt['cleanup']['postgres_endpoint_closed'] is True
    assert json.loads((tmp_path / 'external-lifecycle/summary.json').read_text()) == receipt


def test_sigterm_during_temporal_shutdown_preserves_terminal_receipt_and_cleanup(tmp_path):
    environment, state, _ = fake_container(tmp_path)
    wrapper = tmp_path / 'external_temporal.py'
    wrapper.write_text(PUBLICATION_CONNECTION_STUB + '''import asyncio, os, runpy, signal
from types import SimpleNamespace
from temporalio.testing import WorkflowEnvironment
async def shutdown():
    os.kill(os.getpid(), signal.SIGTERM)
    await asyncio.sleep(.05)
async def start_local(**kwargs):
    # This external SDK stub owns no native server. An invalid SDK client
    # makes the real Worker reject startup, reaching normal shutdown.
    return SimpleNamespace(client=None, shutdown=shutdown)
WorkflowEnvironment.start_local = start_local
runpy.run_path('scripts/run_canonical_five_case_evaluation.py', run_name='__main__')
''')
    command = fixture_command(tmp_path, seconds=10)
    command[1] = str(wrapper)
    result = subprocess.run(command, cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'incomplete'
    assert receipt['cleanup']['temporal_closed'] is True
    assert receipt['cleanup']['readiness_closed'] is True
    assert receipt['cleanup']['postgres_fixture_closed'] is True
    assert receipt['cleanup']['workspace_removed'] is True
    assert not state.exists()
    assert json.loads((tmp_path / 'external-lifecycle/summary.json').read_text()) == receipt


def test_native_service_logs_do_not_corrupt_public_cli_json(tmp_path):
    environment, _, _ = fake_container(tmp_path)
    wrapper = tmp_path / 'external_temporal_logs.py'
    wrapper.write_text(PUBLICATION_CONNECTION_STUB + '''import runpy
from types import SimpleNamespace
from temporalio.testing import WorkflowEnvironment
async def shutdown(): pass
async def start_local(**kwargs):
    print('Synthetic Temporal startup banner', flush=True)
    return SimpleNamespace(client=None, shutdown=shutdown)
WorkflowEnvironment.start_local = start_local
runpy.run_path('scripts/run_canonical_five_case_evaluation.py', run_name='__main__')
''')
    command = fixture_command(tmp_path, seconds=10)
    command[1] = str(wrapper)
    result = subprocess.run(command, cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'incomplete'
    assert 'Synthetic Temporal startup banner' in result.stderr


def test_canonical_fixture_uses_only_its_owned_postgres_publication_authority(tmp_path):
    environment, state, commands = fake_container(tmp_path)
    environment.update(MEMOIR_PUBLICATION_DATABASE_URL='postgresql://unrelated.invalid/forbidden',
        MEMOIR_LEGACY_ONLY_DEPLOYMENT='1')
    observed = tmp_path / 'observed-authority.json'
    wrapper = tmp_path / 'external_authority.py'
    wrapper.write_text(PUBLICATION_CONNECTION_STUB + f'''import json, os, pathlib, runpy
from temporalio.testing import WorkflowEnvironment
async def start_local(**kwargs):
    pathlib.Path({str(observed)!r}).write_text(json.dumps({{
        'dsn': os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),
        'legacy_only': os.getenv('MEMOIR_LEGACY_ONLY_DEPLOYMENT')}}))
    raise RuntimeError('Synthetic stop before native Temporal allocation')
WorkflowEnvironment.start_local = start_local
runpy.run_path('scripts/run_canonical_five_case_evaluation.py', run_name='__main__')
''')
    command = fixture_command(tmp_path, seconds=10)
    command[1] = str(wrapper)
    result = subprocess.run(command, cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['cleanup']['postgres_fixture_closed'] is True and not state.exists()
    authority = json.loads(observed.read_text())
    assert authority['legacy_only'] is None
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    start = next(call for call in calls if call[0] == 'run')
    binding = start[start.index('--publish') + 1]
    host, port, target = binding.split(':')
    assert host == '127.0.0.1' and target == '5432'
    assert authority['dsn'] == f'host=127.0.0.1 port={port} user=postgres dbname=postgres'


@pytest.mark.parametrize('failure', ['mismatch', 'unavailable', 'timeout'])
def test_publication_identity_failure_cannot_expose_dsn_or_start_temporal(tmp_path, failure):
    environment, state, commands = fake_container(tmp_path)
    stub = PUBLICATION_CONNECTION_STUB
    if failure == 'mismatch':
        stub = stub.replace("return ('987654321',)", "return ('123456789',)")
    elif failure == 'unavailable':
        stub = stub.replace('return cls()', "raise psycopg.OperationalError('synthetic connection refusal')")
    else:
        stub = stub.replace('return cls()', 'import asyncio; await asyncio.sleep(10); return cls()')
    observed = tmp_path / 'authority-after-failure.json'
    temporal_marker = tmp_path / 'temporal-started'
    wrapper = tmp_path / 'external_wrong_instance.py'
    wrapper.write_text(stub + f'''import json, os, pathlib, runpy
from temporalio.testing import WorkflowEnvironment
async def start_local(**kwargs):
    pathlib.Path({str(temporal_marker)!r}).touch()
    raise AssertionError('Must not start Temporal without owned authority')
WorkflowEnvironment.start_local = start_local
try:
    runpy.run_path('scripts/run_canonical_five_case_evaluation.py', run_name='__main__')
finally:
    pathlib.Path({str(observed)!r}).write_text(json.dumps({{'dsn': os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')}}))
''')
    command = fixture_command(tmp_path, seconds=10)
    command[1] = str(wrapper)
    result = subprocess.run(command, cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'incomplete' and receipt['provider_requests_started'] == 0
    assert receipt['error_class'] == {'mismatch': 'RuntimeError', 'unavailable': 'OperationalError', 'timeout': 'TimeoutError'}[failure]
    assert not receipt['postgres_publication_endpoint'].get('instance_verified')
    assert json.loads(observed.read_text())['dsn'] is None
    assert not temporal_marker.exists() and not state.exists()
    assert receipt['cleanup']['postgres_removal_verified'] and receipt['cleanup']['postgres_endpoint_closed']
    assert '123456789' not in result.stdout + result.stderr
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    assert all(call[-1] == receipt['postgres_container'] for call in calls if call[0] in {'inspect', 'stop'})


@pytest.mark.parametrize('cancel', [False, True])
def test_blocked_local_identity_probe_is_reaped_before_timeout_or_cancellation_returns(tmp_path, monkeypatch, cancel):
    from scripts.canonical_native_fixture import verify_publication_instance
    import psycopg
    pid_file = tmp_path / 'probe.pid'
    probe = tmp_path / 'blocked_psql.py'
    probe.write_text(f'''import os, pathlib, sys, time
assert sys.stdin.read() == 'select system_identifier::text from pg_control_system();'
pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))
time.sleep(30)
''')
    async def forbidden_connect(*args, **kwargs):
        raise AssertionError('A blocked local identity must never contact the TCP endpoint')
    monkeypatch.setattr(psycopg.AsyncConnection, 'connect', forbidden_connect)
    sql = SimpleNamespace(command=[sys.executable, str(probe)], env=offline_environment(ROOT),
        publication_dsn='host=127.0.0.1 port=1 user=postgres dbname=postgres')
    async def scenario():
        task = asyncio.create_task(verify_publication_instance(sql, time.monotonic() + (10 if cancel else .3)))
        async with asyncio.timeout(2):
            while not pid_file.exists(): await asyncio.sleep(.01)
        if cancel: task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_file.read_text()), 0)
    started = time.monotonic()
    asyncio.run(scenario())
    assert time.monotonic() - started < 2


def test_failed_postgres_startup_and_stop_cannot_report_no_allocation_or_closed(tmp_path):
    environment, state, commands = fake_container(tmp_path, malformed_logs=True, stop_fails=True)
    result = subprocess.run(fixture_command(tmp_path), cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'incomplete'
    assert receipt['resources_allocated'] is True
    assert receipt['cleanup']['postgres_fixture_closed'] is False
    assert receipt['postgres_container'] == state.read_text()
    assert receipt['cleanup']['workspace_removed'] is False
    retained = Path(receipt['workspace_retained_for_reconciliation'])
    try:
        assert retained.is_dir(), 'Unreconciled native resources require their owned workspace'
    finally:
        # This stub never owns native services; clean only its receipt's workspace.
        if retained.is_dir() and retained.parent == Path('/tmp') and retained.name.startswith('memoir-canonical-'):
            shutil.rmtree(retained)
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    # Inspection/reconciliation may address only this previously recorded UUID.
    assert all(call[-1] == receipt['postgres_container'] for call in calls
        if call[0] in {'stop', 'inspect'})
    assert json.loads((tmp_path / 'external-lifecycle/summary.json').read_text()) == receipt
