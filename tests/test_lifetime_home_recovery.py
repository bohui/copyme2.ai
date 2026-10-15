"""Product-home identity and guest recovery against isolated real PostgreSQL."""
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api import main, supabase_routes
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest, quoted
from test_agent_commit_postgres import OWNER, OTHER, as_user
from test_lifetime_memory_postgres import database, attachment_database, private_database, event_database
from test_shared_memory_events_postgres import sql, rpc, literal
from test_guest_conversation_transfer import TOKEN, THIRD


class HomeRest(PostgresRest):
    """Add the existing attachment recovery read to the real-RLS test facade."""
    def handle(self, request):
        if request.url.path == '/auth/v1/user':
            anonymous = self.sql(f"select is_anonymous from auth.users where id={quoted(self.owner)};").stdout.strip() == 't'
            return httpx.Response(200, json={'id': self.owner, 'is_anonymous': anonymous})
        if request.method == 'GET' and request.url.path == '/rest/v1/user_conversation_attachment':
            params = request.url.params
            assert params['user_id'] == 'eq.' + self.owner
            project = params['project_id'].removeprefix('eq.')
            query = f"select coalesce(jsonb_agg(to_jsonb(a)),'[]') from public.user_conversation_attachment a where user_id={quoted(self.owner)} and project_id={quoted(project)}"
            if 'workspace->>guest_user_id' in params:
                query += " and workspace->>'guest_user_id'=" + quoted(params['workspace->>guest_user_id'].removeprefix('eq.'))
            result = self.sql(as_user(query + ';', self.owner))
            return httpx.Response(200, json=json.loads(result.stdout.splitlines()[-1]))
        return super().handle(request)


@pytest.fixture
def home_auth(sql, monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    tokens = {'owner': OWNER, 'owner-new-device': OWNER, 'reauthenticated': OWNER, 'other': OTHER, 'third': THIRD}
    def storage(authorization):
        token = (authorization or '').removeprefix('Bearer ')
        if token not in tokens:
            raise HTTPException(401, 'Invalid or expired Supabase session')
        return HomeRest(sql, tokens[token]).storage()
    monkeypatch.setattr(main, 'authenticated_storage', storage)
    monkeypatch.setattr(supabase_routes, 'storage', storage)
    return tokens


def headers(token='owner'):
    return {'Authorization': 'Bearer ' + token}


def identity(sql, owner=OWNER):
    return rpc(sql, 'resolve_lifetime_conversation', 'null', owner=owner)


def test_product_home_new_account_reuses_identity_after_restart_and_reauthentication(sql, home_auth):
    profile = {'name': 'Joan', 'preferred_language': 'zh-CN'}
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}',{literal(profile)}::jsonb);")
    first_store = MemoryStore()
    with TestClient(main.create_app(first_store)) as client:
        first = client.post('/v1/projects', headers=headers(), json={})
        assert first.status_code == 201, first.text
        canonical = identity(sql)
        assert first.json()['id'] == canonical['project_id']
        assert first.json()['profile']['name'] == 'Joan'
        repeated = client.post('/v1/projects', headers=headers('owner-new-device'), json={})
        assert repeated.status_code == 201 and repeated.json()['id'] == first.json()['id']
        assert list(first_store.projects) == [canonical['project_id']]
        assert client.get('/v1/projects/' + canonical['project_id']).status_code == 401
    # Lost process-local adapter and 12 months of absence do not affect identity.
    sql("update public.user_lifetime_conversation set created_at=clock_timestamp()-interval '12 months';")
    home_auth.pop('owner')
    recovered = MemoryStore()
    with TestClient(main.create_app(recovered)) as client:
        assert client.post('/v1/projects', headers=headers(), json={}).status_code == 401
        returned = client.post('/v1/projects', headers=headers('reauthenticated'), json={})
        assert returned.status_code == 201 and returned.json()['id'] == canonical['project_id']
    assert identity(sql) == canonical
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '1'
    assert sql('select count(*) from public.user_memoir_project;').stdout.strip() == '1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip() == '0'


