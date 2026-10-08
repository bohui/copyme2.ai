"""Contract for explicitly opted-in, deny-only issue 14 admission.

Synthetic tests. No credentials or real provider/judge calls.
These are policy contracts; actual runtime/socket/subprocess tests must follow
the integration checklist. They are not evidence of completed integration.
"""
from dataclasses import FrozenInstanceError
from uuid import uuid4
import asyncio
from contextlib import asynccontextmanager
import json
import os

import httpx

import pytest

from apps.api.issue14_execution_admission import (
    AdmissionDenied,
    Issue14Admission,
    require_issue14_admission,
)


REVISION = '18f6ad6c190aafd3ba7a23ed2b28ced03a178d9f'
ROLES = ('collector', 'workspace', 'classification', 'composer_preparation',
         'composer_draft', 'composer_review', 'tool_loop', 'retry', 'judge', 'photo')


def policy():
    return Issue14Admission.deny_only(run_id=str(uuid4()), source_revision=REVISION)


@pytest.mark.parametrize('role', ROLES)
def test_valid_owned_policy_still_refuses_every_live_role(role):
    admission = policy()
    with pytest.raises(AdmissionDenied, match='provider_capability_unverified'):
        require_issue14_admission(admission, run_id=admission.run_id,
            source_revision=REVISION, role=role)


@pytest.mark.parametrize('foreign', [None, True, {}, {'live_ready': True}, object()])
def test_missing_or_caller_invented_policy_never_grants_admission(foreign):
    with pytest.raises(AdmissionDenied):
        require_issue14_admission(foreign, run_id=str(uuid4()),
            source_revision=REVISION, role='collector')


def test_object_with_successful_check_method_is_not_authority():
    class Forged:
        live_ready = True
        def check(self, **kwargs):
            return True
    with pytest.raises(AdmissionDenied):
        require_issue14_admission(Forged(), run_id=str(uuid4()),
            source_revision=REVISION, role='collector')


@pytest.mark.parametrize('change', [
    {'run_id': str(uuid4())}, {'source_revision': '0' * 40}, {'role': 'unknown'}])
def test_identity_and_role_mismatch_fail_closed(change):
    admission = policy()
    values = {'run_id': admission.run_id, 'source_revision': REVISION, 'role': 'collector'}
    with pytest.raises(AdmissionDenied):
        require_issue14_admission(admission, **{**values, **change})


def test_policy_is_immutable_and_has_no_live_switch():
    admission = policy()
    with pytest.raises((AttributeError, FrozenInstanceError)):
        admission.run_id = str(uuid4())
    with pytest.raises(TypeError):
        Issue14Admission.deny_only(run_id=str(uuid4()), source_revision=REVISION,
            live_ready=True)


def test_receipt_never_claims_provider_enforcement():
    receipt = policy().receipt()
    assert receipt['mode'] == 'deny_only'
    assert receipt['live_ready'] is False
    assert receipt['actual_provider_requests'] is None
    assert receipt['real_provider_token_or_cost_limits_verified'] is False


@pytest.fixture
def app_modules(monkeypatch, tmp_path):
    # Application imports and constructors must never see real provider config.
    original = os.getenv
    def fixture_env(name, default=None):
        if name == 'MEMORY_SPARK_TEST_MODE':
            return '1'
        if name == 'MEMORY_SPARK_CODEX_HOME':
            return str(tmp_path / 'fixture-default-home')
        if name.startswith('MEMORY_SPARK_'):
            return default
        return original(name, default)
    monkeypatch.setattr(os, 'getenv', fixture_env)
    from apps.api import codex_agent, codex_runtime, codex_worker_service
    return codex_agent, codex_runtime, codex_worker_service


@asynccontextmanager
async def counted_endpoint():
    contacts = []
    async def connected(reader, writer):
        contacts.append(True)
        writer.close()
        await writer.wait_closed()
    listener = await asyncio.start_server(connected, '127.0.0.1', 0)
    try:
        yield 'http://127.0.0.1:%d' % listener.sockets[0].getsockname()[1], contacts
    finally:
        listener.close()
        await listener.wait_closed()


@pytest.mark.parametrize('entry', ['enter', 'send', 'request', 'turn'])
def test_opted_native_connection_refuses_before_spawn_or_stdio(app_modules, tmp_path, monkeypatch, entry):
    agent, _, _ = app_modules
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append('subprocess')
        raise AssertionError('Native launch occurred')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    async def check():
        home = tmp_path / 'not-created'
        connection = agent.CodexConnection(['synthetic-codex'], home, issue14_admission=policy())
        with pytest.raises(AdmissionDenied):
            if entry == 'enter':
                await connection.__aenter__()
            elif entry == 'send':
                await connection.send({'method': 'turn/start', 'params': {}})
            elif entry == 'request':
                await connection.request('turn/start', {})
            else:
                await connection.turn('synthetic-thread', 'synthetic text')
        assert calls == []
        assert not home.exists()
    asyncio.run(check())


