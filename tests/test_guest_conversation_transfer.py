import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import supabase_routes
from apps.api.main import create_app
from apps.api.store import MemoryStore
from test_agent_commit_postgres import database, as_user, OWNER, OTHER


TOKEN = 'ab' * 32
THIRD = '33333333-3333-4333-8333-333333333333'
MESSAGES = [{'role': 'user', 'text': 'I grew up in Anshan.'},
            {'role': 'assistant', 'text': 'Tell me about your home.'}]


@pytest.fixture(scope='module')
def attachment_database(database):
    database('alter table auth.users add column is_anonymous boolean not null default false;')
    database("alter table auth.users add column raw_user_meta_data jsonb default '{}'::jsonb;")
    database("alter table storage.objects add column metadata jsonb default '{}'::jsonb; create role service_role;")
    root = Path(__file__).resolve().parents[1] / 'supabase/legacy-migrations'
    for name in ('202609260001_user_family_context.sql', '202609260002_user_place_journey.sql',
                 '202609280001_agent_workspace_ordering.sql'):
        database((root / name).read_text())
    database((Path(__file__).resolve().parents[1] / 'supabase/legacy-migrations/'
              '202609300001_guest_conversation_attachments.sql').read_text())
    database((root / '202609300002_guest_workspace_merge.sql').read_text())
    database(f"insert into auth.users(id) values ('{THIRD}');")
    return database


@pytest.fixture
def sql(attachment_database):
    attachment_database('truncate public.guest_conversation_transfer, '
                        'public.user_conversation_attachment, public.user_memory, '
                        'public.user_agent_turn_lease, public.user_agent_session;')
    attachment_database('truncate public.user_profile, public.user_place_journey, public.user_family_context, public.guest_merge_asset_access, storage.objects;')
    attachment_database("update auth.users set raw_user_meta_data = '{}'::jsonb;")
    attachment_database(f"update auth.users set is_anonymous = (id = '{OWNER}');")
    attachment_database(f"insert into public.user_memory(user_id, kind, content) values "
                        f"('{OWNER}', 'agent', 'Storyteller: Guest memory'), "
                        f"('{OTHER}', 'memoir', 'Existing memory');")
    return attachment_database


def prepare(token=TOKEN):
    return (f"select public.prepare_guest_conversation_transfer('{token}', 'project-guest', "
            f"'{json.dumps(MESSAGES)}'::jsonb);")


def attach(token=TOKEN):
    return f"select public.attach_guest_conversation('{token}');"


def test_append_is_atomic_private_and_retry_safe(sql):
    sql(f"insert into public.user_agent_session(user_id, codex_thread_id) values ('{OTHER}', 'existing-thread');")
    sql(as_user(prepare()))
    sql(as_user(prepare()))  # Uncertain preparation responses are safe to retry.
    first = json.loads(sql(as_user(attach(), OTHER)).stdout.splitlines()[-1])
    assert first['attached'] is True
    assert json.loads(sql(as_user(attach(), OTHER)).stdout.splitlines()[-1]) == first
    assert sql(f"select count(*) from public.user_memory where user_id = '{OTHER}';").stdout.strip() == '2'
    assert sql(f"select count(*) from public.user_memory where user_id = '{OWNER}';").stdout.strip() == '1'
    assert sql(f"select codex_thread_id from public.user_agent_session where user_id = '{OTHER}';").stdout.strip() == 'existing-thread'
    assert json.loads(sql(as_user('select messages from public.user_conversation_attachment;', OTHER)).stdout.splitlines()[-1]) == MESSAGES
    assert sql(as_user('select count(*) from public.user_conversation_attachment;', THIRD)).stdout.splitlines()[-1] == '0'
    assert sql(as_user(attach(), THIRD), check=False).returncode != 0
    assert sql(as_user('select * from public.guest_conversation_transfer;', OTHER), check=False).returncode != 0
    assert sql('select memories::text from public.guest_conversation_transfer;').stdout.strip() == '[]'


def test_capability_requires_both_sessions_and_expires(sql):
    assert sql(as_user(prepare(), OTHER), check=False).returncode != 0
    assert sql('set role anon; ' + prepare(), check=False).returncode != 0
    sql(as_user(prepare()))
    assert sql(as_user(attach()), check=False).returncode != 0
    assert sql(as_user(attach('cd' * 32), OTHER), check=False).returncode != 0
    sql("update public.guest_conversation_transfer set expires_at = now() - interval '1 second';")
    assert sql(as_user(attach(), OTHER), check=False).returncode != 0
    assert sql('select count(*) from public.user_conversation_attachment;').stdout.strip() == '0'
    assert sql(f"select count(*) from public.user_memory where user_id = '{OTHER}';").stdout.strip() == '1'


