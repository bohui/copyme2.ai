"""Local-only transport for comparing the two agent loops with identical Responses requests."""
import asyncio
from contextlib import aclosing, asynccontextmanager, nullcontext
from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
import socket
import time

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx
import uvicorn

from apps.api.codex_agent import CodexRequestError, CodexTurnIncomplete
from apps.api.issue14_execution_admission import check_issue14_dispatch
from scripts.memoir_skill_eval_suite import digest


def message(role, text):
    content_type = 'output_text' if role == 'assistant' else 'input_text'
    return dict(type='message', role=role, content=[dict(type=content_type, text=text)])


def model_tool_schema(schema):
    """Match Codex's function-schema projection. Host validators keep the full schema."""
    node = {key: value for key, value in schema.items()
            if key not in ('maxLength', 'maxItems', 'uniqueItems')}
    if 'properties' in node:
        node['properties'] = {key: model_tool_schema(value) for key, value in node['properties'].items()}
    if 'items' in node:
        node['items'] = model_tool_schema(node['items'])
    return node


def provider_body(body):
    """Give the provider the app's inputs and allowed tools in both arms."""
    body = deepcopy(body)
    items = body['input']
    if (len(items) >= 2 and items[0].get('role') == 'developer'
            and items[0]['content'][0]['text'].startswith('<permissions instructions>\n')
            and items[1].get('role') == 'user'
            and items[1]['content'][0]['text'].startswith('<environment_context>\n')):
        body['input'] = items[2:]
    body['tools'] = [tool for tool in body.get('tools', []) if tool.get('name', '').startswith('memoir_')]
    for tool in body['tools']:
        tool['parameters'] = model_tool_schema(tool['parameters'])
    for key in ('client_metadata', 'prompt_cache_key'):
        body.pop(key, None)
    for item in body['input']:
        if item['type'] in ('message', 'function_call', 'function_call_output'):
            item.pop('id', None)
            item.pop('status', None)
    return body


def request_evidence(body):
    items = body['input']
    schema = body.get('text', {}).get('format', {}).get('schema')
    return dict(model=body['model'], effort=body['reasoning']['effort'],
                instructions_sha256=digest(body['instructions']), schema_sha256=digest(schema),
                input_sha256=digest(items), tool_names=sorted(t['name'] for t in body['tools']),
                tools_sha256=digest(sorted(body['tools'], key=lambda t: t['name'])))


def tool_result(call_id, text):
    return dict(type='function_call_output', call_id=call_id, output=text)


def output_item(answer):
    if isinstance(answer, dict) and answer.get('type') == 'function_call':
        return {**answer, 'id': 'fc_' + answer['call_id'], 'status': 'completed'}
    text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    item = message('assistant', text)
    item['content'][0]['annotations'] = []
    return {**item, 'id': 'msg_fixture', 'status': 'completed', 'phase': 'final_answer'}


async def replay_events(body, answer, delay):
    item = output_item(answer)
    response = dict(id='resp_fixture', object='response', status='completed', model=body['model'],
                    created_at=time.time(), output=[item], usage=dict(input_tokens=100,
                        input_tokens_details=dict(cached_tokens=0), output_tokens=20,
                        output_tokens_details=dict(reasoning_tokens=0), total_tokens=120))
    yield dict(type='response.created', response={**response, 'status': 'in_progress', 'output': []})
    yield dict(type='response.output_item.added', output_index=0,
               item={**item, 'status': 'in_progress', **({'content': []} if 'content' in item else {})})
    if item['type'] == 'message':
        text = item['content'][0]['text']
        split = text.find(',') + 1 or len(text) // 2
        for part in (text[:split], text[split:]):
            await asyncio.sleep(delay)
            yield dict(type='response.output_text.delta', output_index=0, content_index=0,
                       item_id=item['id'], delta=part)
        yield dict(type='response.output_text.done', output_index=0, content_index=0,
                   item_id=item['id'], text=text, logprobs=[])
    else:
        await asyncio.sleep(delay)
    yield dict(type='response.output_item.done', output_index=0, item=item)
    yield dict(type='response.completed', response=response)


