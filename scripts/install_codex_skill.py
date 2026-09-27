#!/usr/bin/env python3
"""Install one validated skill archive into a Codex home."""

from __future__ import annotations

import os
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath


def install_skill(archive_path: str, skill_name: str, codex_home: str | None = None) -> None:
    archive = Path(archive_path)
    if not archive.is_file():
        raise FileNotFoundError(archive)
    if not skill_name or Path(skill_name).name != skill_name or skill_name in {'.', '..'}:
        raise ValueError('invalid skill name')

    root = Path(codex_home or os.environ.get('CODEX_HOME', '/codex-home')).resolve()
    skills_root = root / 'skills'
    target = skills_root / skill_name
    staging = skills_root / f'.{skill_name}.installing'
    skills_root.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            prefix = f'{skill_name}/'
            if not members or any(not info.filename.startswith(prefix) for info in members):
                raise ValueError('skill archive must contain one top-level skill directory')

            shutil.rmtree(staging, ignore_errors=True)
            for info in members:
                relative = PurePosixPath(info.filename).relative_to(prefix)
                if not relative.parts or '..' in relative.parts or relative.is_absolute():
                    raise ValueError('skill archive contains an unsafe path')
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError('skill archive cannot contain symlinks')
                destination = staging.joinpath(*relative.parts)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, destination.open('wb') as target_file:
                    shutil.copyfileobj(source, target_file)

        if not (staging / 'SKILL.md').is_file():
            raise ValueError('skill archive does not contain SKILL.md')
        if target.is_symlink() or (target.exists() and not target.is_dir()):
            raise ValueError(f'existing skill target is not a directory: {target}')
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        archive.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) != 3:
        print('usage: install_codex_skill.py ARCHIVE SKILL_NAME', file=sys.stderr)
        return 2
    try:
        install_skill(sys.argv[1], sys.argv[2])
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f'Codex skill install failed: {error}', file=sys.stderr)
        return 1
    print(f'Installed {sys.argv[2]} into {Path(os.environ.get("CODEX_HOME", "/codex-home")) / "skills" / sys.argv[2]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
