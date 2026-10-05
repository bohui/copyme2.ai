"""Atomic private-round/outbox and RLS checks on disposable PostgreSQL."""
import json
from pathlib import Path
import pytest
from test_agent_commit_postgres import database, as_user, OWNER, OTHER, OLD
from test_guest_conversation_transfer import attachment_database


@pytest.fixture(scope='module')
def private_database(attachment_database):
    root=Path(__file__).resolve().parents[1]
    attachment_database((root/'supabase/legacy-migrations/202609300003_recall_usage.sql').read_text())
    attachment_database((root/'supabase/migrations/202610020002_private_draft_rounds.sql').read_text())
    attachment_database((root/'supabase/migrations/202610020004_response_stage_index.sql').read_text())
    return attachment_database


@pytest.fixture
def sql(private_database):
    private_database('truncate public.user_memory,public.user_completed_round,public.user_private_draft_outbox,public.user_recall_usage,public.user_agent_session,public.user_agent_turn_lease cascade;')
    private_database(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    return private_database


def commit(turn=1,user_response=True):
    return f"select public.commit_user_agent_turn('{OLD}','thread',E'Storyteller: Original memory\nMemory Spark: A successful reply','{{}}',null,'project','00000000-0000-4000-8000-{turn:012d}',{'true' if user_response else 'false'});"


def test_round_and_outbox_are_atomic_idempotent_and_owner_scoped(sql):
    first=json.loads(sql(as_user(commit())).stdout.splitlines()[-1])
    repeated=json.loads(sql(as_user(commit())).stdout.splitlines()[-1])
    assert first==repeated
    assert first[0]['life_stage']=='unplaced' and first[0]['life_stage_order']==7
    assert sql('select count(*) from public.user_memory;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_private_draft_outbox;').stdout.strip()=='1'
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'
    assert sql(as_user('select count(*) from public.user_completed_round;',OTHER)).stdout.splitlines()[-1]=='0'
    assert sql(as_user('insert into public.user_private_draft_outbox(user_id,project_id,change_kind) values(auth.uid(),\'project\',\'round\');'),check=False).returncode!=0


def test_known_stage_commits_atomically_and_retries_keep_original_assignment(sql):
    tagged=commit().replace('true);', "true,'childhood');")
    saved=json.loads(sql(as_user(tagged)).stdout.splitlines()[-1])
    assert saved[0]['life_stage']=='childhood' and saved[0]['life_stage_order']==2
    assert json.loads(sql(as_user(commit())).stdout.splitlines()[-1])==saved
    assert sql('select count(*) from public.user_private_draft_outbox;').stdout.strip()=='1'
    invalid=commit(2).replace('true);', "true,'invented');")
    assert sql(as_user(invalid),check=False).returncode!=0
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'


def test_null_legacy_assignment_is_unplaced_and_database_orders_by_stage(sql):
    sql(as_user(commit()))
    sql(as_user(commit(2).replace('true);', "true,'midlife');")))
    sql(as_user(commit(3).replace('true);', "true,'childhood');")))
    assert sql('select life_stage from public.user_memory order by life_stage_order,created_at,id;').stdout.splitlines()==['childhood','midlife','unplaced']
    sql(as_user("update public.user_memory set life_stage=null where life_stage='midlife';"))
    assert sql('select count(*) from public.user_memory where life_stage is null;').stdout.strip()=='0'


def test_assistant_only_reply_does_not_count_and_edits_do_not_increment(sql):
    sql(as_user(commit(user_response=False)))
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='0'
    sql(as_user(commit(2)))
    sql(as_user("update public.user_memory set life_stage='childhood' where kind='agent';"))
    sql(as_user("update public.user_memory set content=E'Storyteller: Corrected memory\nMemory Spark: A successful reply' where kind='agent';"))
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
    assert sql('select rounds_completed from public.user_recall_usage;').stdout.strip()=='1'
    assert sql("select count(*) from public.user_private_draft_outbox where change_kind in ('assignment','edit');").stdout.strip()=='2'
    sql(as_user("delete from public.user_memory where kind='agent';"))
    assert sql('select memory_id is null from public.user_completed_round;').stdout.strip()=='t'
    sql(as_user(commit(3)))
    assert sql('select max(ordinal) from public.user_completed_round;').stdout.strip()=='2'


def test_failed_outbox_commit_rolls_back_exchange_and_allowance(sql):
    sql("alter table public.user_private_draft_outbox add constraint reject_round check(change_kind <> 'round');")
    try:
        assert sql(as_user(commit()),check=False).returncode!=0
        assert sql('select count(*) from public.user_memory;').stdout.strip()=='0'
        assert sql('select count(*) from public.user_recall_usage;').stdout.strip()=='0'
        assert sql('select count(*) from public.user_agent_session;').stdout.strip()=='0'
    finally:
        sql('alter table public.user_private_draft_outbox drop constraint reject_round;')


def test_broker_snapshot_requires_service_role_and_is_receipt_scoped(sql):
    sql(as_user(commit()))
    event=sql('select id from public.user_private_draft_outbox limit 1;').stdout.strip()
    query=f"select public.private_draft_event_snapshot('{event}');"
    assert sql(as_user(query),check=False).returncode!=0
    snapshot=json.loads(sql('set role service_role; '+query).stdout.splitlines()[-1])
    assert snapshot['user_id']==OWNER and snapshot['project_id']=='project'
    assert len(snapshot['rounds'])==1 and len(snapshot['memories'])==1 and snapshot['completed']==1
    sql('delete from public.user_private_draft_outbox;')
    assert sql('set role service_role; '+query.replace(');',') is null;')).stdout.strip()=='t'


def test_guest_transfer_preserves_private_round_identity_and_stage_once(sql):
    from test_guest_conversation_transfer import prepare,attach
    sql('truncate public.guest_conversation_transfer,public.user_conversation_attachment cascade;')
    sql(f"update auth.users set is_anonymous=(id='{OWNER}');")
    sql('update public.user_agent_turn_lease set expires_at=clock_timestamp();')
    for i in range(1,6):
        sql(f"insert into public.user_memory(user_id,kind,content,project_id,client_turn_id,life_stage) values('{OWNER}','agent',E'Storyteller: Fixture memory {i}\\nMemory Spark: Fixture reply','project-guest','00000000-0000-4000-8000-{i:012d}','childhood');")
    sql(as_user(prepare()))
    first=sql(as_user(attach(),OTHER)).stdout.splitlines()[-1]
    assert sql(as_user(attach(),OTHER)).stdout.splitlines()[-1]==first
    assert sql(f"select count(*) from public.user_completed_round where user_id='{OTHER}' and project_id='project-guest';").stdout.strip()=='5'
    assert sql(f"select count(*) from public.user_private_draft_outbox where user_id='{OTHER}';").stdout.strip()=='5'
    assert sql(f"select count(*) from public.user_memory where user_id='{OTHER}' and life_stage='childhood' and client_turn_id is not null;").stdout.strip()=='5'
