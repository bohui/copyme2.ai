"""Matched bilingual tool loops through real runtimes and disposable PostgreSQL."""
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from functools import partial
from hashlib import sha256
import json
import os
import shutil
import time
from uuid import uuid4

from dotenv import dotenv_values
from fastapi import FastAPI
import httpx
import psycopg
import pytest

from apps.api.conversation_reply_transport import aas_tool_relay, responses_tools, stream_document
from apps.api.lifetime_memory_publication import GovernedRequestBody
from controlled_skill_harness import empty_document
from memoir_postgres_workflow import PostgresRest, seed_fresh_canonical_project
from test_agent_commit_postgres import database as postgres_database
from test_background_profile_workflow import Broker
from test_conversation_reply import proposal
from test_mira_aas_trial import EFFORT, MODEL, aas_server, provider_fixture, run_turn, serve, wire_contract


pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_TEST_AAS_CORE') or not shutil.which('codex'),
    reason='A built advanced_aas core and native Codex CLI are required')

CASES = {
    'en-AU': dict(original='I kept a red kite in the attic.', query='kite', fact='red',
        follow_up='Could you look up what I told you about the kite?',
        resumed='I am back. Please check the earlier memory for the colour of the kite.',
        opening_ack='The kite in the attic stands out.', recall_ack='The kite you described was red.',
        question='Who used to fly it with you?'),
    'zh-CN': dict(original='我把一只红风筝放在阁楼里。', query='风筝', fact='红',
        follow_up='请帮我查一下之前说过的风筝。', resumed='我回来了。请查一下之前那只风筝是什么颜色。',
        opening_ack='您提到阁楼里放着一只风筝。', recall_ack='您说那只风筝是红色的。',
        question='以前谁和您一起放那只风筝？'),
}
SECRET = 'synthetic-worker-secret'


@pytest.fixture(scope='module')
def benchmark_database():
    yield from postgres_database.__wrapped__(publication_tcp=True, deadline=time.monotonic() + 720)


@pytest.fixture
def app_setup(benchmark_database, tmp_path, monkeypatch):
    from apps.api import agent_routes, codex_worker_service

    with psycopg.connect(benchmark_database.publication_dsn, connect_timeout=5) as connection:
        assert connection.execute('select 1').fetchone() == (1,)
    settings = {'MEMOIR_TWO_LANES': '1', 'MEMORY_SPARK_COLLECTOR_MODEL': MODEL,
        'MEMORY_SPARK_COLLECTOR_REASONING_EFFORT': EFFORT, 'MEMORY_SPARK_LLM_MODEL': MODEL,
        'MEMORY_SPARK_LLM_REASONING_EFFORT': EFFORT, 'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL': MODEL,
        'MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT': EFFORT, 'MEMORY_SPARK_DISABLE_PRIVDROP': '1',
        'MEMOIR_PUBLICATION_DATABASE_URL': benchmark_database.publication_dsn, 'MEMOIR_CODEX_HOME_BACKUPS': '0',
        'MEMORY_SPARK_CODEX_WORKER_SECRET': SECRET, 'MEMORY_SPARK_PARALLEL_POLICY_REVIEW': '0',
        'MEMORY_SPARK_LLM_API_KEY': 'synthetic-provider-key', 'MEMORY_SPARK_EARLY_POLICY_ACK': '0',
        'MEMORY_SPARK_HISTORICAL_NEWS': '0', 'MEMORY_SPARK_MEMOIR_RUN_SECONDS': '90',
        'MEMORY_SPARK_TASK_DB': str(tmp_path / 'tasks.sqlite')}
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('MEMOIR_MIRA_AAS_URL', raising=False)
    benchmark_database('update public.lifetime_two_lane_rollout set enabled=true,strategy_enabled=true,strategy_shadow=false;')
    app = FastAPI()
    app.include_router(agent_routes.router)
    app.mount('/worker', codex_worker_service.app)
    return app