def test_two_product_home_devices_resolve_one_database_identity(sql, home_auth):
    def visit(token):
        with TestClient(main.create_app(MemoryStore())) as client:
            response = client.post('/v1/projects', headers=headers(token), json={})
            assert response.status_code == 201, response.text
            return response.json()['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        projects = list(pool.map(visit, ['owner', 'owner-new-device']))
    assert projects == [identity(sql)['project_id']] * 2


@pytest.mark.parametrize('projects', [('old',), ('old', 'new')])
def test_home_mapping_required_preserves_all_legacy_ids_and_explicit_restoration(sql, home_auth, projects):
    originals = [rpc(sql, 'accept_user_interview_turn', f"'{project}','{uuid4()}','Original testimony'") for project in projects]
    before = sql('select row_to_json(t) from public.user_interview_turn t order by project_id;').stdout
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response = client.post('/v1/projects', headers=headers(), json={})
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == {'schema_version': 1, 'outcome': 'mapping_required', 'project_ids': sorted(projects)}
        assert response.headers['x-error-code'] == 'LIFETIME_MAPPING_REQUIRED'
        assert not store.projects
        for project in projects:
            restored = client.post('/v1/projects', headers=headers(), json={'restore_project_id': project})
            assert restored.status_code == 201 and restored.json()['id'] == project
    assert sql('select row_to_json(t) from public.user_interview_turn t order by project_id;').stdout == before
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    assert all(rpc(sql, 'read_user_interview_turn', f"'{project}','{original['client_turn_id']}'")['source']['id'] == original['source']['id'] for project, original in zip(projects, originals))


def test_home_rejects_owner_and_restore_substitution_without_claiming_history(sql, home_auth):
    canonical = identity(sql, OTHER)
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response = client.post('/v1/projects', headers={**headers(), 'X-Account-Id': OTHER}, json={})
        assert response.status_code == 403
        response = client.post('/v1/projects', headers=headers(), json={'restore_project_id': canonical['project_id']})
        assert response.status_code == 404
        response = client.post('/v1/projects', headers=headers(), json={'storyteller_account_id': OTHER})
        assert response.status_code == 422
        assert not store.projects
        response = client.post('/v1/projects', headers=headers(), json={'project_id': canonical['project_id'], 'conversation_id': canonical['conversation_id'], 'owner_id': OTHER})
        assert response.status_code == 201, response.text
        assert response.json()['id'] == identity(sql)['project_id'] != canonical['project_id']
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '2'


@pytest.mark.parametrize('variant', ['guest', 'family', 'disabled', 'demo'])
def test_legacy_guest_family_and_disabled_paths_do_not_claim_lifetime_identity(sql, home_auth, monkeypatch, variant):
    if variant == 'guest':
        sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    if variant == 'disabled':
        monkeypatch.delenv('MEMOIR_LIFETIME_MEMORY')
    with TestClient(main.create_app(MemoryStore())) as client:
        response = client.post('/v1/projects', headers={} if variant == 'demo' else headers(), json={'mode': 'family'} if variant == 'family' else {})
        assert response.status_code == 201, response.text
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_memoir_project;').stdout.strip() == '0'


def test_guest_transfer_reports_mapping_without_replacing_canonical_or_original_evidence(sql, home_auth):
    canonical = identity(sql, OTHER)
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    original = rpc(sql, 'accept_user_interview_turn', f"'guest-original','{uuid4()}','My original guest memory'")
    phase = rpc(sql, 'change_user_conversation_phase', "'guest-original','shape',0")
    with TestClient(main.create_app(MemoryStore())) as client:
        prepared = client.post('/v1/user/conversation-transfer', headers=headers(), json={'token': TOKEN, 'project_id': 'guest-original', 'messages': []})
        assert prepared.status_code == 200, prepared.text
        attached = client.post('/v1/user/conversation-transfer/attach', headers=headers('other'), json={'token': TOKEN})
        assert attached.status_code == 200, attached.text
        result = attached.json()
        assert result['attached'] and result['project_id'] == 'guest-original'
        assert result['lifetime_identity'] == {'schema_version': 1, 'outcome': 'mapping_required', 'transferred_project_id': 'guest-original', 'canonical_project_id': canonical['project_id'], 'conversation_id': canonical['conversation_id']}
        retry = client.post('/v1/user/conversation-transfer/attach', headers=headers('other'), json={'token': TOKEN})
        assert retry.status_code == 200 and retry.json() == result
        denied = client.post('/v1/user/conversation-transfer/attach', headers=headers('third'), json={'token': TOKEN})
        assert denied.status_code == 409
        restored = client.post('/v1/projects', headers=headers('other'), json={'restore_project_id': 'guest-original'})
        assert restored.status_code == 201 and restored.json()['id'] == 'guest-original'
    assert identity(sql, OTHER) == canonical
    transferred = rpc(sql, 'read_user_interview_turn', f"'guest-original','{original['client_turn_id']}'", owner=OTHER)
    assert transferred['source']['id'] == original['source']['id']
    assert transferred['client_turn_id'] == original['client_turn_id']
    assert rpc(sql, 'read_user_conversation_phase', "'guest-original'", owner=OTHER) == phase
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '1'
    assert sql(f"select count(*) from public.user_narrator_source where user_id='{OTHER}' and project_id={literal(canonical['project_id'])};").stdout.strip() == '0'


@pytest.mark.parametrize('failure', ['unavailable', 'foreign_identity', 'malformed_identity', 'missing_identity'])
def test_product_home_resolution_failure_never_falls_back_to_random_project(sql, home_auth, monkeypatch, failure):
    other = identity(sql, OTHER)
    class BrokenResolution(HomeRest):
        def handle(self, request):
            if request.url.path == '/rest/v1/rpc/resolve_lifetime_conversation':
                if failure == 'unavailable':
                    return httpx.Response(503, json={'code': 'unavailable'})
                if failure == 'missing_identity':
                    return httpx.Response(200, json=[])
                return httpx.Response(200, json=other if failure == 'foreign_identity' else {'outcome': 'resolved'})
            return super().handle(request)
    monkeypatch.setattr(main, 'authenticated_storage', lambda _: BrokenResolution(sql, OWNER).storage())
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response = client.post('/v1/projects', headers=headers(), json={})
        assert response.status_code == 503
        assert response.headers['x-error-code'] == 'LIFETIME_IDENTITY_UNAVAILABLE'
        assert not store.projects
    assert sql(f"select count(*) from public.user_lifetime_conversation where user_id='{OWNER}';").stdout.strip() == '0'


def test_approved_synthetic_mapping_uses_original_project_without_name_convention(sql, home_auth):
    project = 'original_storyteller_project'
    turn = rpc(sql, 'accept_user_interview_turn', f"'{project}','{uuid4()}','Original testimony'")
    # An isolated explicit fixture mapping, never application backfill.
    sql(f"insert into public.user_lifetime_conversation(user_id,project_id,preference_revision) values('{OWNER}','{project}',7);")
    canonical = identity(sql)
    assert canonical['project_id'] == project
    original = sql('select row_to_json(s) from public.user_narrator_source s;').stdout
    pending = rpc(sql, 'read_lifetime_policy_status', f"'{canonical['conversation_id']}'")
    assert pending['pending'] is True
    with TestClient(main.create_app(MemoryStore())) as client:
        response = client.post('/v1/projects', headers=headers(), json={})
        # Mapping identity does not attest that historical privacy was reviewed.
        # The fixed response must not publish the still-pending private home.
        assert response.status_code == 503, response.text
        assert response.headers['x-error-code'] == 'LIFETIME_POLICY_PENDING'
        assert response.headers['retry-after'] == '60'
        assert response.headers['cache-control'] == 'no-store'
        assert response.json() == {'detail': 'Accepted conversation policy requires maintenance before private content can be used'}
        assert project not in response.text and canonical['conversation_id'] not in response.text
    assert identity(sql) == canonical
    assert rpc(sql, 'read_lifetime_policy_status', f"'{canonical['conversation_id']}'") == pending
    assert sql('select row_to_json(s) from public.user_narrator_source s;').stdout == original
    assert rpc(sql, 'read_user_interview_turn', f"'{project}','{turn['client_turn_id']}'")['source']['id'] == turn['source']['id']
    assert sql('select preference_revision from public.user_lifetime_conversation;').stdout.strip() == '7'


@pytest.mark.parametrize('streaming', [False, True])
def test_product_home_to_first_governed_turn_and_cold_replay(sql, home_auth, tmp_path, monkeypatch, streaming):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from test_name_only_opening import proposal
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'gpt-5.6-luna-pooled')
    calls = []
    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['governed']['fence']['identity']['project_id'] == canonical['project_id']
        assert body['governed']['fence']['identity']['conversation_id'] == canonical['conversation_id']
        response = proposal(name='Joan', question='What would you like to share?')
        response['plan']['conversation_phase'] = 'comfort'
        raw = json.dumps(response)
        if request.headers.get('accept') == 'application/x-ndjson':
            return httpx.Response(200, headers={'Content-Type': 'application/x-ndjson'}, content='\n'.join(json.dumps(event) for event in [
                {'type': 'text_delta', 'text': raw}, {'type': 'result', 'data': {'reply': raw, 'thread_id': 'synthetic-home', 'artifacts': []}}]) + '\n')
        return httpx.Response(200, json={'reply': raw, 'thread_id': 'synthetic-home', 'artifacts': []})
    def runtime():
        return CodexRuntime(home_root=tmp_path / str(uuid4()), worker_url='http://controlled.invalid', worker_secret='synthetic', worker_transport=httpx.MockTransport(provider))
    monkeypatch.setattr(agent_routes, 'authenticated_storage', main.authenticated_storage)
    monkeypatch.setattr(agent_routes, 'runtime', runtime())
    def saved(response):
        assert response.status_code == 200, response.text
        if not streaming:
            return response.json()
        events = [json.loads(line) for line in response.text.splitlines()]
        assert not any(event['type'] == 'error' for event in events), events
        return next(event['data'] for event in events if event['type'] == 'result')
    turn_id = str(uuid4())
    accept = {'Accept': 'application/x-ndjson' if streaming else 'application/json'}
    with TestClient(main.create_app(MemoryStore())) as client:
        home = client.post('/v1/projects', headers=headers(), json={})
        assert home.status_code == 201, home.text
        canonical = identity(sql)
        assert home.json()['id'] == canonical['project_id']
        payload = {'project_id': home.json()['id'], 'client_turn_id': turn_id, 'text': 'My name is Joan'}
        first = saved(client.post('/v1/agent/turn', headers={**headers(), **accept}, json=payload))
        assert first['conversation_saved'] and first['accepted_source_id']
    # Both the local adapter and worker runtime are disposable. The same saved
    # request after reauthentication must replay rather than call the provider.
    monkeypatch.setattr(agent_routes, 'runtime', runtime())
    with TestClient(main.create_app(MemoryStore())) as client:
        home = client.post('/v1/projects', headers=headers('reauthenticated'), json={})
        assert home.status_code == 201 and home.json()['id'] == canonical['project_id']
        replay = saved(client.post('/v1/agent/turn', headers={**headers('reauthenticated'), **accept}, json=payload))
        assert replay['cached'] and replay['reply'] == first['reply']
        assert replay['accepted_source_id'] == first['accepted_source_id']
    assert identity(sql) == canonical
    assert len(calls) == 1
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip() == '1'
    assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip() == '0'


