import pytest
from test_lifetime_policy_atomic_postgres import accept, begin_review, complete, restriction
from test_lifetime_memory_postgres import sql, resolve, event_database, private_database, attachment_database, database
from test_shared_memory_events_postgres import rpc, literal
from test_agent_commit_postgres import OTHER, as_user


@pytest.mark.parametrize('restricted', [False, True])
def test_only_the_current_draft_can_bypass_its_own_pending_review(sql, restricted):
    identity = resolve(sql)
    text = 'Please leave my family out of our conversation.'
    source = accept(sql, identity, text)['source']
    fence = begin_review(sql, identity)
    args = f'{literal(fence)}::jsonb'
    assert rpc(sql,'lock_lifetime_publication',args,check=False).returncode != 0
    rpc(sql,'lock_lifetime_draft_reply',args)
    assert rpc(sql,'lock_lifetime_draft_reply',args,owner=OTHER,check=False).returncode != 0
    complete(sql,fence,source,[restriction(text)] if restricted else [])
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{fence['lease_token']}'")
    args=f'{literal(fence)}::jsonb'
    rpc(sql,'lock_lifetime_publication',args)
    result = rpc(sql,'lock_lifetime_draft_reply',args,check=False)
    assert (result.returncode != 0) == restricted


def test_draft_guard_rejects_older_pending_sources_and_stale_fences(sql):
    identity = resolve(sql)
    accept(sql,identity,'An older unreviewed source.')
    fence = begin_review(sql,identity)
    sql(as_user(f"select public.accept_user_narrator_source({literal(identity['project_id'])},'00000000-0000-4000-8000-000000000702','A newer source.');"))
    assert rpc(sql,'lock_lifetime_draft_reply',f'{literal(fence)}::jsonb',check=False).returncode != 0
    fresh = rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{fence['lease_token']}'")
    assert rpc(sql,'lock_lifetime_draft_reply',f'{literal(fresh)}::jsonb',check=False).returncode != 0
