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
from scripts.backend_operation_lock import LOCK_PATH as MACHINE_BACKEND_LOCK
from test_issue14_subscription_runner import Storage

OWNER = '11111111-1111-4111-8111-111111111111'
OWNERS = {case: OWNER if i == 0 else str(UUID(int=200+i)) for i,case in enumerate(module.CASE_IDS)}
PROJECTS = {case:'lifetime-'+str(uuid5(UUID(OWNER),case)) for case in module.CASE_IDS}
CONVERSATIONS = {case:str(uuid5(UUID(OWNER),case+'/conversation')) for case in module.CASE_IDS}
SETTINGS = {'SUPABASE_URL': 'https://supabase.example',
            'SUPABASE_PUBLISHABLE_KEY': 'public-key', 'SUPABASE_SECRET_KEY': 'admin-secret',
            'SUPABASE_DB_URL': 'postgresql://offline-fixture-only'}


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
        self.transient_draft_error_reads=0;self.extraction_retry_required=False;self.composition_retry_required=False;self.pending_reads=0
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
                    if self.composition_retry_required and ordinal >= 5:
                        result.update(status='pending',error='MEMOIR_UNAVAILABLE')
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
            if path=='/rest/v1/rpc/validate_lifetime_replay_input':
                storage=self.storages[PROJECTS[case_id]]
                record=next((row for row in self.submitted if row['client_turn_id']==payload['p_client_turn_id']),None)
                accepted=bool(record and record['text']==payload['p_text'] and payload['p_kind']=='narrator_chat'
                    and any(source['text']==record['text'] for source in storage.sources))
                return httpx.Response(200,json=accepted)
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
                if self.composition_retry_required:
                    result['progress']['composition'] = {'state':'retry_required','error':None,'pending':False}

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
def setup(monkeypatch, tmp_path):
    from scripts import backend_operation_lock
    monkeypatch.setattr(backend_operation_lock, "LOCK_PATH", tmp_path / "offline-backend.lock")
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


def test_checkpoint_timeout_records_the_actual_wait_boundary_without_changing_the_deadline(setup, tmp_path, monkeypatch):
    plan, remote = setup()
    async def pending(*args):
        return None
    monkeypatch.setattr(module, 'saved_canonical_checkpoint', pending)
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'incomplete' and len(remote.submitted) == 5
    assert result['stop_reason'] == 'Background extraction or saved checkpoint did not settle before its deadline'
    progress = result['evaluation']['cases'][0]['rounds'][-1]['settlement_progress']
    assert progress['waiting_for'] == 'canonical_checkpoint'
    assert progress['completed_rounds'] == progress['extracted_through'] == 5
    assert progress['pending_inputs'] == 0 and progress['polls'] > 0
    assert progress['elapsed_seconds'] >= plan['settle_seconds']
    assert result['evaluation']['cases'][0]['checkpoints'] == []


def test_extraction_timeout_records_its_boundary(setup, tmp_path):
    plan, remote = setup()
    remote.pending_reads = 10000
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'incomplete' and len(remote.submitted) == 1
    progress = result['evaluation']['cases'][0]['rounds'][0]['settlement_progress']
    assert progress['waiting_for'] == 'extraction' and progress['polls'] > 0
    assert result['evaluation']['cases'][0]['rounds'][0]['background_settled'] is False


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


def test_realtime_clearance_denial_reports_the_operator_prerequisite(setup, tmp_path):
    plan, remote = setup()
    handler = remote.handler

    def denied(request):
        if request.url.path.endswith('/read_lifetime_project_identity'):
            return httpx.Response(200, json=None, text='null')
        if request.url.path.endswith('/resolve_lifetime_conversation'):
            return httpx.Response(500, json={'code': '55000',
                'message': 'LIFETIME_REALTIME_CLEARANCE_REQUIRED', 'details': 'private database details'})
        return handler(request)

    remote.handler = denied
    result = asyncio.run(module.execute(plan, tmp_path / 'run', SETTINGS))
    assert result['status'] == 'incomplete' and result['backend_turn_submissions'] == 0
    assert result['evaluation']['failure_stage'] == 'authentication'
    assert 'canonical-only conversation migration' in result['stop_reason']
    assert result['evaluation']['failure_summary']['http_failure']['error_code'] == 'LIFETIME_REALTIME_CLEARANCE_REQUIRED'
    assert 'private database details' not in json.dumps(result)
    assert not remote.submitted


@pytest.mark.parametrize('body', [{'code': '55000', 'message': 'private error'},
    {'code': '55000', 'message': 'LIFETIME_REALTIME_CLEARANCE_REQUIRED: private detail'},
    {'code': 'private-code', 'message': 'LIFETIME_REALTIME_CLEARANCE_REQUIRED'}, ['private detail']])