def test_guest_transfer_before_first_home_requires_mapping_and_preserves_receipt(sql, home_auth):
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    original = rpc(sql, 'accept_user_interview_turn', f"'guest-original','{uuid4()}','Original guest testimony'")
    rpc(sql, 'prepare_guest_conversation_transfer', f"'{TOKEN}','guest-original','[]'::jsonb")
    result = rpc(sql, 'attach_guest_conversation', f"'{TOKEN}'", owner=OTHER)
    assert 'lifetime_identity' not in result
    assert rpc(sql, 'attach_guest_conversation', f"'{TOKEN}'", owner=OTHER) == result
    with TestClient(main.create_app(MemoryStore())) as client:
        response = client.post('/v1/projects', headers=headers('other'), json={})
        assert response.status_code == 409
        assert response.json()['detail']['project_ids'] == ['guest-original']
        restored = client.post('/v1/projects', headers=headers('other'), json={'restore_project_id': 'guest-original'})
        assert restored.status_code == 201
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    assert rpc(sql, 'read_user_interview_turn', f"'guest-original','{original['client_turn_id']}'", owner=OTHER)['source']['id'] == original['source']['id']


def test_guest_transfer_racing_first_home_never_adopts_or_merges_a_project(sql):
    from threading import Barrier
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    original = rpc(sql, 'accept_user_interview_turn', f"'guest-original','{uuid4()}','Original guest testimony'")
    rpc(sql, 'prepare_guest_conversation_transfer', f"'{TOKEN}','guest-original','[]'::jsonb")
    barrier = Barrier(2)
    def attach():
        barrier.wait()
        return rpc(sql, 'attach_guest_conversation', f"'{TOKEN}'", owner=OTHER)
    def resolve():
        barrier.wait()
        return identity(sql, OTHER)
    with ThreadPoolExecutor(max_workers=2) as pool:
        transfer, home = pool.submit(attach), pool.submit(resolve)
        transferred, resolved = transfer.result(timeout=10), home.result(timeout=10)
    assert transferred['project_id'] == 'guest-original'
    if resolved['outcome'] == 'resolved':
        assert resolved['project_id'] != 'guest-original'
        assert transferred['lifetime_identity']['outcome'] == 'mapping_required'
        assert transferred['lifetime_identity']['canonical_project_id'] == resolved['project_id']
    else:
        assert resolved == {'schema_version': 1, 'outcome': 'mapping_required', 'project_ids': ['guest-original']}
        assert 'lifetime_identity' not in transferred
    assert rpc(sql, 'read_user_interview_turn', f"'guest-original','{original['client_turn_id']}'", owner=OTHER)['source']['id'] == original['source']['id']


