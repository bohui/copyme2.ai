#!/usr/bin/env python3
"""Build changed repository images and start the local Mocker stack.

The cache records content hashes and image IDs, never resolved environment
values. A completed image build is cached separately so a later startup
failure does not trigger the same expensive build again.
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


# Keep these inputs aligned with the Compose build targets' COPY instructions.
IMAGES = {
    'api': {
        'tag': 'localhost/memory-spark:dev',
        'services': ['api', 'worker', 'photo-worker'],
        'context': '.',
        'inputs': ['Containerfile', 'pyproject.toml'],
    },
    'codex-worker': {
        'tag': 'localhost/memory-spark-codex-worker:dev',
        'services': ['codex-worker'],
        'context': '.',
        'inputs': ['codex-worker/Containerfile', 'pyproject.toml',
                   'scripts/verify_codex_worker_isolation.py'],
    },
    'web': {
        'tag': 'localhost/copyme2-web:dev',
        'services': ['web'],
        'context': 'apps/web',
        'inputs': ['apps/web'],
    },
}


# These paths are bind-mounted into the local services. They are tracked
# separately from image build inputs so a source edit restarts the process that
# imports it without invalidating the dependency image layers.
_BACKEND_RUNTIME_INPUTS = (
    'apps/__init__.py', 'apps/api', 'apps/web/public', 'README.md', 'docs', 'skills',
)
SERVICE_RUNTIME_INPUTS = {
    'api': _BACKEND_RUNTIME_INPUTS + ('scripts', 'infra'),
    'worker': _BACKEND_RUNTIME_INPUTS + ('scripts', 'infra'),
    'photo-worker': _BACKEND_RUNTIME_INPUTS + ('infra',),
    'codex-worker': ('apps/__init__.py', 'apps/api', 'README.md', 'skills'),
    'web': ('apps/web',),
}


def compose_build_text(compose_file, service):
    text = compose_file.read_text()
    # shortcut: anchors/custom layouts hash the full file; parse YAML if those become common.
    if re.search(r'(?m)^[^#\n]*[&*][a-zA-Z_]', text):
        return text
    section = re.search(rf'(?ms)^  {re.escape(service)}:[ \t]*\n(.*?)(?=^  \S|\Z)', text)
    if section:
        build = re.search(r'(?ms)^    build:[ \t]*\n(.*?)(?=^    \S|\Z)', section[1])
        if build:
            return build[0]
    return text


def fingerprint(root, definition, compose_file, build_args):
    digest = hashlib.sha256()
    digest.update(json.dumps([definition, build_args], sort_keys=True).encode())
    digest.update(compose_build_text(compose_file, definition['services'][0]).encode())
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


def runtime_fingerprint(root, inputs):
    """Hash files visible through a service's bind mounts."""
    digest = hashlib.sha256()
    ignored_names = {'.git', '.next', '.pytest_cache', '.DS_Store', '__pycache__',
                     'node_modules'}

    def excluded(path):
        return path.name in ignored_names or fnmatch.fnmatch(path.name, '*.py[cod]')

    files = set()
    for source in inputs:
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


def compose_service_text(compose_file, service):
    text = compose_file.read_text()
    section = re.search(rf'(?ms)^  {re.escape(service)}:[ \t]*\n(.*?)(?=^  \S|\Z)', text)
    return section[0] if section else text


def temporal_config_fingerprint(compose_file):
    network = os.environ.get('MEMORY_SPARK_LLM_NETWORK', 'llm-provider-llm-network')
    return hashlib.sha256((compose_service_text(compose_file, 'temporal')
                           + '\0' + network).encode()).hexdigest()


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


