"""Generic diagnostics must use process columns supported by Apple's ps."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest

from scripts.controlled_lifecycle import reconcile_native_directory, register_command_group


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def darwin_ps(tmp_path):
    """Reject unsupported Apple columns, delegating supported calls to real ps."""
    real = shutil.which('ps')
    assert real is not None
    records = tmp_path/'ps-calls.jsonl'
    binary = tmp_path/'bin';binary.mkdir()
    shim = binary/'ps'
    shim.write_text(f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with Path({str(records)!r}).open('a') as log:log.write(json.dumps(args)+'\\n')
if '-o' in args:
    columns=args[args.index('-o')+1].split(',')
    for column in columns:
        name=column.split('=')[0]
        if name not in {{'pid','pgid','stat','lstart','args'}}:
            print('ps: '+name+': keyword not found',file=sys.stderr)
            raise SystemExit(1)
os.execv({real!r},[{real!r},*args])
''')
    shim.chmod(0o700)
    return dict(os.environ,PATH=str(binary)+':'+os.environ['PATH']),records


def assert_portable_process_calls(records):
    calls = [json.loads(line) for line in records.read_text().splitlines()]
    formats = [call[call.index('-o')+1] for call in calls if '-o' in call]
    assert 'lstart=' in formats
    assert 'pid=,pgid=,stat=' in formats
    assert all('sid' not in value and 'sess' not in value for value in formats)


@pytest.mark.parametrize('apple_columns', [False, True])
def test_generic_success_keeps_zero_exit_and_verified_cleanup(tmp_path, darwin_ps, apple_columns):
    env,records = darwin_ps
    result = subprocess.run([sys.executable,str(ROOT/'scripts/run_isolated_check.py'),
        '--root',str(ROOT),'--output-dir',str(tmp_path/'receipts'),'--name','generic-success','--',
        sys.executable,'-c','print("synthetic success")'],
        env=env if apple_columns else dict(os.environ),text=True,capture_output=True,timeout=15)
    receipt = json.loads((tmp_path/'receipts/generic-success.json').read_text())
    assert result.returncode == receipt['exit_code'] == 0, (result.stderr,receipt)
    assert receipt['status'] == 'completed' and receipt['child_returncode'] == 0
    assert (tmp_path/'receipts/generic-success.log').read_text() == 'synthetic success\n'
    assert receipt['native_allocation_cleanup']['verified']
    assert receipt['native_allocation_cleanup']['root_removed']
    assert receipt['native_allocation_cleanup']['postmasters_stopped'] == []
    assert not Path(receipt['native_allocation_root']).exists()
    if apple_columns:assert_portable_process_calls(records)


def test_darwin_compatible_inspection_stops_the_exact_live_owned_session(tmp_path, darwin_ps):
    env,records = darwin_ps
    root = tmp_path/'owned-root';root.mkdir()
    child = subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
    try:
        assert os.getsid(child.pid) == os.getpgid(child.pid) == child.pid
        identity = register_command_group(root,child.pid,env)
        assert identity['leader_started']
        result = reconcile_native_directory(root,env)
        assert child.wait(timeout=5) == -signal.SIGKILL
        assert result['verified'] and result['root_removed'] and not root.exists()
        assert result['command_groups_stopped'] == [identity]
        assert_portable_process_calls(records)
    finally:
        if child.poll() is None:child.kill()
        child.wait(timeout=5)


def test_member_exiting_before_session_lookup_is_reaped_without_signalling(tmp_path, darwin_ps, monkeypatch):
    env,records = darwin_ps
    root = tmp_path/'owned-root';root.mkdir()
    child = subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
    getsid,signals,looked_up = os.getsid,[],[]
    def inspect(pid):
        assert pid == child.pid
        looked_up.append(pid)
        child.terminate()
        assert child.wait(timeout=5) == -signal.SIGTERM
        return getsid(pid)
    try:
        register_command_group(root,child.pid,env)
        monkeypatch.setattr(os,'getsid',inspect)
        monkeypatch.setattr(os,'killpg',lambda *args:signals.append(args))
        result = reconcile_native_directory(root,env)
        assert looked_up == [child.pid] and signals == []
        assert result['verified'] and result['root_removed'] and not root.exists()
        assert result['command_groups_stopped'] == []
        assert_portable_process_calls(records)
    finally:
        if child.poll() is None:child.kill()
        child.wait(timeout=5)


@pytest.mark.parametrize('fault', ['different_session','permission_denied'])
def test_portable_session_identity_failure_retains_metadata_and_never_signals(tmp_path, darwin_ps, monkeypatch, fault):
    env,records = darwin_ps
    root = tmp_path/'owned-root';root.mkdir()
    child = subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
    getsid,signals = os.getsid,[]
    def inspect(pid):
        if pid != child.pid:return getsid(pid)
        if fault == 'permission_denied':raise PermissionError('Synthetic session inspection denial')
        return child.pid+1
    try:
        identity = register_command_group(root,child.pid,env)
        monkeypatch.setattr(os,'getsid',inspect)
        monkeypatch.setattr(os,'killpg',lambda *args:signals.append(args))
        error = PermissionError if fault == 'permission_denied' else RuntimeError
        with pytest.raises(error):reconcile_native_directory(root,env)
        assert signals == [] and child.poll() is None
        assert json.loads((root/'command-group.json').read_text()) == identity
        assert_portable_process_calls(records)
    finally:
        if child.poll() is None:child.kill()
        child.wait(timeout=5)
