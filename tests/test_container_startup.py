"""Exercise the real Make startup path without starting containers."""
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


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
    (tmp_path / 'scripts/refresh_mocker_compose_hosts.py').write_text('')
    for name in ('Containerfile', 'codex-worker/Containerfile', 'apps/web/Containerfile',
                 'pyproject.toml', 'apps/api/main.py', 'skills/example/SKILL.md',
                 'apps/web/app/page.tsx', 'compose.yml'):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(name)
    (tmp_path / '.dockerignore').write_text('__pycache__\n*.py[cod]\nnode_modules\n**/node_modules\n**/.next\n')
    (tmp_path / 'apps/web/.dockerignore').write_text('node_modules\n.next\n')
    command = tmp_path / 'mocker'
    command.write_text(f'''#!{sys.executable}
import json, sys
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
if args[:2] == ['image', 'inspect']:
    if args[2] not in images: sys.exit(1)
    print(images[args[2]])
if args[:2] == ['compose', 'build']:
    if (p / 'fail-build').exists(): sys.exit(8)
    services = [a for a in args[2:] if a in tags] or list(tags) + ['api', 'api']
    for service in services:
        tag = tags[service]
        version = int(images.get(tag, 'sha256:' + '0' * 64)[7:], 16) + 1
        images[tag] = 'sha256:' + format(version, '064x')
    images_file.write_text(json.dumps(images))
if args[:2] == ['compose', 'up']:
    if (p / 'fail-up').exists(): sys.exit(9)
    for service in ['api', 'worker', 'photo-worker', 'codex-worker', 'web', 'temporal']:
        if service in args:
            mounts = [{{'destination': '/app/apps/api', 'source': str(p / 'apps/api')}}] if service not in ['web', 'temporal'] else []
            containers.setdefault('memory-spark-' + service + '-1', mounts)
    containers_file.write_text(json.dumps(containers))
if args[:2] == ['compose', 'ps']:
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


def test_repeat_up_skips_builds_and_keeps_unchanged_containers(stack):
    _, up, calls = stack
    up()
    first = calls()
    assert builds(first) == [['compose', 'build', '-f', 'compose.yml', 'api', 'codex-worker', 'web']]
    assert not any(c[:2] == ['compose', 'down'] for c in first)
    assert all('memory-spark-temporal-1' not in c for c in recreates(first))
    up()
    repeated = calls()
    assert not builds(repeated)
    assert not recreates(repeated)
    assert any('--wait' in c for c in repeated)


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
    assert recreates(commands) == [['rm', '-f', *foreign]]
    restored = json.loads(file.read_text())
    assert all(restored[container][0]['source'] == str(root / 'apps/api') for container in foreign)
    up()
    assert not recreates(calls())


def test_failed_live_inspection_leaves_containers_and_cache_untouched(stack):
    root, up, calls = stack
    up()
    calls()
    containers = (root / 'containers.json').read_bytes()
    cache = (root / 'var/container-startup.json').read_bytes()
    (root / 'fail-inspect').touch()
    up(success=False)
    assert (root / 'containers.json').read_bytes() == containers
    assert (root / 'var/container-startup.json').read_bytes() == cache
    assert not recreates(calls())


@pytest.mark.parametrize('path,services', [
    ('apps/api/main.py', ['api', 'codex-worker']),
    ('skills/example/SKILL.md', ['api', 'codex-worker']),
    ('apps/web/app/page.tsx', ['web']),
    ('pyproject.toml', ['api', 'codex-worker']),
])
def test_changed_inputs_rebuild_only_affected_images(stack, path, services):
    root, up, calls = stack
    up()
    calls()
    (root / path).write_text('changed')
    up()
    changed = calls()
    assert builds(changed) == [['compose', 'build', '-f', 'compose.yml', *services]]
    recreated = recreates(changed)
    assert len(recreated) == 1
    assert 'memory-spark-temporal-1' not in recreated[0]
    if 'api' in services:
        assert all('memory-spark-' + s + '-1' in recreated[0] for s in ('api', 'worker', 'photo-worker'))
    up()
    assert not builds(calls())


def test_deleted_input_invalidates_image_but_generated_cache_does_not(stack):
    root, up, calls = stack
    up()
    calls()
    generated = root / 'apps/api/__pycache__/main.pyc'
    generated.parent.mkdir()
    generated.write_bytes(b'cache')
    up()
    assert not builds(calls())
    (root / 'apps/api/main.py').unlink()
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
    assert builds(calls())[0][-1:] == ['web']


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
    up()
    assert builds(calls())[0][-3:] == ['api', 'codex-worker', 'web']


def test_make_dry_run_never_builds_or_changes_containers(stack):
    root, up, calls = stack
    up('-n')
    assert calls() == []
    assert not (root / 'images.json').exists()
    assert not (root / 'var/container-startup.json').exists()
