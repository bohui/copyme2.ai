"""Canonical recovery contracts. No model, worker, or live Supabase calls."""
from copy import deepcopy
import json
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes, supabase_routes
from apps.api.agent_storage import UserStorage
from apps.api.main import create_app
from apps.api.store import MemoryStore

OWNER = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
TURN = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
MEMORY = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
SOURCE = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
BASE = '/api/v1/memoir'
UNSAFE = 1790000000000000123


@pytest.fixture
def recovery(monkeypatch):
    rows = {
        'user_memoir_project': [dict(user_id=OWNER, project_id='project-a',
            source_sequence=UNSAFE, event_sequence=3, policy_epoch=1)],
        'user_memory': [], 'user_narrator_source': [], 'user_completed_round': [],
        'user_recall_usage': [dict(user_id=OWNER, rounds_completed=4)],
        'story_entitlements': [],
    }
    calls = []
    failure = {}

    def storage(authorization):
        if authorization not in ('Bearer owner', 'Bearer other'):
            from fastapi import HTTPException
            raise HTTPException(401, 'Supabase sign-in required')
        owner = OWNER if authorization == 'Bearer owner' else OTHER

        def server(request):
            calls.append(request)
            assert request.method == 'GET', 'Recovery must never mutate or generate'
            if request.url.path == '/auth/v1/user':
                return httpx.Response(200, json={'id': owner})
            table = request.url.path.rsplit('/', 1)[-1]
            if failure:
                return httpx.Response(failure['status'], json={'message': 'private-service-token'})
            query = dict(request.url.params)
            assert query['user_id'] == 'eq.' + owner, 'RLS plus explicit owner scope'
            result = deepcopy(rows[table])
            for key, value in query.items():
                if value.startswith('eq.'):
                    result = [r for r in result if str(r.get(key)) == value[3:]]
                elif value.startswith('gt.'):
                    result = [r for r in result if str(r.get(key)) > value[3:]]
                elif value.startswith('in.('):
                    values = value[4:-1].split(',')
                    result = [r for r in result if str(r.get(key)) in values]
            if query.get('order') == 'created_at.desc,id.desc':
                result.sort(key=lambda r: (r['created_at'], r['id']), reverse=True)
            elif query.get('order') == 'project_id.asc':
                result.sort(key=lambda r: r['project_id'])
            if 'or' in query:
                import re
                match = re.fullmatch(r'\(created_at.lt.([^,]+),and\(created_at.eq.([^,]+),id.lt.([^\)]+)\)\)', query['or'])
                assert match, 'Only validated keyset boundaries are accepted'
                timestamp, same_timestamp, memory_id = match.groups()
                assert timestamp == same_timestamp
                from datetime import datetime
                boundary = datetime.fromisoformat(timestamp)
                result = [r for r in result if (datetime.fromisoformat(r['created_at']), r['id']) < (boundary, memory_id)]
            return httpx.Response(200, json=result[:int(query.get('limit', 1000))])

        return UserStorage('https://example.supabase.co', 'public-key', authorization[7:],
            client=httpx.Client(transport=httpx.MockTransport(server)))

    monkeypatch.setattr(agent_routes, 'authenticated_storage', storage)
    monkeypatch.setattr(supabase_routes, 'storage', storage)
    return TestClient(create_app(MemoryStore())), rows, calls, failure


def source(**changes):
    return dict(dict(user_id=OWNER, project_id='project-a', id=SOURCE,
        client_turn_id=TURN, sequence=UNSAFE, version=1, kind='narrator_chat',
        text='I lived near the river.', language='en-AU', status='active',
        processing_status='pending', created_at='2026-10-07T05:00:00+00:00'), **changes)


def memory(**changes):
    return dict(dict(user_id=OWNER, project_id='project-a', id=MEMORY,
        client_turn_id=TURN, kind='agent', source_sequence=UNSAFE,
        content='Storyteller: I lived near the river.\nMemory Spark: What do you remember?',
        created_at='2026-10-07T05:00:00+00:00'), **changes)


def receipt(client, owner='owner', project='project-a'):
    return client.get(f'{BASE}/agent/turns/{TURN}', params={'project_id': project},
        headers={'Authorization': f'Bearer {owner}'})


def test_receipt_unknown_is_not_a_save_or_an_admission_claim(recovery):
    client, _, _, _ = recovery
    response = receipt(client)
    assert response.status_code == 200
    body = response.json()
    assert body['schema_version'] == 1
    assert body['state'] == 'not_found'
    assert body['conversation_saved'] is False
    assert body['server_turn_id'] is None and body['reply'] is None
    assert body['enrichment_state'] == 'unknown'
    assert body['recall_status']['rounds_completed'] == 4


