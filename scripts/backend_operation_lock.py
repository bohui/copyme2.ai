#!/usr/bin/env python3
"""Keep local stack changes from interrupting a live Supabase evaluation."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat
import subprocess
import sys

LOCK_PATH = Path('/tmp') / f'memoir-backend-{os.getuid()}.lock'
LOCK_FD_ENV = 'MEMOIR_BACKEND_LOCK_FD'


class BackendInUseError(ValueError):
    pass


@contextmanager
def backend_operation_lock():
    inherited = os.environ.get(LOCK_FD_ENV)
    descriptor = int(inherited) if inherited is not None else os.open(
        LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode):
            raise ValueError('Invalid backend operation lock')
        if inherited is not None and not os.path.samestat(info, LOCK_PATH.stat()):
            raise ValueError('Invalid inherited backend operation lock')
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackendInUseError('The Memoir backend is in use by a live evaluation or another stack operation; wait for it to finish.') from None
        yield descriptor
    finally:
        if inherited is None:
            # Closing releases the lock even after cancellation or process exit.
            # Keep the inode: unlinking would let another process bypass it.
            os.close(descriptor)


def main():
    command = sys.argv[1:]
    if command[:1] == ['--']:
        command = command[1:]
    if not command:
        raise ValueError('A backend operation command is required')
    # Make executes recursive recipes even under -n. Their child Make still
    # only prints commands, so inspecting a running stack needs no lock.
    flags = os.environ.get('MAKEFLAGS', '').split()
    dry_run = any(flag in {'--just-print', '--dry-run', '--recon'}
        or (not flag.startswith('--') and flag.lstrip('-').isalpha() and 'n' in flag)
        for flag in flags)
    if Path(command[0]).name in {'make', 'gmake'} and dry_run:
        return subprocess.run(command).returncode
    try:
        with backend_operation_lock() as descriptor:
            return subprocess.run(command, pass_fds=(descriptor,),
                env={**os.environ, LOCK_FD_ENV: str(descriptor)}).returncode
    except BackendInUseError as error:
        print(str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