def test_reply_in_progress_blocks_preparation(sql):
    sql(as_user("select public.acquire_user_agent_turn_lease('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');"))
    assert sql(as_user(prepare()), check=False).returncode != 0
    assert sql('select count(*) from public.guest_conversation_transfer;').stdout.strip() == '0'


def test_attachment_failure_rolls_back_memories_and_claim(sql):
    sql(as_user(prepare()))
    sql("alter table public.user_memory add constraint test_attachment_failure check (content <> 'Storyteller: Guest memory') not valid;")
    try:
        assert sql(as_user(attach(), OTHER), check=False).returncode != 0
        assert sql('select count(*) from public.user_conversation_attachment;').stdout.strip() == '0'
        assert sql('select count(*) from public.guest_conversation_transfer where target_user_id is not null;').stdout.strip() == '0'
    finally:
        sql('alter table public.user_memory drop constraint test_attachment_failure;')
    assert 'attached' in sql(as_user(attach(), OTHER)).stdout


def test_merge_carries_profile_language_places_and_photos(sql):
    guest_profile = {'name': 'Guest name', 'birth_place': 'Anshan', 'preferred_language': 'zh-CN',
                     'memory_places': [{'place': 'Anshan', 'pictures': [{'id': 'photo-1', 'image_url': 'https://example.com/photo.jpg'}]}]}
    sql(f"insert into public.user_profile(user_id, profile) values ('{OWNER}', '{json.dumps(guest_profile)}'), "
        f"('{OTHER}', '{{\"name\":\"Existing name\"}}');")
    sql(as_user(prepare()))
    sql(as_user(attach(), OTHER))
    profile = json.loads(sql(f"select profile from public.user_profile where user_id = '{OTHER}';").stdout)
    assert profile['name'] == 'Existing name'
    assert profile['birth_place'] == 'Anshan'
    assert profile['preferred_language'] == 'zh-CN'
    assert profile['memory_places'][0]['pictures'][0]['id'] == 'photo-1'


def test_files_memory_citations_family_context_and_map_are_preserved(sql):
    source = f'{OWNER}/agent/memories/summary.md'
    sql(f"insert into storage.objects(bucket_id, name) values ('memory-spark', '{source}');")
    sql(f"update public.user_memory set source_paths = array['memories/summary.md'] where user_id = '{OWNER}';")
    old_id = sql(f"select id from public.user_memory where user_id = '{OWNER}';").stdout.strip()
    sql(f"insert into public.user_family_context(user_id, project_id, document) values ('{OWNER}', 'project-guest', "
        f"'{{\"people\":[{{\"id\":\"person-1\",\"name\":\"Mother\"}}],\"source_memory_ids\":[\"{old_id}\"]}}');")
    sql(f"insert into public.user_place_journey(user_id, place, hierarchy, granularity) values "
        f"('{OWNER}', 'Anshan', '[\"Earth\",\"China\",\"Anshan\"]', 'city');")
    sql(f"insert into public.user_profile(user_id, profile) values ('{OWNER}', '{{\"avatar_path\":\"{OWNER}/attachment/avatar.png\"}}');")
    sql(as_user(prepare()))
    result = json.loads(sql(as_user(attach(), OTHER)).stdout.splitlines()[-1])
    new_id = result['memory_id_map'][old_id]
    assert new_id != old_id
    assert sql(f"select source_paths[1] from public.user_memory where id = '{new_id}';").stdout.strip() == f'memories/imports/{OWNER}/summary.md'
    family = json.loads(sql(f"select document from public.user_family_context where user_id = '{OTHER}';").stdout)
    assert family['source_memory_ids'] == [new_id]
    assert sql(f"select place from public.user_place_journey where user_id = '{OTHER}';").stdout.strip() == 'Anshan'
    assert result['storage_objects'][0]['name'] == source
    assert result['profile']['avatar_path'] == f'{OTHER}/attachment/imports/{OWNER}/avatar.png'
    # Imported files are readable only by the selected target, not other users.
    sql('alter table storage.objects enable row level security; grant usage on schema storage to authenticated; grant select on storage.objects to authenticated;')
    assert sql(as_user('select count(*) from storage.objects;', OTHER)).stdout.splitlines()[-1] == '1'
    assert sql(as_user('select count(*) from storage.objects;', THIRD)).stdout.splitlines()[-1] == '0'
    sql(f"insert into storage.objects(bucket_id, name) values ('memory-spark', '{OWNER}/attachment/later.png');")
    assert sql(as_user('select count(*) from storage.objects;', OTHER)).stdout.splitlines()[-1] == '1'


