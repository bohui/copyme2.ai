"""Exercise recovery and subsequent access through the real HTTP boundary."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api import main, supabase_routes
from apps.api.store import MemoryStore


OWNER = {'Authorization': 'Bearer owner-session'}
OTHER = {'Authorization': 'Bearer other-session'}
OPERATOR = {'Authorization': 'Bearer support-session'}
FINANCE = {'Authorization': 'Bearer finance-session'}


@pytest.fixture
def recovery(monkeypatch, request):
    tables = {'owner': {'user_memoir_project': ['project_saved']}, 'other': {}, 'support': {}, 'finance': {}}
    services = {}
    for user in tables:
        service = Mock()
        service.user_id = user
        roles = {'support': ['operator'], 'finance': ['finance']}.get(user, [])
        service.user = {'id': user, 'app_metadata': {'roles': roles},
                        'user_metadata': {}, 'is_anonymous': False}
        if user == 'other' and hasattr(request, 'param'):
            service.user.update(request.param)
        service.profile.return_value = {'name': f'{user} private profile'}
        service.all_memories.return_value = []

        def request(method, path, *, params=None, user=user):
            assert method == 'GET'
            assert params['user_id'] == f'eq.{user}'
            ids = tables[user].get(path.rsplit('/', 1)[-1], [])
            wanted = params.get('project_id', '').removeprefix('eq.')
            rows = [{'id': project, 'project_id': project, 'created_at': '2026-10-07',
                     'messages': [], 'workspace': {}} for project in ids if not wanted or project == wanted]
            return Mock(json=lambda: rows)

        service.request.side_effect = request
        services[user] = service

    def authenticated(authorization):
        if authorization == OWNER['Authorization']:
            return services['owner']
        if authorization == OTHER['Authorization']:
            return services['other']
        if authorization == OPERATOR['Authorization']:
            return services['support']
        if authorization == FINANCE['Authorization']:
            return services['finance']
        raise HTTPException(401, 'Invalid or missing session')

    monkeypatch.setattr(main, 'authenticated_storage', authenticated)
    monkeypatch.setattr(supabase_routes, 'storage', authenticated)
    monkeypatch.setattr(supabase_routes, '_queue_if_configured', lambda: None)
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        yield client, store, tables


def restore(client, headers=OWNER, **fields):
    return client.post('/v1/projects', headers=headers,
                       json={'restore_project_id': 'project_saved', **fields})


@pytest.mark.parametrize('method', ['get', 'patch'])
@pytest.mark.parametrize('headers,expected', [
    ({}, 401),
    ({'X-Account-Id': 'demo-storyteller'}, 401),
    ({'X-Account-Id': 'owner'}, 401),
    (OTHER, 403),
    ({**OTHER, 'X-Account-Id': 'owner'}, 403),
])
def test_recovered_profile_requires_its_verified_principal(recovery, method, headers, expected):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    before = dict(store.projects['project_saved']['profile'])
    options = {'json': {'profile': {'name': 'unauthorized change'}}} if method == 'patch' else {}
    response = getattr(client, method)('/v1/projects/project_saved', headers=headers, **options)
    assert response.status_code == expected
    assert 'owner private profile' not in response.text
    assert store.projects['project_saved']['profile'] == before


def test_verified_owner_can_read_and_mutate_without_an_account_header(recovery):
    client, store, _ = recovery
    result = restore(client)
    assert result.status_code == 201
    assert result.json()['owner_id'] == 'owner'
    assert result.json()['storyteller_id'] == 'owner'
    assert set(store.projects['project_saved']['members']) == {'owner'}
    assert client.get('/v1/projects/project_saved', headers=OWNER).status_code == 200
    changed = client.patch('/v1/projects/project_saved', headers=OWNER, json={'profile': {'name': 'Owner edit'}})
    assert changed.status_code == 200
    assert changed.json()['profile']['name'] == 'Owner edit'
    assert restore(client).json()['profile']['name'] == 'Owner edit'


@pytest.mark.parametrize('headers', [
    {}, {'X-Role': 'operator'}, {'X-Account-Id': 'ops-attacker'},
    {'X-Account-Id': 'operator-attacker'}, {**OTHER, 'X-Role': 'operator'},
    {**OTHER, 'X-Role': 'admin'}, {**OTHER, 'X-Role': 'finance'},
    {**OWNER, 'X-Role': 'operator'}, {**OTHER, 'X-Account-Id': 'owner', 'X-Role': 'operator'},
])
@pytest.mark.parametrize('operation', ['list', 'retry', 'cancel'])
def test_forged_operator_identity_cannot_read_or_mutate_recovered_jobs(recovery, headers, operation):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    job = store.queue_job('project_saved', 'BuildFreePreview',
                          {'private_story': 'Synthetic owner-only recollection'})
    path = '/v1/jobs/' + job['id']
    before = client.get(path, headers=OWNER).json()
    if operation == 'list':
        response = client.get('/v1/ops/jobs', headers=headers)
    else:
        response = client.post('/v1/ops/jobs/' + job['id'] + '/' + operation, headers=headers)
    assert response.status_code == 403
    assert client.get(path, headers=OWNER).json() == before
    assert 'Synthetic owner-only recollection' not in response.text


@pytest.mark.parametrize('recovery', [
    {'app_metadata': {}, 'user_metadata': {'roles': ['operator', 'admin']}},
    {'app_metadata': {'roles': 'operator'}},
    {'app_metadata': {'roles': ['operator', 7]}},
    {'app_metadata': 'operator'},
    {'app_metadata': {'role': 'admin'}},
    {'app_metadata': {'roles': ['fulfilment']}},
], indirect=True)
def test_user_editable_or_malformed_roles_cannot_authorize_operator_actions(recovery):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    job = store.queue_job('project_saved', 'BuildFreePreview', {'private_story': 'Owner-only story'})
    path = '/v1/jobs/' + job['id']
    before = client.get(path, headers=OWNER).json()
    forged = {**OTHER, 'X-Role': 'operator'}
    assert client.get('/v1/ops/jobs', headers=forged).status_code == 403
    assert client.post('/v1/ops/jobs/' + job['id'] + '/cancel', headers=forged).status_code == 403
    assert client.get(path, headers=OWNER).json() == before


def test_unverified_bearer_cannot_supply_operator_claims(recovery):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    job = store.queue_job('project_saved', 'BuildFreePreview', {'private_story': 'Owner-only story'})
    path = '/v1/jobs/' + job['id']
    before = client.get(path, headers=OWNER).json()
    response = client.post('/v1/ops/jobs/' + job['id'] + '/cancel', headers={
        'Authorization': 'Bearer unverified-operator-claim', 'X-Role': 'admin',
    })
    assert response.status_code == 401
    assert client.get(path, headers=OWNER).json() == before


@pytest.mark.parametrize('operation', ['list', 'retry', 'cancel'])
def test_verified_operator_job_actions_return_only_metadata(recovery, operation):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    job = store.queue_job('project_saved', 'BuildFreePreview',
                          {'private_story': 'Synthetic owner-only recollection'})
    store.fail_job(job['id'], 'PROVIDER_UNAVAILABLE', 'Synthetic owner-only failure payload')
    job['result'] = {'manuscript': 'Synthetic private generated prose'}
    job['provider_debug'] = {'source': 'Synthetic private provider diagnostic'}
    if operation == 'list':
        response = client.get('/v1/ops/jobs', headers=OPERATOR)
    else:
        response = client.post('/v1/ops/jobs/' + job['id'] + '/' + operation, headers=OPERATOR)
    assert response.status_code == 200
    metadata = response.json()['items'][0] if operation == 'list' else response.json()
    expected_status = {'list': 'FAILED', 'retry': 'QUEUED', 'cancel': 'CANCELLED'}[operation]
    assert metadata['status'] == expected_status
    assert 'snapshot' not in metadata and 'result' not in metadata and 'error' not in metadata
    assert 'Synthetic owner-only recollection' not in response.text
    assert 'Synthetic owner-only failure payload' not in response.text
    assert 'Synthetic private generated prose' not in response.text
    assert 'Synthetic private provider diagnostic' not in response.text
    path = '/v1/jobs/' + job['id']
    owner_view = client.get(path, headers=OWNER).json()
    assert owner_view['status'] == expected_status
    assert owner_view['snapshot'] == {'private_story': 'Synthetic owner-only recollection'}
    assert client.get(path, headers=OPERATOR).status_code == 403


def test_finance_identity_can_read_job_metadata_but_cannot_cancel_owner_work(recovery):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    job = store.queue_job('project_saved', 'BuildFreePreview', {'private_story': 'Synthetic private story'})
    listed = client.get('/v1/ops/jobs', headers=FINANCE)
    assert listed.status_code == 200
    assert 'Synthetic private story' not in listed.text
    denied = client.post('/v1/ops/jobs/' + job['id'] + '/cancel',
                         headers={**FINANCE, 'X-Role': 'operator'})
    assert denied.status_code == 403
    assert client.get('/v1/jobs/' + job['id'], headers=OWNER).json()['status'] == 'QUEUED'
    assert client.get('/v1/jobs/' + job['id'], headers=FINANCE).status_code == 403


@pytest.mark.parametrize('headers,expected', [
    ({'X-Account-Id': 'ops-attacker'}, 401),
    ({'X-Account-Id': 'operator-attacker'}, 401),
    ({'X-Role': 'operator'}, 401),
    ({**OTHER, 'X-Role': 'operator'}, 403),
    ({**OTHER, 'X-Role': 'admin'}, 403),
    ({**FINANCE, 'X-Role': 'operator'}, 403),
])
def test_operator_prefixes_and_forged_roles_cannot_invalidate_private_print_proof(recovery, headers, expected):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    order = {'id': 'print-fixture', 'project_id': 'project_saved',
             'supplier_manifest_hash': 'approved-manifest', 'status': 'CUSTOMER_APPROVED',
             'proof_approval': {'approved': True}, 'proof': {'manifest_hash': 'approved-manifest'}}
    store.print_orders[order['id']] = order
    path = '/v1/print-orders/' + order['id']
    before = client.get(path, headers=OWNER).json()
    response = client.post(path + '/supplier-update', headers=headers, json={'manifest_hash': 'forged-manifest'})
    assert response.status_code == expected
    assert client.get(path, headers=OWNER).json() == before
    assert 'approved-manifest' not in response.text


def test_scoped_support_metadata_requires_the_verified_grant_recipient(recovery):
    client, _, _ = recovery
    assert restore(client).status_code == 201
    created = client.post('/v1/ops/support-grants', headers=OPERATOR,
                          json={'project_id': 'project_saved', 'account_id': 'other',
                                'capabilities': ['read_metadata']})
    assert created.status_code == 201
    path = '/v1/ops/support-grants/' + created.json()['id'] + '/projects/project_saved/metadata'
    assert client.get(path, headers={'X-Account-Id': 'other'}).status_code == 401
    assert client.get(path, headers=OWNER).status_code == 403
    granted = client.get(path, headers=OTHER)
    assert granted.status_code == 200 and granted.json()['project_id'] == 'project_saved'
    assert 'owner private profile' not in granted.text


def test_restore_cannot_assign_the_private_profile_to_another_account(recovery):
    client, store, _ = recovery
    assert restore(client, {**OWNER, 'X-Account-Id': 'other'}).status_code == 403
    assert not store.projects


@pytest.mark.parametrize('fields', [
    {'mode': 'family', 'storyteller_account_id': 'other'},
    {'storyteller_account_id': 'other'},
])
def test_recovery_does_not_grant_caller_selected_storyteller_membership(recovery, fields):
    client, store, _ = recovery
    assert restore(client, **fields).status_code == 422
    assert not store.projects


def test_repeated_restore_rejects_another_verified_owner_even_if_ids_collide(recovery):
    client, store, tables = recovery
    assert restore(client).status_code == 201
    tables['other']['user_memoir_project'] = ['project_saved']
    assert restore(client, OTHER).status_code == 403
    assert store.projects['project_saved']['profile']['name'] == 'owner private profile'
    assert store.projects['project_saved']['owner_id'] == 'owner'


def test_recovery_does_not_copy_private_profile_into_an_unbound_local_collision(recovery):
    client, store, _ = recovery
    original = client.post('/v1/projects', json={}).json()
    project = store.projects.pop(original['id'])
    project['id'] = 'project_saved'
    store.projects['project_saved'] = project
    assert restore(client).status_code == 409
    assert store.projects['project_saved']['profile']['name'] != 'owner private profile'
    assert store.projects['project_saved']['owner_id'] == 'demo-storyteller'


@pytest.mark.parametrize('path', ['/v1/projects/project_saved/journey',
                                  '/api/v1/memoir/projects/project_saved/events'])
def test_secondary_and_canonical_routes_enforce_recovered_ownership(recovery, path):
    client, _, _ = recovery
    assert restore(client).status_code == 201
    assert client.get(path, headers={'X-Account-Id': 'owner'}).status_code == 401
    assert client.get(path, headers=OTHER).status_code == 403
    assert client.get(path, headers=OWNER).status_code == 200


def test_attachment_only_resume_id_can_be_recovered_by_its_verified_owner(recovery):
    client, store, tables = recovery
    tables['owner'] = {'user_conversation_attachment': ['project_saved']}
    history = client.get('/v1/user/conversations', headers=OWNER)
    assert history.json()['resume_project_id'] == 'project_saved'
    assert restore(client, OTHER).status_code == 404
    assert restore(client).status_code == 201
    assert store.projects['project_saved']['owner_id'] == 'owner'


def test_invitation_cannot_mutate_recovered_membership_before_authorization(recovery):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    invitation = client.post('/v1/projects/project_saved/invitations', headers=OWNER,
        json={'intended_role': 'contributor', 'capability_set': ['record']})
    assert invitation.status_code == 201
    response = client.post('/v1/invitations/' + invitation.json()['token'] + '/accept',
                           headers={'X-Account-Id': 'owner'})
    assert response.status_code == 401
    assert set(store.projects['project_saved']['members']) == {'owner'}
    assert not store.invitations[invitation.json()['id']]['redeemed_at']


def test_indirect_session_routes_keep_the_verified_project_boundary(recovery):
    client, _, _ = recovery
    assert restore(client).status_code == 201
    session = client.post('/v1/projects/project_saved/memory-sessions', headers=OWNER, json={})
    assert session.status_code == 201
    path = '/v1/memory-sessions/' + session.json()['id']
    assert client.get(path, headers={'X-Account-Id': 'owner'}).status_code == 401
    assert client.get(path, headers=OTHER).status_code == 403
    assert client.get(path, headers=OWNER).status_code == 200


def test_explicitly_authenticated_creation_retains_its_authentication_contract(recovery):
    client, _, _ = recovery
    result = client.post('/v1/projects', headers=OWNER, json={'storyteller_name': 'New private profile'})
    assert result.status_code == 201
    assert result.json()['requires_supabase_auth'] is True
    path = '/v1/projects/' + result.json()['id']
    assert client.get(path, headers={'X-Account-Id': 'owner'}).status_code == 401
    assert client.get(path, headers=OWNER).status_code == 200


@pytest.mark.parametrize('operation', ['resolve', 'grant', 'revoke-grant', 'revoke-link',
                                      'checkout', 'read-order', 'supplier-update'])
def test_direct_resource_routes_reject_forged_owner_headers(recovery, operation):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    project = store.projects['project_saved']
    link = {'id': 'audio-fixture', 'project_id': 'project_saved', 'edition_id': 'edition-fixture',
            'revoked': False, 'grants': {}}
    project['audio_links'] = {link['id']: link}
    grant = client.post('/v1/audio-links/audio-fixture/grants', headers=OWNER, json={}).json()
    store.orders['order-fixture'] = {'id': 'order-fixture', 'beneficiary_project_id': 'project_saved',
                                     'payer_account_id': 'owner'}
    print_order = {'id': 'print-fixture', 'project_id': 'project_saved', 'payer_account_id': 'owner',
                   'supplier_manifest_hash': 'before', 'status': 'CUSTOMER_APPROVED', 'proof_approval': {'approved': True},
                   'proof': {'manifest_hash': 'before'}}
    store.print_orders['print-fixture'] = print_order
    headers = {'X-Account-Id': 'owner'}
    path = '/v1/audio-links/audio-fixture'
    if operation == 'resolve': response = client.get(path, headers=headers)
    elif operation == 'grant': response = client.post(path + '/grants', headers=headers, json={})
    elif operation == 'revoke-grant': response = client.post(path + '/grants/' + grant['id'] + '/revoke', headers=headers)
    elif operation == 'revoke-link': response = client.post(path + '/revoke', headers=headers)
    elif operation == 'checkout': response = client.post('/v1/projects/project_saved/checkout', headers=headers, json={})
    elif operation == 'read-order': response = client.get('/v1/orders/order-fixture', headers=headers)
    else: response = client.post('/v1/print-orders/print-fixture/supplier-update', headers=headers,
                                 json={'manifest_hash': 'forged'})
    assert response.status_code == 401
    assert not link['revoked']
    assert len(link['grants']) == 1 and not link['grants'][grant['id']]['revoked']
    assert len(store.orders) == 1
    assert print_order['status'] == 'CUSTOMER_APPROVED'
    assert print_order['proof_approval'] == {'approved': True}


def test_authorized_audio_share_token_remains_readable_without_owner_identity(recovery):
    client, store, _ = recovery
    assert restore(client).status_code == 201
    store.projects['project_saved']['audio_links'] = {'audio-fixture': {
        'id': 'audio-fixture', 'project_id': 'project_saved', 'edition_id': 'edition-fixture',
        'revoked': False, 'grants': {}}}
    path = '/v1/audio-links/audio-fixture'
    grant = client.post(path + '/grants', headers=OWNER, json={})
    assert grant.status_code == 201
    assert client.get(path, params={'token': grant.json()['token']}).status_code == 200
    assert client.get(path, params={'token': 'invalid'}, headers={'X-Account-Id': 'owner'}).status_code == 401
    assert client.post(path + '/grants/' + grant.json()['id'] + '/revoke', headers=OWNER).status_code == 200
    assert client.get(path, params={'token': grant.json()['token']}).status_code == 401


def test_authenticated_family_creation_preserves_verified_storyteller_access(recovery):
    client, _, _ = recovery
    created = client.post('/v1/projects', headers=OWNER,
        json={'mode': 'family', 'storyteller_account_id': 'other', 'storyteller_name': 'Shared family profile'})
    assert created.status_code == 201
    path = '/v1/projects/' + created.json()['id']
    assert client.get(path, headers=OTHER).status_code == 200
    assert client.get(path, headers={'X-Account-Id': 'other'}).status_code == 401


def test_authenticated_creation_idempotency_does_not_bypass_identity(recovery):
    client, _, _ = recovery
    headers = {**OWNER, 'Idempotency-Key': 'same-creation'}
    first = client.post('/v1/projects', headers=headers, json={})
    assert first.status_code == 201
    forged = client.post('/v1/projects', json={},
        headers={'X-Account-Id': 'owner', 'Idempotency-Key': 'same-creation'})
    assert forged.status_code == 401
    assert client.post('/v1/projects', headers=headers, json={}).json()['id'] == first.json()['id']


def test_parallel_requests_do_not_share_verified_principals(recovery):
    from concurrent.futures import ThreadPoolExecutor
    client, _, _ = recovery
    assert restore(client).status_code == 201
    headers = [OWNER, OTHER, {}] * 3
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda h: client.get('/v1/projects/project_saved', headers=h).status_code, headers))
    assert results == [200, 403, 401] * 3


def test_family_membership_does_not_authorize_same_id_recovery_as_another_owner(recovery):
    client, store, tables = recovery
    created = client.post('/v1/projects', headers=OWNER,
                         json={'mode': 'family', 'storyteller_account_id': 'other'}).json()
    project = store.projects.pop(created['id'])
    project['id'] = 'project_saved'
    store.projects['project_saved'] = project
    tables['other']['user_memoir_project'] = ['project_saved']
    assert client.get('/v1/projects/project_saved', headers=OTHER).status_code == 200
    assert restore(client, OTHER).status_code == 403
    assert project['supabase_owner_id'] == 'owner'


def test_registered_external_payer_retains_order_access_with_verified_identity(recovery):
    client, _, _ = recovery
    assert restore(client).status_code == 201
    checkout = client.post('/v1/projects/project_saved/checkout', headers=OTHER,
                           json={'beneficiary_project_id': 'project_saved'})
    assert checkout.status_code == 201
    path = '/v1/orders/' + checkout.json()['id']
    assert client.get(path, headers=OTHER).status_code == 200
    assert client.get(path, headers={'X-Account-Id': 'other'}).status_code == 401


def test_prototype_cookie_cannot_replace_the_recovered_supabase_principal(recovery):
    from datetime import datetime, timedelta, timezone
    client, store, _ = recovery
    assert restore(client).status_code == 201
    store.auth_sessions[main._token_hash('prototype-cookie')] = {
        'account_id': 'owner', 'csrf_token_hash': main._token_hash('csrf'),
        'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        'revoked_at': None}
    client.cookies.set('memory_spark_session', 'prototype-cookie')
    assert client.get('/v1/projects/project_saved').status_code == 401
    result = client.patch('/v1/projects/project_saved', headers=OWNER, json={'profile': {'name': 'Verified edit'}})
    assert result.status_code == 200