def test_unrecognized_database_errors_remain_sanitized(body):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(500, json=body))) as client:
            requests = module.Requests(client, 1, 5)
            with pytest.raises(module.EvaluationError) as failure:
                await requests.json('POST', 'https://backend.example/rest/v1/rpc/resolve_lifetime_conversation')
            assert str(failure.value) == 'HTTP request failed with status 500'
            assert 'error_code' not in failure.value.diagnostic
            assert 'private' not in str(failure.value) + json.dumps(failure.value.diagnostic)
    asyncio.run(run())


@pytest.mark.parametrize('target', ['container-up', 'container-down', 'install_skill',
    'db-truncate', 'memoir-live-fifty-backend'])
def test_live_execution_blocks_a_concurrent_backend_stop(setup, tmp_path, target, monkeypatch):
    # This subprocess integration must share the real machine lock. Other
    # controlled HTTP tests use a private lock and never touch the live stack.
    from scripts import backend_operation_lock
    monkeypatch.setattr(backend_operation_lock, 'LOCK_PATH', MACHINE_BACKEND_LOCK)
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


@pytest.mark.parametrize('publication_url', [None, 'postgresql://explicit-offline-publication'])
def test_backend_startup_uses_existing_usage_and_scoped_owner_without_postgres(setup, tmp_path, monkeypatch, publication_url):
    plan, remote = setup()
    started = []
    def start(command, **kwargs):
        started.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', start)
    settings = {**SETTINGS, 'SUPABASE_SECRET_KEY': None, 'SUPABASE_SERVICE_ROLE_KEY': 'admin-secret'}
    if publication_url is not None:
        settings['MEMOIR_PUBLICATION_DATABASE_URL'] = publication_url
    result = asyncio.run(module.execute(plan, tmp_path / 'run', settings, start_backend=True))
    assert result['status'] == 'completed', result
    assert len(started) == 1
    command, options = started[0]
    assert command == ['make', '--no-print-directory', 'memoir-live-fifty-backend']
    assert options['env']['MEMORY_SPARK_EVAL_RECALL_OWNER_ID'] == OWNER
    assert options['env']['MEMORY_SPARK_EVAL_RECALL_LIMIT'] == '75'
    assert options['env']['SUPABASE_SECRET_KEY'] == 'admin-secret'
    assert options['env']['MEMORY_SPARK_API_PORT'] == '8010'
    assert options['env']['MEMOIR_PUBLICATION_DATABASE_URL'] == (publication_url or SETTINGS['SUPABASE_DB_URL'])


@pytest.mark.parametrize('overrides,reason', [
    ({'SUPABASE_DB_URL': None}, 'publication database connection'),
    ({'MEMOIR_LIFETIME_GENERATION_PAUSED': 'true'}, 'canonical generation is paused'),
])
def test_backend_startup_honors_explicit_rollout_controls(setup, tmp_path, monkeypatch, overrides, reason):
    plan, remote = setup()
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: pytest.fail('Invalid configuration started services.'))
    result = asyncio.run(module.execute(plan, tmp_path / 'run', {**SETTINGS, **overrides}, start_backend=True))
    assert result['status'] == 'incomplete' and reason in result['stop_reason']
    assert result['evaluation']['failure_stage'] == 'backend_startup'
    assert not remote.submitted


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