def write_cache(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value, stream, sort_keys=True)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def compose_container_ids(mocker, compose_file, services):
    inventory = subprocess.run([mocker, 'compose', 'ps', '-f', compose_file, '--all',
        '-q', *services], capture_output=True, text=True, check=True, timeout=30)
    ids = inventory.stdout.split()
    if not all(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', value) for value in ids):
        raise ValueError('Mocker returned an invalid container ID')
    return ids


def service_from_container_id(container_id):
    prefix = 'memory-spark-'
    if not container_id.startswith(prefix) or not container_id.endswith('-1'):
        return None
    return container_id[len(prefix):-2]


def container_mounts(apple_container, container_id):
    result = subprocess.run([apple_container, 'inspect', container_id],
                            capture_output=True, text=True, check=True, timeout=30)
    try:
        metadata = json.loads(result.stdout)
        mounts = metadata[0]['configuration']['mounts']
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise ValueError('Apple Container returned invalid mount metadata') from error
    if not isinstance(mounts, list) or not all(isinstance(value, dict) for value in mounts):
        raise ValueError('Apple Container returned invalid mount metadata')
    return mounts


def checkout_mounts_match(root, apple_container, container_ids):
    """Ensure bind-mounted application services still point at this checkout."""
    expected_api_source = (root.resolve() / 'apps' / 'api').resolve()
    mounted_services = {'api', 'worker', 'photo-worker', 'codex-worker'}
    for container_id in container_ids:
        service = service_from_container_id(container_id)
        if service is None:
            return False
        if service not in mounted_services:
            continue
        sources = [str(mount.get('source', '')) for mount in
                   container_mounts(apple_container, container_id)]
        if not any(Path(source).resolve() == expected_api_source for source in sources
                   if source):
            return False
    return True


def prepare_external_images(mocker, apple_container, compose_file):
    # Mocker 0.9.3 ignores config's --images/--format flags; capture its secret-bearing YAML.
    config = subprocess.run([mocker, 'compose', 'config', '-f', compose_file],
                            capture_output=True, text=True, check=True, timeout=30)
    references = re.findall(r'(?m)^    image: (\S+)[ \t]*$', config.stdout)
    if not references:
        raise ValueError('Compose configuration did not list service images')
    local_tags = {definition['tag'] for definition in IMAGES.values()}
    for reference in dict.fromkeys(references):
        if reference in local_tags or image_id(mocker, reference):
            continue
        print('Pulling missing external image for linux/arm64: ' + reference, flush=True)
        subprocess.run([apple_container, 'image', 'pull', '--platform', 'linux/arm64',
                        '--progress', 'plain', reference], check=True, timeout=300)
        if not image_id(mocker, reference):
            raise ValueError('Pulled image was not found in the local image store')
    return hashlib.sha256(config.stdout.encode()).hexdigest()


def start(args):
    root = Path.cwd()
    compose_file = Path(args.compose_file).resolve()
    state_file = root / 'var' / 'container-startup.json'
    build_state_file = root / 'var' / 'container-build.json'
    previous = read_cache(state_file)
    built = read_cache(build_state_file)
    saved = previous.get('images', {})
    built_images = built.get('images', {})
    current = {}
    changed = []
    current_runtime = {service: runtime_fingerprint(root, inputs)
                       for service, inputs in SERVICE_RUNTIME_INPUTS.items()}
    previous_runtime = previous.get('services', {})
    changed_runtime_services = {service for service, value in current_runtime.items()
                                if previous_runtime.get(service) != value}
    compose_fingerprint = prepare_external_images(args.mocker, args.apple_container,
                                                   args.compose_file)
    current_temporal_config = temporal_config_fingerprint(compose_file)
    for name, definition in IMAGES.items():
        build_args = {'CODEX_VERSION': os.environ.get('MEMORY_SPARK_CODEX_VERSION') or '0.156.1'} \
            if name == 'codex-worker' else {}
        entry = {'fingerprint': fingerprint(root, definition, compose_file, build_args),
                 'image_id': image_id(args.mocker, definition['tag'])}
        current[name] = entry
        cached_entries = [saved.get(name), built_images.get(name)]
        if (args.force_build or not entry['image_id']
                or not any(cached == entry for cached in cached_entries)):
            changed.append(name)

    compose = [args.mocker, 'compose']
    services = ['temporal', 'api', 'worker', 'web', 'codex-worker', 'photo-worker']
    if changed:
        print('Building changed images: ' + ', '.join(changed), flush=True)
        subprocess.run([*compose, 'build', '-f', args.compose_file, *changed], check=True)
        for name in changed:
            current[name]['image_id'] = image_id(args.mocker, IMAGES[name]['tag'])
            if not current[name]['image_id']:
                raise ValueError('Built image was not found in the local image store')
    else:
        print('Build inputs and local images unchanged; reusing existing images.', flush=True)

    # Persist successful builds before touching containers. If a later health
    # check fails, the next retry can reuse these images instead of rebuilding
    # the dependency-heavy runtime from scratch.
    write_cache(build_state_file, {'version': 1, 'images': current})

    existing = compose_container_ids(args.mocker, args.compose_file, services)
    existing_services = {service_from_container_id(value) for value in existing}
    missing_services = set(services) - existing_services
    changed_services = ({service for name in changed for service in IMAGES[name]['services']}
                        | changed_runtime_services)
    config_changed = previous.get('compose_fingerprint') != compose_fingerprint
    temporal_changed = (previous.get('temporal_config_fingerprint')
                        != current_temporal_config)
    mounts_match = checkout_mounts_match(root, args.apple_container, existing)
    remove_services = set()
    if config_changed:
        # Environment values belong to the app containers. Keep Temporal's
        # persistent server up unless its own config or network changed.
        remove_services.update(existing_services - {'temporal'})
    else:
        remove_services.update(changed_services)
    if temporal_changed and 'temporal' in existing_services:
        remove_services.add('temporal')
    if not mounts_match:
        remove_services.update(existing_services - {'temporal'})
    ids = [value for value in existing
           if service_from_container_id(value) in remove_services]
    if ids:
        # Mocker misses image-tag changes and ignores --no-deps with --force-recreate.
        # Remove only containers whose image/config/mounts are stale; named
        # volumes remain intact and unchanged Temporal stays running.
        print('Recreating local stack containers: ' + ', '.join(ids), flush=True)
        subprocess.run([args.mocker, 'rm', '-f', *ids], check=True)
    elif missing_services:
        print('Starting missing services: ' + ', '.join(sorted(missing_services)), flush=True)
    else:
        print('Reusing unchanged running containers.', flush=True)

    # Start missing/stale processes with current mounts/config, then repair aliases before waiting.
    print('Starting services from local images (timeout: 180s).', flush=True)
    subprocess.run([*compose, 'up', '-f', args.compose_file, '--no-build', '--no-deps',
        '--no-recreate', '--detach', *services], check=True, timeout=180)
    subprocess.run(['python3', 'scripts/refresh_mocker_compose_hosts.py',
        '--mocker', args.mocker, '--apple-container', args.apple_container,
        '--compose-file', args.compose_file], check=True)
    subprocess.run([*compose, 'up', '-f', args.compose_file, '--no-build', '--no-recreate',
        '--no-deps', '--detach', '--wait', '--wait-timeout', '120', *services], check=True, timeout=180)
    subprocess.run(args.health_command, check=True)

    write_cache(state_file, {'version': 1, 'compose_fingerprint': compose_fingerprint,
                             'temporal_config_fingerprint': current_temporal_config,
                             'images': current, 'services': current_runtime})


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
            print('Startup: build changed images, reuse unchanged services, and refresh live aliases.')
            subprocess.run(args.health_command, check=True)
            return 0
        start(args)
    except subprocess.TimeoutExpired:
        print('Container startup timed out; the successful startup cache was not updated.', flush=True)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        # Subprocess commands and Compose inspect/config output can contain secrets.
        print('Container startup failed; the successful startup cache was not updated.', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
