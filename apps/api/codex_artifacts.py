"""Safe, allowlisted Codex artifact enumeration shared by API and worker."""
from __future__ import annotations

import os
import stat
from pathlib import Path


ARTIFACT_ROOTS = ("sessions", "archived_sessions", "memories")
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024


def iter_artifacts(home: Path):
    """Yield ``(relative_path, bytes)`` only for safe Codex artifacts.

    Symlinks are intentionally excluded.  The worker may run with elevated
    privileges to drop Codex subprocesses into per-user OS identities, so a
    symlink must never let artifact synchronization escape the user home.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    home_fd = os.open(home, flags)
    try:
        for root_name in ARTIFACT_ROOTS:
            try:
                root_fd = os.open(root_name, flags, dir_fd=home_fd)
            except OSError:
                continue
            try:
                yield from _walk(root_fd, root_name)
            finally:
                os.close(root_fd)
    finally:
        os.close(home_fd)


def _walk(directory_fd, prefix):
    for name in sorted(os.listdir(directory_fd)):
        if name.startswith('.'):
            continue
        path = f'{prefix}/{name}'
        try:
            info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=directory_fd)
                try:
                    yield from _walk(fd, path)
                finally:
                    os.close(fd)
            elif stat.S_ISREG(info.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
                with os.fdopen(fd, 'rb') as source:
                    opened = os.fstat(source.fileno())
                    if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                            or opened.st_size > MAX_ARTIFACT_BYTES):
                        continue
                    content = source.read(MAX_ARTIFACT_BYTES + 1)
                if len(content) <= MAX_ARTIFACT_BYTES:
                    yield path, content
        except OSError:
            # A concurrently renamed/deleted file is not a safe snapshot.
            continue