def test_source_acceptance_does_not_claim_completed_exchange(recovery):
    client, rows, _, _ = recovery
    rows['user_narrator_source'] = [source()]
    body = receipt(client).json()
    assert body['state'] == 'source_accepted'
    assert body['conversation_saved'] is False
    assert body['source_id'] == SOURCE
    assert body['source_sequence'] == str(UNSAFE)
    assert body['source_version'] == '1'
    assert body['narrator_text'] == 'I lived near the river.'
    assert body['source_processing_state'] == 'pending'
    assert body['project_ordinal'] is None


def test_committed_receipt_replays_durable_reply_and_exact_counters(recovery):
    client, rows, _, _ = recovery
    rows['user_narrator_source'] = [source()]
    rows['user_memory'] = [memory()]
    rows['user_completed_round'] = [dict(user_id=OWNER, project_id='project-a',
        turn_id=TURN, memory_id=MEMORY, ordinal=UNSAFE)]
    body = receipt(client).json()
    assert body['state'] == 'conversation_saved' and body['conversation_saved'] is True
    assert body['server_turn_id'] == MEMORY
    assert body['reply'] == 'What do you remember?'
    assert body['conversation_sequence'] == str(UNSAFE)
    assert body['project_ordinal'] == str(UNSAFE)
    # A second HTTP request creates fresh storage and does not rely on process state.
    assert receipt(client).json() == body


def test_receipt_isolated_by_owner_and_project(recovery):
    client, rows, _, _ = recovery
    rows['user_narrator_source'] = [source()]
    rows['user_memory'] = [memory()]
    for response in (receipt(client, owner='other'), receipt(client, project='unowned-project')):
        assert response.status_code == 200
        assert response.json()['state'] == 'not_found'
        assert response.json()['reply'] is None
        assert response.json()['narrator_text'] is None


@pytest.mark.parametrize('status,text,version', [('withdrawn', '[withdrawn]', 2), ('active', 'Corrected testimony', 2)])
def test_changed_source_cannot_resurrect_old_text_or_reply(recovery, status, text, version):
    client, rows, _, _ = recovery
    rows['user_narrator_source'] = [source(status=status, text=text, version=version)]
    rows['user_memory'] = [memory()]
    body = receipt(client).json()
    assert body['conversation_saved'] is True
    assert body['reply'] is None
    assert body['narrator_text'] == (text if status == 'active' else None)
    history = client.get(f'{BASE}/user/projects/project-a/history', headers={'Authorization': 'Bearer owner'}).json()
    assert history['items'][0]['reply'] is None
    assert history['items'][0]['narrator_text'] == body['narrator_text']


def test_greeting_receipt_has_no_narrator_evidence(recovery):
    client, rows, _, _ = recovery
    rows['user_memory'] = [memory(kind='agent_greeting')]
    body = receipt(client).json()
    assert body['conversation_saved'] is True
    assert body['narrator_text'] is None
    assert body['source_id'] is None
    assert body['project_ordinal'] is None


def test_projects_are_canonical_owner_scoped_and_paginated(recovery):
    client, rows, _, _ = recovery
    rows['user_memoir_project'] += [dict(rows['user_memoir_project'][0], project_id='project-b'),
        dict(rows['user_memoir_project'][0], user_id=OTHER, project_id='secret-project')]
    response = client.get(f'{BASE}/user/projects?limit=1', headers={'Authorization': 'Bearer owner'})
    assert response.status_code == 200
    body = response.json()
    assert body['items'] == [dict(project_id='project-a', source_sequence=str(UNSAFE), event_sequence='3', policy_epoch='1')]
    assert body['next_after_project_id'] == 'project-a'
    page = client.get(f'{BASE}/user/projects?limit=1&after_project_id=project-a', headers={'Authorization': 'Bearer owner'}).json()
    assert page['items'][0]['project_id'] == 'project-b'
    assert page['next_after_project_id'] is None


