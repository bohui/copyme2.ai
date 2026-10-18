"""Fresh schema, grants, transaction boundaries and query plans on real PostgreSQL."""
import json
from pathlib import Path
import re

from test_agent_commit_postgres import database, as_user, OWNER, OTHER


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'supabase/migrations/202610180001_initial_schema.sql'
RETIRED_TABLES = (
    'user_conversation_phase_archive', 'user_lifetime_legacy_draft_snapshot',
    'user_lifetime_legacy_draft_cursor', 'user_memoir_section_revision',
    'user_memory_event_alias', 'user_narrator_source_alias', 'user_memoir_manuscript',
    'story_entitlements', 'place_photo_searches',
)


def test_one_fresh_baseline_has_no_upgrade_or_backfill_statements():
    migrations = sorted(BASELINE.parent.glob('*.sql'))
    assert migrations[0] == BASELINE
    assert [path for path in migrations if path.name.endswith('_initial_schema.sql')] == [BASELINE]
    assert not (ROOT / 'supabase/legacy-migrations').exists()
    sql = re.sub(r'\$([a-zA-Z_0-9]*)\$.*?\$\1\$', '', BASELINE.read_text(), flags=re.S)
    sql = re.sub(r'--[^\n]*', '', sql)
    assert not re.search(r'(?:^|;)\s*(?:update|delete|drop)\b', sql, flags=re.I)
    assert not re.search(r'\balter\s+(?:table|function).*\brename\b', sql, flags=re.I)
    assert sql.strip().lower().startswith('begin;')
    assert sql.strip().lower().endswith('commit;')


def test_removed_storage_and_imports_are_absent(database):
    for table in RETIRED_TABLES:
        assert database(f"select to_regclass('public.{table}') is null;").stdout.strip() == 't'
    for name in ('import_user_legacy_memoir', 'import_legacy_memory_events',
                 'migrate_user_memory_events', 'migrate_user_memoir_index',
                 'read_lifetime_legacy_draft_head', 'read_lifetime_legacy_draft_page',
                 'finish_memoir_composer', 'finish_memoir_timeline'):
        assert database(f"select count(*) from pg_proc where pronamespace='public'::regnamespace "
                        f"and proname='{name}';").stdout.strip() == '0'
    columns = database("select column_name from information_schema.columns "
                       "where table_schema='public' and table_name='user_memoir_edition';").stdout.splitlines()
    assert {'revision', 'covered_round', 'completed_milestone', 'human_locked'} <= set(columns)
    assert not {'bundle', 'proposal', 'reuse', 'eligible'} & set(columns)


def test_every_foreign_key_has_an_index_on_its_referencing_columns(database):
    missing = database("""
      select c.relname || ':' || k.conname
      from pg_constraint k join pg_class c on c.oid=k.conrelid
      where k.contype='f' and c.relnamespace='public'::regnamespace
        and not exists (
          select 1 from pg_index i where i.indrelid=k.conrelid and i.indisvalid
            and i.indpred is null
            and (i.indkey::smallint[])[0:cardinality(k.conkey)-1] @> k.conkey
        );
    """).stdout.strip()
    assert missing == ''


def test_all_function_definitions_validate_with_their_final_dependencies(database):
    definitions = json.loads(database("select jsonb_agg(pg_get_functiondef(oid)) from pg_proc "
        "where pronamespace='public'::regnamespace and prokind='f';").stdout)
    database('set check_function_bodies=true;\n' + ';\n'.join(definitions) + ';')


def test_data_reset_covers_all_application_tables_and_preserves_global_configuration(database):
    from scripts.truncate_local_data import APP_TABLES, PRESERVED_TABLES
    tables = set(database("select 'public.' || tablename from pg_tables where schemaname='public';").stdout.splitlines())
    assert set(APP_TABLES) | set(PRESERVED_TABLES) == tables
    assert not set(APP_TABLES) & set(PRESERVED_TABLES)


def test_worker_polling_ignores_unmapped_receipts_and_lanes(database):
    database(f"""
      insert into public.user_memoir_project(user_id,project_id)
        values ('{OWNER}','canonical'),('{OWNER}','unmapped');
      insert into public.user_lifetime_conversation(user_id,project_id) values ('{OWNER}','canonical');
      insert into public.user_private_draft_outbox(user_id,project_id,change_kind)
        values ('{OWNER}','unmapped','accepted'),('{OWNER}','canonical','accepted');
      insert into public.user_memoir_lane(user_id,project_id,skill,pending)
        values ('{OWNER}','unmapped','timeline',true),('{OWNER}','canonical','timeline',true);
    """)
    try:
        for function, table in (('pending_memoir_receipts', 'user_private_draft_outbox'),
                                ('pending_memoir_lanes', 'user_memoir_lane')):
            ready = json.loads(database(f'set role service_role; select public.{function}();').stdout)
            expected = database(f"select id from public.{table} where project_id='canonical';").stdout.strip()
            assert ready == [expected]
        assert database("select delivered from public.user_private_draft_outbox "
                        "where project_id='unmapped';").stdout.strip() == 'f'
    finally:
        database('truncate public.user_memoir_project,public.user_memoir_lane,public.user_private_draft_outbox cascade;')


