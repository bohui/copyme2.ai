"""Shipped outer/inner deadlines and short native Unix-socket ownership."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from scripts.controlled_native_state import ROOT
from test_controlled_supervisor_lifecycle import allocations, emergency_cleanup, native_fault_environment, process_identity, running


@pytest.mark.parametrize('kind', ['frozen_case', 'profiler_closer'])
def test_default_outer_kill_boundary_reconciles_detached_postmasters(tmp_path, kind):
    env, record_path, stops, real = native_fault_environment(tmp_path, 'hold_case' if kind=='frozen_case' else 'fast_times_out')
    group_marker=tmp_path/'command-owner.json'
    code=f'''import os,json
from pathlib import Path
pid=os.getpid()
Path({str(group_marker)!r}).write_text(json.dumps(dict(pid=pid,started=Path('/proc/'+str(pid)+'/stat').read_text().split()[21])))
'''
    if kind=='frozen_case':
        code+=f'''import asyncio
from scripts import controlled_five_case as driver
from scripts.run_memoir_five_case_evaluation import make_arg_parser
assert driver.CHILD_CLEANUP_SECONDS==20
args=make_arg_parser().parse_args(['--mode','pilot','--run-id','outer-defaults','--output-root',{str(tmp_path)!r}])
asyncio.run(driver.run_isolated_case(dict(id='outer-defaults',project_id='outer-defaults',locale='en-AU',rounds=['Synthetic memory.']),{{}},{{}},args=args,run_dir=Path({str(tmp_path)!r}),max_rounds=1))
'''
    else:
        source=tmp_path/'inputs.json';source.write_text(json.dumps(['I started school.']))
        code+=f'''import runpy,sys
sys.argv=['profile','--inputs',{str(source)!r},'--output',{str(tmp_path/'profile.json')!r}]
runpy.run_module('scripts.profile_canonical_controlled',run_name='__main__')
'''
    with (tmp_path/'outer.log').open('w') as log:
        outer=subprocess.Popen([sys.executable,'scripts/run_isolated_check.py','--root',str(ROOT),
            '--output-dir',str(tmp_path/'receipts'),'--name','default-boundary','--timeout','90',
            '--',sys.executable,'-c',code],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            until=time.monotonic()+45
            while True:
                records=allocations(record_path)
                if kind=='frozen_case':
                    ready=len(records)==1 and process_identity(records[0]['owner'])[0]=='T'
                else:
                    ready=len(records)==2 and any(item['mode']=='fast' for item in allocations(stops))
                if ready:break
                assert outer.poll() is None, (tmp_path/'outer.log').read_text()
                assert time.monotonic()<until
                time.sleep(.02)
            sent=time.monotonic();outer.send_signal(signal.SIGTERM)
            assert outer.wait(timeout=40)==143
            assert time.monotonic()-sent>=4.5, 'Regression must exercise the shipped five-second escalation'
            records=allocations(record_path)
            assert all(not running(item['pid'],item['started']) for item in records), 'Outer deadline left detached PostgreSQL alive'
            receipt=json.loads((tmp_path/'receipts/default-boundary.json').read_text())
            assert receipt['status']=='terminated' and receipt['termination_signal']==signal.SIGTERM
            native=receipt['native_allocation_cleanup']
            assert native['verified'] and native['root_removed']
            root=Path(receipt['native_allocation_root'])
            assert not root.exists()
            for item in records:
                assert Path(item['data']).is_relative_to(root)
                assert not Path(item['data']).parent.exists()
                assert any(stop['mode']=='immediate' and stop['pid']==item['pid'] and stop['data']==item['data'] for stop in allocations(stops))
        finally:
            if outer.poll() is None:outer.kill();outer.wait(timeout=5)
            if group_marker.exists():
                owner=json.loads(group_marker.read_text())
                if running(owner['pid'],owner['started']) and os.getpgid(owner['pid'])==owner['pid']:
                    os.killpg(owner['pid'],signal.SIGKILL)
            emergency_cleanup(allocations(record_path),real,outer.pid,held_child=kind=='frozen_case')


def test_long_tmpdir_keeps_owned_native_socket_paths_short(tmp_path):
    env, record_path, stops, real=native_fault_environment(tmp_path,'normal')
    long_root=tmp_path/('long-tmp-'+'x'*48);long_root.mkdir()
    env.update(TMPDIR=str(long_root),PYTHONPATH=str(ROOT)+':'+str(ROOT/'tests'))
    baseline=tmp_path/'raw-short-path-ok'
    code=f'''from pathlib import Path
from test_agent_commit_postgres import database
from scripts.controlled_native_state import controlled_database
generator=database.__wrapped__()
try:
    sql=next(generator)
    assert sql('select 1;').stdout.strip()=='1'
    Path({str(baseline)!r}).touch()
finally:generator.close()
with controlled_database() as sql:
    assert sql('select 1;').stdout.strip()=='1'
'''
    with (tmp_path/'long-tmp.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            process.wait(timeout=30)
            assert baseline.exists(), 'Same TMPDIR must pass the original short-path fixture first'
            assert process.returncode==0, (tmp_path/'long-tmp.log').read_text()
            records=allocations(record_path);assert len(records)==2
            for item in records:
                socket=str(Path(item['data']).parent/'.s.PGSQL.5432')
                assert len(os.fsencode(socket))<=107
                assert not running(item['pid'],item['started'])
                assert not Path(item['data']).parent.exists()
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
            emergency_cleanup(allocations(record_path),real,process.pid)
