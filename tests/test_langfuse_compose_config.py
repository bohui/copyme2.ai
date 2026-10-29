"""Keep every model-calling process connected to the same Langfuse project."""
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('mocker') is None, reason='Mocker is not installed')
@pytest.mark.parametrize('trace_url', [None, 'https://langfuse.example.test'])
def test_langfuse_configuration_reaches_api_and_workers(tmp_path, trace_url):
    compose = tmp_path / 'compose.yml'
    compose.write_text(Path('compose.yml').read_text())
    environment = dict(os.environ)
    environment.pop('MEMORY_SPARK_LANGFUSE_RUNTIME_BASE_URL', None)
    if trace_url is not None:
        environment['MEMORY_SPARK_LANGFUSE_RUNTIME_BASE_URL'] = trace_url
    environment.update(MEMORY_SPARK_LANGFUSE_PUBLIC_KEY='test-public',
                       MEMORY_SPARK_LANGFUSE_SECRET_KEY='test-secret',
                       MEMORY_SPARK_LANGFUSE_ENVIRONMENT='trace-test')
    result = subprocess.run(['mocker', 'compose', 'config', '-f', str(compose)],
                            env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    expected = {'LANGFUSE_BASE_URL': trace_url or 'http://192.168.67.1:3001',
                'LANGFUSE_PUBLIC_KEY': 'test-public', 'LANGFUSE_SECRET_KEY': 'test-secret',
                'LANGFUSE_TRACING_ENVIRONMENT': 'trace-test'}
    for service in ['api', 'worker', 'codex-worker', 'photo-worker']:
        section = re.search(rf'(?ms)^  {service}:\n(.*?)(?=^  \S|\Z)', result.stdout)
        assert section is not None
        for key, value in expected.items():
            entries = [line.strip().removeprefix('- ').strip('"')
                       for line in section[1].splitlines()
                       if line.strip().removeprefix('- ').strip('"').startswith(key + '=')]
            assert entries == [key + '=' + value], (service, key)
