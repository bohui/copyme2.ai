"""Exercise the migration runner's statement splitter on disposable PostgreSQL."""
from pathlib import Path
import json
import shutil
import subprocess
import time

import pytest

from test_agent_commit_postgres import database


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('resume_policy', [False, True], ids=['fresh', 'resume-policy'])
def test_supabase_cli_pushes_the_tracked_migration_chain(tmp_path, resume_policy):
    cli = shutil.which('supabase')
    if cli is None:
        pytest.skip('Supabase CLI required to exercise its SQL statement splitter')
    fixture = database.__wrapped__(legacy_schema=False, deadline=time.monotonic() + 120, tcp=True)
    try:
        sql = next(fixture)
        sql('create role service_role bypassrls; alter table storage.objects add column owner_id text;')
        migrations = tmp_path / 'supabase' / 'migrations'
        migrations.mkdir(parents=True)
        if sql.command[0] == 'container':
            name = sql.command[sql.command.index('--interactive') + 1]
            inspected = subprocess.run(['container', 'inspect', name],
                capture_output=True, text=True, check=True, timeout=10)
            container = json.loads(inspected.stdout)[0]
            host = container['status']['networks'][0]['ipv4Address'].split('/')[0]
            port = '5432'
        else:
            host = '127.0.0.1'
            port = sql.command[sql.command.index('-p') + 1]
        command = [
            cli, 'db', 'push', '--workdir', str(tmp_path),
            '--db-url', f'postgresql://postgres@{host}:{port}/postgres?sslmode=disable',
            '--yes',
        ]
        paths = sorted((ROOT / 'supabase' / 'migrations').glob('*.sql'))
        batches = [paths]
        if resume_policy:
            # Match a database where everything preceding the failing migration
            # has already been applied and recorded by the CLI.
            batches = [[path for path in paths if path.name < '202610120027'],
                       [path for path in paths if path.name >= '202610120027']]
        for batch in batches:
            for path in batch:
                shutil.copy2(path, migrations / path.name)
            result = subprocess.run(command, capture_output=True, text=True,
                env={**sql.env, 'PGSSLMODE': 'disable'}, timeout=60)
            assert result.returncode == 0, result.stdout + result.stderr
        expected = [path.name.split('_', 1)[0] for path in sorted(migrations.glob('*.sql'))]
        assert sql('select version from supabase_migrations.schema_migrations order by version;').stdout.splitlines() == expected
    finally:
        fixture.close()
