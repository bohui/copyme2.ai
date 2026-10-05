import asyncio
import json
import sys

import pytest
import httpx
from fastapi import FastAPI
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from test_shared_memory_events_postgres import (
    database, attachment_database, private_database, event_database, sql, OWNER, ROOT,
)
from memoir_postgres_workflow import PostgresRest


@pytest.mark.parametrize('timeout', [None, True, 0, -1, float('nan'), float('inf')])
def test_unbounded_or_invalid_settle_timeout_fails_before_dispatch(timeout):
    from apps.api.agent_storage import UserStorage
    from scripts.canonical_evaluation import CanonicalEvaluationDriver

    def authentication_only(request):
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': OWNER, 'is_anonymous': False})
        pytest.fail('Invalid timeout must fail before storage/provider dispatch')
    with httpx.Client(transport=httpx.MockTransport(authentication_only)) as client:
        storage = UserStorage('http://synthetic.invalid', 'synthetic-public', OWNER, client=client)
        driver = CanonicalEvaluationDriver(storage=storage, runtime=None, broker=None,
            temporal_client=None, task_queue='synthetic')
        with pytest.raises(ValueError, match='finite positive settle timeout'):
            asyncio.run(driver.run_case(case_id='invalid-timeout', project_id='invalid-timeout',
                rounds=['Synthetic input'], language='en-AU', evidence_mode='mock_only', settle_timeout=timeout))


@pytest.mark.parametrize('rounds', [[], [''], ['  '], ['good', None], ['good'] * 51])
def test_invalid_case_inputs_fail_before_storage_or_provider_dispatch(rounds):
    from apps.api.agent_storage import UserStorage
    from scripts.canonical_evaluation import CanonicalEvaluationDriver

    def authentication_only(request):
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': OWNER, 'is_anonymous': False})
        pytest.fail('Invalid case must fail before storage/provider dispatch')
    with httpx.Client(transport=httpx.MockTransport(authentication_only)) as client:
        storage = UserStorage('http://synthetic.invalid', 'synthetic-public', OWNER, client=client)
        driver = CanonicalEvaluationDriver(storage=storage, runtime=None, broker=None,
            temporal_client=None, task_queue='synthetic')
        with pytest.raises(ValueError, match='1 to 50 nonempty original inputs'):
            asyncio.run(driver.run_case(case_id='invalid-case', project_id='invalid-case',
                rounds=rounds, language='en-AU', evidence_mode='mock_only'))


@pytest.mark.parametrize('mode', ['live', 'fixture_live', 'passed'])
def test_unverified_live_provider_cannot_be_dispatched_or_labeled_as_acceptance(mode):
    from apps.api.agent_storage import UserStorage
    from scripts.canonical_evaluation import CanonicalEvaluationDriver

    def no_network(request):
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': OWNER, 'is_anonymous': False})
        pytest.fail('Unverified live mode must fail before any storage/provider contact')
    with httpx.Client(transport=httpx.MockTransport(no_network)) as client:
        storage = UserStorage('http://synthetic.invalid', 'synthetic-public', OWNER, client=client)
        driver = CanonicalEvaluationDriver(storage=storage, runtime=None, broker=None,
            temporal_client=None, task_queue='synthetic')
        with pytest.raises(ValueError, match='verified provider'):
            asyncio.run(driver.run_case(case_id='blocked-live', project_id='blocked-live',
                rounds=['Synthetic input'], language='en-AU', evidence_mode=mode))


def test_canonical_driver_refuses_legacy_storage_before_dispatch():
    from scripts.canonical_evaluation import CanonicalEvaluationDriver

    with pytest.raises(TypeError, match='UserStorage'):
        CanonicalEvaluationDriver(storage=object(), runtime=None, broker=None,
            temporal_client=None, task_queue='synthetic')


