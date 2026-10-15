"""Real stage extraction conflicts preserve fences without HTTP retry signals."""
import json
from pathlib import Path

import pytest

from stage_progress_fixture import save_stage_source, link_stage
from test_agent_commit_postgres import as_user
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve
from test_shared_memory_events_postgres import literal


def durable_snapshot(sql):
    tables = sql("select tablename from pg_tables where schemaname='public' order by tablename;").stdout.splitlines()
    queries = ' union all '.join(
        f"select '{table}' name, coalesce(jsonb_agg(to_jsonb(t) order by to_jsonb(t)::text),'[]') value "
        f'from public."{table}" t' for table in tables)
    return json.loads(sql(f'select jsonb_object_agg(name,value) from ({queries}) tables;').stdout)


@pytest.mark.parametrize('conflict', ['source', 'event', 'evidence'])
def test_stage_revision_conflicts_are_nonretryable_without_durable_mutation(sql, conflict):
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, 'During childhood I walked to our synthetic school.')
    event = link_stage(sql, project, source, 'childhood')
    ref = {'source_id': source['id'], 'version': source['version'], 'quote': source['text'],
           'char_start': 0, 'char_end': len(source['text'])}
    manifest = [{'id': source['id'], 'version': source['version']}]
    proposal = {'kind': 'event', 'title': 'Synthetic school', 'life_stage': 'childhood',
                'source_refs': [ref], 'stage_evidence': [ref]}
    if conflict == 'source':
        manifest[0]['version'] += 1
    elif conflict == 'event':
        revision = int(sql(f"select revision from public.user_memory_event where id='{event}';").stdout)
        proposal.update(existing_id=event, expected_revision=revision + 1)
    else:
        ref['version'] += 1
    before = durable_snapshot(sql)
    command = f"select public.apply_user_memory_events({literal(project)}," \
        f"{literal(manifest)}::jsonb,{literal([proposal])}::jsonb);"
    rejected = sql('\\set VERBOSITY verbose\n' + as_user(command), check=False)
    assert rejected.returncode != 0
    assert 'PT409' in rejected.stderr, rejected.stderr
    assert f'{conflict} revision conflict' in rejected.stderr
    assert durable_snapshot(sql) == before


def test_existing_stage_upgrade_restores_conflicts_without_changing_authority_or_data(sql):
    root = Path(__file__).resolve().parents[1]
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, 'Synthetic childhood evidence.')
    link_stage(sql, project, source, 'childhood')
    # Reproduce an installation that already applied the upstream stage DDL.
    sql((root / 'supabase/migrations/202610150003_canonical_stage_readiness.sql').read_text())
    def authority():
        return json.loads(sql("select row_to_json(a) from (select oid,proowner,proacl,prosecdef,proconfig "
                              "from pg_proc where oid='public.apply_user_memory_events_before_photos(text,jsonb,jsonb)'::regprocedure) a;").stdout)
    before, security = durable_snapshot(sql), authority()
    migration = (root / 'supabase/migrations/202610150006_stage_nonretryable_application_conflicts.sql').read_text()
    sql(migration)
    assert authority() == security
    assert durable_snapshot(sql) == before
    assert sql("select count(*) from pg_proc where oid='public.apply_user_memory_events_before_photos(text,jsonb,jsonb)'::regprocedure "
               "and prosrc ~* 'errcode\\s*=\\s*''40001''';").stdout.strip() == '0'
    definition = sql("select pg_get_functiondef('public.apply_user_memory_events_before_photos(text,jsonb,jsonb)'::regprocedure);").stdout
    sql(migration)
    assert authority() == security and durable_snapshot(sql) == before
    assert sql("select pg_get_functiondef('public.apply_user_memory_events_before_photos(text,jsonb,jsonb)'::regprocedure);").stdout == definition