def test_source_fix_resume_requires_opt_in_and_records_original_evidence(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'source-fix'
    remote.extraction_retry_required=True
    first=asyncio.run(module.execute(plan,directory,SETTINGS))
    assert first['status']=='incomplete' and len(remote.submitted)==1
    original=deepcopy(first['evaluation']['cases'][0]['rounds'][0])
    changed=deepcopy(plan)
    changed['local_checkout_source']={**plan['local_checkout_source'],'snapshot_sha256':'b'*64}
    calls=len(remote.calls)
    with pytest.raises(module.EvaluationError,match='source'):
        asyncio.run(module.execute(changed,directory,SETTINGS,resume=directory))
    assert len(remote.calls)==calls
    remote.extraction_retry_required=False
    result=asyncio.run(module.execute(changed,directory,SETTINGS,
        resume=directory,accept_source_change=True))
    assert result['status']=='completed' and len(remote.submitted)==50
    restored=result['evaluation']['cases'][0]['rounds'][0]
    assert all(restored[key]==original[key] for key in ('client_turn_id','accepted_source_id','reply'))
    change=result['source_changes'][0]
    assert change['previous']==plan['local_checkout_source']
    assert change['current']==changed['local_checkout_source']
    assert change['backend_turn_submissions']==1
    assert result['local_checkout_source']==changed['local_checkout_source']
    saved_plan=json.loads((directory/'plan.json').read_text())
    assert saved_plan['local_checkout_source']==changed['local_checkout_source']
    assert saved_plan['cases']==plan['cases']
    assert module.budget_contract(saved_plan)==module.budget_contract(plan)
    again=asyncio.run(module.execute(changed,directory,SETTINGS,resume=directory))
    assert again['status']=='completed' and len(again['source_changes'])==1


def test_source_fix_opt_in_cannot_change_original_commit_or_service(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'source-fix-scope'
    remote.extraction_retry_required=True
    asyncio.run(module.execute(plan,directory,SETTINGS))
    calls=len(remote.calls)
    for key,value in [('source_revision','c'*40),('api_base','http://foreign.invalid'),('dataset_sha256','d'*64)]:
        changed={**plan,key:value}
        with pytest.raises(module.EvaluationError,match='identities'):
            asyncio.run(module.execute(changed,directory,SETTINGS,resume=directory,accept_source_change=True))
        assert len(remote.calls)==calls


def test_accepted_source_without_reply_requires_explicit_idempotent_response_recovery(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'accepted-without-reply';handler=remote.handler
    recovery=[]
    def missing_response(request):
        if request.url.path.endswith('read_lifetime_reply') and not recovery:
            return httpx.Response(200,text='null',headers={'Content-Type':'application/json'})
        if request.url.path.endswith('/agent/turn'):
            payload=json.loads(request.content)
            if remote.submitted and payload['client_turn_id']==remote.submitted[0]['client_turn_id']:
                recovery.append(payload)
                source=remote.storages[payload['project_id']].sources[0]
                return httpx.Response(200,json={'project_id':payload['project_id'],
                    'accepted_source_id':source['id'],'reply':'Recovered response','cached':False,'task_errors':[]})
            result=handler(request)
            if len(remote.submitted)==1:return httpx.Response(502,json={'detail':'Response failed after source acceptance'})
            return result
        return handler(request)
    remote.handler=missing_response
    first=asyncio.run(module.execute(plan,directory,SETTINGS))
    assert first['status']=='incomplete' and len(remote.submitted)==1
    stopped=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert stopped['status']=='incomplete' and not recovery
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory,recover_accepted_turn=True))
    assert result['status']=='completed',result
    assert len(remote.submitted)==50 and len(recovery)==1
    assert recovery[0]==remote.submitted[0]
    assert len(remote.storages[PROJECTS[module.CASE_IDS[0]]].sources)==50
    assert result['backend_turn_submissions']==50 and result['backend_recovery_submissions']==1
    rounds=result['evaluation']['cases'][0]['rounds']
    assert rounds[0]['accepted_source_id']==first['evaluation']['cases'][0]['rounds'][0].get('accepted_source_id',rounds[0]['accepted_source_id'])
    assert rounds[0]['response_retry_attempts']==1
    assert len({row['accepted_source_id'] for row in rounds})==50


def test_response_recovery_cannot_resubmit_unaccepted_original(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'unaccepted-response';remote.fail_round=1
    asyncio.run(module.execute(plan,directory,SETTINGS))
    remote.fail_round=None
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory,recover_accepted_turn=True))
    assert result['status']=='incomplete' and len(remote.submitted)==1


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


@pytest.mark.parametrize('key,value', [
    ('max_backend_requests',1000),('max_backend_requests',90),
    ('max_elapsed_seconds',1000),('max_elapsed_seconds',100),
    ('max_case_elapsed_seconds',600),('max_case_elapsed_seconds',50),
    ('settle_seconds',2),('settle_seconds',.5),('poll_seconds',.01),('poll_seconds',.0005),
])
def test_resume_rejects_changed_original_limits_before_auth_and_preserves_partial_failure(setup,tmp_path,key,value):
    plan,remote=setup();plan['max_backend_requests']=100;remote.draft_failed=True;directory=tmp_path/'immutable'
    first=asyncio.run(module.execute(plan,directory,SETTINGS))
    assert first['status']=='incomplete' and len(remote.submitted)==5
    before={name:(directory/name).read_bytes() for name in ('plan.json','receipt.json','request-counter.json')}
    calls=len(remote.calls)
    with pytest.raises(module.EvaluationError,match='immutable budget'):
        asyncio.run(module.execute({**plan,key:value},directory,SETTINGS,resume=directory))
    assert len(remote.calls)==calls and len(remote.submitted)==5
    assert all((directory/name).read_bytes()==data for name,data in before.items())


def test_expired_case_resume_stops_before_auth_without_resetting_case_origin(setup,tmp_path):
    plan,remote=setup();remote.draft_failed=True;directory=tmp_path/'expired-case'
    first=asyncio.run(module.execute(plan,directory,SETTINGS));assert first['status']=='incomplete'
    receipt=module.private_json(directory/'receipt.json');now=module.time.time()
    receipt['started_at_unix']=now-70;origin=now-61
    receipt['case_started_at_unix'][module.CASE_IDS[0]]=origin
    module.save(directory/'receipt.json',receipt)
    calls=len(remote.calls);counter=module.private_json(directory/'request-counter.json')['reserved']
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='incomplete' and result['stop_reason']=='Original case elapsed-time ceiling reached'
    assert len(remote.calls)==calls and len(remote.submitted)==5
    assert result['case_started_at_unix'][module.CASE_IDS[0]]==origin
    assert result['request_accounting']['backend_http_requests_reserved']==counter