def test_lifetime_admission_keeps_verified_legacy_adapters_without_canonical_downgrade(sql):
    def admission(project=None, owner=OWNER):
        return rpc(sql, 'read_lifetime_admission', 'null' if project is None else literal(project), owner=owner)
    assert admission() == 'governed'
    assert admission('invented') == 'governed'
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    rpc(sql, 'accept_user_narrator_source', f"'legacy','{uuid4()}','Original testimony'")
    assert admission('legacy') == 'legacy'
    assert admission() == 'governed'
    assert admission('legacy', OTHER) == 'governed'
    # Truly old durable adapters may predate canonical narrator sources.
    sql(f"insert into public.user_memory(user_id,project_id,kind,content) values('{OWNER}','old-memory','memoir','Legacy prose');")
    sql(f"insert into public.user_conversation_attachment(user_id,project_id,messages) values('{OWNER}','old-attachment','[]');")
    assert admission('old-memory') == admission('old-attachment') == 'legacy'
    before = sql('select row_to_json(t) from public.user_memoir_project t;').stdout
    sql(as_user("begin read only; select public.read_lifetime_admission('legacy'); commit;"))
    assert sql('select row_to_json(t) from public.user_memoir_project t;').stdout == before
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    canonical = identity(sql, OTHER)
    for project in (None, canonical['project_id'], 'invented', 'legacy', 'old-memory', 'old-attachment'):
        assert admission(project, OTHER) == 'governed'
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    assert admission() == admission('legacy') == admission('invented') == 'legacy'
    assert sql("set role anon; select public.read_lifetime_admission(null);", check=False).returncode != 0


