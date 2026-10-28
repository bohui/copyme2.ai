"""Exercise actual Compose interpolation without starting any services."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('mocker') is None, reason='Mocker is not installed')
@pytest.mark.parametrize('model,effort', [(None,None), ('gpt-5.6-sol','medium')])
def test_composer_settings_reach_all_three_processes_without_hardcoded_defaults(tmp_path, model, effort):
    compose = tmp_path / 'compose.yml'
    compose.write_text(Path('compose.yml').read_text())
    environment = dict(os.environ)
    for key, value in [('MEMOIR_COMPOSER_MODEL',model), ('MEMOIR_COMPOSER_REASONING_EFFORT',effort)]:
        environment.pop(key,None)
        if value is not None:
            environment[key] = value
    environment['MEMORY_SPARK_MEMOIR_COMPOSER_MODEL'] = 'memoir-luna-low'
    environment['MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT'] = 'low'
    environment['MEMORY_SPARK_LLM_MODEL'] = 'configured-shared-model'
    environment['MEMORY_SPARK_LLM_REASONING_EFFORT'] = 'high'
    environment['MEMOIR_GAME_MODEL'] = 'configured-game-model'
    environment['MEMOIR_GAME_REASONING_EFFORT'] = 'medium'
    result = subprocess.run(['mocker','compose','config','-f',str(compose)],
        env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    for key, value, count in [('MEMOIR_COMPOSER_MODEL',model or '',3),
            ('MEMOIR_COMPOSER_REASONING_EFFORT',effort or '',3),
            ('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL','memoir-luna-low',4),
            ('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT','low',4),
            ('MEMORY_SPARK_LLM_MODEL','configured-shared-model',4),
            ('MEMORY_SPARK_LLM_REASONING_EFFORT','high',4),
            ('MEMOIR_GAME_MODEL','configured-game-model',2),
            ('MEMOIR_GAME_REASONING_EFFORT','medium',2)]:
        entries = [line.strip().removeprefix('- ').strip('"') for line in result.stdout.splitlines()
            if line.strip().removeprefix('- ').strip('"').startswith(key + '=')]
        assert entries == [key + '=' + value] * count
