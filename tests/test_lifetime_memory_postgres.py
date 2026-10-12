"""Issue 60 real isolated PostgreSQL invariants, never a configured service."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_agent_commit_postgres import database, as_user, OWNER, OTHER
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, rpc, literal


@pytest.fixture
def sql(event_database):
    event_database('truncate public.user_memoir_project cascade;')
    event_database('truncate public.user_memory, public.user_agent_turn_lease, public.user_agent_session cascade;')
    event_database('update auth.users set is_anonymous=false;')
    return event_database


def resolve(sql, project=None, owner=OWNER, check=True):
    return rpc(sql, 'resolve_lifetime_conversation', 'null' if project is None else literal(project), owner=owner, check=check)


def test_new_account_two_devices_and_long_absence_resolve_one_identity(sql):
    first = resolve(sql)
    assert first['outcome'] == 'resolved'
    assert first['schema_version'] == 1 and first['owner_id'] == OWNER
    assert first['product'] == 'memoir'
    # Authentication sessions and visits do not participate in product identity.
    assert resolve(sql) == first
    assert resolve(sql, first['project_id']) == first
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '1'


def test_concurrent_new_account_resolution_is_database_unique(sql):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: resolve(sql), range(2)))
    assert results[0] == results[1]
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '1'


@pytest.mark.parametrize('projects', [['old'], ['old', 'new']])
def test_historical_mapping_is_explicit_and_never_mutates_original_ids(sql, projects):
    for project in projects:
        rpc(sql, 'accept_user_narrator_source', f"{literal(project)}, '00000000-0000-4000-8000-000000000001', 'An original memory'")
    before = sql('select row_to_json(s) from public.user_narrator_source s order by project_id;').stdout
    result = resolve(sql)
    assert result == {'schema_version':1, 'outcome':'mapping_required', 'project_ids': sorted(projects)}
    assert resolve(sql, projects[-1]) == result
    assert sql('select row_to_json(s) from public.user_narrator_source s order by project_id;').stdout == before
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'


def test_unowned_arbitrary_project_and_guest_fail_without_creation(sql):
    first = resolve(sql)
    assert resolve(sql, first['project_id'], OTHER, check=False).returncode != 0
    assert resolve(sql, 'invented', OTHER, check=False).returncode != 0
    assert resolve(sql, 'invented', OWNER, check=False).returncode != 0
    sql(f"update auth.users set is_anonymous=true where id='{OTHER}';")
    assert resolve(sql, owner=OTHER, check=False).returncode != 0
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '1'


def test_identity_rls_and_direct_write_protection(sql):
    resolve(sql)
    assert sql(as_user('select count(*) from public.user_lifetime_conversation;', OTHER)).stdout.splitlines()[-1] == '0'
    assert sql(as_user("update public.user_lifetime_conversation set execution_generation=99;"), check=False).returncode != 0
    assert sql("set role anon; select * from public.user_lifetime_conversation;", check=False).returncode != 0


def test_explicit_synthetic_mapping_preserves_source_turn_and_profile_revisions(sql):
    source = rpc(sql, 'accept_user_narrator_source', "'original', '00000000-0000-4000-8000-000000000001', 'I lived in Chengde'")
    profile = {'preferred_language':'zh-CN', 'conversation_phase':{'schema_version':1,'phase':'shape','selection':'explicit','preferred_phase':'shape','paused':True,'revision':7,'reason':'fixture','source_turn_id':None}}
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}',{literal(profile)}::jsonb) on conflict(user_id) do update set profile=excluded.profile;")
    # Explicit fixture mapping simulates a separately approved operator action.
    sql(f"insert into public.user_lifetime_conversation(user_id,project_id,preference_revision) values('{OWNER}','original',9);")
    assert resolve(sql)['project_id'] == 'original'
    preserved = json.loads(sql("select row_to_json(s) from public.user_narrator_source s;").stdout.strip())
    assert preserved['id'] == source['id'] and preserved['client_turn_id'] == source['client_turn_id']
    assert json.loads(sql('select profile from public.user_profile;').stdout.strip()) == profile
    assert sql('select preference_revision from public.user_lifetime_conversation;').stdout.strip() == '9'
    # Rollback is read-adapter selection, never dropping newly accepted evidence.
    assert rpc(sql,'read_user_memory_events',"'original'")['sources'][0]['id'] == source['id']


def test_typed_continuity_requires_current_evidence_policy_and_lease(sql):
    from test_agent_commit_postgres import OLD
    identity = resolve(sql)
    project = identity['project_id']
    source = rpc(sql, 'accept_user_narrator_source', f"{literal(project)}, '00000000-0000-4000-8000-000000000001', 'My uncle is Ming.'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    data = {'text':'My uncle is Ming.', 'assertion':'asserted', 'uncertainty':None,
        'source_refs':[{'source_id':source['id'],'version':1,'char_start':0,'char_end':17,'quote':'My uncle is Ming.'}]}
    args = f"'{identity['conversation_id']}', 'uncle', 'person', 0, 1, '{OLD}', {literal(data)}::jsonb"
    saved = rpc(sql,'save_lifetime_continuity',args)
    assert saved['revision'] == 1 and saved['data'] == data
    assert rpc(sql,'save_lifetime_continuity',args,check=False).returncode != 0
    assert rpc(sql,'save_lifetime_continuity',args,owner=OTHER,check=False).returncode != 0
    records = rpc(sql,'read_lifetime_continuity',f"'{identity['conversation_id']}', 1")
    assert records['records'] == [saved] and records['complete'] is True
    rpc(sql,'change_user_narrator_source',f"{literal(project)}, '{source['id']}', 1, 'withdraw', null")
    assert rpc(sql,'read_lifetime_continuity',f"'{identity['conversation_id']}', 1",check=False).returncode != 0
    assert rpc(sql,'read_lifetime_continuity',f"'{identity['conversation_id']}', 2")['records'] == []


def test_continuity_rejects_fabricated_spans_and_direct_reads(sql):
    from test_agent_commit_postgres import OLD
    identity = resolve(sql)
    source = rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])}, '00000000-0000-4000-8000-000000000001', 'Original wording'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    for ref in [dict(source_id=source['id'],version=1,char_start=0,char_end=16,quote='Fabricated words'),
                dict(source_id=source['id'],version=1,quote='Original wording')]:
        data = dict(text='Claim',assertion='inferred',source_refs=[ref])
        result = rpc(sql,'save_lifetime_continuity',f"'{identity['conversation_id']}', 'claim', 'person', 0, 1, '{OLD}', {literal(data)}::jsonb",check=False)
        assert result.returncode != 0
    assert sql(as_user('select * from public.user_lifetime_continuity;'),check=False).returncode != 0


@pytest.mark.parametrize('override', [dict(char_start=None,char_end=None,quote=None),dict(char_start=True),
    dict(char_end=1.5),dict(char_start='0'),dict(version='1'),dict(quote=''),dict(unexpected='value')])
def test_continuity_rejects_null_and_untyped_evidence_before_sql_casts(sql,override):
    from test_agent_commit_postgres import OLD
    identity=resolve(sql)
    source=rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])}, '00000000-0000-4000-8000-000000000001', 'Original'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    ref=dict(source_id=source['id'],version=1,char_start=0,char_end=8,quote='Original');ref.update(override)
    data=dict(text='Claim',assertion='asserted',source_refs=[ref])
    assert rpc(sql,'save_lifetime_continuity',f"'{identity['conversation_id']}', 'claim', 'person', 0, 1, '{OLD}', {literal(data)}::jsonb",check=False).returncode != 0
