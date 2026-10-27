"""Exercise the real Make startup path without starting containers."""
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEMPORAL_IMAGE = 'temporalio/temporal@sha256:' + 'b' * 64


@pytest.fixture
def stack(tmp_path):
    (tmp_path / 'scripts').mkdir()
    shutil.copy(ROOT / 'Makefile', tmp_path / 'Makefile')
    for name in ('start_container_stack.py',):
        if (ROOT / 'scripts' / name).exists():
            shutil.copy(ROOT / 'scripts' / name, tmp_path / 'scripts' / name)
    # This fixture has no live backend and must not acquire the machine's lock.
    (tmp_path / 'scripts/backend_operation_lock.py').write_text(
        'import subprocess,sys\nraise SystemExit(subprocess.call(sys.argv[2:]))\n')
    (tmp_path / 'scripts/refresh_mocker_compose_hosts.py').write_text(
        'import json\nfrom pathlib import Path\n'
        'with Path("commands.jsonl").open("a") as f:\n'
        ' f.write(json.dumps(["refresh-aliases"]) + "\\n")\n')
    for name in ('Containerfile', 'codex-worker/Containerfile', 'apps/web/Containerfile',
                 'pyproject.toml', 'apps/api/main.py', 'skills/example/SKILL.md',
                 'apps/web/app/page.tsx', 'compose.yml'):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(name)
    (tmp_path / '.dockerignore').write_text('__pycache__\n*.py[cod]\nnode_modules\n**/node_modules\n**/.next\n')
    (tmp_path / 'apps/web/.dockerignore').write_text('node_modules\n.next\n')
    (tmp_path / 'compose.yml').write_text(f'''name: memory-spark
services:
  api:
    build:
      context: .
      dockerfile: Containerfile
      target: runtime
    environment:
      MEMORY_SPARK_MODE: demo
  codex-worker:
    build:
      context: .
      dockerfile: codex-worker/Containerfile
      target: runtime
  web:
    build:
      context: ./apps/web
      dockerfile: Containerfile
      args:
        MEMORY_SPARK_API_ORIGIN: http://api:8000
  temporal:
    image: {TEMPORAL_IMAGE}
''')
    command = tmp_path / 'mocker'
    command.write_text(f'''#!{sys.executable}
import hashlib, json, os, sys
from pathlib import Path
p = Path(__file__).parent
args = sys.argv[1:]
with (p / 'commands.jsonl').open('a') as f:
    f.write(json.dumps(args) + '\\n')
images_file = p / 'images.json'
images = json.loads(images_file.read_text()) if images_file.exists() else {{}}
containers_file = p / 'containers.json'
containers = json.loads(containers_file.read_text()) if containers_file.exists() else {{}}
tags = {{'api': 'localhost/memory-spark:dev', 'codex-worker': 'localhost/memory-spark-codex-worker:dev', 'web': 'localhost/copyme2-web:dev'}}
external_image = {TEMPORAL_IMAGE!r}
if args[:2] == ['compose', 'config']:
    compose_path = p / args[3] if len(args) > 3 and args[2] == '-f' else p / 'compose.yml'
    config_inputs = compose_path.read_bytes() + repr(sorted(
        (key, value) for key, value in os.environ.items()
        if key.startswith(('MEMOIR_', 'MEMORY_SPARK_', 'SUPABASE_')))).encode()
    print('services:')
    for service, tag in {{**tags, 'temporal': external_image}}.items():
        print('  ' + service + ':\\n    image: ' + tag)
    print('    environment:\\n      - SECRET=synthetic-do-not-print')
    print('    config-fingerprint: ' + hashlib.sha256(config_inputs).hexdigest())
if args[:2] == ['image', 'inspect']:
    if args[2] not in images: sys.exit(1)
    print(images[args[2]])
if args[:2] == ['image', 'pull']:
    if (p / 'fail-pull').exists(): sys.exit(12)
    images[args[-1]] = 'sha256:' + 'b' * 64
    images_file.write_text(json.dumps(images))
if args[:2] == ['compose', 'build']:
    if (p / 'fail-build').exists(): sys.exit(8)
    services = [a for a in args[2:] if a in tags] or list(tags) + ['api', 'api']
    for service in services:
        tag = tags[service]
        version = int(images.get(tag, 'sha256:' + '0' * 64)[7:], 16) + 1
        images[tag] = 'sha256:' + format(version, '064x')
    images_file.write_text(json.dumps(images))
if args[:2] == ['compose', 'up']:
    if external_image not in images: sys.exit(11)
    if (p / 'fail-up').exists(): sys.exit(9)
    for service in ['api', 'worker', 'photo-worker', 'codex-worker', 'web', 'temporal']:
        if service in args:
            mounts = [{{'destination': '/app/apps/api', 'source': str(p / 'apps/api')}}] if service not in ['web', 'temporal'] else []
            containers.setdefault('memory-spark-' + service + '-1', mounts)
    containers_file.write_text(json.dumps(containers))
if args[:2] == ['compose', 'ps']:
    if (p / 'fail-inventory').exists(): sys.exit(10)
    print('\\n'.join('memory-spark-' + a + '-1' for a in args[2:] if 'memory-spark-' + a + '-1' in containers))
if args[:1] == ['inspect']:
    if (p / 'fail-inspect').exists(): sys.exit(10)
    print(json.dumps([{{'id': args[1], 'configuration': {{'mounts': containers[args[1]]}}}}]))
if args[:1] == ['rm']:
    for container in args[2:]: containers.pop(container, None)
    containers_file.write_text(json.dumps(containers))
''')
    command.chmod(0o700)
    overrides = tmp_path / 'overrides.mk'
    overrides.write_text('''check runtime-start _validate-skills:
\t@true
container-health:
\t@test ! -f fail-health
''')

    def up(*options, success=True):
        result = subprocess.run(['make', '-f', 'Makefile', '-f', 'overrides.mk', 'up',
            'MAKE=make -f Makefile -f overrides.mk',
            f'MOCKER={command}', f'APPLE_CONTAINER_BIN={command}', *options], cwd=tmp_path, capture_output=True, text=True)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result

    def calls():
        file = tmp_path / 'commands.jsonl'
        commands = [json.loads(v) for v in file.read_text().splitlines()] if file.exists() else []
        file.unlink(missing_ok=True)
        return commands

    return tmp_path, up, calls


