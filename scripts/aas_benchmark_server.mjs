// Benchmark-only copy of the Memoir AAS pilot sidecar.
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const secret = process.env.MEMOIR_MIRA_AAS_SECRET ?? '';
const apiKey = process.env.MEMORY_SPARK_LLM_API_KEY;
const gatewayUrl = process.env.MEMORY_SPARK_LLM_BASE_URL;
if (!process.argv[2] || !apiKey || !gatewayUrl || secret.length < 32) {
  throw new Error('Configure the built AAS core path, gateway, and private Mira secret');
}

const core = pathToFileURL(resolve(process.argv[2]) + '/');
const { query } = await import(new URL('dist/query/query.js', core));
const { createTokenBudget } = await import(new URL('dist/query/tokenBudget.js', core));
const { ToolRegistry } = await import(new URL('dist/tools/registry.js', core));
const { StreamingToolExecutor } = await import(new URL('dist/tools/streamingExecutor.js', core));
const { buildTool } = await import(new URL('dist/tools/buildTool.js', core));
const requireCore = createRequire(new URL('package.json', core));
const { OpenAI } = requireCore('openai');
const { z } = requireCore('zod');
const gateway = new OpenAI({ apiKey, baseURL: gatewayUrl, maxRetries: 0,
  fetch: (input, init) => fetch(input, { ...init, redirect: 'error' }) });

const authorization = Buffer.from(`Bearer ${secret}`);
const pendingTools = new Map();
const allowedTools = new Set(['memoir_read_context', 'memoir_read_skill', 'memoir_execute_skill',
  'memoir_pending_work', 'memoir_process_source']);

async function readBody(request, limit) {
  const length = Number(request.headers['content-length']);
  if (!Number.isSafeInteger(length) || length < 1 || length > limit) {
    throw new Error('Invalid request length');
  }
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks, length));
}

async function requestBody(request) {
  const body = await readBody(request, 65_536);
  const [instructions, ...messages] = body.input;
  if (body.stream !== true || body.store !== false || !Array.isArray(body.tools) || body.tools.length > 4
      || body.tool_choice !== (body.tools.length ? 'auto' : 'none') || body.parallel_tool_calls === true
      || !body.tools.every(tool => tool.type === 'function' && allowedTools.has(tool.name)
        && typeof tool.description === 'string' && tool.parameters?.type === 'object')
      || new Set(body.tools.map(tool => tool.name)).size !== body.tools.length
      || body.text?.format?.type !== 'json_schema'
      || body.text.format.strict !== true || typeof body.model !== 'string'
      || instructions?.role !== 'developer' || !Array.isArray(instructions.content)
      || !instructions.content.length || !instructions.content.every(part =>
        part.type === 'input_text' && typeof part.text === 'string')
      || !messages.length || !messages.every(message =>
        ['user', 'assistant', 'developer'].includes(message.role) && typeof message.content === 'string')) {
    throw new Error('Invalid Mira request');
  }
  return { body, systemPrompt: instructions.content.map(part => part.text).join('\n'), messages };
}

async function hostTool(name, args, send, signal, traceparent) {
  const id = randomUUID();
  const { promise, resolve: settle } = Promise.withResolvers();
  const abort = () => settle(null);
  pendingTools.set(id, { settle, traceparent });
  signal.addEventListener('abort', abort, { once: true });
  try {
    await send({ type: 'memoir.tool_call', id, name, arguments: args });
    const result = await promise;
    signal.throwIfAborted();
    return result;
  } finally {
    pendingTools.delete(id);
    signal.removeEventListener('abort', abort);
  }
}

async function acceptToolResult(request, response) {
  try {
    const { id, result } = await readBody(request, 131_072);
    const pending = pendingTools.get(id);
    if (!pending || pending.traceparent !== request.headers.traceparent) {
      response.writeHead(404).end();
      return;
    }
    const content = result?.contentItems;
    if (typeof result?.success !== 'boolean' || !Array.isArray(content) || content.length !== 1
        || content[0]?.type !== 'inputText' || typeof content[0].text !== 'string') {
      throw new Error('Invalid tool result');
    }
    const value = JSON.parse(content[0].text);
    pendingTools.delete(id);
    pending.settle(value);
    response.writeHead(204).end();
  } catch {
    response.writeHead(400).end();
  }
}