@pytest.mark.parametrize('entry', ['worker', 'turn', 'workspace', 'language', 'publish'])
@pytest.mark.parametrize('metadata', [None, {}, {'run_id': str(uuid4())}, {'live_ready': True}])
def test_opted_runtime_refuses_all_paths_with_zero_worker_contacts(app_modules, tmp_path, monkeypatch, entry, metadata):
    _, runtime_module, _ = app_modules
    def no_home(*args, **kwargs):
        raise AssertionError('Runtime home/config was touched')
    async def check():
        async with counted_endpoint() as (endpoint, contacts):
            runtime = runtime_module.CodexRuntime(home_root=tmp_path / 'runtime',
                command=['synthetic-codex'], provider_env={}, base_url=endpoint,
                worker_url=endpoint, worker_secret='synthetic-worker-secret',
                issue14_admission=policy())
            monkeypatch.setattr(runtime, '_home', no_home)
            with pytest.raises(AdmissionDenied):
                if entry == 'worker':
                    await runtime._worker_turn(user_id=str(uuid4()), prior=None,
                        memories=[], profile={}, place_journey={}, family_enabled=False,
                        family_context={}, project_id=None, text='synthetic', language='en-AU',
                        evaluation=metadata)
                elif entry == 'turn':
                    await runtime.turn(object(), 'synthetic', evaluation=metadata)
                elif entry == 'workspace':
                    await runtime._workspace_extraction(user_id=str(uuid4()), memories=[],
                        profile={}, place_journey={}, family_enabled=False, family_context={},
                        project_id=None, text='synthetic', language='en-AU')
                elif entry == 'language':
                    await runtime._resolve_language(str(uuid4()), 'synthetic', 'en-AU')
                else:
                    await runtime.publish_task(str(uuid4()), 'synthetic-project', {})
            await asyncio.sleep(0)
            assert contacts == []
            assert runtime.observed_worker_requests == 0
    asyncio.run(check())


@pytest.mark.parametrize('role,phase', [('collector','draft'), ('workspace','draft'),
    ('memory_context','draft'), ('author_timeline','draft'), ('organiser','draft'),
    ('composer','prepare'), ('composer','draft'), ('composer','review')])
def test_opted_worker_denies_before_provider_probe_home_or_launch(app_modules, tmp_path, monkeypatch, role, phase):
    _, _, module = app_modules
    def forbidden(*args, **kwargs):
        raise AssertionError('Worker identity/home/config was touched')
    async def check():
        async with counted_endpoint() as (endpoint, contacts):
            worker = module.CodexWorker(home_root=tmp_path / 'worker', api_key='',
                command=['synthetic-codex'], base_url=endpoint,
                issue14_admission=policy())
            monkeypatch.setattr(worker, '_uid_for', forbidden)
            monkeypatch.setattr(worker, '_home', forbidden)
            payload = module.WorkerTurnInput(user_id=uuid4(), text='synthetic',
                agent_role=role, composer_phase=phase,
                preparation_id='0' * 64 if phase == 'prepare' else None)
            for invoke in [worker.turn, worker._turn]:
                with pytest.raises(AdmissionDenied):
                    await invoke(payload)
            with pytest.raises(AdmissionDenied):
                await worker._ensure_composer_provider()
            assert contacts == []
    asyncio.run(check())


@pytest.mark.parametrize('stream', [False, True])
def test_dedicated_worker_http_rejects_before_starting_turn(app_modules, tmp_path, monkeypatch, stream):
    _, _, module = app_modules
    worker = module.CodexWorker(home_root=tmp_path / 'worker', api_key='',
        command=['synthetic-codex'], base_url='http://127.0.0.1:9', issue14_admission=policy())
    calls = []
    async def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError('Worker turn was invoked')
    monkeypatch.setattr(worker, 'turn', forbidden)
    monkeypatch.setattr(module, 'worker', worker)
    monkeypatch.setattr(module, '_require_worker_secret', lambda value: None)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app),
                base_url='http://fixture-worker') as session:
            response = await session.post('/internal/codex/turn',
                json={'user_id': str(uuid4()), 'text': 'synthetic'},
                headers={'accept': 'application/x-ndjson' if stream else 'application/json'})
        assert response.status_code == 403
        assert response.headers['x-error-code'] == 'ISSUE14_ADMISSION_DENIED'
        assert calls == []
    asyncio.run(check())


