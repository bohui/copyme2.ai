"""Exercise Mocker's actual interpolation and YAML parsing without containers."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('mocker') is None, reason='Mocker is not installed')
@pytest.mark.parametrize('model,effort', [(None, None), ('', ''), ('memoir-luna-low', 'low')])
def test_collector_compose_preserves_empty_defaults_and_explicit_overrides(tmp_path, model, effort):
    compose = tmp_path / 'compose.yml'
    compose.write_text(Path('compose.yml').read_text(encoding='utf-8'), encoding='utf-8')
    environment = dict(os.environ)
    expected = {}
    for suffix, value in [('MODEL', model), ('REASONING_EFFORT', effort)]:
        key = 'MEMORY_SPARK_COLLECTOR_' + suffix
        environment.pop(key, None)
        if value is not None:
            environment[key] = value
        expected[key] = value or ''
    result = subprocess.run(
        ['mocker', 'compose', 'config', '-f', str(compose)],
        env=environment, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    # Inspect only these safe fields: full Compose output can contain credentials.
    for key, value in expected.items():
        entries = [line.strip().removeprefix('- ').strip('"')
                   for line in result.stdout.splitlines()
                   if line.strip().removeprefix('- ').strip('"').startswith(key + '=')]
        assert entries == [key + '=' + value] * 3  # API, Codex worker and checkpoint worker.
