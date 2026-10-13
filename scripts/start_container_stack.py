#!/usr/bin/env python3
"""Build changed repository images and reconcile the local Mocker stack.

The cache records content hashes and image IDs, never resolved environment
values. It is committed only after alias repair and the stack health checks.
"""
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


# Keep these COPY inputs aligned with the three repository Containerfiles.
IMAGES = {
    'api': {
        'tag': 'localhost/memory-spark:dev',
        'services': ['api', 'worker', 'photo-worker'],
        'context': '.',
        'inputs': ['Containerfile', 'pyproject.toml', 'apps/__init__.py', 'apps/api',
                   'README.md', 'Mira_Memoir_Journalist_System_Prompt_v1.0.md',
                   'apps/web/public', 'skills', 'docs', 'infra', 'scripts'],
    },
    'codex-worker': {
        'tag': 'localhost/memory-spark-codex-worker:dev',
        'services': ['codex-worker'],
        'context': '.',
        'inputs': ['codex-worker/Containerfile', 'pyproject.toml', 'apps/__init__.py',
                   'apps/api', 'README.md', 'Mira_Memoir_Journalist_System_Prompt_v1.0.md',
                   'skills', 'scripts/verify_codex_worker_isolation.py'],
    },
    'web': {
        'tag': 'localhost/copyme2-web:dev',
        'services': ['web'],
        'context': 'apps/web',
        'inputs': ['apps/web'],
    },
}


def fingerprint(root, definition, compose_file, build_args):
    digest = hashlib.sha256()
    digest.update(json.dumps([definition, build_args], sort_keys=True).encode())
    digest.update(compose_file.read_bytes())
    ignore_file = root / definition['context'] / '.dockerignore'
    rules = ignore_file.read_text().splitlines() if ignore_file.exists() else []
    digest.update('\n'.join(rules).encode())
    # Only omit unambiguous generated files explicitly ignored by this context.
    # Other ignore syntax is conservatively over-included in the fingerprint.
    ignored_names = {v for v in rules if v in {
        'node_modules', '.next', '__pycache__', '.git', '.pytest_cache', '.DS_Store'}}
    if '**/.next' in rules:
        ignored_names.add('.next')
    if '**/node_modules' in rules:
        ignored_names.add('node_modules')

    def excluded(path):
        return path.name in ignored_names or ('*.py[cod]' in rules
            and fnmatch.fnmatch(path.name, '*.py[cod]'))

    files = set()
    for source in definition['inputs']:
        path = root / source
        if path.is_dir() and not path.is_symlink():
            for directory, dirs, names in os.walk(path):
                dirs[:] = sorted(v for v in dirs if not excluded(Path(v)))
                files.update(Path(directory) / v for v in dirs
                             if (Path(directory) / v).is_symlink())
                files.update(Path(directory) / v for v in names if not excluded(Path(v)))
        else:
            files.add(path)
    for path in sorted(files):
        digest.update(str(path.relative_to(root)).encode() + b'\0')
        if path.is_symlink():
            digest.update(b'link\0' + os.readlink(path).encode())
        elif path.is_file():
            digest.update(str(path.stat().st_mode & 0o777).encode() + b'\0')
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
        else:
            digest.update(b'missing')
        digest.update(b'\0')
    return digest.hexdigest()


def image_id(mocker, tag):
    result = subprocess.run([mocker, 'image', 'inspect', tag, '--format', '{{.Id}}'],
                            capture_output=True, text=True, timeout=30)
    value = result.stdout.strip()
    if result.returncode:
        return None
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
        raise ValueError('Mocker returned an invalid image ID')
    return value


def read_cache(path):
    try:
        value = json.loads(path.read_text())
        return value if (isinstance(value, dict) and value.get('version') == 1
                         and isinstance(value.get('images'), dict)) else {}
    except (FileNotFoundError, ValueError):
        return {}