@pytest.mark.parametrize('legacy_kind', ['memory', 'attachment'])
def test_legacy_only_project_home_requires_mapping_without_rewriting_history(sql, home_auth, legacy_kind):
    table = 'user_memory' if legacy_kind == 'memory' else 'user_conversation_attachment'
    if legacy_kind == 'memory':
        sql(f"insert into public.user_memory(user_id,project_id,kind,content) values('{OWNER}','old-project','agent','Original legacy testimony');")
    else:
        sql(f"insert into public.user_conversation_attachment(user_id,project_id,messages) values('{OWNER}','old-project','[{{\"role\":\"user\",\"text\":\"Original legacy testimony\"}}]');")
    before = sql(f'select row_to_json(t) from public.{table} t;').stdout
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response = client.post('/v1/projects', headers=headers(), json={})
        assert response.status_code == 409, response.text
        assert response.json()['detail'] == {'schema_version': 1, 'outcome': 'mapping_required', 'project_ids': ['old-project']}
        assert not store.projects
        assert rpc(sql, 'resolve_lifetime_conversation', "'old-project'") == response.json()['detail']
        restored = client.post('/v1/projects', headers=headers(), json={'restore_project_id': 'old-project'})
        assert restored.status_code == 201 and restored.json()['id'] == 'old-project'
    assert sql(f'select row_to_json(t) from public.{table} t;').stdout == before
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_memoir_project;').stdout.strip() == '0'


def test_unscoped_legacy_history_requires_explicit_mapping_without_new_identity(sql, home_auth):
    sql(f"insert into public.user_memory(user_id,kind,content) values('{OWNER}','agent','Original unscoped testimony');")
    before = sql('select row_to_json(t) from public.user_memory t;').stdout
    with TestClient(main.create_app(MemoryStore())) as client:
        response = client.post('/v1/projects', headers=headers(), json={})
        assert response.status_code == 409
        assert response.json()['detail'] == {'schema_version': 1, 'outcome': 'mapping_required', 'project_ids': [], 'unscoped_history': True}
    assert sql('select row_to_json(t) from public.user_memory t;').stdout == before
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