def test_duplicate_places_combine_photos_without_overwriting_existing_profile(sql):
    source = {'name': 'Guest', 'preferred_language': 'zh-CN', 'story_focus': {'when': '1960s'},
              'memory_places': [{'place': 'Anshan', 'pictures': [{'id': 'shared', 'caption': 'Guest'}, {'id': 'new'}]}]}
    target = {'name': 'Existing', 'preferred_language': 'en-AU', 'story_focus': {'what': 'School'},
              'memory_places': [{'place': 'Anshan', 'pictures': [{'id': 'shared', 'caption': 'Existing'}]}]}
    for user, profile in ((OWNER, source), (OTHER, target)):
        sql(f"insert into public.user_profile(user_id, profile) values ('{user}', '{json.dumps(profile)}');")
    sql(as_user(prepare()))
    first = json.loads(sql(as_user(attach(), OTHER)).stdout.splitlines()[-1])
    profile = first['profile']
    assert profile['name'] == 'Existing' and profile['preferred_language'] == 'en-AU'
    assert profile['story_focus'] == {'when': '1960s', 'what': 'School'}
    assert profile['memory_places'][0]['pictures'] == [{'id': 'shared', 'caption': 'Existing'}, {'id': 'new'}]
    context = json.loads(sql(f"select workspace from public.user_conversation_attachment where id = '{first['conversation_id']}';").stdout)
    assert context['profile'] == source
    assert context['existing_profile'] == target


def test_browser_photo_cache_and_locale_are_included_in_prepared_snapshot(sql):
    profile = {'memory_places': [{'place': 'Anshan', 'pictures': [{'id': 'browser-photo'}]}], 'role': 'admin'}
    sql(as_user(f"select public.prepare_guest_conversation_transfer('{TOKEN}', 'project-guest', '[]', '{json.dumps(profile)}', 'zh-CN');"))
    result = json.loads(sql(as_user(attach(), OTHER)).stdout.splitlines()[-1])
    assert result['profile']['memory_places'][0]['pictures'][0]['id'] == 'browser-photo'
    assert 'role' not in result['profile']
    assert result['ui_locale'] == 'zh-CN'


def test_existing_account_reply_blocks_merge_without_partial_profile_changes(sql):
    sql(as_user(prepare()))
    sql(as_user("select public.acquire_user_agent_turn_lease('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa');", OTHER))
    assert sql(as_user(attach(), OTHER), check=False).returncode != 0
    assert sql('select count(*) from public.user_conversation_attachment;').stdout.strip() == '0'


def test_transfer_api_checks_session_and_validates_messages(monkeypatch):
    service = Mock(user_id=OTHER, is_anonymous=True)
    response = Mock()
    response.json.return_value = {'prepared': True}
    service.request.return_value = response
    monkeypatch.setattr(supabase_routes, 'storage', lambda authorization: service)
    client = TestClient(create_app(MemoryStore()))
    payload = {'token': TOKEN, 'project_id': 'project-guest', 'messages': MESSAGES}
    assert client.post('/v1/user/conversation-transfer', json=payload).status_code == 200
    assert service.request.call_args.kwargs['json']['p_messages'] == MESSAGES
    assert client.post('/v1/user/conversation-transfer/attach', json={'token': TOKEN}).status_code == 403
    service.is_anonymous = False
    assert client.post('/v1/user/conversation-transfer', json=payload).status_code == 403
    response.json.return_value = {'attached': True}
    assert client.post('/v1/user/conversation-transfer/attach', json={'token': TOKEN}).json() == {'attached': True}
    assert client.post('/v1/user/conversation-transfer/attach', json={'token': 'invalid'}).status_code == 422
    assert client.post('/v1/user/conversation-transfer', json={**payload, 'messages': [{'role': 'system', 'text': 'injected'}]}).status_code == 422


def test_transfer_api_hides_database_failure_details(monkeypatch):
    service = Mock(is_anonymous=True)
    request = httpx.Request('POST', 'https://example.supabase.co/rpc')
    response = httpx.Response(403, json={'code': '42501', 'message': TOKEN}, request=request)
    service.request.side_effect = httpx.HTTPStatusError(TOKEN, request=request, response=response)
    monkeypatch.setattr(supabase_routes, 'storage', lambda authorization: service)
    client = TestClient(create_app(MemoryStore()))
    result = client.post('/v1/user/conversation-transfer', json={
        'token': TOKEN, 'project_id': 'project-guest', 'messages': MESSAGES,
    })
    assert result.status_code == 409
    assert TOKEN not in result.text