def builds(commands):
    return [c for c in commands if c[:2] == ['compose', 'build']]


def recreates(commands):
    return [c for c in commands if c[:1] == ['rm']]


def test_missing_external_image_is_pulled_once_before_building_or_recreating(stack):
    _, up, calls = stack
    result = up()
    commands = calls()
    pull = ['image', 'pull', '--platform', 'linux/arm64', '--progress', 'plain', TEMPORAL_IMAGE]
    assert [c for c in commands if c[:2] == ['image', 'pull']] == [pull]
    assert commands.index(pull) < commands.index(builds(commands)[0])
    assert 'synthetic-do-not-print' not in result.stdout + result.stderr
    up()
    assert not any(c[:2] == ['image', 'pull'] for c in calls())


def test_failed_external_pull_preserves_running_containers_and_startup_cache(stack):
    root, up, calls = stack
    up()
    calls()
    containers = (root / 'containers.json').read_bytes()
    cache = (root / 'var/container-startup.json').read_bytes()
    images_file = root / 'images.json'
    images = json.loads(images_file.read_text())
    del images[TEMPORAL_IMAGE]
    images_file.write_text(json.dumps(images))
    (root / 'fail-pull').touch()

    up(success=False)

    commands = calls()
    assert any(c[:2] == ['image', 'pull'] for c in commands)
    assert not builds(commands) and not recreates(commands)
    assert not any(c[:2] == ['compose', 'up'] for c in commands)
    assert (root / 'containers.json').read_bytes() == containers
    assert (root / 'var/container-startup.json').read_bytes() == cache


@pytest.mark.parametrize('phase,seconds', [('pull', 300), ('start', 180)])
def test_startup_timeouts_are_bounded_and_do_not_expose_captured_output(stack, monkeypatch, capsys, phase, seconds):
    from scripts import start_container_stack as startup

    root, _, calls = stack
    command = str(root / 'mocker')
    run = subprocess.run

    def timeout_command(args, **kwargs):
        prefix = [command, 'image', 'pull'] if phase == 'pull' else [command, 'compose', 'up']
        if args[:3] == prefix:
            assert kwargs['timeout'] == seconds
            raise subprocess.TimeoutExpired(args, seconds, output='synthetic-do-not-print')
        return run(args, **kwargs)

    monkeypatch.chdir(root)
    monkeypatch.setenv('MAKEFLAGS', '')
    monkeypatch.setattr(sys, 'argv', ['start_container_stack.py', '--mocker', command,
        '--apple-container', command, '--', 'true'])
    monkeypatch.setattr(startup.subprocess, 'run', timeout_command)

    assert startup.main() == 1
    output = capsys.readouterr()
    assert 'timed out' in output.out
    assert 'synthetic-do-not-print' not in output.out + output.err
    if phase == 'pull':
        assert not builds(calls())
    assert not (root / 'containers.json').exists()
    assert not (root / 'var/container-startup.json').exists()