const server = createServer(async (request, response) => {
  if (request.method !== 'POST' || !['/v1/responses', '/v1/tool-results'].includes(request.url)) {
    response.writeHead(404).end();
    return;
  }
  const presented = Buffer.from(request.headers.authorization ?? '');
  if (presented.length !== authorization.length || !timingSafeEqual(presented, authorization)) {
    response.writeHead(401).end();
    return;
  }
  if (request.url === '/v1/tool-results') {
    await acceptToolResult(request, response);
    return;
  }

  const cancellation = new AbortController();
  response.once('close', () => cancellation.abort());
  const signal = AbortSignal.any([cancellation.signal, AbortSignal.timeout(120_000)]);
  let payload;
  try {
    payload = await requestBody(request);
  } catch {
    response.writeHead(400).end();
    return;
  }

  const { body, systemPrompt, messages } = payload;
  const traceparent = request.headers.traceparent;
  if (!/^00-[a-f0-9]{32}-[a-f0-9]{16}-01$/.test(traceparent ?? '')) {
    response.writeHead(400).end();
    return;
  }
  const registry = new ToolRegistry();
  for (const tool of body.tools) {
    registry.register(buildTool({ name: tool.name, description: tool.description,
      inputSchema: z.record(z.unknown()), call: args => hostTool(tool.name, args, send, signal, traceparent) }));
  }
  const executor = new StreamingToolExecutor(registry);
  const recall = registry.has('memoir_read_context');
  const transcript = [...messages];
  let seenMessages = messages.length;
  let terminal;
  const provider = {
    name: 'memoir-responses',
    modelId: body.model,
    async *stream(options) {
      const results = options.messages.slice(seenMessages).filter(message => message.role === 'tool');
      transcript.push(...results.map(message => ({ type: 'function_call_output',
        call_id: message.toolCallId, output: message.content })));
      seenMessages = options.messages.length;
      const wire = { ...body, instructions: options.systemPrompt, input: transcript };
      if (body.tools.length) wire.include = ['reasoning.encrypted_content'];
      if (Buffer.byteLength(JSON.stringify(wire)) > 131_072) throw new Error('AAS input limit exceeded');
      const upstream = await gateway.responses.create(wire, { signal: options.abortSignal, headers: { traceparent,
        'x-litellm-num-retries': '0' } });
      const phases = new Map();
      const buffered = [];
      let streamed = false;
      let bytes = 0;
      for await (const event of upstream) {
        bytes += Buffer.byteLength(JSON.stringify(event));
        if (bytes > 512_000) throw new Error('AAS output limit exceeded');
        if (event.type === 'response.output_item.added' && event.item?.type === 'message') {
          phases.set(event.output_index, event.item.phase);
        } else if (event.type === 'response.output_text.delta') {
          if (typeof event.delta !== 'string') throw new Error('Invalid text delta');
          const phase = phases.get(event.output_index);
          if (phase === 'commentary') continue;
          if (body.tools.length && phase !== 'final_answer') buffered.push(event.delta);
          else {
            streamed = true;
            yield { type: 'text_delta', delta: event.delta };
          }
        } else if (event.type === 'response.completed') {
          const items = event.response.output;
          if (!items.every(item => ['message', 'reasoning', 'function_call'].includes(item.type))) {
            throw new Error('Unexpected AAS provider output');
          }
          const calls = items.filter(item => item.type === 'function_call');
          if (calls.length) {
            const [call] = calls;
            if (calls.length !== 1 || streamed || !registry.has(call.name) || typeof call.call_id !== 'string') {
              throw new Error('Unexpected AAS tool call');
            }
            transcript.push(...items);
            yield { type: 'tool_use', toolCallId: call.call_id, toolName: call.name, input: JSON.parse(call.arguments) };
          } else {
            if (streamed && buffered.length) throw new Error('Mixed AAS reply phases');
            for (const delta of buffered) yield { type: 'text_delta', delta };
            terminal = { ...event, response: { ...event.response, output: items.filter(item =>
              item.type === 'message' && item.phase !== 'commentary') } };
          }
          return;
        } else if (['response.incomplete', 'response.cancelled'].includes(event.type)) {
          terminal = event;
          return;
        } else if (event.type === 'response.failed' || event.type === 'error') {
          throw new Error('Mira provider failed');
        }
      }
    },
  };

  response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' });
  async function send(event) {
    signal.throwIfAborted();
    if (!response.write(`data: ${JSON.stringify(event)}\n\n`)) {
      await once(response, 'drain', { signal });
    }
  }

  try {
    const localMessages = messages.map(message => message.role === 'developer'
      ? { ...message, role: 'user' } : message);
    for await (const event of query(localMessages, { provider, registry, executor, systemPrompt,
      permissionContext: { userId: 'memoir', sessionId: traceparent, agentId: 'mira', agentType: 'session' },
      tokenBudget: createTokenBudget(recall ? 16_384 : 65_536),
      maxTurns: body.tools.length ? (recall ? 5 : 33) : 1, abortSignal: signal })) {
      if (event.type === 'error') throw new Error('Mira query failed');
      if (event.type === 'text_delta') await send({ type: 'response.output_text.delta', delta: event.delta });
    }
    await send(terminal ?? { type: 'response.incomplete' });
    response.end();
  } catch {
    if (signal.aborted) response.destroy();
    else response.end('data: {"type":"error"}\n\n');
  }
});

server.listen(Number(process.env.MEMOIR_MIRA_AAS_PORT ?? '8780'), '127.0.0.1', () => {
  process.stdout.write(`${server.address().port}\n`);
});
