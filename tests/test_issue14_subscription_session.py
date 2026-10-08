"""Owned-loopback session binding tests; all provider traffic is synthetic."""
import asyncio
import hashlib
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx
import pytest

from scripts.issue14_subscription_session import (
    OwnedSubscriptionSession, assert_owned_subscription_session, case_plans_for_run,
)

REVISION = '9895006f0aaec8425abb21a99f88e39a3a982c2f'


@pytest.fixture(autouse=True)
def controlled_temporal_startup(monkeypatch):
    async def start(self):
        # Binding/socket tests only. No native Temporal activity is claimed.
        self._workflow_ready = True
    monkeypatch.setattr(OwnedSubscriptionSession, '_start_workflows', start)


@pytest.mark.parametrize('value', [None, object(), {}, object.__new__(OwnedSubscriptionSession)])
def test_forged_session_is_denied(value):
    with pytest.raises(ValueError, match='owned subscription session'):
        assert_owned_subscription_session(value)


def test_case_plan_is_exact_deterministic_and_synthetic():
    run = str(uuid4())
    plans = case_plans_for_run(run)
    assert plans == case_plans_for_run(run)
    assert list(plans) == ['chapters.transitions.en-AU', 'chapters.transitions.zh-CN']
    assert len({v['owner_id'] for v in plans.values()}) == 2
    assert len({v['project_id'] for v in plans.values()}) == 2


@pytest.fixture
def gateway():
    contacts = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            contacts.append(json.loads(self.rfile.read(int(self.headers['content-length']))))
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1/responses', contacts
    server.shutdown(); server.server_close(); thread.join()


async def session(tmp_path, endpoint):
    from apps.api.agent_storage import UserStorage
    from apps.api.memory_event_worker import MemoirLaneBroker
    from scripts.issue14_subscription_transport import SubscriptionLimits, SubscriptionRun, SubscriptionTransport
    (tmp_path / 'journal').mkdir()
    run = SubscriptionRun.create(reservation_root=tmp_path / 'journal', run_id=str(uuid4()),
        source_revision=REVISION, limits=SubscriptionLimits(max_requests=10, max_elapsed_seconds=30))
    transport = SubscriptionTransport.controlled(run=run, endpoint=endpoint)
    storages = {}
    for case_id, plan in case_plans_for_run(run.run_id).items():
        client = httpx.Client(transport=httpx.MockTransport(lambda request, owner=plan['owner_id']:
            httpx.Response(200, json={'id': owner, 'is_anonymous': False})))
        storages[case_id] = UserStorage('http://synthetic.invalid', 'synthetic-public', 'synthetic-user-token', client=client)
    binary = Path('/bin/true').resolve()
    broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service',
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))))
    return await OwnedSubscriptionSession.create(run=run, provider_transport=transport,
        storages=storages, broker=broker, temporal_client=object(), home_root=tmp_path / 'home',
        codex_binary=binary, codex_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        api_key='synthetic-token')


@pytest.mark.parametrize('role', ['collector', 'workspace', 'memory_context', 'author_timeline', 'composer'])
def test_every_role_gets_owned_scope_and_one_shared_client_seam(tmp_path, gateway, monkeypatch, role):
    from apps.api.codex_worker_service import CodexWorker
    endpoint, contacts = gateway
    async def controlled_turn(self, payload, **kwargs):
        assert payload.evaluation['round_id'] == ('5' if role == 'composer' else '1')
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.post(self.base_url + '/responses',
                headers={'Authorization': 'Bearer synthetic-token'}, json={'stream': True,
                    'model': self.model, 'reasoning': {'effort': self.reasoning_effort},
                    'input': 'synthetic', 'client_metadata': payload.evaluation})
            response.raise_for_status()
        return {'reply': 'Controlled', 'trajectory': {'correlation': payload.evaluation}}
    monkeypatch.setattr(CodexWorker, 'turn', controlled_turn)
    async def scenario():
        owned = await session(tmp_path, endpoint)
        try:
            assert_owned_subscription_session(owned)
            case_id = owned.case_ids[0]
            plan = owned.case_plans[case_id]
            if role == 'composer':
                for ordinal in range(1, 5):
                    owned.activate_round(case_id, ordinal)
                    owned.finish_round()
            owned.activate_round(case_id, 5 if role == 'composer' else 1)
            if role in {'author_timeline', 'composer'}:
                owned._job_context.set({'job_id': 'synthetic-workflow:activity'})
            async with httpx.AsyncClient(transport=owned.worker_transport, base_url=owned.worker_url) as client:
                response = await client.post('/internal/codex/turn', json={
                    'user_id': plan['owner_id'], 'project_id': plan['project_id'],
                    'language': plan['language'], 'agent_role': role, 'text': 'synthetic'})
                assert response.status_code == 200
            owned.finish_round()
            assert len(contacts) == 1
            assert contacts[0]['client_metadata']['run_id'] == owned.run.run_id
        finally:
            await owned.close()
        with pytest.raises(ValueError):
            assert_owned_subscription_session(owned)
    asyncio.run(scenario())


