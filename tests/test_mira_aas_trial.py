"""One matched Mira turn through the real HTTP endpoints and disposable SQL."""
from contextlib import contextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import threading
import time
from uuid import uuid4

from dotenv import dotenv_values
from fastapi import FastAPI
import httpx
import psycopg
import pytest
import uvicorn

from memoir_postgres_workflow import PostgresRest, seed_fresh_canonical_project
from test_conversation_reply import proposal
from test_two_lane_memory import database


TEXT = 'My brother Ming moved to Perth.'
MODEL = 'gpt-6.1-sol'
EFFORT = 'low'
ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def provider_fixture(calls, permitted, live_key=None, disconnected=None, script=None, admit_live=None):
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            assert self.path == '/v1/responses'
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body)
            if len(calls) > permitted[0]:
                self.send_error(409)
                return
            output = script(body) if script else None
            if live_key and output is None:
                self.relay(body)
                return
            if isinstance(output, dict) and output.get('type') == 'function_call':
                self.write_output(body, output)
                return
            answer = json.dumps(output if output is not None else
                dict(proposal(), acknowledgement='Ming’s move to Perth stands out.'))
            item = dict(type='message', id='message-1', role='assistant', status='completed',
                phase='final_answer', content=[dict(type='output_text', text=answer, annotations=[])])
            self.write_output(body, item, answer=answer)

        def write_output(self, body, item, *, answer=None):
            response = dict(id='response-1', object='response', status='completed', model=body['model'],
                output=[item], usage=dict(input_tokens=100, output_tokens=20, total_tokens=120))
            created = dict(type='response.created', response={**response, 'status': 'in_progress', 'output': []})
            if answer is None:
                started = dict(type='response.output_item.added', output_index=0, item=item)
                output_events, deltas = [], []
            else:
                started = dict(type='response.output_item.added', output_index=0,
                    item={**item, 'status': 'in_progress', 'content': []})
                content = dict(type='response.content_part.added', item_id=item['id'], output_index=0,
                    content_index=0, part=dict(type='output_text', text='', annotations=[]))
                split = answer.find(',')
                parts = (answer[:split], answer[split:]) if split >= 0 else (answer,)
                deltas = [dict(type='response.output_text.delta', item_id=item['id'], output_index=0,
                    content_index=0, delta=part) for part in parts]
                output_events = [content, *deltas]
            done = dict(type='response.output_item.done', output_index=0, item=item)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for event in (created, started, *output_events, done, dict(type='response.completed', response=response)):
                if event in deltas or (answer is None and event is done):
                    time.sleep(0.04)
                self.wfile.write(f'data: {json.dumps(event)}\n\n'.encode())
                self.wfile.flush()
                if disconnected is not None and event is deltas[0]:
                    self.connection.settimeout(5)
                    try:
                        if self.connection.recv(1) == b'':
                            disconnected.set()
                    except ConnectionResetError:
                        disconnected.set()
                    return

        def relay(self, body):
            from apps.api.conversation_reply import reply_instructions

            contract = wire_contract(body)
            if (body.get('store') is not False or contract['model'] != MODEL or contract['effort'] != EFFORT
                    or contract['prompt'] != reply_instructions()
                    or (not admit_live(body) if admit_live else contract != wire_contract(calls[0]))):
                self.send_error(409)
                return
            headers = {'Authorization': 'Bearer ' + live_key, 'x-litellm-num-retries': '0',
                'Accept': 'text/event-stream'}
            with httpx.Client(timeout=60, trust_env=False) as client, client.stream('POST',
                    'http://127.0.0.1:4000/v1/responses', json=body, headers=headers) as response:
                self.send_response(response.status_code)
                self.send_header('Content-Type', response.headers.get('Content-Type', 'text/event-stream'))
                self.end_headers()
                if response.is_success:
                    for chunk in response.iter_bytes():
                        self.wfile.write(chunk)
                        self.wfile.flush()

    with ThreadingHTTPServer(('127.0.0.1', 0), Provider) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}/v1'
        finally:
            server.shutdown()
            thread.join(timeout=5)


@contextmanager
def aas_server(core, gateway, secret):
    node = os.environ.get('MEMOIR_TEST_NODE', 'node')
    env = {**os.environ, 'MEMORY_SPARK_LLM_BASE_URL': gateway,
        'MEMORY_SPARK_LLM_API_KEY': 'synthetic-provider-key', 'MEMOIR_MIRA_AAS_SECRET': secret,
        'MEMOIR_MIRA_AAS_PORT': '0'}
    with subprocess.Popen([node, str(ROOT / 'mira-aas/server.mjs'), core], env=env,
            stdout=subprocess.PIPE, text=True) as process:
        try:
            assert select.select([process.stdout], [], [], 10)[0], 'AAS startup timed out'
            port = int(process.stdout.readline())
            yield f'http://127.0.0.1:{port}/v1'
        finally:
            process.terminate()
            process.wait(timeout=5)