def test_explicit_time_extension_preserves_original_origins_requests_and_turns(setup,tmp_path):
    plan,remote=setup();plan.update(max_elapsed_seconds=7200,max_case_elapsed_seconds=7200)
    remote.draft_failed=True;directory=tmp_path/'time-extension'
    first=asyncio.run(module.execute(plan,directory,SETTINGS))
    assert first['status']=='incomplete' and len(remote.submitted)==5
    original_rounds=deepcopy(first['evaluation']['cases'][0]['rounds'])
    receipt=module.private_json(directory/'receipt.json');now=module.time.time()
    receipt['started_at_unix']=now-7300
    receipt['case_started_at_unix'][module.CASE_IDS[0]]=now-7250
    module.save(directory/'receipt.json',receipt)
    origins=deepcopy(receipt['case_started_at_unix'])
    reserved=module.private_json(directory/'request-counter.json')['reserved']
    remote.draft_failed=False
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory,extend_time_limit_seconds=14400))
    assert result['status']=='completed',result
    saved=module.private_json(directory/'plan.json')
    assert module.budget_contract(saved)==module.budget_contract(plan)==result['budget_contract']
    assert result['started_at_unix']==receipt['started_at_unix'] and result['case_started_at_unix']==origins
    resumed_rounds=result['evaluation']['cases'][0]['rounds'][:5]
    assert resumed_rounds[:4]==original_rounds[:4]
    for before,after in zip(original_rounds,resumed_rounds):
        assert all(after[key]==before[key] for key in ('round','client_turn_id','accepted_source_id','reply'))
    assert resumed_rounds[-1]['previous_failure_summary']==original_rounds[-1]['failure_summary']
    assert len(remote.submitted)==50 and result['backend_turn_submissions']==50
    assert result['request_accounting']['backend_http_requests_reserved']==len(remote.calls)>reserved
    assert saved['elapsed_time_extensions']==result['elapsed_time_extensions']
    event=result['elapsed_time_extensions'][0]
    assert event['seconds']==14400 and event['backend_turn_submissions']==5
    again=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert again['status']=='completed' and again['elapsed_time_extensions']==result['elapsed_time_extensions']
    assert len(remote.submitted)==50 and again['case_started_at_unix']==origins


@pytest.mark.parametrize('invalid', [14401, True, 0, 14400.0])
def test_invalid_time_extension_stops_before_auth_or_evidence_changes(setup,tmp_path,invalid):
    plan,remote=setup();plan.update(max_elapsed_seconds=7200,max_case_elapsed_seconds=7200)
    remote.draft_failed=True;directory=tmp_path/'bad-extension'
    asyncio.run(module.execute(plan,directory,SETTINGS))
    before={name:(directory/name).read_bytes() for name in ('plan.json','receipt.json','request-counter.json')}
    calls=len(remote.calls)
    with pytest.raises(module.EvaluationError,match='14400 seconds'):
        asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory,extend_time_limit_seconds=invalid))
    assert len(remote.calls)==calls
    assert all((directory/name).read_bytes()==data for name,data in before.items())


def test_time_extension_requires_resume_and_original_single_case(setup,tmp_path):
    plan,remote=setup(None);directory=tmp_path/'multi-case-extension'
    with pytest.raises(module.EvaluationError,match='saved resume'):
        asyncio.run(module.execute(plan,directory,SETTINGS,extend_time_limit_seconds=14400))
    assert not directory.exists() and not remote.calls
    remote.draft_failed=True
    asyncio.run(module.execute(plan,directory,SETTINGS))
    calls=len(remote.calls)
    with pytest.raises(module.EvaluationError,match='single-case'):
        asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory,extend_time_limit_seconds=14400))
    assert len(remote.calls)==calls


