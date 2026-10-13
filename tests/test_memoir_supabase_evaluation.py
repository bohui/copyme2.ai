"""Remote launcher orchestration with controlled HTTP; no services or LLMs."""
import asyncio
from copy import deepcopy
import json
import subprocess
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5
from urllib.parse import urlencode

import httpx
import pytest

from scripts import run_memoir_supabase_evaluation as module
from test_issue14_subscription_runner import Storage

OWNER = '11111111-1111-4111-8111-111111111111'
OWNERS = {case: OWNER if i == 0 else str(UUID(int=200+i)) for i,case in enumerate(module.CASE_IDS)}
PROJECTS = {case:'lifetime-'+str(uuid5(UUID(OWNER),case)) for case in module.CASE_IDS}
CONVERSATIONS = {case:str(uuid5(UUID(OWNER),case+'/conversation')) for case in module.CASE_IDS}
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
                user={'id': storage.user_id}, verified_owner=storage.user_id, access_token='user-token', expires_at=float('inf'))
            result = await module.preflight(account, plan)
            assert result['backend_auth_mode'] == 'supabase'
            assert result['recall_status']['free_rounds'] == 250
    asyncio.run(check())


class Remote:
    def __init__(self,plan):
        self.plan=plan
        self.users={case:{'id':OWNERS[case],'email':module.CASE_EMAILS[case],'email_confirmed_at':'confirmed','is_anonymous':False} for case in module.CASE_IDS}
        self.calls,self.submitted,self.recovered=[],[],[]
        self.restored=set();self.fail_round=None;self.draft_failed=False
        self.transient_draft_error_reads=0;self.extraction_retry_required=False;self.pending_reads=0
        self.fail_auth_case=None;self.foreign_identity_case=None;self.shape_unavailable=False
        self.storages={PROJECTS[case]:Storage(SimpleNamespace(read_hook=None,draft_hook=None,events=[]),
            {**binding,'project_id':PROJECTS[case],'owner_id':OWNERS[case]}) for case,binding in plan['cases'].items()}
        self.token_cases={'user-token-'+case:case for case in module.CASE_IDS}
        self.submission_owners=[]
    @property
    def user(self):return self.users[module.CASE_IDS[0]]
    @user.setter
    def user(self,value):self.users[module.CASE_IDS[0]]=value
    def handler(self,request):
        self.calls.append(request);path=request.url.path;payload=json.loads(request.content) if request.content else None
        if path=='/health':return httpx.Response(200,json={'status':'ok'})
        if path.startswith('/auth/v1/admin/'):
            assert request.headers['apikey']=='admin-secret'
            if path=='/auth/v1/admin/users':
                if request.method=='POST':
                    case=next(case for case,email in module.CASE_EMAILS.items() if email==payload['email'])
                    self.users[case]={'id':OWNERS[case],**payload,'email_confirmed_at':'confirmed','is_anonymous':False};result=self.users[case]
                else:result={'users':[user for user in self.users.values() if user] if request.url.params.get('page','1')=='1' else []}
            elif path=='/auth/v1/admin/generate_link':
                case=next(case for case,email in module.CASE_EMAILS.items() if email==payload['email'])
                if case==self.fail_auth_case:return httpx.Response(401,json={'private':'not logged'})
                result={**self.users[case],'hashed_token':'private-hash-'+case,
                    'action_link':SETTINGS['SUPABASE_URL']+'/auth/v1/verify?'+urlencode({'token':'private-link-'+case,'redirect_to':payload['redirect_to']})}
            else:
                user=next(user for user in self.users.values() if user and path.endswith(user['id']))
                if request.method=='PUT':user['email_confirmed_at']='confirmed'
                result=user
        elif path in {'/auth/v1/verify','/auth/v1/token'}:
            case=(payload['token_hash'].removeprefix('private-hash-') if path.endswith('/verify') else payload['refresh_token'].removeprefix('private-refresh-'))
            result={'user':self.users[case],'access_token':'user-token-'+case,'refresh_token':'private-refresh-'+case,'expires_in':3600}
        else:
            token=request.headers.get('Authorization','').removeprefix('Bearer ');case_id=self.token_cases[token];owner=OWNERS[case_id]
            assert request.headers['apikey']=='public-key'
            if path=='/auth/v1/user':return httpx.Response(200,json=deepcopy(self.users[case_id]))
            if path=='/rest/v1/rpc/read_lifetime_project_identity':
                result={'schema_version':1,'owner_id':owner,'conversation_id':CONVERSATIONS[case_id],'project_id':PROJECTS[case_id],'product':'memoir'}
                if case_id==self.foreign_identity_case:result['owner_id']=OWNERS[module.CASE_IDS[0]]
                return httpx.Response(200,json=result) if result is not None else httpx.Response(200,text='null',headers={'Content-Type':'application/json'})
            if path=='/rest/v1/rpc/resolve_lifetime_conversation':raise AssertionError('Existing canonical identity must be reused.')
            if path in {'/rest/v1/rpc/read_lifetime_private_draft_head','/rest/v1/rpc/read_lifetime_private_draft_page'}:
                project=PROJECTS[case_id];storage=self.storages[project];ordinal=len(storage.sources)
                common={'schema_version':1,'owner_id':owner,'conversation_id':CONVERSATIONS[case_id],
                    'project_id':project,'locale':storage.plan['language'],'source_revision':ordinal,'event_revision':ordinal,
                    'policy_epoch':1,'snapshot_state':'completed','root_digest':'a'*64,
                    'snapshot_id':str(uuid5(UUID(owner),'snapshot/'+str(ordinal))),'approval_required':False}
                if path.endswith('_head'):
                    result={**common,'status':'ready' if ordinal else 'pending','coverage_round':ordinal,
                        'current_source_revision':ordinal,'current_event_revision':ordinal,'retrieval_complete':bool(ordinal),
                        'updating':False,'revision':max(1,ordinal//5),'error':None}
                    if self.transient_draft_error_reads:
                        self.transient_draft_error_reads-=1;result.update(status='pending',error='LIFETIME_COMPOSITION_PENDING')
                    if self.draft_failed:result.update(snapshot_state='proposed',approval_required=True)
                else:
                    result={**common,'snapshot_complete':True,'complete':True,'next_cursor':None,
                        'records':[{'id':'partition-'+str(ordinal),'event_id':'controlled-event','event_revision':1,
                            'preview':{'locale':storage.plan['language'],'text':storage.sources[0]['text']},
                            'source_refs':[{'source_id':storage.sources[0]['id'],'version':1,'char_start':0,'char_end':10}],
                            'approval_required':False,'original_withheld':False}]}
                return httpx.Response(200,json=result)
            if path=='/rest/v1/rpc/read_lifetime_reply':
                storage=self.storages[PROJECTS[case_id]]
                record=next((row for row in self.submitted if row['client_turn_id']==payload['p_client_turn_id']),None)
                source=next((row for row in storage.sources if record and row['text']==record['text']),None)
                result={'conversation_saved':True,'accepted_source_id':source['id'],'project_id':PROJECTS[case_id],
                    'client_turn_id':payload['p_client_turn_id'],'reply':'Recovered controlled reply','context_rebuild_required':False} if source else None
                return httpx.Response(200,json=result) if result is not None else httpx.Response(200,text='null',headers={'Content-Type':'application/json'})
            if payload and ('project_id' in payload or 'p_project_id' in payload):
                assert payload.get('project_id',payload.get('p_project_id'))==PROJECTS[case_id],'Cross-account project request.'
            if path == '/api/v1/memoir/agent/config':
                result = {'auth_mode': 'supabase', 'supabase_url': SETTINGS['SUPABASE_URL'],
                          'private_draft_cadence': 5}
            elif path == '/api/v1/memoir/story/state':
                result = {'user_id': owner, 'is_anonymous': False, 'family_features_enabled': False,
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
                if self.extraction_retry_required and result['completed_rounds']:
                    result['processing']['pending_inputs'] = 1
            elif path == '/rest/v1/rpc/read_user_memoir_draft':
                storage = self.storages[payload['p_project_id']]
                result = storage.saved_memoir_draft(payload['p_project_id'], payload['p_locale'])
                if self.transient_draft_error_reads:
                    self.transient_draft_error_reads -= 1
                    result.update(status='collecting', covered_round=0, milestone=0,
                                  revision=0, updating=True, error='MEMOIR_UNAVAILABLE',
                                  preview=None, sections=[], milestones=[])
                    result['progress']['composition'] = {
                        'state': 'pending', 'pending': True,
                        'error': 'MEMOIR_UNAVAILABLE', 'covered_round': 0,
                        'target_milestone': 5,
                    }
                if self.extraction_retry_required:
                    result['updating'] = False
                    result['error'] = 'MEMOIR_UNAVAILABLE'
                    result['progress']['extraction'] = {
                        'state': 'retry_required', 'pending': False,
                        'error': 'MEMOIR_UNAVAILABLE', 'extracted_through': 0,
                    }
                if self.draft_failed:
                    result['status'] = 'failed'

            elif path=='/api/v1/memoir/projects' and request.method=='POST':
                project=payload['restore_project_id'];assert project==PROJECTS[case_id]
                self.restored.add(project);result={'id':project,'owner_id':owner,'requires_supabase_auth':True}
            elif path.startswith('/api/v1/memoir/projects/'):
                project=path.rsplit('/',1)[1];assert project==PROJECTS[case_id]
                self.recovered.append(project);result={'id':project,'owner_id':owner,'requires_supabase_auth':True}
            elif path=='/rest/v1/user_recall_usage':
                assert request.url.params['user_id']=='eq.'+owner;result=[{'rounds_completed':25}]
            else:raise AssertionError(path)
            if path.endswith('/agent/turn'):self.submission_owners.append((case_id,owner,payload['project_id']))
            if self.shape_unavailable and path.endswith('read_user_memory_events'):result={'project_id':PROJECTS[case_id]}
        return httpx.Response(200,json=deepcopy(result))


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(module, 'local_checkout_snapshot', lambda revision: {'head': revision})
    monkeypatch.setattr(module, 'verify_execution_source', lambda *args: None)
    client = httpx.AsyncClient

    def create(case_id=module.CASE_IDS[0]):
        plan = module.build_plan(run_id=str(uuid4()), source_revision='a' * 40,
            case_id=case_id, api_base='http://127.0.0.1:8010', web_base='http://localhost:3010',
            max_seconds=120, max_case_seconds=60, max_backend_requests=2000,
            settle_seconds=1, poll_seconds=.001, user_email=None)
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
        assert binding['owner_id'] == OWNERS[case_id] and binding['user_email'] == module.CASE_EMAILS[case_id]
    assert remote.recovered == [p['project_id'] for p in plan['cases'].values()]
    for binding in plan['cases'].values():
        calls = [r for r in remote.calls if (json.loads(r.content) if r.content else {}).get('project_id') == binding['project_id']
                 or (json.loads(r.content) if r.content else {}).get('restore_project_id') == binding['project_id']]
        turn_calls = [i for i, r in enumerate(calls) if r.url.path.endswith('/agent/turn')]
        restore_calls = [i for i, r in enumerate(calls) if r.url.path == '/api/v1/memoir/projects']
        assert len(restore_calls) == 1 and restore_calls[0] < turn_calls[0]
    assert all(c['ui_recovery_verified'] and len(c['rounds']) == 50
               and [v['milestone'] for v in c['checkpoints']] == list(module.CHECKPOINTS)
               for c in result['evaluation']['cases'])
    assert result['data_retained'] and not result['local_postgres_started'] and not result['browser_started']
    assert result['actual_upstream_provider_requests'] is None
    assert result['request_accounting']['backend_http_requests_reserved'] == len(remote.calls)
    evidence = (directory / 'receipt.json').read_text() + (directory / 'plan.json').read_text()
    assert all(secret not in evidence for secret in ['admin-secret', 'user-token', 'private-hash', 'private-refresh', 'private-link'])
    for case in result['evaluation']['cases']:
        link=directory/case['ui_login_file']
        assert 'private-link-'+case['case_id'] in link.read_text() and link.stat().st_mode & 0o777==0o600
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
    assert 'checkpoint requires human' in result['stop_reason']


def test_retryable_checkpoint_error_is_polled_until_the_worker_saves(setup, tmp_path):
    plan, remote = setup()
    remote.transient_draft_error_reads = 2
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'completed', result
    assert len(remote.submitted) == 50
    assert result['evaluation']['cases'][0]['checkpoints']


def test_terminal_extraction_error_stops_without_waiting_for_settle_deadline(setup, tmp_path):
    plan, remote = setup()
    remote.extraction_retry_required = True
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'incomplete'
    assert len(remote.submitted) == 1
    assert result['stop_reason'] == 'Background extraction failed; explicit review is required'


def test_retry_required_lane_state_is_terminal_even_without_error_text():
    assert module._extraction_error_is_terminal({'progress': {
        'extraction': {'state': 'retry_required', 'error': None}}})
    assert module._checkpoint_error_is_terminal({'progress': {
        'composition': {'state': 'retry_required', 'error': None}}})


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


def test_source_change_does_not_mask_an_earlier_conversation_failure(setup, tmp_path, monkeypatch):
    plan, remote = setup()
    handler = remote.handler

    def interrupted(request):
        if request.url.path.endswith('/agent/turn') and len(remote.submitted) == 6:
            raise httpx.RemoteProtocolError('private response bytes', request=request)
        return handler(request)

    remote.handler = interrupted
    checks = []

    def changed(*args):
        checks.append(args)
        if len(checks) > 1:
            raise ValueError('changed')

    monkeypatch.setattr(module, 'verify_execution_source', changed)
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    rounds = result['evaluation']['cases'][0]['rounds']
    assert [r['status'] for r in rounds] == ['completed'] * 6 + ['incomplete']
    assert result['local_checkout_unchanged'] is False
    assert result['source_validation_error'] == 'source_changed_during_run'
    assert result['stop_reason'] == rounds[-1]['failure_summary']['reason']
    diagnostic = rounds[-1]['failure_summary']['http_failure']
    assert diagnostic['failure_type'] == 'RemoteProtocolError'
    assert diagnostic['method'] == 'POST'
    assert diagnostic['path'] == '/api/v1/memoir/agent/turn'
    assert diagnostic['http_status'] is None
    assert diagnostic['elapsed_ms'] >= 0
    assert 'private response bytes' not in json.dumps(result)


def test_invalid_json_response_is_distinct_from_a_transport_failure():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text='private malformed reply'))) as client:
            requests = module.Requests(client, 1, 5)
            with pytest.raises(module.EvaluationError) as failure:
                await requests.json('GET', 'https://backend.example/result?token=private-token')
            assert failure.value.diagnostic['failure_type'] == 'invalid_json'
            assert failure.value.diagnostic['http_status'] == 200
            assert failure.value.diagnostic['path'] == '/result'
            assert 'private' not in str(failure.value) + json.dumps(failure.value.diagnostic)

    asyncio.run(run())