@pytest.mark.parametrize('foreign', [True, {}, {'live_ready': True}])
def test_opt_in_constructors_reject_forged_context(app_modules, tmp_path, foreign):
    agent, runtime, worker = app_modules
    for construct in [
        lambda: agent.CodexConnection(['synthetic'], tmp_path / 'a', issue14_admission=foreign),
        lambda: runtime.CodexRuntime(home_root=tmp_path / 'r', issue14_admission=foreign),
        lambda: worker.CodexWorker(home_root=tmp_path / 'w', api_key='', issue14_admission=foreign),
    ]:
        with pytest.raises(AdmissionDenied):
            construct()
    assert not (tmp_path / 'w').exists()


@pytest.mark.parametrize('admission_kind', ['missing', 'forged', 'valid', 'mismatched', 'closed'])
def test_new_launcher_denies_before_any_factory_or_judge_contact(admission_kind):
    from scripts.run_issue14_evaluation import run_evaluation
    admission = policy()
    run_id = admission.run_id
    if admission_kind == 'missing':
        admission = None
    elif admission_kind == 'forged':
        admission = {'live_ready': True}
    elif admission_kind == 'mismatched':
        run_id = str(uuid4())
    elif admission_kind == 'closed':
        admission.close()
    calls = []
    def forbidden():
        calls.append(True)
        raise AssertionError('Application/provider/judge factory was called')
    for role in ('collector', 'judge', 'photo'):
        with pytest.raises(AdmissionDenied):
            run_evaluation(admission=admission, run_id=run_id, source_revision=REVISION,
                role=role, runtime_factory=forbidden, worker_factory=forbidden,
                judge_factory=forbidden)
    assert calls == []


def test_launcher_cli_is_blocked_and_reads_no_environment(monkeypatch, capsys):
    from scripts.run_issue14_evaluation import main
    def forbidden(*args):
        raise AssertionError('Provider environment was read')
    monkeypatch.setattr(os, 'getenv', forbidden)
    assert main(['--run-id', str(uuid4()), '--source-revision', REVISION, '--role', 'judge']) == 3
    output = json.loads(capsys.readouterr().out)
    assert output['status'] == 'blocked'
    assert output['reason'] == 'provider_capability_unverified'
    assert output['live_ready'] is False


def test_normal_native_stdio_shape_is_unchanged(app_modules, tmp_path):
    from types import SimpleNamespace
    agent, _, _ = app_modules
    written = []
    async def drain():
        return None
    connection = agent.CodexConnection(['synthetic-codex'], tmp_path)
    connection.process = SimpleNamespace(stdin=SimpleNamespace(write=written.append, drain=drain))
    asyncio.run(connection.send({'method': 'initialized', 'params': {}}))
    assert written == [b'{"method": "initialized", "params": {}}\n']


def test_normal_runtime_worker_request_and_result_are_unchanged(app_modules, tmp_path):
    _, module, _ = app_modules
    requests = []
    async def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'thread_id': 'synthetic-thread', 'reply': 'fixture reply',
            'artifacts': []})
    async def check():
        runtime = module.CodexRuntime(home_root=tmp_path / 'normal', command=['synthetic'],
            worker_url='http://worker.synthetic.invalid', worker_secret='synthetic-secret',
            worker_transport=httpx.MockTransport(reply))
        result = await runtime._worker_turn(user_id=str(uuid4()), prior=None,
            memories=[], profile={}, place_journey={}, family_enabled=False,
            family_context={}, project_id=None, text='synthetic', language='en-AU')
        assert result['reply'] == 'fixture reply'
        assert len(requests) == 1
        body = json.loads(requests[0].content)
        assert body['text'] == 'synthetic'
        assert not any('issue14' in key or 'admission' in key for key in body)
        assert runtime.observed_worker_requests == 1
    asyncio.run(check())


def test_normal_worker_default_remains_callable(app_modules, tmp_path, monkeypatch):
    _, _, module = app_modules
    worker = module.CodexWorker(home_root=tmp_path / 'normal-worker', api_key='',
        command=['synthetic-codex'], base_url='http://127.0.0.1:9')
    calls = []
    async def fake_turn(payload, **kwargs):
        calls.append(payload.agent_role)
        return {'thread_id': 'synthetic-thread', 'reply': 'fixture reply'}
    monkeypatch.setattr(worker, '_turn', fake_turn)
    result = asyncio.run(worker.turn(module.WorkerTurnInput(user_id=uuid4(), text='synthetic')))
    assert result['reply'] == 'fixture reply'
    assert calls == ['collector']


def test_closed_and_tampered_owned_policy_remain_denied():
    admission = policy()
    original = admission.run_id
    object.__setattr__(admission, 'run_id', str(uuid4()))
    with pytest.raises(AdmissionDenied, match='admission_missing_or_foreign'):
        require_issue14_admission(admission, run_id=original,
            source_revision=REVISION, role='collector')
    closed = policy()
    closed.close()
    for _ in range(3):
        with pytest.raises(AdmissionDenied, match='admission_closed'):
            require_issue14_admission(closed, run_id=closed.run_id,
                source_revision=REVISION, role='collector')