@pytest.mark.parametrize('mutation', ['foreign_project', 'foreign_owner', 'judge', 'forged_correlation', 'wrong_url'])
def test_invalid_worker_scope_never_calls_worker_or_gateway(tmp_path, gateway, monkeypatch, mutation):
    from apps.api.codex_worker_service import CodexWorker
    endpoint, contacts = gateway
    async def forbidden(*args, **kwargs):
        pytest.fail('Invalid worker scope dispatched')
    monkeypatch.setattr(CodexWorker, 'turn', forbidden)
    async def scenario():
        owned = await session(tmp_path, endpoint)
        try:
            case_id = owned.case_ids[0]
            plan = owned.case_plans[case_id]
            owned.activate_round(case_id, 1)
            payload = {'user_id': plan['owner_id'], 'project_id': plan['project_id'],
                       'language': plan['language'], 'agent_role': 'collector', 'text': 'synthetic'}
            if mutation == 'foreign_project': payload['project_id'] = str(uuid4())
            if mutation == 'foreign_owner': payload['user_id'] = str(uuid4())
            if mutation == 'judge': payload['agent_role'] = 'judge'
            if mutation == 'forged_correlation': payload['evaluation'] = {'run_id': 'other'}
            async with httpx.AsyncClient(transport=owned.worker_transport, base_url=owned.worker_url) as client:
                with pytest.raises((ValueError, httpx.RequestError)):
                    await client.post('/wrong' if mutation == 'wrong_url' else '/internal/codex/turn', json=payload)
            assert contacts == []
        finally:
            await owned.close()
    asyncio.run(scenario())


def test_runtime_binding_mutation_is_denied_before_worker(tmp_path, gateway):
    async def scenario():
        owned = await session(tmp_path, gateway[0])
        try:
            owned.runtime.worker_url = 'http://unowned.invalid'
            with pytest.raises(ValueError):
                assert_owned_subscription_session(owned)
            assert gateway[1] == []
        finally:
            await owned.close()
    asyncio.run(scenario())


def test_actual_runtime_streaming_abi_uses_ndjson_terminal(tmp_path,gateway,monkeypatch):
    from apps.api.codex_worker_service import CodexWorker
    async def reply(self,payload,**kwargs):
        return {'thread_id':'synthetic-thread','reply':'Controlled reply','artifacts':[],
            'trajectory':{'correlation':payload.evaluation,'final':{'status':'completed'}}}
    monkeypatch.setattr(CodexWorker,'turn',reply)
    async def scenario():
        owned=await session(tmp_path,gateway[0]);case=owned.case_ids[0];plan=owned.case_plans[case]
        correlation=owned.activate_round(case,1)
        async def delta(text):pass
        try:
            result=await owned.runtime._worker_turn(user_id=plan['owner_id'],prior=None,memories=[],
                profile={},place_journey={},family_enabled=False,family_context={},
                project_id=plan['project_id'],text='synthetic',language=plan['language'],
                evaluation=correlation,on_delta=delta)
            assert result['reply']=='Controlled reply'
            await result['_artifact_task']
            owned.finish_round()
        finally:await owned.close()
    asyncio.run(scenario())


def test_workflow_cleanup_failure_does_not_strand_listener_or_http_clients(tmp_path,gateway):
    async def scenario():
        owned=await session(tmp_path,gateway[0])
        class Failure:
            async def __aexit__(self,*args):raise RuntimeError('synthetic cleanup failure')
        owned._workflow=Failure()
        with pytest.raises(RuntimeError,match='cleanup incomplete'):
            await owned.close()
        assert owned._server_task.done()
        assert owned._socket.fileno()==-1
        assert owned._http.is_closed
        assert owned.broker.client.is_closed
        assert owned.run.snapshot()['closed'] is True
    asyncio.run(scenario())


@pytest.mark.parametrize('foreign',[False,True])
def test_real_broker_dispatch_orders_extraction_first_and_rejects_foreign_receipts(foreign):
    from types import SimpleNamespace
    from apps.api.memory_event_worker import MemoirLaneBroker
    from scripts.task_runtime import dispatch_memoir_lanes_once
    from scripts.issue14_subscription_session import _ScopedSubscriptionBroker
    async def scenario():
        owner_id,project_id=str(uuid4()),str(uuid4())
        replies={'pending_memoir_receipts':['receipt'],
            'read_memoir_receipt_scope':{'change_kind':'accepted','user_id':str(uuid4()) if foreign else owner_id,'project_id':project_id},
            'queue_memoir_receipt':{'composer_lane_id':'composer','timeline_lane_id':'timeline'},
            'pending_memoir_lanes':['timeline','composer']}
        def respond(request):return httpx.Response(200,json=replies[request.url.path.rsplit('/',1)[-1]])
        raw=MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic',
            client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        owner=SimpleNamespace(_active=('case',5),_plans={'case':{'owner_id':owner_id,'project_id':project_id}})
        broker=_ScopedSubscriptionBroker(raw,owner);started=[];extracted=False
        class Handle:
            def __init__(self,lane):self.id=lane
            async def result(self):
                nonlocal extracted
                if self.id=='timeline':extracted=True
                return {'status':'finished' if extracted else 'retry_required'}
        class Client:
            async def start_workflow(self,fn,*,args,**kwargs):started.append(args[0]);return Handle(args[0])
        try:
            if foreign:
                with pytest.raises(ValueError):
                    await dispatch_memoir_lanes_once(Client(),broker,'canary-subscription-synthetic',single_attempt=True)
                assert started==[]
            else:
                await dispatch_memoir_lanes_once(Client(),broker,'canary-subscription-synthetic',single_attempt=True)
                assert started==['timeline','composer']
        finally:await raw.client.aclose()
    asyncio.run(scenario())
