"""Regressions for PR 62: canonical reads and exact photo dependencies."""
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.conversation_recovery import conversation_history, turn_receipt
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER, as_user
from test_lifetime_composer_capacity import seeded_composer, section_result, service
from test_lifetime_memory_commit import prepare, commit
from test_lifetime_memory_postgres import (
    sql, event_database, private_database, attachment_database, database,
)
from test_shared_memory_events_postgres import literal, rpc


@pytest.mark.parametrize('current', [
    {'name': 'Joan', 'preferred_language': 'zh-CN', 'birth_year': 1960,
     'birth_place': 'New town', 'childhood_place': 'New childhood place'},
    {},
])
def test_warm_home_uses_current_profile_and_does_not_resurrect_removed_fields(monkeypatch, current):
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response = client.post('/v1/projects', headers={'X-Account-Id': 'fixture-owner'},
            json={'birth_place': 'Old town', 'birth_year': 1950, 'language': 'en-AU'})
        assert response.status_code == 201, response.text
    project = store.projects[response.json()['id']]
    project['profile']['childhood_place'] = 'Old childhood place'
    project['profile']['_private_cache'] = 'Internal bookkeeping'
    before = deepcopy(project['profile'])
    authoritative = {**current, '_private_cache': 'Current internal bookkeeping'}
    monkeypatch.setattr(main, '_require_project_access', lambda project: None)
    result = main._project_response(project, authoritative_profile=authoritative)['profile']
    for key in ('name', 'preferred_language', 'birth_year', 'birth_place'):
        assert result.get(key) == current.get(key)
    assert 'childhood_place' not in result
    assert '_private_cache' not in result
    assert project['profile'] == before


@pytest.mark.parametrize('enabled', ['true', 'false'])
@pytest.mark.parametrize('kind', ['receipt', 'history'])
def test_current_policy_filters_saved_replies_even_after_rollout_rollback(sql, monkeypatch, enabled, kind):
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    sql(as_user("update public.user_profile set profile=profile||"
        "'{\"memory_preferences\":{\"excluded_topics\":[\"Joan\"]}}'::jsonb;"))
    assert rpc(sql, 'read_lifetime_reply', f"'{identity['conversation_id']}','{turn}'")['reply'] is None
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', enabled)
    storage = PostgresRest(sql, OWNER).storage()
    try:
        result = (turn_receipt(storage, identity['project_id'], turn) if kind == 'receipt' else
            conversation_history(storage, identity['project_id'], 8, None).items[0])
        assert result.reply is None
        assert result.narrator_text == accepted['source']['text']
    finally:
        storage.client.close()


def add_photo_link(sql, identity, source, page):
    photo, link = str(uuid4()), str(uuid4())
    project = identity['project_id']
    sql(f"insert into public.user_interview_photo(user_id,project_id,id,object_path,content_type,byte_size,width,height,status) "
        f"values('{OWNER}',{literal(project)},'{photo}','synthetic/{photo}.jpg','image/jpeg',1,1,1,'ready');")
    rpc(sql, 'accept_user_interview_turn',
        f"{literal(project)},'{uuid4()}','','narrator_chat','en-AU',{literal([photo])}")
    sql(f"insert into public.user_interview_photo_link(user_id,project_id,id,photo_id,intended_event_id,source_id,source_version,quote,description,provenance) "
        f"values('{OWNER}',{literal(project)},'{link}','upload:{photo}',{literal(page['partition']['id'])},"
        f"'{source['id']}',1,{literal(source['text'])},'A later selected photo.','narrator_metadata');")
    sql(f"select public.reconcile_interview_photo_links('{OWNER}',{literal(project)});")
    assert sql(f"select status from public.user_interview_photo_link where id='{link}';").stdout.strip() == 'confirmed'
    return link


@pytest.mark.parametrize('protection', ['approved', 'human_locked'])
def test_photo_addition_preserves_protected_source_only_prose(sql, protection):
    identity, source, lane, page = seeded_composer(sql)
    result = section_result(page, 'Original narrator prose protected from unrelated photo changes.')
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{page['token']}',0,{literal(result)}")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    sql(f'update public.user_lifetime_memoir_section set {protection}=true;')
    before = sql('select row_to_json(s)::text from public.user_lifetime_memoir_section s;').stdout
    assert 'Original narrator prose' in before
    add_photo_link(sql, identity, source, page)
    assert sql('select row_to_json(s)::text from public.user_lifetime_memoir_section s;').stdout == before


@pytest.mark.parametrize('action', ['update', 'delete'])
def test_photo_change_invalidates_only_its_partition_and_pending_proposal(sql, action):
    identity, source, lane, first = seeded_composer(sql)
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{first['token']}'")
    link = add_photo_link(sql, identity, source, first)
    other_link = add_photo_link(sql, identity, source, first)
    # A new claim uses the revised event and actual confirmed photo partitions.
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    while not page['complete']:
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    sql("update public.user_lifetime_memoir_section set approved=true,proposal=bundle;")
    other = sql(f"select row_to_json(s)::text from public.user_lifetime_memoir_section s "
        f"where right(partition_key,37)=':{other_link}';").stdout
    assert other
    assert sql(f"select count(*) from public.user_lifetime_memoir_section where right(partition_key,37)=':{link}';").stdout.strip() == '1'
    if action == 'update':
        sql(f"update public.user_interview_photo_link set description='Corrected photo description' where id='{link}';")
    else:
        sql(f"delete from public.user_interview_photo_link where id='{link}';")
    assert sql(f"select count(*) from public.user_lifetime_memoir_section where right(partition_key,37)=':{link}';").stdout.strip() == '0'
    assert sql(f"select row_to_json(s)::text from public.user_lifetime_memoir_section s "
        f"where right(partition_key,37)=':{other_link}';").stdout == other