def configure_api(monkeypatch, origin, gateway):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime

    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(worker_url=origin + '/worker',
        worker_secret=SECRET, base_url=gateway, model=MODEL, task_publisher_enabled=False))


def configure_worker(monkeypatch, home, gateway, *, aas=None, secret=None):
    from apps.api import codex_worker_service

    if aas:
        monkeypatch.setenv('MEMOIR_MIRA_AAS_URL', aas)
        monkeypatch.setenv('MEMOIR_MIRA_AAS_SECRET', secret)
    else:
        monkeypatch.delenv('MEMOIR_MIRA_AAS_URL', raising=False)
    worker = codex_worker_service.CodexWorker(home_root=home, model=MODEL,
        base_url=gateway, api_key='synthetic-provider-key', timeout=75)
    monkeypatch.setattr(codex_worker_service, 'worker', worker)


def fresh_project(database, monkeypatch):
    from apps.api import agent_routes

    owner, project = str(uuid4()), 'aas-benchmark-' + uuid4().hex
    database(f"insert into auth.users(id,is_anonymous) values('{owner}',false);")
    seed_fresh_canonical_project(database, owner, project)
    monkeypatch.setattr(agent_routes, 'authenticated_storage',
        lambda _: PostgresRest(database, owner).storage())
    return owner, project


def text_of(value):
    return value if isinstance(value, str) else ''.join(part.get('text', '') for part in value or [])


def returned_tool(body, call_id):
    for item in body['input']:
        if item.get('type') == 'function_call_output' and item.get('call_id') == call_id:
            return json.loads(text_of(item['output']))
    return None


def tool_call(call_id, name, arguments):
    return dict(type='function_call', id='fc_' + call_id, call_id=call_id, name=name,
        arguments=json.dumps(arguments, ensure_ascii=False), status='completed')


def reply_for(case, *, recalled=False):
    return dict(proposal(), acknowledgement=case['recall_ack' if recalled else 'opening_ack'], question=case['question'])


def wire_signature(body, *, fixture_source=None):
    contract = wire_contract(body)
    assert contract['model'] == MODEL and contract['effort'] == EFFORT
    assert body['text']['format']['strict'] is True
    schema = contract['schema']
    signature = dict(model=MODEL, effort=EFFORT, prompt_sha256=sha256(contract['prompt'].encode()).hexdigest(),
        schema_sha256=sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest())
    if fixture_source and 'CurrentSourceRef' in schema.get('$defs', {}):
        normalized = deepcopy(schema)
        for reference in ('EvidenceRef', 'CurrentSourceRef'):
            source_ids = normalized['$defs'][reference]['properties']['source_id']
            assert source_ids['enum'] == [fixture_source]
            source_ids['enum'] = ['fixture-source']
        continuity_source = normalized['$defs']['_ContinuityUpdate']['properties']['source_id']
        assert continuity_source['const'] == fixture_source
        continuity_source['const'] = 'fixture-source'
        signature['scoped_wire_schema_sha256'] = signature['schema_sha256']
        signature['schema_sha256'] = sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    return signature


def complete_turn(client, database, owner, project, language, text, *, require_question=True):
    payload = dict(project_id=project, language=language, text=text, client_turn_id=str(uuid4()))
    saved, timing = run_turn(client, payload, require_question=require_question)
    replay = client.post('/v1/agent/turn', json=payload).json()
    assert replay['cached'] and replay['reply'] == saved['reply']
    thread = database(f"select thread_id from public.user_lifetime_conversation where user_id='{owner}';").stdout.strip()
    return saved, timing, thread


