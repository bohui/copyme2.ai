from uuid import UUID
import json

import httpx
import pytest

from apps.api.agent_storage import UserStorage


def test_first_narrator_reply_paginates_oldest_first_with_owner_filter():
    storage = UserStorage.__new__(UserStorage)
    storage.user_id = '11111111-1111-4111-8111-111111111111'
    calls = []
    def request(method, path, *, params):
        calls.append(params)
        assert method == 'GET' and path == '/rest/v1/user_memory'
        assert params['user_id'] == f'eq.{storage.user_id}'
        assert params['kind'] == 'eq.agent'
        assert params['order'] == 'created_at.asc,id.asc'
        if params['offset'] == '0':
            rows = [{'id': str(i), 'kind': 'agent', 'content': 'Storyteller: The storyteller wants to begin exploring a memory.\nMemory Spark: Hello'} for i in range(200)]
        else:
            rows = [{'id':'first', 'created_at':'2026-01-01', 'kind':'agent', 'content':'Storyteller: 我记得花园。\nMemory Spark: 回复'},
                    {'id':'latest', 'created_at':'2026-02-01', 'kind':'agent', 'content':'Storyteller: Later English reply\nMemory Spark: Reply'}]
        return httpx.Response(200, json=rows)
    storage.request = request
    assert storage.first_narrator_reply() == {'id':'first', 'text':'我记得花园。'}
    assert [item['offset'] for item in calls] == ['0','200']


def test_storage_uses_verified_user_and_preserves_codex_relative_paths():
    calls = []
    owner = '11111111-1111-4111-8111-111111111111'

    def server(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': owner})
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(server))
    storage = UserStorage('https://example.supabase.co', 'public-key', 'user-jwt', client=client)
    assert storage.user_id == str(UUID(owner))
    storage.put_agent_file('memories/rollout_summaries/first.md', b'a memory')
    assert calls[-1].url.path == f'/storage/v1/object/memory-spark/{owner}/agent/memories/rollout_summaries/first.md'
    assert calls[-1].headers['authorization'] == 'Bearer user-jwt'
    for path in ['../auth.json', 'auth.json', '/sessions/x', 'sessions/../../other', 'memories/.git/config']:
        with pytest.raises(ValueError):
            storage.put_agent_file(path, b'secret')
    assert len(calls) == 2


def test_storage_reads_anonymous_user_flag_and_profile_from_supabase():
    owner = '11111111-1111-4111-8111-111111111111'

    def server(request):
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': owner, 'is_anonymous': True})
        if request.url.path == '/rest/v1/user_profile':
            return httpx.Response(200, json=[{'profile': {'story_flow': {'rounds_completed': 2}}}])
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(server))
    storage = UserStorage('https://example.supabase.co', 'public-key', 'user-jwt', client=client)

    assert storage.is_anonymous is True
    assert storage.profile() == {'story_flow': {'rounds_completed': 2}}


