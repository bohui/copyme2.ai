#!/usr/bin/env python3
"""Install or update upstream game instructions without changing Memoir prompts."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def activate(source, destination, revision):
    """An atomic link switches future builds; prior snapshots remain readable."""
    versions = destination / '.versions'
    versions.mkdir(exist_ok=True)
    installed = versions / revision
    if not installed.exists():
        source.rename(installed)
    target = destination / 'higgsfield-websites'
    link = destination / ('.next-' + uuid4().hex)
    link.symlink_to(installed.relative_to(destination), target_is_directory=True)
    if target.exists() and not target.is_symlink():
        target.rename(versions / ('legacy-' + uuid4().hex))
    os.replace(link, target)
    return target


def update(destination, *, ref='main'):
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.higgsfield-', dir=destination) as temporary:
        checkout = Path(temporary) / 'upstream'
        subprocess.run(['git', 'clone', '--depth', '1', '--filter=blob:none', '--sparse', '--branch', ref,
            'https://github.com/higgsfield-ai/skills.git', str(checkout)], check=True, timeout=120)
        subprocess.run(['git', '-C', str(checkout), 'sparse-checkout', 'set', 'higgsfield-websites'], check=True, timeout=60)
        revision = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
        source = checkout / 'higgsfield-websites'
        if 'name: higgsfield-websites' not in (source / 'SKILL.md').read_text():
            raise ValueError('Upstream did not return the requested skill')
        shutil.copy2(checkout / 'LICENSE', source / 'LICENSE')
        (source / '.upstream.json').write_text(json.dumps(dict(repository='higgsfield-ai/skills',
            path='higgsfield-websites', revision=revision), indent=2) + '\n')
        target = activate(source, destination, revision)
    return dict(skill='higgsfield-websites', revision=revision, path=str(target))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dest', type=Path, default=ROOT / 'var/external-skills')
    parser.add_argument('--ref', default='main', help='Upstream branch or tag to install')
    args = parser.parse_args()
    print(json.dumps(update(args.dest, ref=args.ref)))