@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('env_kind', ['default', 'relative_spaced', 'absolute_spaced'])
def test_up_resolves_publication_database_before_starting_services(stack, explicit, env_kind):
    root, up, _ = stack
    database = 'postgresql://synthetic.invalid/application'
    publication = 'postgresql://synthetic.invalid/publication' if explicit else database
    filename = '.env' if env_kind == 'default' else 'settings/test env.conf'
    config = root / filename
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text('SUPABASE_DB_URL=' + database + '\n'
        + ('MEMOIR_PUBLICATION_DATABASE_URL=' + publication + '\n' if explicit else ''))
    with (root / 'overrides.mk').open('a') as file:
        file.write('\ncontainer-health:\n\t@python3 -c '
            + shlex.quote('import os; assert os.environ["MEMOIR_PUBLICATION_DATABASE_URL"] == ' + repr(publication))
            + '\n')
    up(*([] if env_kind == 'default' else ['ENV_FILE=' + (str(config) if env_kind == 'absolute_spaced' else filename)]))


def test_environment_change_restarts_app_services_without_restarting_temporal(stack):
    root, up, calls = stack
    up()
    calls()
    (root / '.env').write_text('MEMORY_SPARK_MODE=connected\n')

    up('ENV_FILE=.env')

    commands = calls()
    assert not builds(commands)
    assert recreates(commands) == [['rm', '-f', *[
        'memory-spark-' + service + '-1'
        for service in ('api', 'worker', 'web', 'codex-worker', 'photo-worker')]]]


def test_repeat_up_skips_builds_and_reuses_every_service(stack):
    _, up, calls = stack
    up()
    first = calls()
    assert builds(first) == [['compose', 'build', '-f', 'compose.yml', 'api', 'codex-worker', 'web']]
    assert not any(c[:2] == ['compose', 'down'] for c in first)
    up()
    repeated = calls()
    assert not builds(repeated)
    assert not recreates(repeated)
    start = next(i for i, c in enumerate(repeated) if c[:2] == ['compose', 'up'] and '--wait' not in c)
    refresh = repeated.index(['refresh-aliases'])
    ready = next(i for i, c in enumerate(repeated) if '--wait' in c)
    assert start < refresh < ready
    assert all('--no-recreate' in c for c in repeated if c[:2] == ['compose', 'up'])
    assert not any('--volumes' in c or c[:2] == ['compose', 'down'] for c in repeated)


def test_up_creates_story_game_object_mount_source(stack):
    root, up, _ = stack
    mount_source = root / 'var/memory-spark/objects/story-game-scenes'
    assert not mount_source.exists()

    up()

    assert mount_source.is_dir()


def test_up_restores_current_checkout_after_another_worktree_takes_over(stack):
    root, up, calls = stack
    up()
    calls()
    file = root / 'containers.json'
    containers = json.loads(file.read_text())
    foreign = ['memory-spark-' + service + '-1' for service in ('api', 'worker', 'photo-worker', 'codex-worker')]
    for container in foreign:
        containers[container][0]['source'] = str(root / 'other-worktree/apps/api')
    file.write_text(json.dumps(containers))

    up()

    commands = calls()
    assert not builds(commands)
    assert len(recreates(commands)) == 1
    assert set(recreates(commands)[0][2:]) == set(containers) - {'memory-spark-temporal-1'}
    restored = json.loads(file.read_text())
    assert all(restored[container][0]['source'] == str(root / 'apps/api') for container in foreign)
    up()
    assert not recreates(calls())


def test_failed_inventory_leaves_containers_and_cache_untouched(stack):
    root, up, calls = stack
    up()
    calls()
    containers = (root / 'containers.json').read_bytes()
    cache = (root / 'var/container-startup.json').read_bytes()
    (root / 'fail-inventory').touch()
    up(success=False)
    assert (root / 'containers.json').read_bytes() == containers
    assert (root / 'var/container-startup.json').read_bytes() == cache
    assert not recreates(calls())


