"""Safe, allowlisted Codex artifact enumeration shared by API and worker."""
from __future__ import annotations

from pathlib import Path


ARTIFACT_ROOTS = ("sessions", "archived_sessions", "memories")
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024


def iter_artifacts(home: Path):
    """Yield ``(relative_path, bytes)`` only for safe Codex artifacts.

    Symlinks are intentionally excluded.  The worker may run with elevated
    privileges to drop Codex subprocesses into per-user OS identities, so a
    symlink must never let artifact synchronization escape the user home.
    """
    home = home.resolve()
    for root_name in ARTIFACT_ROOTS:
        root = home / root_name
        if not root.exists() or root.is_symlink():
            continue
        for file in sorted(root.rglob("*")):
            relative = file.relative_to(home)
            if (
                file.is_symlink()
                or not file.is_file()
                or any(part.startswith(".") for part in relative.parts)
            ):
                continue
            try:
                resolved = file.resolve(strict=True)
                resolved.relative_to(home)
                size = file.stat().st_size
            except (FileNotFoundError, OSError, ValueError):
                continue
            if size > MAX_ARTIFACT_BYTES:
                continue
            yield relative.as_posix(), file.read_bytes()
