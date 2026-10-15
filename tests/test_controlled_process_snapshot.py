"""A vanished snapshot member must not hide its newly forked descendant."""
import itertools
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from scripts import controlled_lifecycle as lifecycle
from test_controlled_process_portability import assert_portable_process_calls, darwin_ps


def process_state(pid, environment):
    result = subprocess.run(['ps','-p',str(pid),'-o','stat='],env=environment,
        text=True,capture_output=True,timeout=2)
    return result.stdout.strip() if result.returncode == 0 else 'absent'


@pytest.mark.parametrize('fault', ['none','different_session','permission_denied'])
def test_fork_after_snapshot_and_reap_before_lookup_does_not_hide_descendant(tmp_path, darwin_ps, monkeypatch, fault):
    env,calls = darwin_ps
    root = tmp_path/'owned-root';root.mkdir()
    marker = tmp_path/'descendant.json'
    descendant_code = f'''import json,os,subprocess,time
from pathlib import Path
pid=os.getpid()
started=' '.join(subprocess.check_output(['ps','-p',str(pid),'-o','lstart='],text=True).split())
Path({str(marker)!r}).write_text(json.dumps(dict(pid=pid,group=os.getpgrp(),session=os.getsid(0),started=started)))
time.sleep(30)
'''
    leader_code = f'''import subprocess,sys,time
from pathlib import Path
assert sys.stdin.readline()=='fork\\n'
subprocess.Popen([sys.executable,'-c',{descendant_code!r}])
deadline=time.monotonic()+5
while not Path({str(marker)!r}).exists():
    assert time.monotonic()<deadline
    time.sleep(.01)
'''
    leader = subprocess.Popen([sys.executable,'-c',leader_code],env=env,
        stdin=subprocess.PIPE,text=True,start_new_session=True)
    getsid,killpg = os.getsid,os.killpg
    descendant,lookups,signals = None,[],[]
    outcome = None
    def inspect(pid):
        nonlocal descendant
        lookups.append(pid)
        if pid == leader.pid:
            # Called only after the real process-table snapshot captured leader.
            assert descendant is None and not marker.exists()
            leader.stdin.write('fork\n');leader.stdin.flush()
            assert leader.wait(timeout=5) == 0
            descendant = json.loads(marker.read_text())
            assert descendant['group'] == descendant['session'] == leader.pid
            assert os.getpgid(descendant['pid']) == getsid(descendant['pid']) == leader.pid
            with pytest.raises(ProcessLookupError):getsid(pid)
            return getsid(pid)
        assert descendant is not None and pid == descendant['pid']
        if fault == 'different_session':return leader.pid+1
        if fault == 'permission_denied':raise PermissionError('Synthetic descendant session denial')
        return getsid(pid)
    def signal_group(group,signum):
        assert group == leader.pid and signum == signal.SIGKILL
        signals.append(dict(group=group,signal=signum))
        return killpg(group,signum)
    try:
        assert getsid(leader.pid) == os.getpgid(leader.pid) == leader.pid
        identity = lifecycle.register_command_group(root,leader.pid,env)
        assert identity['leader_started']
        monkeypatch.setattr(os,'getsid',inspect)
        monkeypatch.setattr(os,'killpg',signal_group)
        error = None
        try:
            outcome = dict(result=lifecycle.reconcile_native_directory(root,env))
        except Exception as caught:
            error=caught;outcome=dict(error=type(caught).__name__,message=str(caught))
        assert descendant is not None
        state = process_state(descendant['pid'],env)
        (tmp_path/'snapshot-observation.json').write_text(json.dumps(dict(
            fault=fault,leader=identity,leader_reaped=leader.returncode==0,descendant=descendant,
            lookup_pids=lookups,signals=signals,reconciliation=outcome,root_exists=root.exists(),
            descendant_state=state,descendant_running=state!='absent' and not state.startswith('Z')),indent=2)+'\n')
        if fault == 'none':
            if error is not None:raise error
            assert state == 'absent' or state.startswith('Z'), 'Snapshot race left the newly forked owned descendant running'
            assert outcome['result']['verified'] and outcome['result']['root_removed'] and not root.exists()
            assert outcome['result']['command_groups_stopped'] == [identity]
            assert signals == [dict(group=leader.pid,signal=signal.SIGKILL)]
        else:
            assert isinstance(error,PermissionError if fault=='permission_denied' else RuntimeError)
            assert signals == [] and state!='absent' and not state.startswith('Z')
            assert json.loads((root/'command-group.json').read_text()) == identity
        assert descendant['pid'] in lookups, 'A fresh snapshot must inspect the descendant after its parent is reaped'
        assert_portable_process_calls(calls)
    finally:
        if leader.poll() is None:leader.kill()
        leader.wait(timeout=5)
        if leader.stdin is not None:leader.stdin.close()
        if descendant is None and marker.exists():descendant=json.loads(marker.read_text())
        cleanup = dict(descendant=descendant,signal_sent=False)
        if descendant is not None:
            state = process_state(descendant['pid'],env);cleanup['before_state']=state
            if state!='absent' and not state.startswith('Z'):
                # Test teardown signals only this exact recorded individual PID.
                started=' '.join(subprocess.check_output(['ps','-p',str(descendant['pid']),'-o','lstart='],env=env,text=True).split())
                assert started == descendant['started']
                assert os.getpgid(descendant['pid']) == getsid(descendant['pid']) == descendant['group']
                os.kill(descendant['pid'],signal.SIGKILL);cleanup['signal_sent']=True
            deadline=time.monotonic()+5
            while True:
                state=process_state(descendant['pid'],env)
                if state=='absent' or state.startswith('Z'):break
                assert time.monotonic()<deadline
                time.sleep(.01)
            cleanup.update(after_state=state,verified_not_running=True)
        (tmp_path/'snapshot-teardown.json').write_text(json.dumps(cleanup,indent=2)+'\n')


def test_repeated_snapshot_member_disappearance_is_bounded_and_retains_identity(tmp_path, monkeypatch):
    identity = dict(group_id=os.getpgrp(),leader_started='synthetic birth')
    record=tmp_path/'command-group.json';record.write_text(json.dumps(identity))
    commands,signals,ticks = [],[],itertools.count()
    def snapshot(command,**options):
        if command == ['ps','-p',str(identity['group_id']),'-o','lstart=']:
            return subprocess.CompletedProcess(command,0,identity['leader_started']+'\n','')
        assert command == ['ps','-e','-o','pid=,pgid=,stat=']
        commands.append(command)
        return subprocess.CompletedProcess(command,0,f'{os.getpid()} {identity["group_id"]} S\n','')
    def vanished(pid):
        assert pid == os.getpid()
        raise ProcessLookupError('Synthetic unstable snapshot')
    monkeypatch.setattr(subprocess,'run',snapshot)
    monkeypatch.setattr(os,'getsid',vanished)
    monkeypatch.setattr(os,'killpg',lambda *args:signals.append(args))
    monkeypatch.setattr(lifecycle.time,'monotonic',lambda:next(ticks))
    with pytest.raises(RuntimeError,match='snapshot.*retained'):
        lifecycle.reconcile_native_directory(tmp_path,dict(os.environ))
    assert 2 <= len(commands) <= 5 and signals == []
    assert json.loads(record.read_text()) == identity