def test_disconnected_recall_drops_callback():
    secret, calls = uuid4().hex, []
    tool = dict(name='memoir_read_context', description='Read authorized earlier testimony.', inputSchema={'type':'object'})
    body = dict(model=MODEL, stream=True, store=False, tool_choice='auto', tools=responses_tools([tool]),
        input=[dict(role='developer', content=[dict(type='input_text', text='Return JSON.')]),
               dict(role='user', content='Recall the kite.')],
        text={'format': dict(type='json_schema', name='recall', strict=True, schema={'type':'object'})})
    headers = {'Authorization': 'Bearer ' + secret}
    with (provider_fixture(calls, [1], script=lambda _: tool_call('recall', tool['name'], {})) as gateway,
          aas_server(os.environ['MEMOIR_TEST_AAS_CORE'], gateway, secret) as aas,
          httpx.Client(timeout=5, trust_env=False) as client):
        with client.stream('POST', aas + '/responses', json=body, headers=headers) as response:
            response.raise_for_status()
            callback = json.loads(next(response.iter_lines()).removeprefix('data: '))
            assert callback['type'] == 'memoir.tool_call'
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = client.post(aas + '/tool-results', headers=headers, json={'id': callback['id'], 'result': None})
            if result.status_code == 404:
                break
            assert result.status_code == 400
            time.sleep(0.05)
        assert result.status_code == 404 and len(calls) == 1


def test_bilingual_follow_up_and_resumed_recall(benchmark_database, app_setup, tmp_path, monkeypatch):
    database = benchmark_database
    state, calls, samples, permitted = {}, [], [], [0]
    live_env = os.getenv('MEMOIR_TEST_MIRA_AAS_RECALL_LIVE_ENV')
    live_key = dotenv_values(live_env).get('MEMORY_SPARK_LLM_API_KEY') if live_env else None
    assert not live_env or live_key, 'Live recall benchmark requires the existing gateway key'
    live_contracts, forwarded = {}, []

    def admit_live(body):
        scenario = state['language'], state['phase']
        slot = (*scenario, state['arm'])
        if state['phase'] == 'opening' or slot in forwarded or len(forwarded) >= 8:
            return False
        signature = wire_signature(body)
        if live_contracts.setdefault(scenario, signature) != signature:
            return False
        forwarded.append(slot)
        print('MIRA_AAS_LIVE_SEND', json.dumps(slot))
        return True

    def script(body):
        case = state['case']
        phase = state['phase']
        current = case['original' if phase == 'opening' else phase]
        assert any(item.get('role') == 'user' and text_of(item.get('content')) == current for item in body['input'])
        if phase == 'opening':
            return reply_for(case)
        for previous in ('original', 'follow_up') if phase == 'resumed' else ('original',):
            assert any(item.get('role') == 'user' and text_of(item.get('content')) == case[previous]
                for item in body['input'])
        call_id = 'recall_' + phase
        result = returned_tool(body, call_id)
        if result is None:
            return tool_call(call_id, 'memoir_read_context',
                dict(collection='sources', after=None, query=case['query'], event_id=None))
        evidence = json.dumps(result, ensure_ascii=False)
        assert case['original'] in evidence and state['source_id'] in evidence
        assert all(foreign not in evidence for foreign in state['foreign_sources'])
        return None if live_key else reply_for(case, recalled=True)

    core = os.environ['MEMOIR_TEST_AAS_CORE']
    with (provider_fixture(calls, permitted, live_key=live_key, script=script, admit_live=admit_live) as gateway,
          serve(app_setup) as origin):
        configure_api(monkeypatch, origin, gateway)
        with httpx.Client(base_url=origin, timeout=90, trust_env=False) as client:
            earlier_owners = []
            for language, case in CASES.items():
                arms = ('codex', 'advanced_aas') if language == 'en-AU' else ('advanced_aas', 'codex')
                for arm in arms:
                    owner, project = fresh_project(database, monkeypatch)
                    home = tmp_path / owner
                    state.update(case=case, language=language, arm=arm, foreign_sources=tuple(earlier_owners))
                    native_thread = None
                    with ExitStack() as stack:
                        for phase in ('opening', 'follow_up', 'resumed'):
                            if phase in {'opening', 'resumed'}:
                                stack.close()
                                secret = uuid4().hex
                                aas = stack.enter_context(aas_server(core, gateway, secret)) if arm == 'advanced_aas' else None
                                configure_worker(monkeypatch, home, gateway, aas=aas, secret=secret)
                            state['phase'] = phase
                            before = len(calls)
                            count = 1 if phase == 'opening' else 2
                            permitted[0] = before + count
                            text = case['original' if phase == 'opening' else phase]
                            saved, timing, thread = complete_turn(client, database, owner, project, language, text,
                                require_question=not live_key or phase == 'opening')
                            assert len(calls) == before + count
                            assert thread.startswith('reply-') == (arm == 'advanced_aas')
                            if phase == 'opening':
                                native_thread = thread
                                source_id = database(f"select id from public.user_narrator_source where user_id='{owner}';").stdout.strip()
                                state['source_id'] = source_id
                                earlier_owners.append(source_id)
                            else:
                                assert case['fact'] in saved['reply'].lower()
                                assert returned_tool(calls[-1], 'recall_' + phase) is not None
                                if arm == 'codex':
                                    assert thread == native_thread, 'Codex did not resume its committed thread'
                                samples.append(dict(language=language, phase=phase, arm=arm, requests=count,
                                    **timing, wire=[wire_signature(call) for call in calls[before:]]))
                                if live_key:
                                    print('MIRA_AAS_LIVE_SAMPLE', json.dumps(samples[-1]))

    for language in CASES:
        for phase in ('follow_up', 'resumed'):
            pair = [sample for sample in samples if sample['language'] == language and sample['phase'] == phase]
            assert len(pair) == 2 and pair[0]['wire'] == pair[1]['wire']
    assert not live_key or len(forwarded) == 8
    print('MIRA_AAS_RECALL', json.dumps(dict(mode='live_final_after_recall' if live_key else 'controlled_provider',
        live_requests=len(forwarded), samples_ms=samples)))