class Exchange:
    def __init__(self, bridge, fixture):
        self.bridge, self.fixture = bridge, fixture
        self.token = secrets.token_hex(24)
        self.connection = None
        self.requests = []
        self.text_phases = {}
        self.dispatch_admission = None
        self.started = time.perf_counter()

    @property
    def origin(self):
        return f'{self.bridge.origin}/{self.token}'

    def ms(self):
        return round((time.perf_counter() - self.started) * 1000, 2)

    async def events(self, body):
        if (body.get('store') is not False or body.get('stream') is not True
                or body.get('model') != self.bridge.model
                or body.get('reasoning', {}).get('effort') != self.bridge.effort
                or len(self.requests) >= self.bridge.max_steps):
            raise ValueError('model_request_outside_benchmark_contract')
        if self.dispatch_admission is not None:
            async with self.dispatch_admission():
                pass
        evidence = dict(**request_evidence(body), dispatch_ms=self.ms())
        self.requests.append(evidence)
        if self.fixture is not None:
            events = replay_events(body, self.fixture(body, len(self.requests)), self.bridge.delay)
        else:
            events = self.bridge.upstream(body)
        async with aclosing(events) as stream:
            async for event in stream:
                if event['type'] == 'response.output_item.added' and event['item']['type'] == 'message':
                    self.text_phases[event['item']['id']] = event['item'].get('phase')
                if event['type'] == 'response.output_text.delta':
                    evidence.setdefault('provider_first_text_ms', self.ms())
                if event['type'] in ('response.completed', 'response.incomplete', 'response.failed'):
                    response = event['response']
                    evidence.update(provider_done_ms=self.ms(), served_model=response.get('model'),
                                    usage=response.get('usage'), provider_status=response.get('status'),
                                    provider_error=(response.get('error') or {}).get('code'))
                yield event


