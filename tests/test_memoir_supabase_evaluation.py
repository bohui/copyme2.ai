"""Remote launcher orchestration with controlled HTTP; no services or LLMs."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4
from urllib.parse import urlencode

import httpx
import pytest

from scripts import run_memoir_supabase_evaluation as module
from test_issue14_subscription_runner import Storage

OWNER = '11111111-1111-4111-8111-111111111111'
SETTINGS = {'SUPABASE_URL': 'https://supabase.example',
            'SUPABASE_PUBLISHABLE_KEY': 'public-key', 'SUPABASE_SECRET_KEY': 'admin-secret'}


def test_preflight_reaches_real_backend_routes_without_model_calls(monkeypatch):
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from apps.api.story_payments import LocalStoryEntitlementStore
    from test_recall import RecallStorage

    for name, value in SETTINGS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '250')
    monkeypatch.setenv('MEMORY_SPARK_PRIVATE_DRAFT_CADENCE', '5')
    storage = RecallStorage()
    memory = MemoryStore()
    app = create_app(memory, story_storage_factory=lambda authorization: storage,
                     story_entitlement_store=LocalStoryEntitlementStore(memory))
    plan = {'api_base': 'http://backend.example', 'case_ids': list(module.CASE_IDS)}

    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
            account = module.SupabaseAccount(module.Requests(client, 5, 10), **{
                'url': SETTINGS['SUPABASE_URL'], 'public_key': 'public-key', 'secret_key': 'admin-secret'},
                user={'id': storage.user_id}, access_token='user-token', expires_at=float('inf'))
            result = await module.preflight(account, plan)
            assert result['backend_auth_mode'] == 'supabase'
            assert result['recall_status']['free_rounds'] == 250
    asyncio.run(check())


class Remote:
    def __init__(self, plan):
        self.plan = plan
        self.user = {'id': OWNER, 'email': 'test@test.com',
                     'email_confirmed_at': 'confirmed', 'is_anonymous': False}
        self.calls, self.submitted, self.recovered = [], [], []
        self.fail_round = None
        self.draft_failed = False
        self.pending_reads = 0
        self.storages = {v['project_id']: Storage(SimpleNamespace(read_hook=None, draft_hook=None, events=[]),
            {**v, 'owner_id': OWNER}) for v in plan['cases'].values()}

    def handler(self, request):
        self.calls.append(request)
        path = request.url.path
        payload = json.loads(request.content) if request.content else None
        if path == '/health':
            return httpx.Response(200, json={'status': 'ok'})
        if path.startswith('/auth/v1/admin/'):
            assert request.headers['apikey'] == 'admin-secret'
            if path == '/auth/v1/admin/users':
                if request.method == 'POST':
                    assert payload == {'email': 'test@test.com', 'email_confirm': True}
                    self.user = {'id': OWNER, **payload, 'email_confirmed_at': 'confirmed'}
                    result = self.user
                else:
                    result = {'users': [self.user] if self.user else []}
            elif path == '/auth/v1/admin/users/' + OWNER:
                if request.method == 'PUT':
                    assert payload == {'email_confirm': True}
                    self.user['email_confirmed_at'] = 'confirmed'
                result = self.user
            elif path == '/auth/v1/admin/generate_link':
                assert payload['email'] == 'test@test.com' and payload['type'] == 'magiclink'
                result = {**self.user, 'hashed_token': 'private-hash',
                    'action_link': SETTINGS['SUPABASE_URL'] + '/auth/v1/verify?' +
                        urlencode({'token': 'private-link', 'redirect_to': payload['redirect_to']})}
            else:
                raise AssertionError(path)
        elif path in {'/auth/v1/verify', '/auth/v1/token'}:
            assert request.headers['apikey'] == 'public-key'
            result = {'user': self.user, 'access_token': 'user-token',
                      'refresh_token': 'private-refresh', 'expires_in': 3600}
        else:
            assert request.headers['Authorization'] == 'Bearer user-token'
            assert request.headers['apikey'] == 'public-key'
            if path == '/api/v1/memoir/agent/config':
                result = {'auth_mode': 'supabase', 'supabase_url': SETTINGS['SUPABASE_URL'],
                          'private_draft_cadence': 5}
            elif path == '/api/v1/memoir/story/state':
                result = {'user_id': OWNER, 'is_anonymous': False, 'family_features_enabled': False,
                          'recall_status': {'paid': False, 'rounds_completed': 0, 'free_rounds': 250}}
            elif path == '/api/v1/memoir/agent/turn':
                self.submitted.append(payload)
                if len(self.submitted) == self.fail_round:
                    return httpx.Response(502, json={'error': 'never retain arbitrary-secret'})
                storage = self.storages[payload['project_id']]
                source = {'id': str(uuid4()), 'project_id': payload['project_id'],
                    'text': payload['text'], 'language': payload['language'], 'kind': 'narrator_chat',
                    'status': 'active', 'version': 1, 'sequence': len(storage.sources) + 1}
                storage.sources.append(source)
                storage.extracted = len(storage.sources)
                result = {'project_id': payload['project_id'], 'reply': 'A live-route fixture reply',
                          'accepted_source_id': source['id'], 'cached': False, 'task_errors': []}
            elif path == '/rest/v1/rpc/read_user_memory_events':
                result = self.storages[payload['p_project_id']].memory_events(payload['p_project_id'])
                if self.pending_reads and result['completed_rounds']:
                    self.pending_reads -= 1
                    result['processing']['pending_inputs'] = 1
            elif path == '/rest/v1/rpc/read_user_memoir_draft':
                storage = self.storages[payload['p_project_id']]
                result = storage.saved_memoir_draft(payload['p_project_id'], payload['p_locale'])
                if self.draft_failed:
                    result['status'] = 'failed'
            elif path.startswith('/api/v1/memoir/projects/'):
                project = path.rsplit('/', 1)[1]
                self.recovered.append(project)
                result = {'id': project, 'requires_supabase_auth': True}
            elif path == '/rest/v1/user_recall_usage':
                result = [{'rounds_completed': 25}]
            else:
                raise AssertionError(path)
        return httpx.Response(200, json=deepcopy(result))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(module, 'local_checkout_snapshot', lambda revision: {'head': revision})
    monkeypatch.setattr(module, 'verify_execution_source', lambda *args: None)
    client = httpx.AsyncClient

    def create(case_id=module.CASE_IDS[0]):
        plan = module.build_plan(run_id=str(uuid4()), source_revision='a' * 40,
            case_id=case_id, api_base='http://127.0.0.1:8010', web_base='http://localhost:3010',
            max_seconds=120, max_case_seconds=60, max_backend_requests=2000,
            settle_seconds=1, poll_seconds=.001, user_email='test@test.com')
        remote = Remote(plan)
        monkeypatch.setattr(module.httpx, 'AsyncClient',
            lambda **kwargs: client(transport=httpx.MockTransport(remote.handler), **kwargs))
        return plan, remote
    return create


@pytest.mark.parametrize('case_id', [None, *module.CASE_IDS])
def test_original_rounds_retained_for_real_owner_without_admin_application_writes(setup, tmp_path, case_id):
    plan, remote = setup(case_id)
    directory = tmp_path / 'run'
    result = asyncio.run(module.execute(plan, directory, SETTINGS))
    assert result['status'] == 'completed', result
    assert len(remote.submitted) == len(plan['cases']) * 50
    assert len({p['client_turn_id'] for p in remote.submitted}) == len(remote.submitted)
    for case_id, binding in plan['cases'].items():
        sent = [p for p in remote.submitted if p['project_id'] == binding['project_id']]
        original = module.FiftyReadback(case_id=case_id, run_id=plan['run_id'],
            project_id=binding['project_id'], source_revision=plan['source_revision']).driver_inputs()['rounds']
        assert [p['text'] for p in sent] == [p['conversation_text'] for p in sent] == original
        assert binding['owner_id'] == OWNER
    assert remote.recovered == [p['project_id'] for p in plan['cases'].values()]
    assert all(c['ui_recovery_verified'] and len(c['rounds']) == 50
               and [v['milestone'] for v in c['checkpoints']] == list(module.CHECKPOINTS)
               for c in result['evaluation']['cases'])
    assert result['data_retained'] and not result['local_postgres_started'] and not result['browser_started']
    assert result['actual_upstream_provider_requests'] is None
    assert result['request_accounting']['backend_http_requests_reserved'] == len(remote.calls)
    evidence = (directory / 'receipt.json').read_text() + (directory / 'plan.json').read_text()
    assert all(secret not in evidence for secret in ['admin-secret', 'user-token', 'private-hash', 'private-refresh', 'private-link'])
    assert 'private-link' in (directory / 'ui-login.html').read_text()
    assert (directory / 'ui-login.html').stat().st_mode & 0o777 == 0o600
    assert not any(r.method in {'PUT', 'DELETE'} for r in remote.calls)


def test_failed_submission_stops_once_preserves_previous_rounds_and_safe_reason(setup, tmp_path):
    plan, remote = setup()
    remote.fail_round = 7
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'incomplete' and len(remote.submitted) == 7
    rounds = result['evaluation']['cases'][0]['rounds']
    assert [r['status'] for r in rounds] == ['completed'] * 6 + ['incomplete']
    assert len(result['evaluation']['cases'][0]['checkpoints']) == 1
    assert result['stop_reason'] == 'HTTP request failed with status 502'
    assert 'arbitrary-secret' not in json.dumps(result)
    assert (tmp_path / 'run' / 'receipt.json').exists()


def test_failed_checkpoint_stops_before_next_input_and_pending_readbacks_are_polled(setup, tmp_path):
    plan, remote = setup()
    remote.pending_reads, remote.draft_failed = 2, True
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'incomplete' and len(remote.submitted) == 5
    assert remote.pending_reads == 0
    assert 'checkpoint failed' in result['stop_reason']


@pytest.mark.parametrize('existing', [False, True])
def test_direct_confirmation_is_verified_without_sending_email_or_changing_password(setup, tmp_path, existing):
    _, remote = setup()
    remote.user = {**remote.user, 'email_confirmed_at': None} if existing else None
    result = asyncio.run(module.prepare_user(SETTINGS, 'test@test.com', tmp_path / 'login', 'http://localhost:3010'))
    assert result['email_confirmed'] and result['owner_id'] == OWNER
    writes = [r for r in remote.calls if r.method in {'POST', 'PUT'}]
    assert [r.url.path for r in writes] == [
        '/auth/v1/admin/users/' + OWNER if existing else '/auth/v1/admin/users',
        '/auth/v1/admin/generate_link']
    assert remote.calls[-2].method == 'GET' and remote.calls[-2].url.path.endswith(OWNER)


def test_owner_mismatch_and_request_ceiling_fail_before_conversation(setup, tmp_path):
    plan, remote = setup()
    remote.user['id'] = str(uuid4())
    result = asyncio.run(module.execute(plan, tmp_path / 'foreign', SETTINGS))
    assert result['status'] == 'incomplete' and not remote.submitted
    plan, remote = setup()
    plan['max_backend_requests'] = 2
    result = asyncio.run(module.execute(plan, tmp_path / 'limit', SETTINGS))
    assert result['status'] == 'incomplete' and not remote.submitted
    assert len(remote.calls) == 2


def test_source_change_retains_evidence_but_invalidates_completion(setup, tmp_path, monkeypatch):
    plan, remote = setup()
    calls = []
    def changed(*args):
        calls.append(args)
        if len(calls) > 1:
            raise ValueError('changed')
    monkeypatch.setattr(module, 'verify_execution_source', changed)
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert len(remote.submitted) == 50 and result['status'] == 'incomplete'
    assert result['stop_reason'] == 'source_changed_during_run'


@pytest.mark.parametrize('flag', ['--max-elapsed-seconds', '--max-backend-requests'])
def test_explicit_zero_ceiling_is_rejected_without_network(setup, capsys, flag):
    _, remote = setup()
    assert module.main([flag, '0', '--source-revision', 'a' * 40]) == 3
    assert not remote.calls


def test_account_session_refresh_keeps_the_real_owner(setup):
    _, remote = setup()
    async def run():
        async with module.httpx.AsyncClient() as client:
            account = module.SupabaseAccount(module.Requests(client, 20, 5), **{
                'url': SETTINGS['SUPABASE_URL'], 'public_key': 'public-key', 'secret_key': 'admin-secret'})
            await account.ensure_user('test@test.com')
            await account.sign_in()
            account.expires_at = 0
            assert (await account.headers())['Authorization'] == 'Bearer user-token'
            account.user['id'] = str(uuid4())
            with pytest.raises(module.EvaluationError, match='session did not match'):
                await account.set_session({'user': {'id': OWNER}, 'access_token': 'x', 'refresh_token': 'y'})
    asyncio.run(run())
    assert any(r.url.path == '/auth/v1/token' for r in remote.calls)


def test_backend_startup_uses_existing_usage_and_scoped_owner_without_postgres(setup, tmp_path, monkeypatch):
    plan, remote = setup()
    started = []
    def start(command, **kwargs):
        started.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', start)
    settings = {**SETTINGS, 'SUPABASE_SECRET_KEY': None, 'SUPABASE_SERVICE_ROLE_KEY': 'admin-secret'}
    result = asyncio.run(module.execute(plan, tmp_path / 'run', settings, start_backend=True))
    assert result['status'] == 'completed', result
    assert len(started) == 1
    command, options = started[0]
    assert command == ['make', '--no-print-directory', 'memoir-live-fifty-backend']
    assert options['env']['MEMORY_SPARK_EVAL_RECALL_OWNER_ID'] == OWNER
    assert options['env']['MEMORY_SPARK_EVAL_RECALL_LIMIT'] == '75'
    assert options['env']['SUPABASE_SECRET_KEY'] == 'admin-secret'
    assert options['env']['MEMORY_SPARK_API_PORT'] == '8010'


def test_prepare_user_refuses_checkout_or_existing_directory(setup, tmp_path):
    _, remote = setup()
    for directory in [module.ROOT / 'private-login', tmp_path]:
        with pytest.raises(module.EvaluationError, match='fresh output directory outside'):
            asyncio.run(module.prepare_user(SETTINGS, 'test@test.com', directory, 'http://localhost:3010'))
    assert not remote.calls