def test_explicit_extension_targets_only_one_existing_case_without_resetting_campaign(setup,tmp_path):
    plan,remote=setup(None);plan.update(max_elapsed_seconds=36000,max_case_elapsed_seconds=7200)
    remote.draft_failed=True;directory=tmp_path/'scoped-extension'
    first=asyncio.run(module.execute(plan,directory,SETTINGS))
    target=module.CASE_IDS[0]
    selected={**plan,'case_ids':[target],'cases':{target:plan['cases'][target]}}
    receipt=module.private_json(directory/'receipt.json');now=module.time.time()
    receipt['started_at_unix']=now-7300;receipt['case_started_at_unix'][target]=now-7250
    module.save(directory/'receipt.json',receipt);origins=deepcopy(receipt['case_started_at_unix'])
    reserved=module.private_json(directory/'request-counter.json')['reserved'];remote.draft_failed=False
    result=asyncio.run(module.execute(selected,directory,SETTINGS,resume=directory,extend_time_limit_seconds=14400))
    case=next(c for c in result['evaluation']['cases'] if c['case_id']==target)
    assert case['status']=='completed' and len(case['rounds'])==50
    assert result['status']=='incomplete' and len(remote.submitted)==50
    assert result['started_at_unix']==receipt['started_at_unix'] and result['case_started_at_unix']==origins
    assert result['budget_contract']==module.budget_contract(plan)
    assert result['request_accounting']['backend_http_requests_reserved']>reserved
    history=result['elapsed_time_extensions'];assert history[0]['case_ids']==[target]
    saved=module.private_json(directory/'plan.json');assert saved['case_ids']==plan['case_ids']
    assert module.budget_contract(saved)==module.budget_contract(plan)
    other=module.CASE_IDS[1];other_plan={**plan,'case_ids':[other],'cases':{other:plan['cases'][other]}}
    assert module.resumed_time_limit(other_plan,saved,result) is None
    with pytest.raises(module.EvaluationError,match='another case'):
        module.resumed_time_limit(other_plan,saved,result,14400)


def test_resumed_partial_case_reuses_remaining_time_and_reserves_all_prior_attempts(setup,tmp_path,monkeypatch):
    plan,remote=setup();remote.draft_failed=True;directory=tmp_path/'remaining-time'
    first=asyncio.run(module.execute(plan,directory,SETTINGS));assert first['status']=='incomplete'
    receipt=module.private_json(directory/'receipt.json');now=module.time.time()
    receipt['started_at_unix']=now-20;origin=now-15;receipt['case_started_at_unix'][module.CASE_IDS[0]]=origin
    module.save(directory/'receipt.json',receipt)
    before=module.private_json(directory/'request-counter.json')['reserved'];observed=[];set_deadline=module.set_case_deadline
    def measured(requests,plan,value):
        set_deadline(requests,plan,value)
        if value is not None:observed.append((value,requests.case_deadline-module.time.monotonic()))
    monkeypatch.setattr(module,'set_case_deadline',measured);remote.draft_failed=False
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='completed',result
    assert observed and all(value==origin and 0<remaining<=45 for value,remaining in observed)
    assert result['case_started_at_unix'][module.CASE_IDS[0]]==origin
    assert result['request_accounting']['backend_http_requests_reserved']==len(remote.calls)>before
    assert len(remote.submitted)==50


def test_expired_campaign_resume_has_no_new_requests(setup,tmp_path):
    plan,remote=setup();remote.draft_failed=True;directory=tmp_path/'expired-campaign'
    asyncio.run(module.execute(plan,directory,SETTINGS))
    receipt=module.private_json(directory/'receipt.json');now=module.time.time()
    receipt['started_at_unix']=now-121;receipt['case_started_at_unix'][module.CASE_IDS[0]]=now-61
    module.save(directory/'receipt.json',receipt);calls=len(remote.calls)
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['stop_reason']=='Original campaign elapsed-time ceiling reached' and len(remote.calls)==calls


def test_resume_rejects_rolled_back_request_counter_without_mutating_receipt(setup,tmp_path):
    plan,remote=setup();remote.draft_failed=True;directory=tmp_path/'rolled-counter'
    asyncio.run(module.execute(plan,directory,SETTINGS));before=(directory/'receipt.json').read_bytes();calls=len(remote.calls)
    count=module.private_json(directory/'request-counter.json');count['reserved']-=1;module.save(directory/'request-counter.json',count)
    with pytest.raises(module.EvaluationError,match='request counter'):
        asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert len(remote.calls)==calls and (directory/'receipt.json').read_bytes()==before


def test_resume_at_original_request_ceiling_has_no_new_attempts(setup,tmp_path):
    plan,remote=setup();plan['max_backend_requests']=100;remote.draft_failed=True;directory=tmp_path/'exhausted-counter'
    asyncio.run(module.execute(plan,directory,SETTINGS));calls=len(remote.calls)
    module.save(directory/'request-counter.json',{'run_id':plan['run_id'],'reserved':100})
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='incomplete' and len(remote.calls)==calls and len(remote.submitted)==5
    assert result['request_accounting']['backend_http_requests_reserved']==100


