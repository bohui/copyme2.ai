"""Foundational chain and subsequent upgrades on disposable PostgreSQL 17."""
import json
import os
from pathlib import Path
import time

import pytest
from test_agent_commit_postgres import database, as_user, OWNER, OTHER

MIGRATIONS = (
    '202610010001_initial_schema.sql',
    '202610020001_guest_transfer_storage_owner.sql',
    '202610020002_private_draft_rounds.sql',
    '202610020003_place_photo_searches.sql',
    '202610020004_response_stage_index.sql',
    '202610030001_unified_author_timeline.sql',
    '202610040001_shared_memory_events.sql',
    '202610040002_memoir_skill_lanes.sql',
)
ROOT = Path(__file__).resolve().parents[1] / 'supabase/migrations'


@pytest.fixture
def consolidated_database():
    # Reuse isolated ownership, bounded setup and exact cleanup.
    fixture = database.__wrapped__(deadline=time.monotonic() + 180,
        legacy_schema=False, postgres_image='postgres:17.6')
    try:
        sql = next(fixture)
        version = sql('show server_version;').stdout.strip()
        assert int(sql('show server_version_num;').stdout.strip()) // 10000 == 17
        if os.getenv('MEMOIR_TEST_POSTGRES_BACKEND') == 'apple-container':
            assert version.startswith('17.6')
        sql('create role service_role bypassrls; alter table storage.objects add column owner_id text;')
        yield sql
    finally:
        fixture.close()


@pytest.mark.parametrize('seed_legacy', [False, True], ids=['fresh', 'seeded-upgrade'])
def test_exact_consolidated_chain_preserves_originals_and_backfills_canonical_evidence(
        consolidated_database, seed_legacy):
    sql = consolidated_database
    migrations = tuple(path.name for path in sorted(ROOT.glob('*.sql')))
    assert migrations[:len(MIGRATIONS)] == MIGRATIONS
    for name in MIGRATIONS[:6]:
        sql((ROOT / name).read_text())
    original = 'I started school in 1983.'
    memory_id = 'aaaaaaaa-0000-4000-8000-000000000001'
    if seed_legacy:
        document = {'schema_version': 2, 'people': [{'id': 'person-1', 'name': 'Synthetic person'}],
            'timeline': [{'id': 'legacy-school', 'title': 'Started school', 'precision': 'year',
                'date_expression': '1983年', 'revision': 4, 'include_in_print': False,
                'person_ids': ['person-1'], 'source_refs': [{'source_id': memory_id, 'quote': original}]}]}
        encoded = json.dumps(document).replace("'", "''")
        sql(f"insert into public.user_memory(id,user_id,kind,content,project_id,client_turn_id) values "
            f"('{memory_id}','{OWNER}','agent',E'Storyteller: {original}\\nMemory Spark: Synthetic reply',"
            "'project','bbbbbbbb-0000-4000-8000-000000000001');")
        sql(f"insert into public.user_family_context(user_id,project_id,document,revision) "
            f"values('{OWNER}','project','{encoded}',4);")
        sql("insert into public.place_photo_searches(search_key,place,period,result) values(" +
            "'a'" + " || repeat('a',63),'Chengde','1980s','{\"complete\":true,\"items\":[]}');")
    for name in MIGRATIONS[6:]:
        sql((ROOT / name).read_text())
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == ('1' if seed_legacy else '0')
    assert sql('select count(*) from public.user_memory_event;').stdout.strip() == ('1' if seed_legacy else '0')
    assert sql('select count(*) from public.user_memoir_manuscript;').stdout.strip() == '0'
    if seed_legacy:
        assert sql('select text from public.user_narrator_source;').stdout.strip() == original
        assert sql('select revision from public.user_memory_event;').stdout.strip() == '4'
        assert sql('select evidence->>\'quote\' from public.user_memory_event_source;').stdout.strip() == original
        assert sql('select count(*) from public.user_memory;').stdout.strip() == '1'
        assert sql('select count(*) from public.place_photo_searches;').stdout.strip() == '1'
        assert sql(as_user('select count(*) from public.user_narrator_source;', OTHER)).stdout.splitlines()[-1] == '0'

    # Preserve foundational schema replay coverage before forward upgrades.
    sql((ROOT / '202610040001_shared_memory_events.sql').read_text())
    # Exercise every later committed migration too; adding a migration must not
    # make this historical foundation test obsolete or silently omit upgrades.
    for name in migrations[len(MIGRATIONS):]:
        sql((ROOT / name).read_text())
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == ('1' if seed_legacy else '0')
    if seed_legacy:
        assert sql('select text from public.user_narrator_source;').stdout.strip() == original
        assert sql('select count(*) from public.user_memory;').stdout.strip() == '1'
        assert sql(as_user('select count(*) from public.user_narrator_source;', OTHER)).stdout.splitlines()[-1] == '0'


@pytest.mark.parametrize('history', ['fresh', 'pre_workspace', 'current_main', 'pre_recordings', 'main_45ea639'],
    ids=['fresh-history', 'main-upgrade-history', 'current-main-upgrade-history', 'pre-recordings-history', 'main-45ea639-history'])
def test_main_migration_history_accepts_the_unapplied_workspace_upgrade(consolidated_database, history):
    sql = consolidated_database
    # Match Supabase's primary key: a descriptive suffix does not make another
    # migration with the same numeric prefix distinct. No CLI or remote DB.
    sql('create schema supabase_migrations; create table supabase_migrations.schema_migrations '
        '(version text primary key, statements text[], name text);')
    paths = sorted(ROOT.glob('*.sql'))
    if history == 'main_45ea639':
        # Exact upstream SQL from 45ea6390fa8b777c0ec2090400fb5eb592466e80.
        # Exercise its real schema + ledger upgrade without importing unrelated
        # main application changes into this task branch or requiring Git/network.
        paths = sorted([*paths, Path(__file__).parent / 'fixtures/issue73/202610160004_transferred_stage_readiness.sql'],
            key=lambda path: path.name)
    workspace = next(path for path in paths if path.name.endswith('_workspace_memory_actions.sql'))
    # A pre-workspace history cannot already contain later migrations that
    # depend on its schema. Apply its real prefix first, then every forward
    # upgrade in version order. Also cover current main's full pre-task chain.
    recordings = next(path for path in paths if path.name.endswith('_original_recordings.sql'))
    boundary = workspace.name if history == 'pre_workspace' else recordings.name if history in {'pre_recordings','main_45ea639'} else '202610150004'
    prior = [path for path in paths if path.name < boundary] if history != 'fresh' else []
    forward = [path for path in paths if path not in prior]
    assert not set(prior).intersection(forward)
    def apply(selected):
        for path in selected:
            version, name = path.stem.split('_', 1)
            sql(path.read_text())
            sql(f"insert into supabase_migrations.schema_migrations(version,name) values('{version}','{name}');")
    apply(prior)
    assert sql('select version from supabase_migrations.schema_migrations order by version;').stdout.splitlines()==[
        path.name.split('_',1)[0] for path in prior]
    if prior:
        sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"upgrade_sentinel\":\"synthetic-preserve\"}}') "
            "on conflict(user_id) do update set profile=excluded.profile;")
        before=sql(f"select profile::text from public.user_profile where user_id='{OWNER}';").stdout
    apply(forward)
    if prior:
        assert sql(f"select profile::text from public.user_profile where user_id='{OWNER}';").stdout==before
    assert sql('select version from supabase_migrations.schema_migrations order by version;').stdout.splitlines() == [
        path.name.split('_', 1)[0] for path in paths]
