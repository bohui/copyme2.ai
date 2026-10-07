"""Verify the data migration on disposable PostgreSQL via Apple Container."""
import json
from pathlib import Path

import pytest
from test_agent_commit_postgres import database


@pytest.fixture(scope='module')
def timeline_sql(database):
    # Reuse the supported UUID fixture: stock PostgreSQL, no mounts/ports,
    # TCP disabled, initialization checked and exact task cleanup.
    database('create table public.user_family_context(user_id text, project_id text, document jsonb, '
             'revision bigint, updated_at timestamptz default now());')

    def sql(query):
        return database(query).stdout.strip()

    return sql


def test_migration_unifies_existing_records_losslessly_and_replays_as_a_noop(timeline_sql):
    old = {'schema_version': 1, 'revision': 4, 'people': [{'id': 'person1', 'name': 'Avery'}],
           'relationships': [], 'source_sequence': 12,
           'timeline': [{'id': 'late', 'title': 'Return', 'date_expression': '2018年'},
                        {'id': 'visit', 'title': 'Visit', 'date_expression': '1958年暑假'},
                        {'id': 'play', 'title': 'Playing', 'date_expression': '童年'}],
           'life_periods': [{'id': 'work', 'title': 'Work', 'start_expression': '1986年', 'end_expression': '2005年',
                            'person_ids': ['person1'], 'visibility': 'private', 'include_in_print': False},
                           {'id': 'school', 'title': 'School', 'start_expression': 'around 1960'}]}
    encoded = json.dumps(old, ensure_ascii=False).replace("'", "''")
    timeline_sql(f"insert into public.user_family_context values ('owner','project','{encoded}',4,now());")
    migration = (Path(__file__).resolve().parents[1] / 'supabase/migrations/202610030001_unified_author_timeline.sql').read_text()
    timeline_sql(migration)
    migrated = json.loads(timeline_sql('select document from public.user_family_context;'))
    assert migrated['schema_version'] == 2 and migrated['revision'] == 5
    assert timeline_sql('select revision from public.user_family_context;') == '5'
    assert 'life_periods' not in migrated
    assert [item['id'] for item in migrated['timeline']] == ['visit', 'school', 'work', 'late', 'play']
    expected = {item['id']: item for item in old['timeline'] + old['life_periods']}
    for item in migrated['timeline']:
        original = {key: value for key, value in item.items() if key != 'kind'}
        assert original == expected[item['id']]
        assert item['kind'] == ('period' if item['id'] in ('school', 'work') else 'event')
    assert migrated['people'] == old['people'] and migrated['source_sequence'] == 12
    timeline_sql(migration)
    assert json.loads(timeline_sql('select document from public.user_family_context;')) == migrated