class Bridge:
    def __init__(self, *, model, effort, gateway=None, key=None, delay=.04, max_steps=12, max_calls=400,
                 normalize=provider_body):
        self.model, self.effort = model, effort
        self.gateway, self.key, self.delay, self.max_steps = gateway, key, delay, max_steps
        self.max_calls, self.calls = max_calls, 0
        self.exchanges = {}
        self.normalize = normalize
        self.app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @self.app.post('/{token}/v1/responses')
        async def codex(token: str, request: Request):
            exchange = self.authorize(token, request)
            return self.responses(exchange, await request.json())

        @self.app.post('/{token}/step')
        async def step(token: str, request: Request):
            connection = self.authorize(token, request).connection
            body = await request.json()
            return StreamingResponse(connection.step(body), media_type='application/x-ndjson')

        @self.app.post('/{token}/tool')
        async def tool(token: str, request: Request):
            connection = self.authorize(token, request).connection
            return await connection.tool(await request.json())

    def authorize(self, token, request):
        if token not in self.exchanges or request.headers.get('authorization') != 'Bearer ' + token:
            raise HTTPException(status_code=403)
        return self.exchanges[token]

    def responses(self, exchange, body):
        body = self.normalize(body)

        async def stream():
            async for event in exchange.events(body):
                yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'

        return StreamingResponse(stream(), media_type='text/event-stream')

    @asynccontextmanager
    async def serve(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            self.origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
            server = uvicorn.Server(uvicorn.Config(self.app, log_level='critical', lifespan='off',
                                                 timeout_graceful_shutdown=3))
            task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with asyncio.timeout(10):
                    while not server.started:
                        if task.done():
                            await task
                            raise RuntimeError('Benchmark bridge did not start')
                        await asyncio.sleep(.01)
                yield self
            finally:
                server.should_exit = True
                await task

    @asynccontextmanager
    async def exchange(self, fixture=None):
        exchange = Exchange(self, fixture)
        self.exchanges[exchange.token] = exchange
        try:
            yield exchange
        finally:
            self.exchanges.pop(exchange.token)

    async def upstream(self, body):
        if self.gateway is None or self.calls >= self.max_calls:
            raise ValueError('live_call_budget_exhausted')
        self.calls += 1
        headers = {'Authorization': 'Bearer ' + self.key, 'x-litellm-num-retries': '0'}
        async with httpx.AsyncClient(trust_env=False, timeout=100) as client:
            async with client.stream('POST', self.gateway + '/responses', headers=headers, json=body) as response:
                if not response.is_success:
                    yield dict(type='response.failed', response=dict(status='failed',
                        error=dict(code='server_error', message=f'gateway_http_{response.status_code}')))
                    return
                async for line in response.aiter_lines():
                    if line.startswith('data: ') and line != 'data: [DONE]':
                        yield json.loads(line[6:])


class DeepSeekConnection:
    """Benchmark adapter for the existing worker connection factory.

    Canonical history, strict schemas and Memoir capabilities come from the
    worker. The SDK owns session lifecycle, model steps and tool scheduling.
    """
    def __init__(self, _command, home, *, exchange, binary, timeout, request_admission=None,
                 tool_handler=None, issue14_admission=None, **_options):
        self.home = Path(home)
        self.exchange, self.binary, self.timeout = exchange, binary, timeout
        self.admit = request_admission or nullcontext
        self.tool_handler, self.issue14_admission = tool_handler, issue14_admission
        self.state = self.home / 'dsh'
        self.process = None
        self.sequence = 0
        self.last_usage = None
        self.pending = []

    async def __aenter__(self):
        self.exchange.connection = self
        return self

    async def __aexit__(self, *args):
        closing = asyncio.create_task(self.close())
        with anyio.CancelScope(shield=True):
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                await asyncio.shield(closing)
                raise

    async def close(self):
        if self.process is None:
            return
        try:
            if self.process.returncode is None:
                async with asyncio.timeout(4):
                    await self.rpc('shutdown')
                    await self.process.wait()
        except (RuntimeError, TimeoutError, OSError):
            pass
        finally:
            if self.process.returncode is None:
                self.process.kill()
            await self.process.wait()

    async def launch(self):
        check_issue14_dispatch(self.issue14_admission, role='native')
        self.state.mkdir(mode=0o700, exist_ok=True)
        disabled = ('session-log-deepseek', 'llm-deepseek', 'persistent-bash', 'persistent-pwsh',
                    'tool-fs', 'tool-working-directory', 'compaction-basic', 'image-offload',
                    'session-checkpoint-policy', 'mcp-resources', 'llm-retry')
        overlay = [{'id': entry, 'disabled': True} for entry in disabled]
        overlay.append({'insert': [dict(id='memoir-benchmark',
            name=str(Path(__file__).with_name('deepseek_benchmark_plugin.mjs').resolve()),
            config=dict(origin=self.exchange.origin, token=self.exchange.token, specs=self.specs,
                        effort=self.exchange.bridge.effort))]})
        patch = self.state / 'memoir.patch.yml'
        patch.write_text(json.dumps(overlay))
        env = {key: os.environ[key] for key in ('PATH', 'TMPDIR') if key in os.environ}
        env.update(HOME=str(self.state), DSH_HOME=str(self.state), DSH_SYSTEM_PROMPT=self.instructions)
        started = time.perf_counter()
        with (self.state / 'runtime.stderr').open('ab') as errors:
            launching = asyncio.create_task(asyncio.create_subprocess_exec(
                str(self.binary), '--profile', 'sdk-minimal', '--patch', str(patch),
                cwd=self.home, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=errors, limit=4 * 1024 * 1024))
            try:
                self.process = await asyncio.shield(launching)
            except asyncio.CancelledError:
                with anyio.CancelScope(shield=True):
                    self.process = await asyncio.shield(launching)
                raise
        await self.rpc('initialize', dict(cwd=str(self.home), provider='memoir-benchmark',
            model=self.model, reasoningEffort=self.exchange.bridge.effort))
        self.startup_ms = round((time.perf_counter() - started) * 1000, 2)

    async def rpc(self, method, params=None, observe=None, *, admit=False):
        self.sequence += 1
        request_id = self.sequence
        request = dict(jsonrpc='2.0', id=request_id, method=method)
        if params is not None:
            request['params'] = params
        async with (self.admit() if admit else nullcontext()):
            self.process.stdin.write((json.dumps(request) + '\n').encode())
            await self.process.stdin.drain()
        async with asyncio.timeout(self.timeout):
            while line := await self.process.stdout.readline():
                event = json.loads(line)
                if event.get('id') == request_id:
                    if 'error' in event:
                        raise CodexRequestError(method, event['error'])
                    return event['result']
                if observe is not None:
                    await observe(event)
        raise RuntimeError('DeepSeek SDK closed its output')

    async def request(self, method, params):
        check_issue14_dispatch(self.issue14_admission, role='native')
        if method == 'thread/inject_items':
            if params['threadId'] != self.thread:
                raise ValueError('benchmark_thread_mismatch')
            async with self.admit():
                self.pending.extend(deepcopy(params['items']))
            return {}
        if method not in ('thread/start', 'thread/resume'):
            raise ValueError('benchmark_thread_method')
        self.model, self.instructions = params['model'], params['baseInstructions']
        self.specs = params.get('dynamicTools') or []
        self.thread = params.get('threadId') or secrets.token_hex(16)
        if not self.thread.isalnum():
            raise ValueError('benchmark_thread_id')
        self.history_path = self.state / (self.thread + '.json')
        self.history = []
        if method == 'thread/resume':
            if not self.history_path.is_file():
                raise CodexRequestError(method, {'message': 'thread not found'})
            self.history = json.loads(self.history_path.read_text())
        if self.process is None:
            await self.launch()
        if method == 'thread/resume':
            await self.rpc('session/resume', {'sessionId': self.thread}, admit=True)
        return {'thread': {'id': self.thread}}

    async def turn(self, thread_id, text, on_delta=None, responsesapi_client_metadata=None,
                   output_schema=None, on_event=None, effort=None, max_response_bytes=None):
        check_issue14_dispatch(self.issue14_admission, role='native',
                               correlation=responsesapi_client_metadata)
        if thread_id != self.thread or effort != self.exchange.bridge.effort:
            raise ValueError('benchmark_turn_mismatch')
        self.text, self.schema = text, output_schema
        self.inputs = [*self.history, *self.pending, message('user', text)]
        self.pending.clear()
        self.calls, self.terminal = {}, None
        self.first_text_ms = self.sdk_first_text_ms = None
        final_text = ''
        response_bytes = 0

        async def observe(event):
            nonlocal final_text, response_bytes
            params = event.get('params', {})
            if params.get('sessionId') != thread_id:
                return
            if event['method'] == 'memoir.delta':
                delta = params['text']
                response_bytes += len(delta.encode())
                if response_bytes > (max_response_bytes or 512_000):
                    raise RuntimeError('Benchmark response exceeds byte limit')
                if delta and self.first_text_ms is None:
                    self.first_text_ms = self.exchange.ms()
                if on_delta:
                    await on_delta(delta)
            if event['method'] != 'session.event':
                return
            item = params['event']
            if item['type'] == 'assistant/message':
                content = item['data']['message']['content']
                final_text = ''.join(block['text'] for block in content if block['type'] == 'text')
                if final_text and self.sdk_first_text_ms is None:
                    self.sdk_first_text_ms = self.exchange.ms()
                self.last_usage = item['data'].get('usage')
            elif item['type'] == 'turn/end':
                self.terminal = item['data']['reason']['kind']

        await self.rpc('session/prompt', dict(sessionId=thread_id,
            contentBlocks=[dict(type='text', text=text)]), observe, admit=True)
        await self.rpc('session/wait', dict(sessionId=thread_id), observe)
        if self.terminal == 'max-tokens':
            raise CodexTurnIncomplete('Provider output was incomplete')
        if self.terminal != 'completed' or not final_text:
            raise RuntimeError('DeepSeek SDK turn did not complete with text')
        self.history = self.inputs
        temporary = self.history_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.history, ensure_ascii=False))
        temporary.replace(self.history_path)
        return final_text

    async def tool(self, payload):
        call_id = payload['callId']
        call = self.calls.pop(call_id, None)
        if (call is None or self.tool_handler is None or call['name'] != payload['tool']
                or json.loads(call['arguments']) != payload['arguments']):
            raise HTTPException(status_code=403)
        result = await self.tool_handler(payload)
        text = ''.join(item['text'] for item in result['contentItems'])
        async with self.admit():
            self.inputs.append(tool_result(call_id, text))
        return {'text': text}

    async def step(self, options):
        last_user = next((m for m in reversed(options['messages']) if m['role'] == 'user'
                          and m.get('source', {}).get('kind') == 'user'), None)
        system = next((m for m in options['messages'] if m['role'] == 'system'), None)
        names = {tool['name'] for tool in options.get('tools') or []}
        if (options['model'] != self.model or options.get('reasoningEffort') != self.exchange.bridge.effort
                or last_user is None or last_user['content'] != [{'type': 'text', 'text': self.text}]
                or system is None or system['content'] != [{'type': 'text', 'text': self.instructions}]
                or names != {tool['name'] for tool in self.specs} or self.calls):
            raise ValueError('SDK step diverged from worker request')
        body = dict(model=self.model, instructions=self.instructions, input=list(self.inputs),
                    tools=[dict(type='function', name=t['name'], description=t['description'],
                                strict=False, parameters=t['inputSchema']) for t in self.specs],
                    tool_choice='auto', parallel_tool_calls=True, store=False, stream=True,
                    reasoning=dict(effort=self.exchange.bridge.effort, summary='auto'),
                    include=['reasoning.encrypted_content'])
        if self.schema is not None:
            body['text'] = dict(format=dict(type='json_schema', strict=True,
                name='codex_output_schema', schema=self.schema))
        async with self.admit():
            check_issue14_dispatch(self.issue14_admission, role='native')
        async with aclosing(self.exchange.events(provider_body(body))) as stream:
            async for chunk in self.chunks(stream):
                yield json.dumps(chunk, ensure_ascii=False) + '\n'

    async def chunks(self, events):
        blocks = {}
        async for event in events:
            kind = event['type']
            index = event.get('output_index', 0)
            if kind == 'response.output_text.delta':
                if index not in blocks:
                    blocks[index] = ''
                    yield dict(type='block-start', index=index, blockType='text')
                blocks[index] += event['delta']
                yield dict(type='text-delta', index=index, text=event['delta'])
            elif kind == 'response.output_item.done':
                item = event['item']
                self.inputs.append(item)
                if item['type'] == 'function_call':
                    self.calls[item['call_id']] = item
                    yield dict(type='block-start', index=index, blockType='tool-call')
                    yield dict(type='block-end', index=index, block={
                        'type': 'tool-call', 'id': item['call_id'], 'name': item['name'],
                        'arguments': item['arguments']})
                elif index in blocks:
                    yield dict(type='block-end', index=index, block=dict(type='text', text=blocks.pop(index)))
            elif kind == 'response.failed':
                yield dict(type='finish', reason=dict(kind='error', failure=dict(
                    code='PROVIDER_FAILED', message='Benchmark provider request failed')))
                return
            elif kind in ('response.completed', 'response.incomplete'):
                response = event['response']
                usage = response.get('usage') or {}
                if {'input_tokens', 'output_tokens', 'total_tokens'} <= usage.keys():
                    cached = (usage.get('input_tokens_details') or {}).get('cached_tokens') or 0
                    yield dict(type='usage', usage=dict(inputTokens=usage['input_tokens'] - cached,
                        outputTokens=usage['output_tokens'], totalTokens=usage['total_tokens'], cacheReadTokens=cached))
                finish = ('max-tokens' if kind == 'response.incomplete'
                          else 'tool-calls' if self.calls else 'stop')
                yield dict(type='finish', reason=dict(kind=finish))
                return
        raise RuntimeError('Benchmark provider stream ended without a terminal event')
