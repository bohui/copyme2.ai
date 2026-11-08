"""Benchmark-only worker connections for embedded Pydantic AI and warm AAS."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, nullcontext
from dataclasses import replace
from functools import partial
import hmac
import json
import os
from pathlib import Path
import secrets
import time

from fastapi import HTTPException, Request
import httpx
from jsonschema import Draft202012Validator
from openai import AsyncOpenAI
from pydantic_ai import Agent, AgentRunResultEvent, NativeOutput, RunContext, StructuredDict, Tool
from pydantic_ai.messages import (ModelRequest, ModelResponse, PartDeltaEvent, PartStartEvent,
                                  SystemPromptPart, TextPart, TextPartDelta, UserPromptPart)
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from apps.api.codex_agent import CodexRequestError, CodexTurnIncomplete
from apps.api.issue14_execution_admission import check_issue14_dispatch
from scripts.benchmark_agent_harness import TimedCodex
from scripts.deepseek_benchmark_transport import message, provider_body


def comparison_body(body):
    for index, item in enumerate(body['input']):
        if isinstance(item.get('content'), str) and item.get('role'):
            body['input'][index] = {**message(item['role'], item['content']), **{
                key: value for key, value in item.items() if key not in ('role', 'content')}}
        elif item.get('role'):
            item.setdefault('type', 'message')
    body = provider_body(body)
    # Pydantic AI strips trailing whitespace when composing instructions.
    body['instructions'] = body['instructions'].rstrip('\n') + '\n'
    for item in body['input']:
        if item.get('role') == 'assistant':
            item.setdefault('phase', 'final_answer')
        for part in item.get('content') or []:
            if not part.get('annotations'):
                part.pop('annotations', None)
    for tool in body['tools']:
        tool.setdefault('strict', False)
    # The AAS pilot executes one function at a time. Use that provider setting
    # for every arm, including Codex, with identical tool declarations.
    body['parallel_tool_calls'] = False
    return body


class ComparisonRuntimes:
    def __init__(self, bridge, aas_core, node):
        self.bridge, self.aas_core, self.node = bridge, Path(aas_core).resolve(), node
        self.secret = secrets.token_hex(32)

        @bridge.app.post('/benchmark/aas/v1/responses')
        async def aas_gateway(request: Request):
            trace = request.headers.get('traceparent', '').split('-')
            token = trace[1] + trace[2] if len(trace) == 4 else ''
            exchange = bridge.exchanges.get(token)
            if (exchange is None or request.headers.get('traceparent') != aas_trace(exchange)
                    or not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + self.secret)):
                raise HTTPException(status_code=403)
            return bridge.responses(exchange, await request.json())

    @asynccontextmanager
    async def serve(self):
        env = {key: os.environ[key] for key in ('PATH', 'TMPDIR') if key in os.environ}
        env.update(MEMOIR_MIRA_AAS_PORT='0', MEMOIR_MIRA_AAS_SECRET=self.secret,
                   MEMORY_SPARK_LLM_API_KEY=self.secret,
                   MEMORY_SPARK_LLM_BASE_URL=self.bridge.origin + '/benchmark/aas/v1')
        process = await asyncio.create_subprocess_exec(self.node,
            str(Path(__file__).with_name('aas_benchmark_server.mjs')), str(self.aas_core),
            env=env, stdout=asyncio.subprocess.PIPE)
        try:
            async with asyncio.timeout(15):
                ready = (await process.stdout.readline()).strip()
            if not ready.isdigit():
                raise RuntimeError('AAS benchmark sidecar did not start')
            self.aas_url = f'http://127.0.0.1:{int(ready)}/v1'
            async with httpx.AsyncClient(trust_env=False, timeout=120,
                    limits=httpx.Limits(max_connections=700, max_keepalive_connections=64)) as client:
                self.client = client
                yield self
        finally:
            if process.returncode is None:
                process.terminate()
            await process.wait()

    def factory(self, arm, exchange):
        if arm == 'codex':
            return partial(TimedCodex, exchange=exchange)
        return partial(EmbeddedConnection, arm=arm, exchange=exchange, runtimes=self)


def aas_trace(exchange):
    return f'00-{exchange.token[:32]}-{exchange.token[32:]}-01'


class MemoirResponsesModel(OpenAIResponsesModel):
    def __init__(self, name, schema, **options):
        super().__init__(name, **options)
        self.schema = schema

    def customize_request_parameters(self, parameters):
        parameters = super().customize_request_parameters(parameters)
        # The worker's schema, including $defs and bounds, is the wire contract.
        return replace(parameters, output_object=replace(parameters.output_object, json_schema=self.schema))


class EmbeddedConnection:
    def __init__(self, _command, _home, *, arm, exchange, runtimes, request_admission=None,
                 tool_handler=None, issue14_admission=None, **_options):
        self.arm, self.exchange, self.runtimes = arm, exchange, runtimes
        self.admit = request_admission or nullcontext
        self.tool_handler, self.issue14_admission = tool_handler, issue14_admission
        self.thread = None
        self.pending = []
        self.last_usage = None
        self.first_text_ms = None
        self.startup_ms = 0.0

    async def __aenter__(self):
        self.exchange.connection = self
        return self

    async def __aexit__(self, *args):
        self.exchange.dispatch_admission = None

    async def request(self, method, params):
        check_issue14_dispatch(self.issue14_admission, role='native')
        async with self.admit():
            if method == 'thread/resume':
                # Memoir rehydrates from its authorized, committed dialogue.
                raise CodexRequestError(method, {'message': 'thread not found'})
            if method == 'thread/start' and self.thread is None:
                self.thread = secrets.token_hex(16)
                self.model, self.instructions = params['model'], params['baseInstructions']
                self.specs = {spec['name']: spec for spec in params.get('dynamicTools', [])}
                return {'thread': {'id': self.thread}}
            if method == 'thread/inject_items' and self.thread is not None and params['threadId'] == self.thread:
                self.pending.extend(params['items'])
                return {}
        raise ValueError('Unexpected benchmark thread request')

    async def turn(self, thread_id, text, on_delta=None, responsesapi_client_metadata=None,
                   output_schema=None, on_event=None, effort=None, max_response_bytes=None):
        check_issue14_dispatch(self.issue14_admission, role='native', correlation=responsesapi_client_metadata)
        if thread_id != self.thread or effort != self.exchange.bridge.effort or output_schema is None:
            raise ValueError('Unexpected benchmark turn')
        self.exchange.dispatch_admission = self.admit
        self.first_text_ms = None
        size = 0

        async def emit(delta):
            nonlocal size
            if not delta:
                return
            size += len(delta.encode())
            if size > (max_response_bytes or 512_000):
                raise ValueError('Benchmark response exceeds byte limit')
            if self.first_text_ms is None:
                self.first_text_ms = self.exchange.ms()
            if on_delta:
                await on_delta(delta)

        history = [dict(role=item['role'], content=''.join(part['text'] for part in item['content']))
                   for item in self.pending]
        self.pending.clear()
        if self.arm == 'pydantic':
            return await self.pydantic(history, text, effort, output_schema, emit)
        return await self.aas([*history, dict(role='user', content=text)], effort, output_schema, emit)

    async def call_tool(self, name, arguments, call_id):
        if name not in self.specs or self.tool_handler is None:
            raise ValueError('Tool is outside the worker capability set')
        check_issue14_dispatch(self.issue14_admission, role='native')
        result = await self.tool_handler(dict(tool=name, arguments=arguments, callId=call_id,
                                              threadId=self.thread))
        async with self.admit():
            return result

    async def pydantic(self, history, text, effort, schema, emit):
        client = AsyncOpenAI(base_url=self.exchange.origin + '/v1', api_key=self.exchange.token,
                             max_retries=0, http_client=self.runtimes.client)
        profile = OpenAIModelProfile(supports_json_schema_output=True, json_schema_transformer=None,
            openai_supports_phase=True,
            openai_system_prompt_role='developer', openai_supports_encrypted_reasoning_content=True)
        model = MemoirResponsesModel(self.model, schema, provider=OpenAIProvider(openai_client=client), profile=profile)

        def register(name, spec):
            async def tool(ctx: RunContext, **arguments):
                result = await self.call_tool(name, arguments, ctx.tool_call_id)
                return ''.join(item['text'] for item in result['contentItems'])

            registered = Tool.from_schema(tool, name, spec['description'], spec['inputSchema'], takes_ctx=True)
            registered.strict = False
            return registered

        messages = []
        for item in history:
            content = item['content']
            if item['role'] == 'assistant':
                messages.append(ModelResponse(parts=[TextPart(content)]))
            else:
                part = UserPromptPart(content) if item['role'] == 'user' else SystemPromptPart(content)
                messages.append(ModelRequest(parts=[part]))
        agent = Agent(model, instructions=self.instructions, retries=0,
            tools=[register(name, spec) for name, spec in self.specs.items()],
            output_type=NativeOutput(StructuredDict(schema), name='codex_output_schema', strict=True),
            model_settings=dict(openai_store=False, openai_reasoning_effort=effort, openai_reasoning_summary='auto',
                                parallel_tool_calls=False))
        streamed_parts = set()
        async with agent.run_stream_events(text, message_history=messages,
                usage_limits=UsageLimits(request_limit=self.exchange.bridge.max_steps)) as events:
            async for event in events:
                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                    streamed_parts.discard(event.index)
                    if self.exchange.text_phases.get(event.part.id) == 'final_answer':
                        streamed_parts.add(event.index)
                        await emit(event.part.content)
                elif (isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta)
                        and event.index in streamed_parts):
                    await emit(event.delta.content_delta)
                elif isinstance(event, AgentRunResultEvent):
                    result = event.result
                    Draft202012Validator(schema).validate(result.output)
                    final = json.dumps(result.output, ensure_ascii=False, separators=(',', ':'))
                    if self.first_text_ms is None:
                        await emit(final)
                    return final
        raise CodexTurnIncomplete('Pydantic AI completed without a final result')

    async def aas(self, messages, effort, schema, emit):
        tools = [dict(type='function', name=name, description=spec['description'],
                      parameters=spec['inputSchema'], strict=False) for name, spec in self.specs.items()]
        body = dict(model=self.model, input=[message('developer', self.instructions), *messages],
            tools=tools, tool_choice='auto' if tools else 'none', parallel_tool_calls=False,
            stream=True, store=False, reasoning=dict(effort=effort, summary='auto'),
            text=dict(format=dict(type='json_schema', name='codex_output_schema', strict=True, schema=schema)))
        headers = {'Authorization': 'Bearer ' + self.runtimes.secret, 'traceparent': aas_trace(self.exchange)}
        client, url = self.runtimes.client, self.runtimes.aas_url
        async with client.stream('POST', url + '/responses', json=body, headers=headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data: '):
                    continue
                event = json.loads(line[6:])
                kind = event['type']
                if kind == 'response.output_text.delta':
                    await emit(event['delta'])
                elif kind == 'memoir.tool_call':
                    result = await self.call_tool(event['name'], event['arguments'], event['id'])
                    callback = await client.post(url + '/tool-results', headers=headers,
                                                 json=dict(id=event['id'], result=result))
                    callback.raise_for_status()
                elif kind == 'response.completed':
                    return ''.join(part['text'] for item in event['response']['output']
                                   for part in item['content'] if part['type'] == 'output_text')
                elif kind in ('error', 'response.incomplete', 'response.cancelled'):
                    raise CodexTurnIncomplete('AAS completed without a final result')
        raise CodexTurnIncomplete('AAS stream ended without a final result')