@pytest.mark.parametrize('lost_response',[False,True])
def test_resume_checks_only_remaining_allowance_after_verified_ledger_and_idempotent_recovery(setup,tmp_path,lost_response):
    plan,remote=setup();directory=tmp_path/'remaining-allowance';handler=remote.handler;lost=[False]
    remote.draft_failed=not lost_response
    def scoped_allowance(request):
        response=handler(request)
        if request.url.path.endswith('/story/state'):
            payload=response.json();payload['recall_status'].update(free_rounds=50,rounds_completed=len(remote.storages[PROJECTS[module.CASE_IDS[0]]].sources))
            return httpx.Response(200,json=payload)
        if lost_response and request.url.path.endswith('/agent/turn') and len(remote.submitted)==7 and not lost[0]:
            lost[0]=True;return httpx.Response(502,json={'fixture':'lost response'})
        return response
    remote.handler=scoped_allowance
    first=asyncio.run(module.execute(plan,directory,SETTINGS));assert first['status']=='incomplete'
    assert len(remote.submitted)==(7 if lost_response else 5)
    remote.draft_failed=False
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='completed',result
    assert len(remote.submitted)==50
    if lost_response:assert sum(call.url.path.endswith('read_lifetime_reply') for call in remote.calls)==1
    # A fully accepted case requires no unused allowance to verify completion again.
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='completed' and len(remote.submitted)==50


def test_insufficient_remaining_allowance_and_foreign_ledger_stop_before_new_turn(setup,tmp_path):
    plan,remote=setup();remote.draft_failed=True;directory=tmp_path/'insufficient';handler=remote.handler;free=[50]
    def scoped(request):
        response=handler(request)
        if request.url.path.endswith('/story/state'):
            value=response.json();value['recall_status'].update(free_rounds=free[0],rounds_completed=len(remote.storages[PROJECTS[module.CASE_IDS[0]]].sources))
            return httpx.Response(200,json=value)
        return response
    remote.handler=scoped;asyncio.run(module.execute(plan,directory,SETTINGS));remote.draft_failed=False;free[0]=49
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='incomplete' and 'allowance is too small' in result['stop_reason'] and len(remote.submitted)==5
    remote.storages[PROJECTS[module.CASE_IDS[0]]].sources[0]['text']='Foreign changed history'
    before=sum(call.url.path.endswith('/story/state') for call in remote.calls)
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='incomplete' and result['evaluation']['failure_stage']=='canonical_ledger'
    assert len(remote.submitted)==5 and sum(call.url.path.endswith('/story/state') for call in remote.calls)==before


@pytest.mark.parametrize('changed',['source_ledger','canonical_count'])
def test_failed_completed_case_revalidation_cannot_be_hidden_by_later_subset_resume(setup,tmp_path,changed):
    plan,remote=setup(None);directory=tmp_path/'revalidate-all'
    first=asyncio.run(module.execute(plan,directory,SETTINGS));assert first['status']=='completed'
    assert len(remote.submitted)==250
    selected=lambda case:{**plan,'case_ids':[case],'cases':{case:plan['cases'][case]}}
    target=module.CASE_IDS[0];handler=remote.handler;bad=[True]
    def changed_readback(request):
        response=handler(request)
        if changed=='canonical_count' and bad[0] and request.url.path.endswith('read_user_memory_events') and json.loads(request.content)['p_project_id']==PROJECTS[target]:
            value=response.json();value['completed_rounds']=51
            return httpx.Response(200,json=value)
        return response
    remote.handler=changed_readback
    if changed=='source_ledger':remote.storages[PROJECTS[target]].sources[0]['version']=2
    failed=asyncio.run(module.execute(selected(target),directory,SETTINGS,resume=directory))
    case=next(item for item in failed['evaluation']['cases'] if item['case_id']==target)
    assert failed['status']=='incomplete' and failed['selected_case_status']=='incomplete'
    assert case['status']=='incomplete' and case['evidence_validated'] is False
    assert all(round['status']=='completed' for round in case['rounds'])
    result=asyncio.run(module.execute(selected(module.CASE_IDS[1]),directory,SETTINGS,resume=directory))
    assert result['selected_case_status']=='completed' and result['status']=='incomplete'
    bad[0]=False;remote.storages[PROJECTS[target]].sources[0]['version']=1
    result=asyncio.run(module.execute(selected(target),directory,SETTINGS,resume=directory))
    assert all(item['status']=='completed' for item in result['evaluation']['cases'])
    assert result['status']=='completed' # All other finished cases were freshly revalidated read-only.
    assert all(item['validation_attempt_id']==result['attempt_id'] for item in result['evaluation']['cases'])
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='completed',result
    assert all(item['validation_attempt_id']==result['attempt_id'] and item['evidence_validated'] for item in result['evaluation']['cases'])
    assert len(remote.submitted)==250


def test_cli_subset_resume_inherits_original_limits_and_rejects_explicit_budget_change(setup,tmp_path,capsys):
    plan,remote=setup(None);plan.update(max_elapsed_seconds=36000,max_case_elapsed_seconds=7200,max_backend_requests=100000)
    remote.draft_failed=True;directory=tmp_path/'cli-original'
    assert asyncio.run(module.execute(plan,directory,SETTINGS))['status']=='incomplete'
    args=['--resume-dir',str(directory),'--case-id',module.CASE_IDS[0],'--source-revision',plan['source_revision'],
        '--api-base',plan['api_base'],'--web-base',plan['web_base']]
    assert module.main(args)==0
    rendered=json.loads(capsys.readouterr().out)
    assert module.budget_contract(rendered)==module.budget_contract(plan)
    assert rendered['max_elapsed_seconds']==36000 and rendered['max_backend_requests']==100000
    calls=len(remote.calls)
    assert module.main(args+['--max-backend-requests','1000'])==3
    assert 'immutable budget' in json.loads(capsys.readouterr().out)['reason'] and len(remote.calls)==calls


