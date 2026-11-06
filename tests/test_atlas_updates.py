import asyncio
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlencode

import psycopg
import pytest

from apps.api.atlas_updates import AtlasUpdates
from test_agent_commit_postgres import OWNER, OTHER
from test_lifetime_memory_reads import sql
from test_lifetime_memory_publication import database, event_database, private_database, attachment_database


@pytest.mark.parametrize('repair', [False, True], ids=['fresh-baseline', 'recorded-baseline'])
def test_atlas_stream_delivers_committed_changes_only_to_the_owning_project(sql, repair):
    sql(f"""insert into public.user_memoir_project(user_id,project_id)
        values ('{OWNER}','atlas-project'),('{OWNER}','other-project'),('{OTHER}','atlas-project');""")

    if repair:
        if not shutil.which('supabase'):
            pytest.skip('Supabase CLI required to exercise make migrate')
        sql("""create schema supabase_migrations;
            create table supabase_migrations.schema_migrations (version text primary key, statements text[], name text);
            insert into supabase_migrations.schema_migrations(version) values ('202610180001');
            drop function public.notify_memoir_atlas_update() cascade;""")
        params = psycopg.conninfo.conninfo_to_dict(sql.publication_dsn)
        dsn = 'postgresql:///' + params.pop('dbname') + '?' + urlencode({**params, 'sslmode':'disable'})
        root = Path(__file__).resolve().parents[1]
        for status in ('installed', 'already installed'):
            result = subprocess.run(['make', 'migrate', 'ENV_FILE=/dev/null'], cwd=root,
                env={**sql.env, 'SUPABASE_DB_URL': dsn, 'PGSSLMODE': 'disable'}, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stdout + result.stderr
            assert f'Atlas notifications {status}.' in result.stdout
        assert sql("""select count(*) from pg_trigger
                      where tgfoid='public.notify_memoir_atlas_update()'::regprocedure
                        and tgenabled='O';""").stdout.strip() == '4'
        assert sql('select count(*) from public.user_memoir_project;').stdout.strip() == '3'
        assert sql('select version from supabase_migrations.schema_migrations;').stdout.strip() == '202610180001'

    async def scenario():
        feed = AtlasUpdates()
        connection = await psycopg.AsyncConnection.connect(sql.publication_dsn)
        streams = [feed.events(sql.publication_dsn, owner, project, expires_in=5, heartbeat=0.1)
                   for owner, project in [(OWNER, 'atlas-project'), (OWNER, 'other-project'), (OTHER, 'atlas-project')]]
        watched, *unrelated = streams
        statement = '''update public.user_memoir_project set event_sequence=event_sequence+1
                       where user_id=%s and project_id='atlas-project' '''
        try:
            for stream in streams:
                while not await anext(stream):
                    pass
            await connection.execute(statement, (OWNER,))
            assert not await anext(watched)
            await connection.rollback()
            assert not await anext(watched)
            await connection.execute(statement, (OWNER,))
            await connection.commit()
            assert await anext(watched)
            for stream in unrelated:
                assert not await anext(stream)
        finally:
            for stream in streams:
                await stream.aclose()
            await feed.close()
            await connection.close()

    asyncio.run(scenario())