def test_history_is_newest_page_in_chronological_order_with_greetings(recovery):
    client, rows, _, _ = recovery
    older = memory(id='00000000-0000-4000-8000-000000000001', created_at='2026-10-07T04:00:00+00:00', client_turn_id=None)
    rows['user_memory'] = [older, memory(), memory(id='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
        created_at='2026-10-07T06:00:00+00:00', kind='agent_greeting', client_turn_id=None)]
    rows['user_narrator_source'] = [source()]
    page = client.get(f'{BASE}/user/projects/project-a/history?limit=2', headers={'Authorization': 'Bearer owner'})
    assert page.status_code == 200
    body = page.json()
    assert [x['server_turn_id'] for x in body['items']] == [MEMORY, 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee']
    assert body['items'][1]['narrator_text'] is None
    assert body['items'][0]['source_id'] == SOURCE
    assert body['items'][0]['conversation_sequence'] == str(UNSAFE)
    assert body['policy_epoch'] == '1'
    assert body['next_cursor']
    second = client.get(f'{BASE}/user/projects/project-a/history', params={'cursor': body['next_cursor'], 'limit': 2}, headers={'Authorization': 'Bearer owner'}).json()
    assert [x['server_turn_id'] for x in second['items']] == [older['id']]
    assert second['next_cursor'] is None


def test_history_denies_missing_or_other_owner_project(recovery):
    client, rows, _, _ = recovery
    rows['user_memory'] = [memory()]
    response = client.get(f'{BASE}/user/projects/project-a/history', headers={'Authorization': 'Bearer other'})
    assert response.status_code == 404
    assert 'river' not in response.text


@pytest.mark.parametrize('path', [f'/agent/turns/{TURN}?project_id=project-a', '/user/projects', '/user/projects/project-a/history'])
def test_recovery_requires_bearer_authentication(recovery, path):
    client, _, _, _ = recovery
    assert client.get(BASE + path).status_code == 401


@pytest.mark.parametrize('suffix', [f'/agent/turns/not-a-uuid?project_id=project-a',
    f'/agent/turns/{TURN}?project_id=a,b', '/user/projects?limit=101',
    '/user/projects?after_project_id=a,b', '/user/projects/project-a/history?cursor=invalid'])
def test_recovery_rejects_invalid_contract_inputs(recovery, suffix):
    client, _, _, _ = recovery
    assert client.get(BASE + suffix, headers={'Authorization': 'Bearer owner'}).status_code == 422


def test_recovery_errors_are_safe_and_keep_shared_error_envelope(recovery):
    client, _, _, failure = recovery
    failure['status'] = 503
    response = receipt(client)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'TURN_RECEIPT_UNAVAILABLE'
    assert response.json()['error']['retryable'] is True
    assert response.headers['x-request-id']
    assert 'private-service-token' not in response.text


def test_openapi_exposes_typed_recovery_responses(recovery):
    client, _, _, _ = recovery
    schema = client.get('/openapi.json').json()
    for path in ['/v1/agent/turns/{client_turn_id}', '/v1/user/projects', '/v1/user/projects/{project_id}/history', '/v1/user/projects/{project_id}/sources/{source_id}']:
        response = schema['paths'][path]['get']['responses']['200']['content']['application/json']['schema']
        assert '$ref' in response

@pytest.fixture
def photo_search(monkeypatch):
    from apps.api import place_photo_pages
    calls = []
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL', raising=False)
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint', lambda url: {})
    def search(place, period, **kwargs):
        calls.append((place, period))
        return [dict(asset_id=f'photo-{index}', title='Chengde street', location='Chengde',
            date_expression='1983', image_url=f'https://images.example/{index}.jpg',
            source_url=f'https://archive.example/{index}', latitude=40.98, longitude=117.94,
            allowed_actions={'embed': True}) for index in range(21)]
    monkeypatch.setattr(place_photo_pages, 'search_place_photos', search)
    return calls


def test_bearer_photo_adapter_preserves_shared_pagination_and_provenance(recovery, photo_search):
    client, _, _, _ = recovery
    url = f'{BASE}/agent/places/project-a/photos'
    params = dict(place='Chengde', period='1980s', latitude=40.98, longitude=117.94)
    first = client.get(url, params=params, headers={'Authorization': 'Bearer owner'})
    assert first.status_code == 200
    body = first.json()
    assert len(body['items']) == 10 and body['count'] == 21
    assert body['items'][0]['source_url'] == 'https://archive.example/0'
    assert body['items'][0]['search_fallback'] == 'none'
    second = client.get(url, params={**params, 'cursor': body['next_cursor']}, headers={'Authorization': 'Bearer owner'})
    assert second.status_code == 200 and len(second.json()['items']) == 10
    assert len(photo_search) == 1


def test_photo_cursor_cannot_cross_owner_or_project(recovery, photo_search):
    client, rows, _, _ = recovery
    rows['user_memoir_project'] += [dict(rows['user_memoir_project'][0], user_id=OTHER),
        dict(rows['user_memoir_project'][0], project_id='project-b')]
    params = dict(place='Chengde', period='1980s', latitude=40.98, longitude=117.94)
    first = client.get(f'{BASE}/agent/places/project-a/photos', params=params, headers={'Authorization': 'Bearer owner'})
    assert first.status_code == 200
    params['cursor'] = first.json()['next_cursor']
    assert client.get(f'{BASE}/agent/places/project-a/photos', params=params, headers={'Authorization': 'Bearer other'}).status_code == 422
    assert client.get(f'{BASE}/agent/places/project-b/photos', params=params, headers={'Authorization': 'Bearer owner'}).status_code == 422
    assert len(photo_search) == 1


def test_photo_adapter_authenticates_before_discovery(recovery, photo_search):
    client, _, _, _ = recovery
    url = f'{BASE}/agent/places/project-a/photos?place=Chengde'
    assert client.get(url, headers={'X-Account-Id': OWNER}).status_code == 401
    assert client.get(url, headers={'Authorization': 'Bearer other'}).status_code == 404
    assert photo_search == []


def test_photo_adapter_keeps_both_coordinate_and_stream_contracts(recovery, photo_search):
    client, _, _, _ = recovery
    url = f'{BASE}/agent/places/project-a/photos'
    headers = {'Authorization': 'Bearer owner'}
    assert client.get(url, params=dict(place='Chengde', latitude=40.98), headers=headers).status_code == 422
    response = client.get(url, params=dict(place='Chengde', period='1980s'),
        headers={**headers, 'Accept': 'application/x-ndjson'})
    assert response.status_code == 200
    frames = [json.loads(line) for line in response.text.splitlines()]
    assert frames[-1]['items'][0]['search_fallback'] == 'gps'
    assert frames[-1]['searching'] is False


def test_history_cursor_rejects_another_owner_and_project_even_when_they_exist(recovery):
    client, rows, _, _ = recovery
    rows['user_memory'] = [memory(), memory(id='dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        client_turn_id=None, created_at='2026-10-07T06:00:00+00:00')]
    rows['user_memoir_project'] += [dict(rows['user_memoir_project'][0], user_id=OTHER),
        dict(rows['user_memoir_project'][0], project_id='project-b')]
    page = client.get(f'{BASE}/user/projects/project-a/history?limit=1', headers={'Authorization': 'Bearer owner'}).json()
    for owner, project in [('other', 'project-a'), ('owner', 'project-b')]:
        response = client.get(f'{BASE}/user/projects/{project}/history', params={'cursor': page['next_cursor']},
            headers={'Authorization': f'Bearer {owner}'})
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'INVALID_HISTORY_CURSOR'


def test_history_tie_break_and_newer_insert_do_not_duplicate_an_older_page(recovery):
    client, rows, _, _ = recovery
    rows['user_memory'] = [memory(), memory(id='dddddddd-dddd-4ddd-8ddd-dddddddddddd', client_turn_id=None)]
    first = client.get(f'{BASE}/user/projects/project-a/history?limit=1', headers={'Authorization': 'Bearer owner'}).json()
    rows['user_memory'].append(memory(id='eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
        client_turn_id=None, created_at='2026-10-07T06:00:00+00:00'))
    second = client.get(f'{BASE}/user/projects/project-a/history', params={'limit': 1, 'cursor': first['next_cursor']},
        headers={'Authorization': 'Bearer owner'}).json()
    assert [item['server_turn_id'] for item in second['items']] == [MEMORY]
    assert second['next_cursor'] is None


def test_history_masks_withdrawn_backfilled_legacy_source(recovery):
    client, rows, _, _ = recovery
    rows['user_memory'] = [memory(client_turn_id=None)]
    rows['user_narrator_source'] = [source(client_turn_id=MEMORY, status='withdrawn', version=2)]
    response = client.get(f'{BASE}/user/projects/project-a/history', headers={'Authorization': 'Bearer owner'})
    assert response.status_code == 200
    assert response.json()['items'][0]['narrator_text'] is None
    assert response.json()['items'][0]['reply'] is None


@pytest.mark.parametrize('path', [f'/agent/turns/{TURN}?project_id=project-a', '/user/projects',
    '/user/projects/project-a/history', '/agent/places/project-a/photos?place=Chengde',
    f'/user/projects/project-a/sources/{SOURCE}'])
def test_recovery_routes_use_real_supabase_auth_boundary(monkeypatch, path):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    client = TestClient(create_app(MemoryStore()))
    response = client.get(BASE + path, headers={'X-Account-Id': OWNER})
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'UNAUTHENTICATED'


def test_source_detail_reads_current_canonical_evidence_without_family_entitlement(recovery):
    client, rows, _, _ = recovery
    rows['user_narrator_source'] = [source(version=3, kind='narrator_transcript', text='My corrected transcript.')]
    url = f'{BASE}/user/projects/project-a/sources/{SOURCE}'
    response = client.get(url, headers={'Authorization': 'Bearer owner'})
    assert response.status_code == 200
    assert response.json() == dict(schema_version=1, id=SOURCE, project_id='project-a',
        version='3', sequence=str(UNSAFE), text='My corrected transcript.',
        source_kind='narrator_transcript', status='active', language='en-AU',
        created_at='2026-10-07T05:00:00+00:00')
    assert client.get(url, params={'expected_version': '3'}, headers={'Authorization': 'Bearer owner'}).json() == response.json()


def test_source_detail_rejects_stale_citation_version_without_disclosing_changed_text(recovery):
    client, rows, _, _ = recovery
    rows['user_narrator_source'] = [source(version=2, text='My corrected private testimony.')]
    response = client.get(f'{BASE}/user/projects/project-a/sources/{SOURCE}',
        params={'expected_version': '1'}, headers={'Authorization': 'Bearer owner'})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'SOURCE_REVISION_CONFLICT'
    assert 'testimony' not in response.text


def test_source_detail_revocation_never_returns_text(recovery):
    client, rows, _, _ = recovery
    rows['user_narrator_source'] = [source(status='withdrawn')]
    response = client.get(f'{BASE}/user/projects/project-a/sources/{SOURCE}', headers={'Authorization': 'Bearer owner'})
    assert response.status_code == 410
    assert response.json()['error']['code'] == 'SOURCE_WITHDRAWN'
    assert 'river' not in response.text


@pytest.mark.parametrize('owner,project', [('other', 'project-a'), ('owner', 'project-b')])
def test_source_detail_is_scoped_to_owner_and_project(recovery, owner, project):
    client, rows, _, _ = recovery
    rows['user_narrator_source'] = [source()]
    response = client.get(f'{BASE}/user/projects/{project}/sources/{SOURCE}', headers={'Authorization': f'Bearer {owner}'})
    assert response.status_code == 404
    assert 'river' not in response.text


@pytest.mark.parametrize('suffix', ['not-a-uuid', SOURCE + '?expected_version=0', SOURCE + '?expected_version=1,2'])
def test_source_detail_validates_source_and_revision_ids(recovery, suffix):
    client, _, _, _ = recovery
    assert client.get(f'{BASE}/user/projects/project-a/sources/{suffix}', headers={'Authorization': 'Bearer owner'}).status_code == 422


def test_source_detail_auth_errors_and_unavailability_are_safe(recovery):
    client, _, _, failure = recovery
    url = f'{BASE}/user/projects/project-a/sources/{SOURCE}'
    assert client.get(url).status_code == 401
    failure['status'] = 503
    response = client.get(url, headers={'Authorization': 'Bearer owner'})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'SOURCE_UNAVAILABLE'
    assert response.headers['x-request-id']
    assert 'private-service-token' not in response.text


@pytest.mark.parametrize('rpc_result,expected', [
    ({'prepared': True}, {'prepared': True, 'expires_in': 3600}),
    ({'prepared': False}, {'prepared': False}),
    ({'prepared': 'true'}, {'prepared': 'true'}),
])
def test_transfer_prepare_exposes_retention_cap_only_after_success(monkeypatch, rpc_result, expected):
    from unittest.mock import Mock
    service = Mock(user_id=OWNER, is_anonymous=True)
    service.request.return_value.json.return_value = rpc_result
    monkeypatch.setattr(supabase_routes, 'storage', lambda authorization: service)
    monkeypatch.setattr(supabase_routes, '_wait_for_deliveries', lambda service: None)
    token = 'ab' * 32
    payload = dict(token=token, project_id='project-a', messages=[{'role': 'user', 'text': 'My story'}])
    client = TestClient(create_app(MemoryStore()))
    for _ in range(2):
        response = client.post(f'{BASE}/user/conversation-transfer', json=payload,
            headers={'Authorization': 'Bearer guest'})
        assert response.status_code == 200
        assert response.json() == expected
        assert service.request.call_args.kwargs['json']['p_token'] == token
        assert service.request.call_args.kwargs['json']['p_messages'] == payload['messages']
        assert token not in response.text
    assert service.request.call_count == 2