@contextmanager
def serve(app):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert server.started
            yield f'http://127.0.0.1:{port}'
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()


def run_turn(client, payload, *, require_question=True):
    milestones = {}
    started = time.perf_counter()
    with client.stream('POST', '/v1/agent/turn', json=payload,
            headers={'Accept': 'application/x-ndjson'}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            event = json.loads(line)
            kind = event['type']
            assert kind != 'error', event.get('code') or event.get('message')
            if kind in {'source_accepted', 'text_delta', 'question_validated', 'conversation_saved'}:
                milestones.setdefault(kind, round((time.perf_counter() - started) * 1000, 1))
            if kind == 'result':
                saved = event['data']
    assert saved['conversation_saved'] and saved['reply']
    assert {'text_delta', 'conversation_saved'} <= milestones.keys()
    if require_question:
        assert 'question_validated' in milestones
    return saved, milestones


def wire_contract(body):
    return dict(model=body['model'], effort=body['reasoning']['effort'],
        prompt=body['instructions'], schema=body['text']['format']['schema'])


@pytest.mark.skipif(not os.getenv('MEMOIR_TEST_AAS_CORE'), reason='A built advanced_aas core is required')
def test_local_mira_aas_starts_with_worker_and_reaps_on_shutdown(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from apps.api import codex_worker_service as service

    core = Path(os.environ['MEMOIR_TEST_AAS_CORE']).resolve()
    node = shutil.which(os.getenv('MEMOIR_TEST_NODE', 'node'))
    assert node
    monkeypatch.setenv('PATH', str(Path(node).parent) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('MEMOIR_MIRA_AAS_BUILD_DIR', str(core.parent.parent))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.delenv('MEMOIR_MIRA_AAS_URL', raising=False)
    monkeypatch.setattr(service, 'MIRA_AAS_CORE_MOUNT', core)
    worker = service.CodexWorker(home_root=tmp_path, base_url='http://127.0.0.1:1/v1', api_key='fixture')
    monkeypatch.setattr(service, 'worker', worker)
    with TestClient(service.app) as client:
        assert client.get('/health').json()['mira_runtime'] == 'advanced_aas'
        process = service.app.state.mira_aas_process
        assert process.returncode is None
        url, _ = worker.mira_aas
        with httpx.Client(timeout=4, trust_env=False) as sidecar:
            assert sidecar.post(url + '/responses').status_code == 401
    assert process.returncode is not None
    assert worker.mira_aas is None
    assert service.app.state.mira_aas_process is None


@pytest.mark.skipif(not os.getenv('MEMOIR_TEST_AAS_CORE'), reason='A built advanced_aas core is required')
def test_mira_aas_disconnect_aborts_provider():
    disconnected = threading.Event()
    secret = uuid4().hex
    body = dict(model=MODEL, stream=True, store=False, tool_choice='none', tools=[],
        input=[dict(role='developer', content=[dict(type='input_text', text='Return JSON.')]),
               dict(role='user', content=TEXT)],
        text={'format': dict(type='json_schema', name='trial', strict=True, schema={'type': 'object'})})
    with (provider_fixture([], [1], disconnected=disconnected) as provider,
          aas_server(os.environ['MEMOIR_TEST_AAS_CORE'], provider, secret) as aas,
          httpx.Client(timeout=8, trust_env=False) as client):
        with client.stream('POST', aas + '/responses', json=body,
                headers={'Authorization': 'Bearer ' + secret}) as response:
            response.raise_for_status()
            assert 'response.output_text.delta' in next(response.iter_lines())
        assert disconnected.wait(5), 'The open provider stream did not close after disconnect'


@pytest.mark.skipif(not os.getenv('MEMOIR_TEST_AAS_CORE') or not shutil.which('codex'),
    reason='A built advanced_aas core and Codex CLI are required')
def test_mira_aas_matched_turn(database, tmp_path, monkeypatch):
    from apps.api import agent_routes, codex_worker_service
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.conversation_reply import reply_instructions

    with psycopg.connect(database.publication_dsn, connect_timeout=5) as connection:
        assert connection.execute('select 1').fetchone() == (1,)

    for key, value in {'MEMOIR_TWO_LANES': '1', 'MEMORY_SPARK_COLLECTOR_MODEL': MODEL,
            'MEMORY_SPARK_COLLECTOR_REASONING_EFFORT': EFFORT, 'MEMORY_SPARK_DISABLE_PRIVDROP': '1',
            'MEMOIR_PUBLICATION_DATABASE_URL': database.publication_dsn, 'MEMOIR_CODEX_HOME_BACKUPS': '0',
            'MEMORY_SPARK_CODEX_WORKER_SECRET': 'synthetic-worker-secret', 'MEMORY_SPARK_PARALLEL_POLICY_REVIEW': '0',
            'MEMORY_SPARK_LLM_API_KEY': 'synthetic-provider-key',
            'MEMORY_SPARK_EARLY_POLICY_ACK': '0', 'MEMORY_SPARK_HISTORICAL_NEWS': '0'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('MEMOIR_MIRA_AAS_URL', raising=False)
    database('update public.lifetime_two_lane_rollout set enabled=true, strategy_enabled=true, strategy_shadow=false;')
    app = FastAPI()
    app.include_router(agent_routes.router)
    app.mount('/worker', codex_worker_service.app)

    calls, measurements, permitted = [], [], [0]
    secret = uuid4().hex
    pairs = int(os.getenv('MEMOIR_TEST_MIRA_AAS_PAIRS', '1'))
    assert 1 <= pairs <= 12
    live_env = os.getenv('MEMOIR_TEST_MIRA_AAS_LIVE_ENV')
    live_key = None
    if live_env:
        live_key = dotenv_values(live_env).get('MEMORY_SPARK_LLM_API_KEY')
        assert live_key and pairs == 1, 'Live mode requires a gateway key and permits one pair'
    with (provider_fixture(calls, permitted, live_key) as provider,
          aas_server(os.environ['MEMOIR_TEST_AAS_CORE'], provider, secret) as aas, serve(app) as origin):
        assert httpx.post(aas + '/responses', json={}, timeout=5).status_code == 401

        def worker(arm):
            return codex_worker_service.CodexWorker(home_root=tmp_path / arm, model=MODEL,
                base_url=provider, api_key='synthetic-provider-key', timeout=60 if live_key else 30)

        codex = worker('codex')
        monkeypatch.setenv('MEMOIR_MIRA_AAS_URL', aas)
        monkeypatch.setenv('MEMOIR_MIRA_AAS_SECRET', secret)
        candidate = worker('advanced_aas')
        monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(worker_url=origin + '/worker',
            worker_secret='synthetic-worker-secret', base_url=provider, model=MODEL, task_publisher_enabled=False))
        with httpx.Client(base_url=origin, timeout=75, trust_env=False) as client:
            for pair in range(pairs):
                arms = [('codex', codex), ('advanced_aas', candidate)]
                if pair % 2:
                    arms.reverse()
                for arm, runtime in arms:
                    monkeypatch.setattr(codex_worker_service, 'worker', runtime)
                    owner = str(uuid4())
                    database(f"insert into auth.users(id,is_anonymous) values('{owner}',false);")
                    project = 'mira-trial-' + uuid4().hex
                    seed_fresh_canonical_project(database, owner, project)
                    monkeypatch.setattr(agent_routes, 'authenticated_storage',
                        lambda _, owner=owner: PostgresRest(database, owner).storage())
                    payload = dict(text=TEXT, language='en-AU', project_id=project, client_turn_id=str(uuid4()))
                    before = len(calls)
                    permitted[0] = before + 1
                    saved, timing = run_turn(client, payload)
                    assert len(calls) == before + 1
                    thread_id = database(f"select thread_id from public.user_lifetime_conversation where user_id='{owner}';").stdout.strip()
                    assert thread_id and thread_id.startswith('reply-') == (arm == 'advanced_aas')
                    replay = client.post('/v1/agent/turn', json=payload).json()
                    assert replay['cached'] and replay['reply'] == saved['reply'] and len(calls) == before + 1
                    measurements.append(dict(arm=arm, pair=pair + 1, **timing))

    expected = wire_contract(calls[0])
    assert expected['model'] == MODEL and expected['effort'] == EFFORT
    assert expected['prompt'] == reply_instructions()
    assert all(wire_contract(call) == expected for call in calls)
    print('MIRA_AAS_TRIAL', json.dumps(dict(mode='live_gateway' if live_key else 'controlled_provider', model=MODEL, effort=EFFORT,
        prompt_sha256=sha256(expected['prompt'].encode()).hexdigest(),
        schema_sha256=sha256(json.dumps(expected['schema'], sort_keys=True).encode()).hexdigest(),
        requests=len(calls), samples_ms=measurements)))
