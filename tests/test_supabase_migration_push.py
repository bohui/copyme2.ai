"""Exercise the migration runner's statement splitter on disposable PostgreSQL."""
from pathlib import Path
import json
import shutil
import subprocess
import time

import pytest

from test_agent_commit_postgres import database


ROOT = Path(__file__).resolve().parents[1]


def test_supabase_cli_pushes_and_tracks_the_fresh_baseline_once(tmp_path):
    cli = shutil.which('supabase')
    if cli is None:
        pytest.skip('Supabase CLI required to exercise its SQL statement splitter')
    fixture = database.__wrapped__(apply_schema=False, deadline=time.monotonic() + 120, tcp=True)
    try:
        sql = next(fixture)
        sql('create role supabase_admin; alter schema auth owner to supabase_admin; '
            'alter schema storage owner to supabase_admin;')
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
        assert len(paths) == 1
        for path in paths:
            shutil.copy2(path, migrations / path.name)
        for _ in range(2):
            result = subprocess.run(command, capture_output=True, text=True,
                env={**sql.env, 'PGSSLMODE': 'disable'}, timeout=60)
            if result.returncode != 0:
                pytest.fail('\n'.join(line.rstrip()[:300] for line in
                    (result.stdout + result.stderr).splitlines()[:25]))
        expected = [path.name.split('_', 1)[0] for path in sorted(migrations.glob('*.sql'))]
        assert sql('select version from supabase_migrations.schema_migrations order by version;').stdout.splitlines() == expected
        # Remote resets preserve Supabase-owned Storage bucket metadata.
        reset = [cli, 'db', 'reset', '--workdir', str(tmp_path), '--db-url',
                 f'postgresql://postgres@{host}:{port}/postgres?sslmode=disable', '--no-seed', '--yes']
        result = subprocess.run(reset, capture_output=True, text=True,
            env={**sql.env, 'PGSSLMODE': 'disable'}, timeout=60)
        if result.returncode != 0:
            pytest.fail('\n'.join(line.rstrip()[:300] for line in
                (result.stdout + result.stderr).splitlines()[:25]))
        assert sql('select count(*) from storage.buckets;').stdout.strip() == '2'
        assert sql('select version from supabase_migrations.schema_migrations order by version;').stdout.splitlines() == expected
    finally:
        fixture.close()