class AdmittedBody(GovernedRequestBody):
    def __init__(self, content, admission):
        self.content, self.admission, self._iterator = content, admission, None

    async def _chunks(self):
        async with self.admission():
            yield self.content


class AtlasBenchmarkConnection:
    """Only the harness changes. The activity, skill callbacks and commits stay real."""
    def __init__(self, _command, _home, *, aas, secret, timeout, request_admission, tool_handler, **options):
        assert 'issue14_admission' not in options
        self.aas, self.secret, self.timeout = aas, secret, timeout
        self.guarded_body = partial(AdmittedBody, admission=request_admission)
        self.tool_handler = tool_handler
        self.thread = 'atlas-benchmark-' + uuid4().hex

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def request(self, method, params):
        assert method == 'thread/start'
        self.params = params
        return {'thread': {'id': self.thread}}

    async def turn(self, thread_id, text, *, output_schema, effort, responsesapi_client_metadata):
        assert thread_id == self.thread
        body = dict(model=self.params['model'], stream=True, store=False, tool_choice='auto',
            tools=responses_tools(self.params['dynamicTools']), parallel_tool_calls=False,
            reasoning={'effort': effort}, metadata=responsesapi_client_metadata,
            input=[dict(role='developer', content=[dict(type='input_text', text=self.params['baseInstructions'])]),
                   dict(role='user', content=text)],
            text={'format': dict(type='json_schema', name='atlas', strict=True, schema=output_schema)})
        encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
        reply, _ = await stream_document(request=self.guarded_body(encoded), content_length=len(encoded),
            base_url=self.aas, api_key=self.secret, timeout=self.timeout,
            on_tool=aas_tool_relay(self.aas, self.secret, self.tool_handler, self.guarded_body))
        return reply


