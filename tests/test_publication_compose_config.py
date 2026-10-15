"""Validate publication DSN interpolation through the actual Compose parser."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('mocker') is None, reason='Mocker is not installed')
@pytest.mark.parametrize('database,publication,expected', [
    ('postgresql://synthetic.invalid/application', None, ''),
    ('postgresql://synthetic.invalid/application', 'postgresql://synthetic.invalid/publication', 'postgresql://synthetic.invalid/publication'),
    (None, None, ''),
])
def test_publication_connection_preserves_explicit_and_empty_values(tmp_path, database, publication, expected):
    compose = tmp_path / 'compose.yml'
    compose.write_text(Path('compose.yml').read_text())
    if database:
        (tmp_path / '.env').write_text('SUPABASE_DB_URL=' + database + '\n')
    environment = dict(os.environ)
    for name in ['MEMOIR_PUBLICATION_DATABASE_URL', 'SUPABASE_DB_URL']:
        environment.pop(name, None)
    if publication is not None:
        environment['MEMOIR_PUBLICATION_DATABASE_URL'] = publication
    result = subprocess.run(['mocker', 'compose', 'config', '-f', str(compose)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    key = 'MEMOIR_PUBLICATION_DATABASE_URL='
    values = [line.strip().removeprefix('- ').strip('"')
        for line in result.stdout.splitlines()
        if line.strip().removeprefix('- ').strip('"').startswith(key)]
    assert values == [key + expected] * 3  # API, Codex worker, task worker.