@pytest.mark.parametrize('target', ['container-up', 'container-down', 'install_skill',
    'db-truncate', 'memoir-live-fifty-backend'])
def test_live_execution_blocks_a_concurrent_backend_stop(setup, tmp_path, target):
    plan, remote = setup()
    stopped = tmp_path / 'backend-stopped'
    command = tmp_path / 'container-command'
    command.write_text(f'#!{sys.executable}\nimport pathlib, sys\n'
        f'if "compose" in sys.argv or "system" in sys.argv:\n'
        f' pathlib.Path({str(stopped)!r}).touch(); sys.exit(7)\n')
    command.chmod(0o700)
    handler = remote.handler
    attempts = []

    def stop_during_turn(request):
        if request.url.path.endswith('/agent/turn') and not attempts:
            attempts.append(subprocess.run(['make', '--no-print-directory', target,
                'MOCKER=' + str(command), 'APPLE_CONTAINER_BIN=' + str(command)],
                cwd=module.ROOT, capture_output=True, text=True, timeout=10))
        return handler(request)

    remote.handler = stop_during_turn
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'completed'
    assert len(attempts) == 1
    assert attempts[0].returncode != 0
    assert 'backend is in use' in attempts[0].stderr
    assert not stopped.exists()


def test_a_second_live_execution_cannot_restart_an_active_run(setup, tmp_path):
    plan, remote = setup()
    handler = remote.handler
    checked = False

    async def parallel_run(request):
        nonlocal checked
        if request.url.path.endswith('/agent/turn') and not checked:
            checked = True
            with pytest.raises(module.BackendInUseError, match='backend is in use'):
                await module.execute(plan, tmp_path / 'second-run', SETTINGS, start_backend=True)
        return handler(request)

    remote.handler = parallel_run
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'completed'
    assert checked and not (tmp_path / 'second-run').exists()


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
            assert (await account.headers())['Authorization'] == 'Bearer user-token-'+module.CASE_IDS[0]
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