def test_atlas_matched_activity(benchmark_database, app_setup, tmp_path, monkeypatch):
    from apps.api import codex_worker_service
    from apps.api.memory_event_worker import MemoryEventWorker
    from apps.api.memoir_background_agent import run_background_agent
    from apps.api.private_draft_broker import PrivateDraftBroker

    database = benchmark_database
    state, calls, samples, permitted = {}, [], [], [0]
    skill = 'memoir-author-timeline'

    def script(body):
        if state['phase'] == 'opening':
            return reply_for(state['case'])
        if isinstance(body['input'], str):
            return empty_document(body)
        if returned_tool(body, 'read_skill') is None:
            return tool_call('read_skill', 'memoir_read_skill', {'skill': skill})
        assert returned_tool(body, 'read_skill')['skill'] == skill
        result = returned_tool(body, 'process_source')
        if result is None:
            return tool_call('process_source', 'memoir_process_source', {'skills': [skill]})
        assert result['status'] in {'saved', 'finished'}
        return {'status': 'finished'}

    secret = uuid4().hex
    with (provider_fixture(calls, permitted, script=script) as gateway,
          aas_server(os.environ['MEMOIR_TEST_AAS_CORE'], gateway, secret) as aas, serve(app_setup) as origin):
        configure_api(monkeypatch, origin, gateway)
        broker = Broker(database)
        activity = MemoryEventWorker(broker, worker_url=origin + '/worker', worker_secret=SECRET)
        with httpx.Client(base_url=origin, timeout=90, trust_env=False) as client:
            for language, case in CASES.items():
                arms = ('codex', 'advanced_aas') if language == 'en-AU' else ('advanced_aas', 'codex')
                for arm in arms:
                    owner, project = fresh_project(database, monkeypatch)
                    configure_worker(monkeypatch, tmp_path / owner, gateway)
                    state.update(case=case, phase='opening')
                    permitted[0] = len(calls) + 1
                    complete_turn(client, database, owner, project, language, case['original'])
                    receipts = database(f"select id from public.user_private_draft_outbox where user_id='{owner}' and not delivered;").stdout.splitlines()

                    async def schedule():
                        for receipt in receipts:
                            page = await broker.rpc('private_draft_event_page', p_event_id=receipt)
                            checkpoint = await asyncio.to_thread(PrivateDraftBroker.reconcile, page)
                            assert checkpoint['retrieval_complete']
                            await broker.rpc('queue_memoir_receipt', p_receipt_id=receipt, p_cadence=5)
                        await broker.rpc('pending_memoir_background_agents')

                    asyncio.run(schedule())
                    run_id = database(f"select id from public.user_memoir_background_agent where user_id='{owner}';").stdout.strip()
                    assert run_id

                    async def execute(worker, payload, *, connection_factory):
                        if arm == 'advanced_aas':
                            connection_factory = partial(AtlasBenchmarkConnection, aas=aas, secret=secret)
                        return await run_background_agent(worker, payload, connection_factory=connection_factory)

                    monkeypatch.setattr(codex_worker_service, 'run_background_agent', execute)
                    state['phase'] = 'atlas'
                    before = len(calls)
                    permitted[0] = before + 6
                    started = time.perf_counter()
                    result = asyncio.run(activity.execute_background_agent(run_id))
                    elapsed = round((time.perf_counter() - started) * 1000, 1)
                    assert result['status'] == 'finished' and result['pending'] is False
                    assert database(f"select processing_status from public.user_narrator_source where user_id='{owner}';").stdout.strip() == 'succeeded'
                    assert database(f"select token is null from public.user_memoir_background_agent where id='{run_id}';").stdout.strip() == 't'
                    source_id = database(f"select id from public.user_narrator_source where user_id='{owner}';").stdout.strip()
                    requests = calls[before:]
                    assert sum(isinstance(call['input'], list) for call in requests) == 3
                    assert any(isinstance(call['input'], str) for call in requests)
                    samples.append(dict(language=language, arm=arm, durable_finish=elapsed,
                        requests=len(requests), wire=[wire_signature(call, fixture_source=source_id) for call in requests]))

    for language in CASES:
        pair = [sample for sample in samples if sample['language'] == language]
        assert len(pair) == 2
        comparable = [[{key: value for key, value in signature.items() if key != 'scoped_wire_schema_sha256'}
            for signature in sample['wire']] for sample in pair]
        assert comparable[0] == comparable[1]
    print('ATLAS_AAS_BENCHMARK', json.dumps(dict(mode='controlled_provider', samples_ms=samples)))
