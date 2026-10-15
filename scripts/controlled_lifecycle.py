"""Signal cancellation and exact native allocation reconciliation for diagnostics."""
import asyncio
from collections import Counter
from contextlib import contextmanager
from functools import wraps
import json
from pathlib import Path
import os
import shlex
import shutil
import signal
import subprocess
import threading
import tempfile
import time


_signal_scopes = {}
ALLOCATION_ROOT_ENV = 'MEMOIR_CONTROLLED_ALLOCATION_ROOT'


def new_native_root(prefix):
    """Register a short physical root with an optional transitive outer owner."""
    root = Path(tempfile.mkdtemp(prefix=prefix, dir='/tmp'))
    try:
        parent = os.getenv(ALLOCATION_ROOT_ENV)
        if parent:
            parent = Path(parent)
            if parent.is_symlink() or parent.stat().st_uid != os.getuid():
                raise RuntimeError('Controlled parent ownership is unverified')
            registrations = parent/'owned-roots'
            registrations.mkdir(mode=0o700, exist_ok=True)
            _save(registrations/(root.name+'.json'), _root_identity(root))
        return root
    except BaseException:
        shutil.rmtree(root)
        raise


def _save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _root_identity(root):
    stat = root.stat()
    return {'root':str(root), 'device':stat.st_dev, 'inode':stat.st_ino}


def _process_start(pid, environment):
    result = subprocess.run(['ps','-p',str(pid),'-o','lstart='], env=environment,
        text=True,capture_output=True,timeout=2)
    return ' '.join(result.stdout.split()) if result.returncode == 0 else None


def register_command_group(root, pid, environment):
    """Retain the Popen session identity, including an unfinished birth lookup."""
    record = {'group_id':pid, 'leader_started':None}
    _save(Path(root)/'command-group.json', record)
    record['leader_started'] = _process_start(pid, environment)
    _save(Path(root)/'command-group.json', record)
    return record


def _quiesce_command_group(root, environment, stopped):
    record = root/'command-group.json'
    if not record.exists():
        if root.name.startswith('memoir-check-pg-'):
            raise RuntimeError(f'Controlled command identity unavailable; retained {root}')
        return
    group = json.loads(record.read_text())
    group_id = group['group_id']
    if type(group_id) is not int or group_id <= 0:
        raise RuntimeError(f'Controlled command identity invalid; retained {root}')
    current = _process_start(group_id, environment)
    if current is not None and current!=group.get('leader_started'):
        raise RuntimeError(f'Controlled command identity unverified; retained {root}')
    def live_members():
        # Apple's ps has no sid column; its sess column is a kernel pointer.
        # getsid supplies the same numeric session identity on both Unix hosts.
        snapshot_deadline = time.monotonic()+2
        while True:
            result = subprocess.run(['ps','-e','-o','pid=,pgid=,stat='],env=environment,
                text=True,capture_output=True,timeout=2,check=True)
            members,vanished = [],False
            for line in result.stdout.splitlines():
                row = line.split()
                if len(row)!=3 or row[1]!=str(group_id) or row[2].startswith('Z'):
                    continue
                try:
                    session = os.getsid(int(row[0]))
                except ProcessLookupError:
                    # This process may have forked after the snapshot. A fresh
                    # enumeration must find and verify its surviving children.
                    vanished = True
                    continue
                if session != group_id:
                    raise RuntimeError(f'Controlled command identity unverified; retained {root}')
                members.append(row)
            if not vanished:
                return members
            if time.monotonic()>=snapshot_deadline:
                raise RuntimeError(f'Controlled command snapshot unstable; retained {root}')
    members = live_members()
    if not members:
        return
    current = _process_start(group_id, environment)
    if not group.get('leader_started') or (current is not None and current!=group['leader_started']):
        raise RuntimeError(f'Controlled command identity unverified; retained {root}')
    try:
        os.killpg(group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    deadline = time.monotonic()+5
    while live_members():
        if time.monotonic()>=deadline:
            raise RuntimeError(f'Controlled command still running; retained {root}')
        time.sleep(.02)
    stopped.append(group)


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


def _reconcile(directory, environment, result, expected=None, visited=None):
    """Stop only postmasters identifying this private root, then remove it.

    A failed command or uncertain identity leaves allocation metadata intact.
    This also runs synchronously while an async owner's cancellation unwinds.
    """
    directory = Path(directory)
    visited = set() if visited is None else visited
    if str(directory) in visited:
        raise RuntimeError(f'Controlled ownership cycle; retained {directory}')
    visited.add(str(directory))
    if directory.is_symlink():
        raise RuntimeError(f'Controlled allocation identity changed; retained {directory}')
    if expected is not None and not directory.exists():
        result['registered_roots'].append(expected)
        return
    if directory.stat().st_uid!=os.getuid():
        raise RuntimeError(f'Controlled allocation identity changed; retained {directory}')
    identity = _root_identity(directory)
    if expected is not None and identity!=expected:
        raise RuntimeError(f'Controlled allocation identity changed; retained {directory}')
    result['registered_roots'].append(identity)
    _quiesce_command_group(directory, environment, result['command_groups_stopped'])
    for registration in sorted((directory/'owned-roots').glob('*.json')):
        child = json.loads(registration.read_text())
        path = Path(child['root'])
        if path.parent!=Path('/tmp') or not path.name.startswith(('memoir-case-','memoir-controlled-pg-','memoir-check-pg-')):
            raise RuntimeError(f'Controlled child root is unverified; retained {directory}')
        _reconcile(path,environment,result,expected=child,visited=visited)
    for data in directory.glob('**/memoir-lease-pg-*/data'):
        if not data.resolve().is_relative_to(directory.resolve()):
            raise RuntimeError(f'Controlled allocation identity changed; retained {directory}')
        path = data
        while path != directory:
            if path.is_symlink():
                raise RuntimeError(f'Controlled allocation identity changed; retained {directory}')
            path = path.parent
        pid_file = data/'postmaster.pid'
        if not pid_file.exists():
            continue
        fields = pid_file.read_text().splitlines()
        if len(fields) < 2 or not fields[0].isdigit() or Path(fields[1]).resolve() != data.resolve():
            raise RuntimeError(f'Controlled allocation identity unavailable; retained {directory}')
        identity = subprocess.run(['ps', '-ww', '-p', fields[0], '-o', 'args='], env=environment,
            text=True, capture_output=True, timeout=2)
        command = shlex.split(identity.stdout)
        if (identity.returncode or len(command) < 3 or Path(command[0]).name != 'postgres'
            or command[1] != '-D' or Path(command[2]).resolve() != data.resolve()):
            raise RuntimeError(f'Controlled postmaster identity unverified; retained {directory}')
        subprocess.run(['pg_ctl', '-D', str(data), '-m', 'immediate', '-w', 'stop'],
            env=environment, capture_output=True, timeout=12, check=True)
        if pid_file.exists():
            raise RuntimeError(f'Controlled shutdown unverified; retained {directory}')
        result['postmasters_stopped'].append({'pid':int(fields[0]), 'data':str(data)})
    shutil.rmtree(directory)


def reconcile_native_directory(directory, environment):
    """Reconcile only identity-checked roots/sessions registered to this owner."""
    result = {'verified':True,'root_removed':True,'postmasters_stopped':[],
        'registered_roots':[],'command_groups_stopped':[]}
    _reconcile(directory,environment,result)
    return result