def test_resumed_backend_startup_reuses_original_case_allowance(setup,tmp_path,monkeypatch):
    plan,remote=setup();remote.draft_failed=True;directory=tmp_path/'scoped-limit';handler=remote.handler;limits=[]
    def scoped(request):
        response=handler(request)
        if request.url.path.endswith('/user_recall_usage'):
            return httpx.Response(200,json=[{'rounds_completed':25+len(remote.storages[PROJECTS[module.CASE_IDS[0]]].sources)}])
        return response
    remote.handler=scoped
    def startup(*args,**kwargs):
        limits.append(kwargs['env']['MEMORY_SPARK_EVAL_RECALL_LIMIT']);return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess,'run',startup)
    first=asyncio.run(module.execute(plan,directory,SETTINGS,start_backend=True));assert first['status']=='incomplete'
    remote.draft_failed=False
    result=asyncio.run(module.execute(plan,directory,SETTINGS,start_backend=True,resume=directory))
    assert result['status']=='completed',result
    assert limits==['75','75'] and len(remote.submitted)==50


@pytest.mark.parametrize('selection',[None,module.CASE_IDS[1]])
def test_legacy_login_email_environment_never_overrides_campaign_mapping(setup,monkeypatch,capsys,selection):
    setup(selection);monkeypatch.setenv('MEMOIR_EVAL_USER_EMAIL','test@test.com')
    args=['--source-revision','a'*40]+(['--case-id',selection] if selection else [])
    assert module.main(args)==0
    rendered=json.loads(capsys.readouterr().out)
    assert rendered['user_email'] is None
    assert all(binding['user_email']==module.CASE_EMAILS[case] for case,binding in rendered['cases'].items())


@pytest.mark.parametrize('changed',[
    {'snapshot_state':'proposed','approval_required':True,'updating':True},
    {'snapshot_state':'completed','approval_required':False,'updating':True},
    {'status':'pending'},
])
def test_completed_resume_rejects_current_pending_or_proposed_draft_without_new_turn(setup,tmp_path,changed):
    plan,remote=setup();directory=tmp_path/'current-draft'
    assert asyncio.run(module.execute(plan,directory,SETTINGS))['status']=='completed'
    old=module.private_json(directory/'receipt.json')['evaluation']['cases'][0]['checkpoints'];handler=remote.handler
    def changed_head(request):
        response=handler(request)
        if request.url.path.endswith('read_lifetime_private_draft_head'):
            value=response.json();value.update(changed);return httpx.Response(200,json=value)
        return response
    remote.handler=changed_head;before=len(remote.submitted)
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    case=result['evaluation']['cases'][0]
    assert result['status']=='incomplete' and case['status']=='incomplete' and case['evidence_validated'] is False
    assert 'current_checkpoint' not in case and case['checkpoints']==old
    assert len(remote.submitted)==before==50