@pytest.mark.parametrize('selection',[[module.CASE_IDS[4],module.CASE_IDS[1]],[module.CASE_IDS[2]],None])
def test_stable_case_accounts_survive_subset_and_reordering(setup,tmp_path,selection):
    plan,remote=setup(selection)
    result=asyncio.run(module.execute(plan,tmp_path/'owners',SETTINGS))
    assert result['status']=='completed',result
    selected=list(module.CASE_IDS) if selection is None else selection
    assert list(plan['cases'])==selected
    assert len({binding['owner_id'] for binding in plan['cases'].values()})==len(selected)
    for case in selected:
        assert plan['cases'][case]['user_email']==module.CASE_EMAILS[case]
        assert plan['cases'][case]['owner_id']==OWNERS[case] and plan['cases'][case]['project_id']==PROJECTS[case]
    assert [(case,owner,project) for case,owner,project in remote.submission_owners]==[
        (case,OWNERS[case],PROJECTS[case]) for case in selected for _ in range(50)]
    assert not any(call.url.path.endswith('resolve_lifetime_conversation') for call in remote.calls)


def test_duplicate_verified_owner_ids_stop_before_sign_in_or_models(setup,tmp_path,monkeypatch):
    plan,remote=setup(None)
    async def duplicate(self,email,**kwargs):
        self.user={'id':OWNER,'email':email,'email_confirmed_at':'confirmed'};self.verified_owner=OWNER
        return OWNER
    monkeypatch.setattr(module.SupabaseAccount,'ensure_user',duplicate)
    result=asyncio.run(module.execute(plan,tmp_path/'duplicate',SETTINGS))
    assert result['status']=='incomplete' and 'same Auth owner' in result['stop_reason'] and not remote.submitted
    assert not any(call.url.path.endswith('generate_link') for call in remote.calls)


