"""Descriptor-based operations at the privileged worker/user-file boundary."""
import os
import shutil
import stat
import tempfile
from pathlib import Path


DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def write_config(home: Path, trusted_root: Path, uid: int, content: str):
    """Replace, never open or chmod, a user-controlled config pathname."""
    home_fd = os.open(home, DIRECTORY_FLAGS)
    temporary = None
    try:
        os.fchmod(home_fd, 0o700)
        os.fchown(home_fd, uid, uid)
        fd, temporary = tempfile.mkstemp(prefix='.config-', dir=trusted_root)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(content)
            output.flush()
            os.fchmod(output.fileno(), 0o600)
            os.fchown(output.fileno(), uid, uid)
        os.replace(temporary, 'config.toml', dst_dir_fd=home_fd)
        temporary = None
    finally:
        os.close(home_fd)
        if temporary is not None:
            os.unlink(temporary)


def _copy_tree(source_fd: int, destination: Path, uid: int):
    for name in os.listdir(source_fd):
        info = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            fd = os.open(name, DIRECTORY_FLAGS, dir_fd=source_fd)
            try:
                child = destination / name
                child.mkdir(mode=0o700)
                _copy_tree(fd, child, uid)
            finally:
                os.close(fd)
        elif stat.S_ISREG(info.st_mode):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=source_fd)
            with os.fdopen(fd, 'rb') as source:
                opened = os.fstat(source.fileno())
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                    raise RuntimeError('Unsafe file in legacy Codex home')
                with (destination / name).open('xb') as target:
                    shutil.copyfileobj(source, target)
                    os.fchmod(target.fileno(), 0o600)
                    os.fchown(target.fileno(), uid, uid)
        else:
            raise RuntimeError('Legacy Codex home contains a symlink or special file')
    os.chown(destination, uid, uid)


def migrate_home(source: Path, destination: Path, uid: int):
    """Copy an offline legacy home atomically; never overwrite worker state.

    The legacy bind mount is read-only. Both SQLite and its WAL are copied;
    deployment must stop the old API before starting the new worker.
    """
    try:
        source_fd = os.open(source, DIRECTORY_FLAGS)
    except FileNotFoundError:
        return
    try:
        # A worker-owned wrapper prevents tenants modifying the staging tree.
        with tempfile.TemporaryDirectory(prefix='.migration-', dir=destination.parent) as stage:
            home = Path(stage) / 'home'
            home.mkdir(mode=0o700)
            _copy_tree(source_fd, home, uid)
            # Caller holds the per-user filesystem lock; destination is absent.
            os.rename(home, destination)
    finally:
        os.close(source_fd)