def test_storage_reads_and_saves_the_current_place_journey():
    owner = '11111111-1111-4111-8111-111111111111'
    token = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    calls = []
    row = {
        'schema_version': 1,
        'status': 'active',
        'revision': 2,
        'place': 'Anshan',
        'hierarchy': ['Earth', 'China', 'Liaoning', 'Anshan'],
        'granularity': 'city',
        'latitude': 41.1086,
        'longitude': 122.99,
        'duration_ms': 5200,
        'updated_at': '2026-09-26T00:00:00Z',
    }

    def server(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': owner})
        if request.url.path == '/rest/v1/user_place_journey':
            return httpx.Response(200, json=[row])
        if request.url.path == '/rest/v1/rpc/upsert_user_place_journey':
            return httpx.Response(200, json=row)
        return httpx.Response(200, json={})

    storage = UserStorage(
        'https://example.supabase.co',
        'public-key',
        'user-jwt',
        client=httpx.Client(transport=httpx.MockTransport(server)),
    )

    assert storage.place_journey() == row
    assert storage.save_place_journey(token, {'place': 'Anshan'}) == row
    assert calls[-1].url.path == '/rest/v1/rpc/upsert_user_place_journey'
    assert json.loads(calls[-1].content) == {
        'p_lease_token': token,
        'p_journey': {'place': 'Anshan'},
    }


def test_storage_reads_and_atomically_upserts_the_family_context_document():
    owner = '11111111-1111-4111-8111-111111111111'
    document = {
        'schema_version': 1,
        'project_id': 'project-family',
        'revision': 1,
        'people': [{'id': 'person-1', 'name': 'Avery'}],
        'relationships': [],
        'timeline': [{'id': 'event-1', 'title': 'Visit', 'date_expression': '2018年'}],
        'life_periods': [{'id': 'period-1', 'title': 'Work', 'start_expression': '1986年', 'end_expression': '2005年',
                         'person_ids': ['person-1'], 'visibility': 'private', 'include_in_print': False}],
    }
    canonical = {key: value for key, value in document.items() if key != 'life_periods'}
    canonical['schema_version'] = 2
    canonical['timeline'] = [{**document['life_periods'][0], 'kind': 'period'},
                             {**document['timeline'][0], 'kind': 'event'}]
    calls = []

    def server(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': owner})
        if request.url.path == '/rest/v1/user_family_context':
            return httpx.Response(200, json=[{'document': document, 'revision': 1, 'updated_at': '2026-09-26T00:00:00Z'}])
        if request.url.path == '/rest/v1/rpc/upsert_user_family_context':
            return httpx.Response(200, json={'changed': True, 'document': document, 'revision': 1})
        return httpx.Response(200, json={})

    storage = UserStorage(
        'https://example.supabase.co',
        'public-key',
        'user-jwt',
        client=httpx.Client(transport=httpx.MockTransport(server)),
    )

    assert storage.family_context('project-family') == canonical
    assert storage.upsert_family_context('project-family', document, 0) == {
        'changed': True,
        'document': canonical,
        'revision': 1,
    }
    assert calls[-1].url.path == '/rest/v1/rpc/upsert_user_family_context'
    assert json.loads(calls[-1].content) == {
        'p_project_id': 'project-family',
        'p_document': canonical,
        'p_expected_revision': 0,
    }


def test_turn_uploads_are_immutable_and_commit_carries_the_lease():
    owner = '11111111-1111-4111-8111-111111111111'
    token = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
    calls = []
    def server(request):
        calls.append(request)
        return httpx.Response(200, json={'id': owner} if request.url.path == '/auth/v1/user' else [])
    storage = UserStorage('https://example.supabase.co', 'public-key', 'user-jwt',
                          client=httpx.Client(transport=httpx.MockTransport(server)))
    path = storage.put_agent_turn_file(token, 'sessions/thread.jsonl', b'rollout')
    assert path == f'sessions/turns/{token}/thread.jsonl'
    assert calls[-1].headers['x-upsert'] == 'false'
    assert calls[-1].content == b'rollout'
    storage.commit_agent_turn(token, 'thread', 'memory', [path])
    assert calls[-1].url.path == '/rest/v1/rpc/commit_user_agent_turn'
    assert calls[-1].headers['authorization'] == 'Bearer user-jwt'
    assert json.loads(calls[-1].content) == {
        'p_lease_token': token, 'p_thread_id': 'thread', 'p_content': 'memory',
        'p_source_paths': [path],
    }


def test_stage_capture_and_composition_retrieval_use_durable_metadata():
    owner = '11111111-1111-4111-8111-111111111111'
    calls = []
    def server(request):
        calls.append(request)
        return httpx.Response(200, json={'id': owner} if request.url.path == '/auth/v1/user' else [])
    storage = UserStorage('https://example.supabase.co', 'public-key', 'user-jwt',
                          client=httpx.Client(transport=httpx.MockTransport(server)))
    storage.commit_agent_turn('lease', 'thread', 'memory', [], project_id='project', life_stage='childhood')
    assert json.loads(calls[-1].content)['p_life_stage'] == 'childhood'
    storage.commit_agent_turn('lease', 'thread', 'memory', [], project_id='project')
    assert json.loads(calls[-1].content)['p_life_stage'] == 'unplaced'
    storage.composition_memories()
    assert calls[-1].url.params['order'] == 'life_stage_order.asc,created_at.asc,id.asc'
    storage.all_memories()
    assert calls[-1].url.params['order'] == 'created_at.asc,id.asc'