@pytest.mark.parametrize('cadence', [3, 5])
def test_authenticated_rounds_extract_original_evidence_and_save_checkpoint_via_temporal(sql, tmp_path, monkeypatch, cadence):
    from scripts.canonical_evaluation import CanonicalEvaluationDriver
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.memory_event_worker import MemoirLaneBroker, MemoryEventWorker
    from apps.api.temporal_workflows import MemoirSkillLane
    from scripts.evaluation_budget import RequestLimitedTransport

    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    monkeypatch.setenv('STRIPE_PRICE_FAMILY', 'synthetic-price')
    monkeypatch.setenv('MEMORY_SPARK_PRIVATE_DRAFT_CADENCE', str(cadence))
    entitlement = {'status': 'paid', 'plan_key': 'family_memoir_v1', 'family_tree': True,
                   'timeline': True, 'stripe_price_id': 'synthetic-price'}
    storage = PostgresRest(sql, OWNER, entitlement=entitlement).storage()
    storage.save_profile({'preferred_language': 'en-AU', 'conversation_language':
        {'locale': 'en-AU', 'source': 'explicit', 'revision': 1}})
    rounds = ['I started school around 1964.', 'Thanks.', 'Tell me more.', 'Yes.', 'Thank you.'][:cadence]
    project = 'synthetic-canonical-case'
    app = FastAPI()
    worker_roles = []

    async def scenario():
        async def ready(reader, writer):
            writer.close()
            await writer.wait_closed()
        readiness = await asyncio.start_server(ready, '127.0.0.1', 0)
        base_url = f'http://127.0.0.1:{readiness.sockets[0].getsockname()[1]}/v1'
        try:
            @app.post('/internal/codex/turn')
            async def turn(payload: WorkerTurnInput):
                # Only the external provider protocol is controlled. Every
                # application worker/runtime/storage/workflow executes normally.
                worker_roles.append(payload.agent_role)
                control = tmp_path / f'provider-{len(worker_roles)}.json'
                if payload.agent_role == 'author_timeline':
                    packet = json.loads(payload.text)
                    sources = [s for s in packet['sources'] if s['text'] == rounds[0]]
                    events = [{'kind': 'event', 'title': 'Started school', 'source_refs':
                        [{'source_id': s['id'], 'version': s['version'], 'quote': s['text']}]} for s in sources]
                    options = {'reply': {'events': events}}
                elif payload.agent_role == 'composer':
                    options = {'mode': 'composer', 'calls': str(tmp_path / 'composer.jsonl')}
                else:
                    options = {'reply': 'Tell me more.'}
                control.write_text(json.dumps(options))
                provider = CodexWorker(home_root=tmp_path / 'worker-homes', base_url=base_url,
                    command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
                return await provider.turn(payload)

            transport = RequestLimitedTransport(httpx.ASGITransport(app=app), max_requests=40)
            runtime = CodexRuntime(home_root=tmp_path / 'api-homes', base_url=base_url,
                worker_url='http://controlled.invalid', worker_secret='synthetic',
                worker_transport=transport, task_publisher_enabled=False)
            options = {'download_dest_dir': '/tmp/memoir-issue6-temporal',
                'dev_server_database_filename': str(tmp_path / 'temporal.sqlite'), 'ip': '127.0.0.1', 'ui': False}
            async with await WorkflowEnvironment.start_local(**options) as env:
                async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)) as db:
                    broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=db)
                    worker = MemoryEventWorker(broker, worker_url='http://controlled.invalid',
                        worker_secret='synthetic', worker_transport=transport)
                    @activity.defn(name='memoir.execute_lane')
                    async def execute(lane_id: str):
                        result = await worker.execute_lane(lane_id)
                        state = await broker.rpc('read_memoir_lane_state', p_lane_id=lane_id)
                        return {'status': result['status'], 'pending': state['pending']}
                    async with Worker(env.client, task_queue='canonical-evaluation-synthetic',
                                      workflows=[MemoirSkillLane], activities=[execute]):
                        driver = CanonicalEvaluationDriver(storage=storage, runtime=runtime, broker=broker,
                            temporal_client=env.client, task_queue='canonical-evaluation-synthetic')
                        result = await driver.run_case(case_id='school-fixture', project_id=project,
                            rounds=rounds, language='en-AU', evidence_mode='mock_only', settle_timeout=30)
                        assert result['status'] == 'completed'
                        assert result['evidence_mode'] == 'mock_only'
                        assert [r['round'] for r in result['rounds']] == list(range(1, cadence + 1))
                        assert all(r['trajectory']['final']['status'] == 'completed' for r in result['rounds'])
                        assert result['checkpoints'][0]['milestone'] == cadence
                        assert result['checkpoints'][0]['draft']['revision'] == 1
                        view = storage.memory_events(project)
                        assert view['completed_rounds'] == view['processing']['extracted_through'] == cadence
                        assert [s['text'] for s in view['sources']] == rounds
                        assert len(view['events']) == 1
                        assert view['events'][0]['title'] == 'Started school'
                        assert view['events'][0]['source_refs'][0]['quote'] == rounds[0]
                        draft = storage.saved_memoir_draft(project)
                        assert draft['milestone'] == draft['covered_round'] == cadence
                        assert rounds[0] in json.dumps(draft)
                        assert 'author_timeline' in worker_roles and 'composer' in worker_roles
                        assert transport.requests_started == len(worker_roles)
                        for workflow_id in result['workflow_ids']:
                            history = await env.client.get_workflow_handle(workflow_id).fetch_history()
                            assert rounds[0].encode() not in b''.join(e.SerializeToString() for e in history.events)
                        contacted = len(worker_roles)
                        with pytest.raises(ValueError, match='fresh synthetic project'):
                            await driver.run_case(case_id='must-not-reuse', project_id=project,
                                rounds=['Do not send this.'], language='en-AU', evidence_mode='mock_only')
                        assert len(worker_roles) == contacted
                        assert storage.memory_events(project)['completed_rounds'] == cadence
        finally:
            readiness.close()
            await readiness.wait_closed()
    asyncio.run(scenario())
