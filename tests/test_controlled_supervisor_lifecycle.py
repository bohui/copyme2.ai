"""Native lifecycle faults observed outside the process being terminated."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

from scripts.controlled_native_state import ROOT
from scripts.run_isolated_check import offline_environment


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().split()
        return fields[2], fields[21]
    except FileNotFoundError:
        return None


def running(pid, started):
    identity = process_identity(pid)
    return identity is not None and identity[1] == started and identity[0] != 'Z'


def allocations(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def native_fault_environment(tmp_path, fault):
    if sys.platform != 'linux' or not Path('/proc/self/stat').is_file():
        pytest.skip('Linux /proc identity checks required; non-Linux coverage unavailable')
    if os.geteuid() == 0 or not all(shutil.which(name) for name in ('pg_ctl', 'initdb', 'psql')):
        pytest.skip('local PostgreSQL tools and a non-root account required')
    real = shutil.which('pg_ctl')
    records, stops = tmp_path/'allocations.jsonl', tmp_path/'stops.jsonl'
    binary = tmp_path/'bin'; binary.mkdir()
    shim = binary/'pg_ctl'
    shim.write_text(f'''#!{sys.executable}
import json, os, pathlib, signal, subprocess, sys, time
data = pathlib.Path(sys.argv[sys.argv.index('-D')+1])
if sys.argv[-1] == 'stop':
    mode = sys.argv[sys.argv.index('-m')+1]
    pid = int((data/'postmaster.pid').read_text().splitlines()[0])
    with pathlib.Path({str(stops)!r}).open('a') as log:
        log.write(json.dumps(dict(mode=mode, pid=pid, data=str(data)))+'\\n')
    if mode == 'fast' and {fault!r} == 'fast_fails': raise SystemExit(42)
    if mode == 'fast' and {fault!r} == 'fast_times_out': time.sleep(30)
result = subprocess.run([{real!r}, *sys.argv[1:]])
if result.returncode == 0 and sys.argv[-1] == 'start':
    pid = int((data/'postmaster.pid').read_text().splitlines()[0])
    owner = os.getppid()
    item = dict(data=str(data), pid=pid, started=pathlib.Path('/proc/'+str(pid)+'/stat').read_text().split()[21],
        owner=owner, owner_started=pathlib.Path('/proc/'+str(owner)+'/stat').read_text().split()[21])
    root=data.parent.parent
    item['allocation_root_identity']=dict(root=str(root),device=root.stat().st_dev,inode=root.stat().st_ino)
    with pathlib.Path({str(records)!r}).open('a') as log:
        log.write(json.dumps(item)+'\\n'); log.flush(); os.fsync(log.fileno())
    if {fault!r} == 'hold_case': os.kill(owner, signal.SIGSTOP)
raise SystemExit(result.returncode)
''')
    shim.chmod(0o700)
    env = offline_environment(ROOT)
    for key in ('LD_LIBRARY_PATH', 'MEMOIR_TEST_TEMPORAL_CLI'):
        if os.getenv(key): env[key] = os.environ[key]
    env.update(PATH=str(binary)+':'+env['PATH'], PYTHONPATH=str(ROOT), MEMOIR_TEST_POSTGRES_BACKEND='native')
    return env, records, stops, real


def emergency_cleanup(records, real, supervisor_pid, *, held_child=False):
    """Red tests retain identity even if the broken process erased its files."""
    for item in records:
        if held_child and item['owner'] != supervisor_pid and running(item['owner'], item['owner_started']):
            command = Path(f"/proc/{item['owner']}/cmdline").read_bytes().split(b'\0')
            assert b'scripts.controlled_five_case' in command
            os.kill(item['owner'], signal.SIGKILL)
        if running(item['pid'], item['started']):
            command = Path(f"/proc/{item['pid']}/cmdline").read_bytes().split(b'\0')
            assert item['data'].encode() in command
            if Path(item['data']).exists():
                subprocess.run([real, '-D', item['data'], '-m', 'immediate', '-w', 'stop'],
                    check=True, capture_output=True, timeout=12)
            else:
                os.kill(item['pid'], signal.SIGQUIT)
            until = time.monotonic()+10
            while running(item['pid'], item['started']) and time.monotonic()<until:
                time.sleep(.02)
            assert not running(item['pid'], item['started'])
        directory = Path(item['data']).parent
        if directory.exists(): shutil.rmtree(directory)
        parent = directory.parent
        if parent.name.startswith(('memoir-case-', 'memoir-controlled-pg-')) and parent.exists():
            shutil.rmtree(parent)


@pytest.mark.parametrize('entry', ['direct', 'direct_delayed_handle', 'evaluation_cli', 'evaluation_cli_concurrent'])
def test_supervisor_sigterm_reconciles_an_unresponsive_case(tmp_path, entry):
    env, record_path, stops, real = native_fault_environment(tmp_path, 'hold_case')
    setup = "import sys; from scripts import controlled_five_case as driver; driver.CHILD_CLEANUP_SECONDS=.2; "
    expected_count = 2 if entry == 'evaluation_cli_concurrent' else 1
    if entry.startswith('direct'):
        code = setup + f'''import asyncio
from scripts.run_memoir_five_case_evaluation import make_arg_parser
from pathlib import Path
args=make_arg_parser().parse_args(['--mode','pilot','--run-id','term-owned','--output-root',{str(tmp_path)!r}])
'''
        if entry == 'direct_delayed_handle':
            code += f'''launch=asyncio.create_subprocess_exec
async def delayed_handle(*args,**kwargs):
    process=await launch(*args,**kwargs)
    Path({str(tmp_path/'child-created.json')!r}).write_text(str(process.pid))
    await asyncio.sleep(5)
    Path({str(tmp_path/'handle-returned')!r}).touch()
    return process
asyncio.create_subprocess_exec=delayed_handle
'''
        code += f'''
asyncio.run(driver.run_isolated_case(dict(id='term-owned',project_id='term-owned-project',locale='en-AU',rounds=['Synthetic memory.']),{{}},{{}},args=args,run_dir=Path({str(tmp_path)!r}),max_rounds=1))
'''
    else:
        code = setup + f'''from scripts.run_memoir_five_case_evaluation import main
sys.argv=['evaluation','--mode',{'fixture' if expected_count==2 else 'pilot'!r},'--run-id','term-owned','--output-root',{str(tmp_path)!r},'--env-file',{str(tmp_path/'no-env')!r},'--max-rounds','1','--skip-preflight']
if {expected_count} == 2: sys.argv += ['--case-concurrency','2','--cases','harbour-copper-notebook','chengdu-tea-ledger']
raise SystemExit(main())
'''
    with (tmp_path/'supervisor.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-c', code], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            until = time.monotonic()+30
            while True:
                records = allocations(record_path)
                if len(records) == expected_count and all(process_identity(item['owner'])[0]=='T' for item in records): break
                assert process.poll() is None, (tmp_path/'supervisor.log').read_text()
                assert time.monotonic()<until, 'Owned native startup was not observed'
                time.sleep(.02)
            if entry == 'direct_delayed_handle':
                assert (tmp_path/'handle-returned').exists(), 'This separate case exercises post-return startup'
                assert int((tmp_path/'child-created.json').read_text()) == records[0]['owner']
            process.send_signal(signal.SIGTERM)
            # A repeated termination must not interrupt the cleanup task.
            time.sleep(.05)
            if process.poll() is None: process.send_signal(signal.SIGTERM)
            process.wait(timeout=15)
            records = allocations(record_path)
            assert len(records) == expected_count
            for item in records:
                assert not running(item['pid'], item['started']), 'Supervisor termination left its postmaster running'
                assert not running(item['owner'], item['owner_started']), 'Case child survived its supervisor'
                assert not Path(item['data']).parent.parent.exists()
            observed = allocations(stops)
            assert sorted(observed,key=lambda a:a['pid']) == sorted(
                [dict(mode='immediate',pid=item['pid'],data=item['data']) for item in records],key=lambda a:a['pid'])
            assert process.returncode != -signal.SIGTERM
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
            emergency_cleanup(allocations(record_path), real, process.pid, held_child=True)


def test_sigterm_before_handle_return_waits_for_exact_created_child(tmp_path):
    env, record_path, stops, real = native_fault_environment(tmp_path, 'hold_case')
    created, returned = tmp_path/'child-created.json', tmp_path/'handle-returned.json'
    cleanup_started, release = tmp_path/'cleanup-started.json', tmp_path/'release-handle'
    code = f'''import asyncio,json
from pathlib import Path
from scripts import controlled_five_case as driver
from scripts.run_memoir_five_case_evaluation import make_arg_parser
driver.CHILD_CLEANUP_SECONDS=.2
def save(path,value):
    path=Path(path);path.with_suffix('.tmp').write_text(json.dumps(value));path.with_suffix('.tmp').replace(path)
launch=asyncio.create_subprocess_exec
async def delayed_handle(*args,**kwargs):
    child=await launch(*args,**kwargs)
    identity=dict(pid=child.pid,started=Path('/proc/'+str(child.pid)+'/stat').read_text().split()[21])
    save({str(created)!r},identity)
    while not Path({str(release)!r}).exists(): await asyncio.sleep(.01)
    save({str(returned)!r},identity)
    return child
cleanup=driver.cleanup_case
async def observed_cleanup(*args,**kwargs):
    save({str(cleanup_started)!r},dict(directory=str(args[1])))
    return await cleanup(*args,**kwargs)
asyncio.create_subprocess_exec=delayed_handle
driver.cleanup_case=observed_cleanup
args=make_arg_parser().parse_args(['--mode','pilot','--run-id','creation-owned','--output-root',{str(tmp_path)!r}])
asyncio.run(driver.run_isolated_case(dict(id='creation-owned',project_id='creation-owned-project',locale='en-AU',rounds=['Synthetic memory.']),{{}},{{}},args=args,run_dir=Path({str(tmp_path)!r}),max_rounds=1))
'''
    child, directory = None, None
    with (tmp_path/'supervisor.log').open('w') as log:
        process = subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            until=time.monotonic()+15
            while not created.exists():
                assert process.poll() is None, (tmp_path/'supervisor.log').read_text()
                assert time.monotonic()<until
                time.sleep(.01)
            child=json.loads(created.read_text())
            assert running(child['pid'],child['started'])
            assert not returned.exists() and not release.exists()
            process.send_signal(signal.SIGTERM)
            while not cleanup_started.exists():
                assert process.poll() is None, (tmp_path/'supervisor.log').read_text()
                assert time.monotonic()<until
                time.sleep(.01)
            directory=Path(json.loads(cleanup_started.read_text())['directory'])
            assert directory.name.startswith('memoir-case-') and directory.exists()
            assert not returned.exists(), 'Supervisor cancellation must precede handle return'
            # No JSON reaches the case until the handle is returned. This phase
            # owns a real child, with no database admitted or allocated yet.
            assert allocations(record_path)==[] and not stops.exists()
            process.send_signal(signal.SIGTERM)
            time.sleep(.05)
            assert process.poll() is None and not returned.exists()
            release.touch()
            process.wait(timeout=15)
            assert json.loads(returned.read_text())==child, 'Cleanup must receive the original child handle'
            assert not running(child['pid'],child['started'])
            assert not directory.exists()
            assert allocations(record_path)==[] and not stops.exists()
            assert process.returncode != -signal.SIGTERM and process.returncode != 0
        finally:
            if process.poll() is None: process.kill();process.wait(timeout=5)
            if child and running(child['pid'],child['started']):
                command=Path(f"/proc/{child['pid']}/cmdline").read_bytes().split(b'\0')
                assert b'scripts.controlled_five_case' in command
                os.kill(child['pid'],signal.SIGKILL)
                until=time.monotonic()+5
                while running(child['pid'],child['started']) and time.monotonic()<until:time.sleep(.01)
                assert not running(child['pid'],child['started'])
            emergency_cleanup(allocations(record_path),real,process.pid,held_child=True)
            if directory and directory.exists():shutil.rmtree(directory)


@pytest.mark.parametrize('fault', ['fast_fails', 'fast_times_out'])
def test_unsupervised_profiler_reconciles_both_failed_database_closers(tmp_path, fault):
    env, record_path, stops, real = native_fault_environment(tmp_path, fault)
    source = tmp_path/'inputs.json'; source.write_text(json.dumps(['I started school.']))
    with (tmp_path/'profiler.log').open('w') as log:
        process = subprocess.Popen([sys.executable, '-m', 'scripts.profile_canonical_controlled',
            '--inputs', str(source), '--output', str(tmp_path/'receipt.json')], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            process.wait(timeout=80)
            records = allocations(record_path)
            assert len(records) == 2, (tmp_path/'profiler.log').read_text()
            assert process.returncode != 0, 'Failed primary cleanup must remain visible'
            assert all(not running(item['pid'], item['started']) for item in records), 'Profiler lost live postmasters during failed close'
            for item in records:
                assert not Path(item['data']).parent.exists()
                assert not Path(item['data']).parent.parent.exists()
                assert [a['mode'] for a in allocations(stops) if a['pid']==item['pid']] == ['fast', 'immediate']
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=5)
            emergency_cleanup(allocations(record_path), real, process.pid)
