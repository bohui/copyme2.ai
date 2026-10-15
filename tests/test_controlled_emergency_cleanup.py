"""Real creator exit races must not prevent exact native-cluster teardown."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import pytest

from scripts.controlled_lifecycle import new_native_root
from scripts.controlled_native_state import ROOT
from test_controlled_supervisor_lifecycle import allocations, emergency_cleanup, native_fault_environment, process_identity, running


@pytest.mark.parametrize('fault', ['zombie','reaped','command_mismatch','birth_mismatch','live_command_unavailable'])
def test_creator_exit_during_command_inspection_keeps_database_cleanup_identity_safe(tmp_path, monkeypatch, fault):
    env,records_path,stops,real = native_fault_environment(tmp_path,'hold_case')
    root = new_native_root('memoir-case-')
    value=dict(args=dict(resume=False),case=dict(id='creator-race',project_id='creator-race'),
        run_dir=str(tmp_path),database_directory=str(root))
    with (tmp_path/'creator.log').open('w') as log:
        creator=subprocess.Popen([sys.executable,'-m','scripts.controlled_five_case'],cwd=ROOT,env=env,
            stdin=subprocess.PIPE,stdout=log,stderr=log,text=True)
    read_bytes,run = Path.read_bytes,subprocess.run
    item=None;triggered=False;stop_attempts=[];outcome=None;error=None
    def inspect(path):
        nonlocal triggered
        if path != Path(f'/proc/{creator.pid}/cmdline'):return read_bytes(path)
        triggered=True
        assert process_identity(creator.pid) == ('T',item['owner_started'])
        if fault=='command_mismatch':return b'unknown-live-command\0'
        if fault=='live_command_unavailable':raise FileNotFoundError('Synthetic live command inspection failure')
        creator.kill()
        deadline=time.monotonic()+5
        while process_identity(creator.pid)[0]!='Z':
            assert time.monotonic()<deadline;time.sleep(.01)
        if fault=='reaped':creator.wait(timeout=5)
        return read_bytes(path)
    def observe(command,**options):
        if command[0]==real and command[-1]=='stop':stop_attempts.append(command)
        return run(command,**options)
    try:
        creator.stdin.write(json.dumps(value));creator.stdin.close()
        deadline=time.monotonic()+30
        while True:
            records=allocations(records_path)
            if len(records)==1 and process_identity(records[0]['owner'])[0]=='T':break
            assert creator.poll() is None,(tmp_path/'creator.log').read_text()
            assert time.monotonic()<deadline;time.sleep(.01)
        item=records[0]
        assert item['owner']==creator.pid and running(item['pid'],item['started'])
        supplied=dict(item)
        if fault=='birth_mismatch':supplied['owner_started']='not-the-original-start'
        monkeypatch.setattr(Path,'read_bytes',inspect)
        monkeypatch.setattr(subprocess,'run',observe)
        try:
            emergency_cleanup([supplied],real,os.getpid(),held_child=True)
            outcome='returned'
        except Exception as caught:
            error=caught;outcome=type(caught).__name__
        observation=dict(fault=fault,allocation=item,inspection_triggered=triggered,
            cleanup_outcome=outcome,stop_attempts=stop_attempts,
            creator_identity=process_identity(creator.pid),postmaster_running=running(item['pid'],item['started']),
            data_exists=Path(item['data']).exists(),root_exists=root.exists())
        (tmp_path/'creator-race-observation.json').write_text(json.dumps(observation,indent=2)+'\n')
        if fault in {'zombie','reaped'}:
            if error is not None:raise error
            assert triggered and len(stop_attempts)==1
            assert stop_attempts[0] == [real,'-D',item['data'],'-m','immediate','-w','stop']
            assert not running(item['pid'],item['started']) and not root.exists()
            assert creator.wait(timeout=5)==-signal.SIGKILL
        else:
            assert isinstance(error,FileNotFoundError if fault=='live_command_unavailable' else AssertionError)
            assert stop_attempts == [] and running(item['pid'],item['started'])
            assert process_identity(creator.pid)==('T',item['owner_started'])
            assert Path(item['data']).exists() and root.exists()
    finally:
        cleanup=dict(creator_pid=creator.pid,postmaster=item['pid'] if item else None,stop_returncode=None)
        if creator.poll() is None:
            assert b'scripts.controlled_five_case' in read_bytes(Path(f'/proc/{creator.pid}/cmdline')).split(b'\0')
            creator.kill()
        creator.wait(timeout=5)
        if creator.stdin is not None:creator.stdin.close()
        if item is None:
            records=allocations(records_path)
            item=records[0] if records else None
        if item is not None and running(item['pid'],item['started']):
            data=Path(item['data']);fields=(data/'postmaster.pid').read_text().splitlines()
            assert fields[0]==str(item['pid']) and fields[1]==str(data)
            command=read_bytes(Path(f"/proc/{item['pid']}/cmdline")).split(b'\0')
            assert data.as_posix().encode() in command and b'postgres' in Path(os.fsdecode(command[0])).name.encode()
            assert dict(root=str(root),device=root.stat().st_dev,inode=root.stat().st_ino)==item['allocation_root_identity']
            stopped=run([real,'-D',str(data),'-m','immediate','-w','stop'],capture_output=True,timeout=12,check=True)
            cleanup['stop_returncode']=stopped.returncode
        if item is not None:
            assert not running(item['pid'],item['started'])
            cleanup['postmaster_not_running']=True
        if root.exists():shutil.rmtree(root)
        cleanup.update(creator_reaped=True,root_removed=not root.exists())
        (tmp_path/'creator-race-teardown.json').write_text(json.dumps(cleanup,indent=2)+'\n')