def test_private_tables_and_worker_operations_keep_their_access_boundaries(database):
    assert database("select count(*) from pg_class where relnamespace='public'::regnamespace "
                    "and relkind='r' and not relrowsecurity;").stdout.strip() == '0'
    database(f"insert into public.user_profile(user_id) values ('{OWNER}'),('{OTHER}');")
    try:
        assert database(as_user('select user_id from public.user_profile;')).stdout.splitlines()[-1] == OWNER
        assert database(as_user('select user_id from public.user_profile;', OTHER)).stdout.splitlines()[-1] == OTHER
        assert database('set role anon; select * from public.user_profile;', check=False).returncode != 0
        assert database(as_user('select public.pending_memoir_receipts();'), check=False).returncode != 0
        assert database('set role service_role; select public.pending_memoir_receipts();').stdout.strip() == '[]'
        assert database("select has_function_privilege('authenticated',"
            "'public.lock_lifetime_memoir_lane_scope(uuid,uuid)','execute');").stdout.strip() == 'f'
        assert database("select has_function_privilege('anon',"
            "'public.read_lifetime_private_draft_head(text,text)','execute');").stdout.strip() == 'f'
        assert database("select has_table_privilege('authenticated',"
            "'public.user_lifetime_artifact_file','select');").stdout.strip() == 'f'
        assert database("select has_table_privilege('service_role',"
            "'public.user_profile','select');").stdout.strip() == 't'
    finally:
        database('truncate public.user_profile;')


def test_baseline_tail_failure_rolls_back_tables_functions_policies_and_buckets():
    fixture = database.__wrapped__(apply_schema=False)
    try:
        sql = next(fixture)
        baseline = BASELINE.read_text()
        broken = baseline.replace("notify pgrst, 'reload schema';",
            "do $failure$ begin raise exception 'controlled baseline failure'; end $failure$;")
        result = sql(broken, check=False)
        assert result.returncode != 0 and 'controlled baseline failure' in result.stderr
        assert sql("select count(*) from pg_class where relnamespace='public'::regnamespace;").stdout.strip() == '0'
        assert sql("select count(*) from pg_proc where pronamespace='public'::regnamespace;").stdout.strip() == '0'
        assert sql("select count(*) from pg_policies where schemaname='storage';").stdout.strip() == '0'
        assert sql('select count(*) from storage.buckets;').stdout.strip() == '0'
        sql(baseline)
        assert sql("select to_regclass('public.user_memoir_edition') is not null;").stdout.strip() == 't'
        assert sql('select count(*) from storage.buckets;').stdout.strip() == '2'
    finally:
        fixture.close()


def test_retained_history_and_receipts_use_their_ordered_indexes(database):
    database(f"""
      insert into public.user_memory(user_id,project_id,kind,content,created_at)
        select '{OWNER}','history-' || (n % 20),'memoir','synthetic',now()-n*interval '1 second'
        from generate_series(1,5000) n;
      insert into public.user_private_draft_outbox(user_id,project_id,change_kind,delivered,created_at)
        select '{OWNER}','synthetic','round',n>20,now()-n*interval '1 second'
        from generate_series(1,5000) n;
      analyze public.user_memory;
      analyze public.user_private_draft_outbox;
    """)
    def indexes(plan):
        return {plan.get('Index Name')} | {name for child in plan.get('Plans', []) for name in indexes(child)}
    try:
        history = json.loads(database(f"explain (format json) select id,created_at from public.user_memory "
            f"where user_id='{OWNER}' and project_id='history-1' order by created_at desc,id desc limit 50;").stdout)
        receipts = json.loads(database('explain (format json) select id from public.user_private_draft_outbox '
            'where not delivered order by created_at,id limit 50;').stdout)
        assert 'user_memory_user_id_project_id_created_at_id_idx' in indexes(history[0]['Plan'])
        assert 'user_private_draft_outbox_created_at_id_idx' in indexes(receipts[0]['Plan'])
    finally:
        database('truncate public.user_memory,public.user_private_draft_outbox cascade;')
