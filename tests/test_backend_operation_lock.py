"""Cross-process stack coordination; commands are provider-free Python probes."""
import os
import subprocess
import sys

import pytest

from scripts import backend_operation_lock as module


def probe(descriptor=None):
    environment = {k: v for k, v in os.environ.items() if k != module.LOCK_FD_ENV}
    if descriptor is not None:
        environment[module.LOCK_FD_ENV] = str(descriptor)
    return subprocess.run([sys.executable, module.__file__, '--', sys.executable,
        '-c', 'print("operation completed")'], env=environment,
        pass_fds=() if descriptor is None else (descriptor,), capture_output=True,
        text=True, timeout=5)


def test_only_the_lock_holders_child_can_start_the_backend():
    with module.backend_operation_lock() as descriptor:
        unrelated = probe()
        assert unrelated.returncode == 3
        assert 'backend is in use' in unrelated.stderr
        assert 'operation completed' not in unrelated.stdout
        inherited = probe(descriptor)
        assert inherited.returncode == 0, inherited.stderr
        assert inherited.stdout.strip() == 'operation completed'
        # The child finishing must not release the active evaluation's lock.
        assert probe().returncode == 3
    assert probe().returncode == 0


def test_exception_releases_the_backend_lock():
    with pytest.raises(RuntimeError, match='interrupted'):
        with module.backend_operation_lock():
            raise RuntimeError('interrupted')
    assert probe().returncode == 0


def test_make_dry_run_remains_available_during_live_execution():
    with module.backend_operation_lock():
        result = subprocess.run(['make', '--no-print-directory', '-n', 'container-down'],
            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert 'compose down' in result.stdout