def test_one_case_authentication_failure_never_falls_back_to_first_account(setup,tmp_path):
    plan,remote=setup(None);remote.fail_auth_case=module.CASE_IDS[2]
    result=asyncio.run(module.execute(plan,tmp_path/'auth-failure',SETTINGS))
    assert result['status']=='incomplete' and result['evaluation']['failure_stage']=='authentication'
    assert not remote.submitted
    assert 'private' not in json.dumps(result)


def test_foreign_canonical_identity_and_missing_readback_fail_before_turn(setup,tmp_path):
    plan,remote=setup(None);remote.foreign_identity_case=module.CASE_IDS[1]
    result=asyncio.run(module.execute(plan,tmp_path/'foreign-identity',SETTINGS))
    assert result['status']=='incomplete' and not remote.submitted
    plan,remote=setup();remote.shape_unavailable=True
    result=asyncio.run(module.execute(plan,tmp_path/'missing-readback',SETTINGS))
    assert result['status']=='incomplete' and 'readback interface' in result['stop_reason'] and not remote.submitted


def test_resume_uses_same_owner_project_and_does_not_replay_delivered_turns(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'resume';remote.draft_failed=True
    first=asyncio.run(module.execute(plan,directory,SETTINGS))
    assert first['status']=='incomplete' and len(remote.submitted)==5
    first_ids=[call['client_turn_id'] for call in remote.submitted];remote.draft_failed=False
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='completed',result
    assert len(remote.submitted)==50 and [call['client_turn_id'] for call in remote.submitted[:5]]==first_ids
    assert {owner for _,owner,_ in remote.submission_owners}=={OWNER}
    assert {project for _,_,project in remote.submission_owners}=={PROJECTS[module.CASE_IDS[0]]}
    count=len(remote.submitted)
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='completed' and len(remote.submitted)==count


def test_uncertain_submission_is_recovered_by_same_client_id_without_reposting(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'uncertain';handler=remote.handler;failed=[False]
    def lost_response(request):
        result=handler(request)
        if request.url.path.endswith('/agent/turn') and len(remote.submitted)==7 and not failed[0]:
            failed[0]=True;return httpx.Response(502,json={'private':'never logged'})
        return result
    remote.handler=lost_response
    first=asyncio.run(module.execute(plan,directory,SETTINGS))
    assert first['status']=='incomplete' and len(remote.submitted)==7
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='completed',result
    assert len(remote.submitted)==50
    recoveries=[call for call in remote.calls if call.url.path.endswith('read_lifetime_reply')]
    assert len(recoveries)==1 and json.loads(recoveries[0].content)['p_client_turn_id']==remote.submitted[6]['client_turn_id']


def test_unrecoverable_resume_preserves_project_without_another_post(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'unrecoverable';remote.fail_round=7
    first=asyncio.run(module.execute(plan,directory,SETTINGS));assert first['status']=='incomplete'
    remote.fail_round=None
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='incomplete' and 'cannot be safely recovered' in result['stop_reason']
    assert len(remote.submitted)==7 and not any(call.url.path.endswith('resolve_lifetime_conversation') for call in remote.calls)


def test_fresh_rerun_keeps_existing_canonical_data_and_stops_instead_of_allocating_project(setup,tmp_path):
    plan,remote=setup();assert asyncio.run(module.execute(plan,tmp_path/'first',SETTINGS))['status']=='completed'
    result=asyncio.run(module.execute(plan,tmp_path/'again',SETTINGS))
    assert result['status']=='incomplete' and 'history already exists' in result['stop_reason']
    assert len(remote.submitted)==50 and not any(call.url.path.endswith('resolve_lifetime_conversation') for call in remote.calls)


def test_account_repr_hides_all_credentials_and_tokens():
    account=module.SupabaseAccount(None,'https://fixture.invalid','private-public-key','private-admin-key',
        user={'id':OWNER},access_token='private-access',refresh_token='private-refresh')
    assert all(value not in repr(account) for value in ['private-public-key','private-admin-key','private-access','private-refresh'])


def test_existing_migration_contracts_define_actual_canonical_rpc_fields():
    from pathlib import Path
    root=Path(module.ROOT)
    identity=(root/'supabase/migrations/202610120013_lifetime_read_publication.sql').read_text()
    reply=(root/'supabase/migrations/202610120010_lifetime_commit.sql').read_text()
    draft=(root/'supabase/migrations/202610120016_lifetime_composer_lanes.sql').read_text()
    events=(root/'supabase/migrations/202610040001_shared_memory_events.sql').read_text()
    assert 'read_lifetime_project_identity(p_project_id text)' in identity and "'owner_id',user_id" in identity
    assert 'read_lifetime_reply(p_conversation_id uuid,p_client_turn_id uuid)' in reply
    for key in ('conversation_saved','accepted_source_id','client_turn_id','context_rebuild_required'):assert "'"+key+"'" in reply
    assert 'read_lifetime_private_draft_head(p_project_id text,p_locale text)' in draft
    assert 'read_lifetime_private_draft_page(p_project_id text,p_snapshot_id uuid,p_after text default null,p_limit integer default 8)' in draft
    for key in ('coverage_round','snapshot_id','root_digest','owner_id','conversation_id','records','complete','source_refs'):assert "'"+key+"'" in draft
    for key in ('completed_rounds','sources','extracted_through','pending_inputs'):assert "'"+key+"'" in events


@pytest.mark.parametrize('changed', [
    {'source_revision':None,'current_source_revision':None},
    {'event_revision':None}, {'current_event_revision':None}, {'policy_epoch':None},
    {'source_revision':True,'current_source_revision':True}, {'policy_epoch':-1},
    {'current_event_revision':6},
])
def test_checkpoint_requires_real_frozen_revision_fields(changed):
    binding={'owner_id':OWNER,'conversation_id':CONVERSATIONS[module.CASE_IDS[0]],
        'project_id':PROJECTS[module.CASE_IDS[0]],'language':'en-AU'}
    head={**binding,'locale':'en-AU','status':'ready','snapshot_state':'completed',
        'approval_required':False,'retrieval_complete':True,'updating':False,'error':None,
        'coverage_round':5,'revision':1,'source_revision':5,'current_source_revision':5,
        'event_revision':5,'current_event_revision':5,'policy_epoch':1,'root_digest':'a'*64,'snapshot_id':str(uuid4())}
    page={**head,'snapshot_complete':True,'complete':True,'records':[
        {'id':'partition','approval_required':False,'original_withheld':False,
         'preview':{'locale':'en-AU','text':'Controlled checkpoint'},'source_refs':[{'source_id':'accepted','version':1}]}]}
    module.validate_checkpoint(head,[page],binding,5,['accepted'])
    head.update(changed)
    with pytest.raises(module.EvaluationError,match='incomplete, stale'):
        module.validate_checkpoint(head,[page],binding,5,['accepted'])


def test_subset_resume_preserves_other_case_evidence_and_campaign_completion(setup,tmp_path):
    plan,remote=setup(None);directory=tmp_path/'subset-resume'
    handler=remote.handler;fail=[True]
    def controlled_stop(request):
        result=handler(request)
        if fail[0] and request.url.path.endswith('read_lifetime_private_draft_head'):
            payload=json.loads(request.content)
            if payload['p_project_id']==PROJECTS[module.CASE_IDS[1]] and len(remote.storages[PROJECTS[module.CASE_IDS[1]]].sources)==5:
                value=result.json();value.update(snapshot_state='proposed',approval_required=True)
                return httpx.Response(200,json=value)
        return result
    remote.handler=controlled_stop
    first=asyncio.run(module.execute(plan,directory,SETTINGS))
    assert first['status']=='incomplete' and len(remote.submitted)==55
    retained=json.loads((directory/'receipt.json').read_text())['evaluation']['cases'][0]
    fail[0]=False
    selected={**plan,'case_ids':[module.CASE_IDS[1]],'cases':{module.CASE_IDS[1]:plan['cases'][module.CASE_IDS[1]]}}
    result=asyncio.run(module.execute(selected,directory,SETTINGS,resume=directory))
    assert result['selected_case_status']=='completed' and result['status']=='incomplete'
    assert len(remote.submitted)==100
    assert result['evaluation']['cases'][0]==retained
    stored=json.loads((directory/'plan.json').read_text())
    assert stored['case_ids']==list(module.CASE_IDS) and len(stored['cases'])==5
    assert stored['last_resume_selection']==[module.CASE_IDS[1]]
    assert not any(call.url.path.endswith('resolve_lifetime_conversation') for call in remote.calls)