def test_completed_resume_retrieves_and_checks_actual_live_draft_pages_again(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'current-pages'
    assert asyncio.run(module.execute(plan,directory,SETTINGS))['status']=='completed'
    before=sum(call.url.path.endswith('read_lifetime_private_draft_page') for call in remote.calls)
    handler=remote.handler
    def bad_page(request):
        response=handler(request)
        if request.url.path.endswith('read_lifetime_private_draft_page'):
            value=response.json();value['records'][0]['source_refs'][0]['source_id']='foreign-current-source'
            return httpx.Response(200,json=value)
        return response
    remote.handler=bad_page
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='incomplete' and result['evaluation']['cases'][0]['evidence_validated'] is False
    assert sum(call.url.path.endswith('read_lifetime_private_draft_page') for call in remote.calls)>before
    assert len(remote.submitted)==50


def test_subset_finishes_with_read_only_validation_of_expired_completed_case_without_new_submission_time(setup,tmp_path,monkeypatch):
    ids=list(module.CASE_IDS[:2]);plan,remote=setup(ids);directory=tmp_path/'late-finish'
    handler=remote.handler;stop=[True];target=ids[1]
    def interrupted_second_case(request):
        response=handler(request)
        if stop[0] and request.url.path.endswith('read_lifetime_private_draft_head') and json.loads(request.content)['p_project_id']==PROJECTS[target] and len(remote.storages[PROJECTS[target]].sources)==5:
            value=response.json();value.update(snapshot_state='proposed',approval_required=True);return httpx.Response(200,json=value)
        return response
    remote.handler=interrupted_second_case
    first=asyncio.run(module.execute(plan,directory,SETTINGS));assert first['status']=='incomplete' and len(remote.submitted)==55
    receipt=module.private_json(directory/'receipt.json');now=module.time.time()
    receipt['started_at_unix']=now-70;receipt['case_started_at_unix'][ids[0]]=now-61;receipt['case_started_at_unix'][ids[1]]=now-1
    original_origins=dict(receipt['case_started_at_unix']);module.save(directory/'receipt.json',receipt)
    stop[0]=False;before=len(remote.calls)
    selected={**plan,'case_ids':[target],'cases':{target:plan['cases'][target]}}
    def no_startup(*args,**kwargs):pytest.fail('Read-only completion verification must not start a service.')
    monkeypatch.setattr(module.subprocess,'run',no_startup)
    result=asyncio.run(module.execute(selected,directory,SETTINGS,resume=directory))
    assert result['status']==result['selected_case_status']=='completed',result
    assert result['case_started_at_unix']==original_origins and module.budget_contract(plan)==result['budget_contract']
    assert len(remote.submitted)==100 and all(item['validation_attempt_id']==result['attempt_id'] for item in result['evaluation']['cases'])
    completed_project=PROJECTS[ids[0]]
    calls=remote.calls[before:]
    assert not any(call.url.path.endswith('/agent/turn') and json.loads(call.content)['project_id']==completed_project for call in calls)
    assert not any(call.url.path.endswith('/projects') and call.method=='POST' and json.loads(call.content)['restore_project_id']==completed_project for call in calls)
    assert result['read_only_revalidation'][-1]['max_elapsed_seconds']==module.READ_ONLY_REVALIDATION_SECONDS
    assert result['request_accounting']['backend_http_requests_reserved']==len(remote.calls)


def test_all_completed_cases_can_be_revalidated_after_submission_deadlines_expire_with_original_counter(setup,tmp_path,monkeypatch):
    plan,remote=setup(list(module.CASE_IDS[:2]));directory=tmp_path/'late-all'
    first=asyncio.run(module.execute(plan,directory,SETTINGS));assert first['status']=='completed'
    receipt=module.private_json(directory/'receipt.json');now=module.time.time()
    receipt['started_at_unix']=now-500
    for case in plan['case_ids']:receipt['case_started_at_unix'][case]=now-450
    origins=dict(receipt['case_started_at_unix']);module.save(directory/'receipt.json',receipt)
    before=len(remote.calls);counter=module.private_json(directory/'request-counter.json')['reserved']
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:pytest.fail('No startup allowed for completed-case read-only validation.'))
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory,start_backend=True))
    assert result['status']=='completed',result
    assert len(remote.submitted)==100 and result['case_started_at_unix']==origins
    assert result['request_accounting']['backend_http_requests_reserved']==len(remote.calls)>counter
    assert not any(call.url.path.endswith('/agent/turn') or call.url.path.endswith('/projects') and call.method=='POST' for call in remote.calls[before:])
    assert not any(call.method=='PUT' for call in remote.calls[before:])


def test_late_completed_case_still_respects_original_request_ceiling(setup,tmp_path):
    plan,remote=setup();directory=tmp_path/'late-counter'
    assert asyncio.run(module.execute(plan,directory,SETTINGS))['status']=='completed'
    receipt=module.private_json(directory/'receipt.json');receipt['started_at_unix']=module.time.time()-500
    receipt['case_started_at_unix'][module.CASE_IDS[0]]=module.time.time()-450
    module.save(directory/'receipt.json',receipt);before=len(remote.calls)
    module.save(directory/'request-counter.json',{'run_id':plan['run_id'],'reserved':plan['max_backend_requests']})
    result=asyncio.run(module.execute(plan,directory,SETTINGS,resume=directory))
    assert result['status']=='incomplete' and len(remote.calls)==before and len(remote.submitted)==50
    assert result['request_accounting']['backend_http_requests_reserved']==plan['max_backend_requests']


def test_read_only_mode_cannot_submit_or_restore_even_if_called_directly():
    class NoContact:
        read_only=True
        async def json(self,*args,**kwargs):pytest.fail('Read-only mutation contacted a service.')
    for path in ['/v1/agent/turn','/v1/projects']:
        with pytest.raises(module.EvaluationError,match='cannot mutate or submit'):
            asyncio.run(module.backend(NoContact(),None,{'api_base':'http://fixture.invalid'},'POST',path,json={}))


def test_terminal_composition_error_stops_at_the_checkpoint_without_settle_wait(setup,tmp_path):
    plan,remote=setup()
    remote.composition_retry_required=True
    result=asyncio.run(module.execute(plan,tmp_path/'run',SETTINGS))
    assert result['status']=='incomplete' and len(remote.submitted)==5
    assert result['stop_reason']=='Background composition failed; explicit review is required'
    assert result['evaluation']['cases'][0]['checkpoints']==[]
