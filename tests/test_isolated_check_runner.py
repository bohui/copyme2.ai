"""The command/receipt seam must retain an actual child's result."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
HEAD = '1' * 40
TREE = '2' * 40


def test_completed_child_keeps_its_receipt_when_later_git_would_abort(tmp_path):
    marker = tmp_path / 'child-finished'
    git = tmp_path / 'git'
    git.write_text(f'#!{sys.executable}\nimport os,signal\nfrom pathlib import Path\n'
                   f'if Path({str(marker)!r}).exists(): os.kill(os.getpid(),signal.SIGABRT)\n'
                   f'print({HEAD!r})\nprint({TREE!r})\n')
    git.chmod(0o755)
    env = {'PATH': str(tmp_path) + ':' + os.environ['PATH']}
    command = [sys.executable, '-c',
               f'from pathlib import Path; Path({str(marker)!r}).write_text("done"); raise SystemExit(7)']
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_isolated_check.py'),
                             '--root', str(tmp_path), '--output-dir', str(tmp_path / 'receipts'),
                             '--name', 'child-result', '--', *command],
                            env=env, capture_output=True, text=True)
    assert marker.read_text() == 'done'
    assert result.returncode == 7, result.stderr
    receipt = json.loads((tmp_path / 'receipts/child-result.json').read_text())
    assert receipt['exit_code'] == 7 and receipt['base_head'] == HEAD and receipt['tree'] == TREE


def test_unavailable_identity_prevents_the_check_and_records_the_blocker(tmp_path):
    marker = tmp_path / 'must-not-run'
    git = tmp_path / 'git'
    git.write_text(f'#!{sys.executable}\nraise SystemExit(42)\n')
    git.chmod(0o755)
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_isolated_check.py'),
                            '--root', str(tmp_path), '--output-dir', str(tmp_path / 'receipts'),
                            '--name', 'identity-blocked', '--', sys.executable, '-c',
                            f'from pathlib import Path; Path({str(marker)!r}).touch()'],
                           env={'PATH': str(tmp_path) + ':' + os.environ['PATH']},
                           capture_output=True, text=True)
    assert not marker.exists()
    assert result.returncode == 2
    receipt = json.loads((tmp_path / 'receipts/identity-blocked.json').read_text())
    assert receipt['status'] == 'metadata_unavailable' and receipt['exit_code'] is None


def test_timed_out_child_is_stopped_and_receipted_as_a_timeout(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_isolated_check.py'),
                            '--root', str(ROOT), '--output-dir', str(tmp_path),
                            '--name', 'bounded-child', '--timeout', '0.2', '--',
                            sys.executable, '-c', 'import time; time.sleep(30)'],
                           capture_output=True, text=True, timeout=10)
    assert result.returncode == 124, result.stderr
    receipt = json.loads((tmp_path / 'bounded-child.json').read_text())
    assert receipt['status'] == 'timed_out' and receipt['exit_code'] == 124
    assert receipt['child_returncode'] < 0


def test_offline_child_cannot_inherit_provider_or_database_credentials(tmp_path):
    env = dict(os.environ, SUPABASE_SECRET_KEY='synthetic-do-not-inherit',
               MEMORY_SPARK_LLM_API_KEY='synthetic-do-not-inherit')
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_isolated_check.py'),
                            '--root', str(ROOT), '--output-dir', str(tmp_path),
                            '--name', 'clean-child', '--', sys.executable, '-c',
                            'import os; print(os.getenv("SUPABASE_SECRET_KEY")); print(os.getenv("MEMORY_SPARK_LLM_API_KEY"))'],
                           env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / 'clean-child.log').read_text() == 'None\nNone\n'


def test_timeout_stops_a_term_resistant_descendant_after_its_parent_exits(tmp_path):
    descendant = tmp_path / 'descendant.py'
    descendant.write_text('import os,signal,time\nfrom pathlib import Path\n'
                          'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
                          f'Path({str(tmp_path / "descendant-pid")!r}).write_text(str(os.getpid()))\n'
                          'time.sleep(30)\n')
    root_script = tmp_path / 'root.py'
    root_script.write_text('import os,subprocess,sys,time\nfrom pathlib import Path\n'
                          f'Path({str(tmp_path / "group-pid")!r}).write_text(str(os.getpid()))\n'
                          f'subprocess.Popen([sys.executable, {str(descendant)!r}])\n'
                          'time.sleep(30)\n')
    group_id = None
    try:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/run_isolated_check.py'),
                                '--root', str(ROOT), '--output-dir', str(tmp_path),
                                '--name', 'owned-descendant', '--timeout', '0.5', '--',
                                sys.executable, str(root_script)],
                               capture_output=True, text=True, timeout=15)
        group_id = int((tmp_path / 'group-pid').read_text())
        descendant_id = int((tmp_path / 'descendant-pid').read_text())
        assert result.returncode == 124, result.stderr
        receipt = json.loads((tmp_path / 'owned-descendant.json').read_text())
        assert receipt['status'] == 'timed_out' and receipt['child_returncode'] == -signal.SIGTERM
        try:
            descendant_group = os.getpgid(descendant_id)
        except ProcessLookupError:
            descendant_group = None
        assert descendant_group is None, 'Owned descendant survived after its parent exited'
    finally:
        # Red runs must clean only the exact synthetic session created above.
        if group_id is not None:
            try:
                if os.getpgid(descendant_id) == group_id:
                    os.killpg(group_id, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_supervisor_sigterm_stops_the_child_and_finalizes_termination_receipt(tmp_path):
    marker = tmp_path / 'owned-child-pid'
    command = [sys.executable, '-c',
               f'import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)']
    runner = subprocess.Popen([sys.executable, str(ROOT / 'scripts/run_isolated_check.py'),
                               '--root', str(ROOT), '--output-dir', str(tmp_path),
                               '--name', 'supervisor-termination', '--', *command],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    child_id = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        child_id = int(marker.read_text())
        runner.send_signal(signal.SIGTERM)
        code = runner.wait(timeout=15)
        receipt = json.loads((tmp_path / 'supervisor-termination.json').read_text())
        assert receipt['status'] == 'terminated'
        assert code == receipt['exit_code'] == 128 + signal.SIGTERM
        assert receipt['termination_signal'] == signal.SIGTERM
        assert receipt['child_returncode'] == -signal.SIGTERM
        with pytest.raises(ProcessLookupError):
            os.kill(child_id, 0)
    finally:
        if runner.poll() is None:
            runner.kill()
            runner.wait(timeout=5)
        if child_id is not None:
            try:
                if os.getpgid(child_id) == child_id:
                    os.killpg(child_id, signal.SIGKILL)
            except ProcessLookupError:
                pass
