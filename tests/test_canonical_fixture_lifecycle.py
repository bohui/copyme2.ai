"""Public fixture CLI failures using only controlled external process boundaries."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time

import pytest

from scripts.run_isolated_check import offline_environment


ROOT = Path(__file__).resolve().parents[1]


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
    if {slow_stage!r} == 'startup': time.sleep(8)
elif action == 'logs':
    if {malformed_logs!r}:
        sys.stdout.buffer.write(b'\\xff')
    else: print('PostgreSQL init process complete; ready for start up.')
elif action == 'exec' and 'pg_isready' in sys.argv:
    pass
elif action == 'exec' and 'psql' in sys.argv:
    pathlib.Path({str(tmp_path / 'sql-process.pid')!r}).write_text(str(os.getpid()))
    if {eof_delay!r} is not None:
        os.close(1)
        time.sleep({eof_delay!r})
        os.write(2, b'Synthetic SQL failure\\n')
        os._exit(1)
    for line in sys.stdin:
        if {slow_stage!r} == 'migration': time.sleep(8)
        if line.startswith('\\\\echo '):
            print(line.split(' ', 1)[1].strip(), flush=True)
elif action == 'stop':
    if {stop_fails!r}: sys.exit(1)
    state.unlink(missing_ok=True)
elif action == 'inspect':
    if state.exists(): print(json.dumps([{{'status': 'running'}}]))
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
        '--execute-fixture', '--run-id', 'external-lifecycle', '--output-root', str(tmp_path),
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


@pytest.mark.parametrize('stage', ['startup', 'migration'])
def test_fixture_deadline_bounds_native_startup_and_migrations(tmp_path, stage):
    environment, state, _ = fake_container(tmp_path, slow_stage=stage)
    started = time.monotonic()
    result = subprocess.run(fixture_command(tmp_path), cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=20)
    assert time.monotonic() - started < 6, 'Setup ignored the three-second fixture deadline'
    assert result.returncode == 3, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt['status'] == 'incomplete'
    assert receipt['cleanup']['postgres_fixture_closed'] is True
    assert not state.exists()
    assert json.loads((tmp_path / 'external-lifecycle/summary.json').read_text()) == receipt


def test_sigterm_during_temporal_shutdown_preserves_terminal_receipt_and_cleanup(tmp_path):
    environment, state, _ = fake_container(tmp_path)
    wrapper = tmp_path / 'external_temporal.py'
    wrapper.write_text('''import asyncio, os, runpy, signal
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
    wrapper.write_text('''import runpy
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