def start(args):
    root = Path.cwd()
    compose_file = Path(args.compose_file).resolve()
    state_file = root / 'var' / 'container-startup.json'
    previous = read_cache(state_file)
    saved = previous.get('images', {})
    current = {}
    changed = []
    for name, definition in IMAGES.items():
        build_args = {'CODEX_VERSION': os.environ.get('MEMORY_SPARK_CODEX_VERSION') or '0.156.1'} \
            if name == 'codex-worker' else {}
        entry = {'fingerprint': fingerprint(root, definition, compose_file, build_args),
                 'image_id': image_id(args.mocker, definition['tag'])}
        current[name] = entry
        if args.force_build or not entry['image_id'] or saved.get(name) != entry:
            changed.append(name)

    compose = [args.mocker, 'compose']
    if changed:
        print('Building changed images: ' + ', '.join(changed), flush=True)
        subprocess.run([*compose, 'build', '-f', args.compose_file, *changed], check=True)
        for name in changed:
            current[name]['image_id'] = image_id(args.mocker, IMAGES[name]['tag'])
            if not current[name]['image_id']:
                raise ValueError('Built image was not found in the local image store')
        # Mocker 0.9.3 misses image-tag changes and ignores --no-deps with
        # --force-recreate. Remove only consumers of rebuilt images using the
        # project/service-filtered inventory, then let Compose start them again.
        services = [service for name in changed for service in IMAGES[name]['services']]
        inventory = subprocess.run([*compose, 'ps', '-f', args.compose_file, '--all',
            '-q', *services], capture_output=True, text=True, check=True, timeout=30)
        ids = inventory.stdout.split()
        if not all(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', v) for v in ids):
            raise ValueError('Mocker returned an invalid container ID')
        if ids:
            print('Refreshing services: ' + ', '.join(services), flush=True)
            subprocess.run([args.mocker, 'rm', '-f', *ids], check=True)
    else:
        print('Build inputs and local images unchanged; reusing existing images.', flush=True)

    # Reconcile changed environment/configuration and start any stopped services.
    # Repair static aliases before waiting: partial recreation changes addresses.
    services = ['temporal', 'api', 'worker', 'web', 'codex-worker', 'photo-worker']
    subprocess.run([*compose, 'up', '-f', args.compose_file, '--no-build', '--no-deps',
        '--detach', *services], check=True)
    subprocess.run(['python3', 'scripts/refresh_mocker_compose_hosts.py',
        '--mocker', args.mocker, '--apple-container', args.apple_container,
        '--compose-file', args.compose_file], check=True)
    subprocess.run([*compose, 'up', '-f', args.compose_file, '--no-build', '--no-recreate',
        '--no-deps', '--detach', '--wait', '--wait-timeout', '120', *services], check=True)
    subprocess.run(args.health_command, check=True)

    state_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=state_file.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump({'version': 1, 'images': current}, stream, sort_keys=True)
    try:
        temporary.replace(state_file)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mocker', default='mocker')
    parser.add_argument('--apple-container', default='/opt/homebrew/bin/container')
    parser.add_argument('--compose-file', default='compose.yml')
    parser.add_argument('--force-build', action='store_true')
    parser.add_argument('health_command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.health_command[:1] == ['--']:
        args.health_command.pop(0)
    if not args.health_command:
        parser.error('A stack health command is required')
    try:
        # Make runs recipes containing $(MAKE) even under -n; do not mutate
        # images, containers, or the cache when that recursive recipe calls us.
        flags = os.environ.get('MAKEFLAGS', '').split()
        dry_run = any(flag in {'--just-print', '--dry-run', '--recon'}
            or (not flag.startswith('--') and flag.lstrip('-').isalpha() and 'n' in flag)
            for flag in flags)
        if dry_run:
            print('Incremental startup: build changed images, reconcile services, and refresh aliases.')
            subprocess.run(args.health_command, check=True)
            return 0
        start(args)
    except (OSError, ValueError, subprocess.SubprocessError):
        # Subprocess commands and Compose inspect/config output can contain secrets.
        print('Container startup failed; the successful startup cache was not updated.', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
