"""Exercise usage permissions, atomic charging, and guest merges on disposable PostgreSQL."""
from pathlib import Path

import pytest

from test_agent_commit_postgres import database, as_user, OWNER, OTHER, OLD, commit
from test_guest_conversation_transfer import attachment_database, prepare, attach


@pytest.fixture(scope='module')
def recall_database(attachment_database):
    migration = Path(__file__).resolve().parents[1] / 'supabase/migrations/202609300003_recall_usage.sql'
    attachment_database(f"insert into public.user_memory(user_id, kind, content) values ('{OWNER}', 'agent', 'old reply');")
    attachment_database(migration.read_text())
    assert attachment_database(f"select rounds_completed from public.user_recall_usage where user_id = '{OWNER}';").stdout.strip() == '1'
    return attachment_database


@pytest.fixture
def sql(recall_database):
    recall_database('truncate public.user_memory, public.user_recall_usage, public.user_agent_turn_lease, '
                    'public.user_agent_session, public.guest_conversation_transfer, public.user_conversation_attachment;')
    recall_database(f"update auth.users set is_anonymous = (id = '{OWNER}');")
    return recall_database


def count(sql, user=OWNER):
    return sql(f"select coalesce((select rounds_completed from public.user_recall_usage where user_id = '{user}'), 0);").stdout.strip()


def test_charge_is_atomic_and_cannot_be_reset_by_deleting_memories(sql):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sql(as_user(commit()))
    assert count(sql) == '1'
    assert sql(as_user('select rounds_completed from public.user_recall_usage;')).stdout.splitlines()[-1] == '1'
    assert sql(as_user('select count(*) from public.user_recall_usage;', OTHER)).stdout.splitlines()[-1] == '0'
    for query in ('update public.user_recall_usage set rounds_completed = 0;',
                  'delete from public.user_recall_usage;',
                  f"insert into public.user_recall_usage values ('{OTHER}', 0);"):
        assert sql(as_user(query), check=False).returncode != 0
    sql(as_user('delete from public.user_memory;'))
    assert count(sql) == '1'
    sql('begin; ' + as_user(commit()) + ' rollback;')
    assert count(sql) == '1'


def test_guest_merge_preserves_deleted_usage_without_double_charging_on_retry(sql):
    sql(f"insert into public.user_memory(user_id, kind, content) values ('{OWNER}', 'agent', 'deleted'), "
        f"('{OWNER}', 'agent', 'kept'), ('{OTHER}', 'agent', 'existing');")
    sql(f"delete from public.user_memory where user_id = '{OWNER}' and content = 'deleted';")
    sql(as_user(prepare()))
    sql(as_user(attach(), OTHER))
    assert count(sql, OTHER) == '3'
    sql(as_user(attach(), OTHER))
    assert count(sql, OTHER) == '3'