@pytest.mark.parametrize('path,services', [
    ('apps/api/main.py', []),
    ('skills/example/SKILL.md', []),
    ('apps/web/app/page.tsx', ['web']),
    ('pyproject.toml', ['api', 'codex-worker']),
])
def test_changed_inputs_rebuild_and_restart_only_affected_services(stack, path, services):
    root, up, calls = stack
    up()
    calls()
    (root / path).write_text('changed')
    up()
    changed = calls()
    assert builds(changed) == ([['compose', 'build', '-f', 'compose.yml', *services]] if services else [])
    recreated = recreates(changed)
    expected_services = ({'web'} if services == ['web'] else
                         {'api', 'worker', 'photo-worker', 'codex-worker'})
    assert len(recreated) == (1 if expected_services else 0)
    if expected_services:
        assert set(recreated[0][2:]) == {'memory-spark-' + s + '-1' for s in expected_services}
    up()
    assert not builds(calls())


def test_dependency_change_invalidates_image_but_generated_cache_does_not(stack):
    root, up, calls = stack
    up()
    calls()
    generated = root / 'apps/api/__pycache__/main.pyc'
    generated.parent.mkdir()
    generated.write_bytes(b'cache')
    up()
    assert not builds(calls())
    (root / 'pyproject.toml').write_text('changed dependencies')
    up()
    assert builds(calls())[0][-2:] == ['api', 'codex-worker']


def test_missing_image_and_explicit_rebuild_refresh_images(stack):
    root, up, calls = stack
    up()
    calls()
    file = root / 'images.json'
    images = json.loads(file.read_text())
    del images['localhost/copyme2-web:dev']
    file.write_text(json.dumps(images))
    up()
    assert builds(calls())[0][-1:] == ['web']
    up('CONTAINER_REBUILD=1')
    assert builds(calls())[0][-3:] == ['api', 'codex-worker', 'web']


@pytest.mark.parametrize('failure', ['fail-build', 'fail-up', 'fail-health'])
def test_failed_startup_does_not_record_success(stack, failure):
    root, up, calls = stack
    up()
    calls()
    (root / 'apps/web/app/page.tsx').write_text('changed')
    (root / failure).touch()
    up(success=False)
    calls()
    (root / failure).unlink()
    up()
    expected_build = [['compose', 'build', '-f', 'compose.yml', 'web']] if failure == 'fail-build' else []
    assert builds(calls()) == expected_build


def test_changed_build_argument_invalidates_codex_image(stack):
    _, up, calls = stack
    up('MEMORY_SPARK_CODEX_VERSION=1.0')
    calls()
    up('MEMORY_SPARK_CODEX_VERSION=1.1')
    assert builds(calls())[0][-1:] == ['codex-worker']


def test_copy_inputs_are_covered_by_image_fingerprints():
    from scripts.start_container_stack import IMAGES

    for name, image in IMAGES.items():
        containerfile = ROOT / ('apps/web/Containerfile' if name == 'web' else image['inputs'][0])
        for line in containerfile.read_text().splitlines():
            if line == 'FROM runtime AS app':
                break  # Local Compose builds the runtime target; application code is mounted.
            if line.startswith('COPY ') and '--from=' not in line:
                for source in shlex.split(line)[1:-1]:
                    if source.startswith('--'):
                        continue
                    path = Path(image['context']) / source
                    assert any(path == Path(v) or Path(v) in path.parents for v in image['inputs']), (name, source)


def test_replaced_image_and_invalid_cache_are_rebuilt(stack):
    root, up, calls = stack
    up()
    calls()
    file = root / 'images.json'
    images = json.loads(file.read_text())
    images['localhost/copyme2-web:dev'] = 'sha256:' + 'a' * 64
    file.write_text(json.dumps(images))
    up()
    assert builds(calls())[0][-1:] == ['web']
    (root / 'var/container-startup.json').write_text('{"version":1,"images":[]}')
    (root / 'var/container-build.json').unlink()
    up()
    assert builds(calls())[0][-3:] == ['api', 'codex-worker', 'web']


def test_make_dry_run_never_builds_or_changes_containers(stack):
    root, up, calls = stack
    up('-n')
    assert calls() == []
    assert not (root / 'images.json').exists()
    assert not (root / 'var/container-startup.json').exists()


def test_runtime_settings_do_not_rebuild_images_but_build_settings_do(stack):
    root, up, calls = stack
    up()
    calls()
    compose = root / 'compose.yml'
    compose.write_text(compose.read_text().replace('MEMORY_SPARK_MODE: demo', 'MEMORY_SPARK_MODE: connected'))
    up()
    assert not builds(calls())
    compose.write_text(compose.read_text().replace('http://api:8000', 'http://api:9000'))
    up()
    assert builds(calls()) == [['compose', 'build', '-f', 'compose.yml', 'web']]
