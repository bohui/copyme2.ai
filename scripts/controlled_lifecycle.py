"""Signal cancellation and exact native allocation reconciliation for diagnostics."""
import asyncio
from collections import Counter
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import threading


_signal_scopes = {}


@contextmanager
def cancel_on_sigterm():
    """Cancel registered owners, leaving their shielded cleanup tasks alive.

    Nested/concurrent diagnostic calls share one handler. The previous process
    handler is restored only after the last owner finishes its cleanup.
    """
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Controlled process supervision requires the main thread')
    loop, owner = asyncio.get_running_loop(), asyncio.current_task()
    state = _signal_scopes.get(loop)
    if state is None:
        owners = Counter()
        def cancel_owners():
            for task in tuple(owners):
                task.cancel()
        def receive(signum, frame):
            loop.call_soon_threadsafe(cancel_owners)
        previous = signal.signal(signal.SIGTERM, receive)
        state = owners, previous
        _signal_scopes[loop] = state
    owners, previous = state
    owners[owner] += 1
    try:
        yield
    finally:
        owners[owner] -= 1
        if not owners[owner]:
            del owners[owner]
        if not owners:
            signal.signal(signal.SIGTERM, previous)
            del _signal_scopes[loop]


def sigterm_cancellable(function):
    @wraps(function)
    async def run(*args, **kwargs):
        with cancel_on_sigterm():
            return await function(*args, **kwargs)
    return run


def reconcile_native_directory(directory, environment):
    """Stop only postmasters identifying this private root, then remove it.

    A failed command or uncertain identity leaves allocation metadata intact.
    This also runs synchronously while an async owner's cancellation unwinds.
    """
    directory = Path(directory)
    for data in directory.glob('memoir-lease-pg-*/data'):
        if data.is_symlink() or data.parent.is_symlink() or data.resolve().parent.parent != directory.resolve():
            raise RuntimeError(f'Controlled allocation identity changed; retained {directory}')
        pid_file = data/'postmaster.pid'
        if not pid_file.exists():
            continue
        fields = pid_file.read_text().splitlines()
        if len(fields) < 2 or not fields[0].isdigit() or Path(fields[1]).resolve() != data.resolve():
            raise RuntimeError(f'Controlled allocation identity unavailable; retained {directory}')
        identity = subprocess.run(['ps', '-p', fields[0], '-o', 'args='], env=environment,
            text=True, capture_output=True, timeout=2)
        command = shlex.split(identity.stdout)
        if (identity.returncode or len(command) < 3 or Path(command[0]).name != 'postgres'
            or command[1] != '-D' or Path(command[2]).resolve() != data.resolve()):
            raise RuntimeError(f'Controlled postmaster identity unverified; retained {directory}')
        subprocess.run(['pg_ctl', '-D', str(data), '-m', 'immediate', '-w', 'stop'],
            env=environment, capture_output=True, timeout=12, check=True)
        if pid_file.exists():
            raise RuntimeError(f'Controlled shutdown unverified; retained {directory}')
    shutil.rmtree(directory)
