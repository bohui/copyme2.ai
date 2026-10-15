"""Cancellation of real disposable PostgreSQL, without external services."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import pytest

from scripts import controlled_five_case as driver
from scripts.run_memoir_five_case_evaluation import make_arg_parser


@pytest.mark.parametrize('shutdown', ['graceful', 'unresponsive', 'fast_stop_fails', 'fast_stop_times_out'])
def test_cancelling_case_after_postgres_start_removes_owned_cluster(tmp_path, monkeypatch, shutdown):
    if os.geteuid() == 0 or not all(shutil.which(name) for name in ('pg_ctl', 'initdb', 'psql')):
        pytest.skip('local PostgreSQL tools and a non-root account required')
    real_pg_ctl = shutil.which('pg_ctl')
    marker = tmp_path / 'started.json'
    stops = tmp_path / 'stops.jsonl'
    binary = tmp_path / 'bin'
    binary.mkdir()
    shim = binary / 'pg_ctl'
    import sys
    shim.write_text(f'''#!{sys.executable}
import json, os, pathlib, subprocess, sys, time
if sys.argv[-1] == 'stop':
    mode = sys.argv[sys.argv.index('-m') + 1]
    data = pathlib.Path(sys.argv[sys.argv.index('-D') + 1])
    postmaster = int((data/'postmaster.pid').read_text().splitlines()[0])
    with pathlib.Path({str(stops)!r}).open('a') as log:
        log.write(json.dumps(dict(mode=mode, pid=os.getpid(), postmaster_pid=postmaster, data=str(data))) + '\\n')
    if mode == 'fast' and {shutdown!r} == 'fast_stop_fails':
        raise SystemExit(42)
    if mode == 'fast' and {shutdown!r} == 'fast_stop_times_out':
        time.sleep(30)
result = subprocess.run([{real_pg_ctl!r}, *sys.argv[1:]])
if result.returncode == 0 and sys.argv[-1] == 'start':
    data = pathlib.Path(sys.argv[sys.argv.index('-D') + 1])
    pid = int((data/'postmaster.pid').read_text().splitlines()[0])
    started = pathlib.Path('/proc/' + str(pid) + '/stat').read_text().split()[21]
    marker = pathlib.Path({str(marker)!r})
    marker.with_suffix('.tmp').write_text(json.dumps(dict(data=str(data), pid=pid, started=started)))
    marker.with_suffix('.tmp').replace(marker)
raise SystemExit(result.returncode)
''')
    shim.chmod(0o700)
    monkeypatch.setenv('PATH', str(binary) + ':' + os.environ['PATH'])
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND', 'native')
    args = make_arg_parser().parse_args(['--mode', 'pilot', '--run-id', 'cancel-owned-case', '--output-root', str(tmp_path)])
    case = {'id':'cancel-owned-case','project_id':'cancel-owned-project','locale':'en-AU',
        'rounds':['I remember the blue gate.']}
    children = []
    launch = asyncio.create_subprocess_exec
    async def observed_launch(*command, **options):
        process = await launch(*command, **options)
        if command[:3] == (sys.executable, '-m', 'scripts.controlled_five_case'):
            children.append(process)
            if shutdown == 'unresponsive':
                # Force the real bounded fallback without an external service.
                process.terminate = lambda: os.kill(process.pid, signal.SIGSTOP)
        return process
    monkeypatch.setattr(driver.asyncio, 'create_subprocess_exec', observed_launch)
    if shutdown == 'unresponsive':
        monkeypatch.setattr(driver, 'CHILD_CLEANUP_SECONDS', .1)
    allocation = None
    started = time.monotonic()
    async def cancel():
        nonlocal allocation
        task = asyncio.create_task(driver.run_isolated_case(case, {}, {}, args=args,
            run_dir=tmp_path, max_rounds=1))
        try:
            async with asyncio.timeout(25):
                while not marker.exists():
                    if task.done():
                        await task
                        pytest.fail('Case finished before native startup was observed')
                    await asyncio.sleep(.02)
                allocation = json.loads(marker.read_text())
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    try:
        asyncio.run(cancel())
        data = Path(allocation['data'])
        assert not data.parent.exists(), 'Cancelled child left its task-owned cluster directory'
        assert data.parent.parent.name.startswith('memoir-case-')
        assert not data.parent.parent.exists()
        assert len(children) == 1 and children[0].returncode is not None
        if shutdown == 'unresponsive':
            assert children[0].returncode == -signal.SIGKILL
        stat = Path(f"/proc/{allocation['pid']}/stat")
        # Some cloud PID 1 implementations retain already-exited daemon zombies;
        # no running PostgreSQL process or usable cluster may survive return.
        assert not stat.exists() or stat.read_text().split()[2] == 'Z'
        if shutdown.startswith('fast_stop_'):
            attempts = [json.loads(line) for line in stops.read_text().splitlines()]
            assert [attempt['mode'] for attempt in attempts] == ['fast', 'immediate']
            assert all(attempt['postmaster_pid'] == allocation['pid'] and attempt['data'] == allocation['data']
                for attempt in attempts), 'Fallback lost the original allocation identity'
            # A failed or killed pg_ctl must not survive either.
            for attempt in attempts:
                path = Path(f"/proc/{attempt['pid']}/stat")
                assert not path.exists() or path.read_text().split()[2] == 'Z'
        assert time.monotonic() - started < 25
    finally:
        # The red reproduction must also clean its exact recorded allocation.
        if allocation and Path(allocation['data']).exists():
            subprocess.run([real_pg_ctl, '-D', allocation['data'], '-m', 'immediate', '-w', 'stop'],
                capture_output=True, timeout=12, check=True)
            shutil.rmtree(Path(allocation['data']).parent)
        elif allocation:
            # The broken child may have deleted the PID file/data directory.
            # The test observer retained this exact daemon's start identity.
            stat = Path(f"/proc/{allocation['pid']}/stat")
            if stat.exists():
                fields = stat.read_text().split()
                if fields[2] != 'Z':
                    assert fields[21] == allocation['started'], 'Owned postmaster PID was reused'
                    command = Path(f"/proc/{allocation['pid']}/cmdline").read_bytes().split(b'\0')
                    assert allocation['data'].encode() in command, 'Recorded daemon ownership changed'
                    os.kill(allocation['pid'], signal.SIGQUIT)
                    until = time.monotonic() + 10
                    while stat.exists() and stat.read_text().split()[2] != 'Z' and time.monotonic() < until:
                        time.sleep(.02)
                    assert not stat.exists() or stat.read_text().split()[2] == 'Z'
