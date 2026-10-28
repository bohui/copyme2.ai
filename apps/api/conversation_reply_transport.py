"""Bounded reply-v2 requests without the general Codex agent context."""
import asyncio
import hashlib
import json
import os
from urllib.parse import urlsplit

import httpx

from .codex_agent import CodexTurnIncomplete
from .issue14_execution_admission import check_issue14_dispatch
from .lifetime_memory_context import serialize_packet
from .lifetime_memory_publication import GovernedRequestBody
from .model_request import completed_response_text
from .trajectory_evaluation import normalise_correlation


MAX_RESPONSE_BYTES = 512_000


def reply_messages(view, prompt):
    context = dict(view)
    instructions = context.pop('instructions')
    current = context.pop('current')
    return [
        dict(role='developer', content=[dict(type='input_text', text=instructions),
                                      dict(type='input_text', text=prompt)]),
        dict(role='user', content=serialize_packet(context)),
        dict(role='user', content=serialize_packet(dict(current=current))),
    ]


class ReplyRequestBody(GovernedRequestBody):
    def __init__(self, *args, issue14_admission=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.issue14_admission = issue14_admission

    async def _chunks(self):
        from .lifetime_memory_lane_engine import check_lane_generation
        check_lane_generation()
        async with self.publisher.guard(self.fence):
            check_lane_generation()
            check_issue14_dispatch(self.issue14_admission, role='collector')
            yield self.content


async def _events(response, *, max_response_bytes=None):
    pending = bytearray()
    data = []
    received = 0
    async for chunk in response.aiter_bytes():
        received += len(chunk)
        if received > (MAX_RESPONSE_BYTES if max_response_bytes is None else max_response_bytes):
            raise RuntimeError('Interview provider response exceeds its byte limit')
        pending.extend(chunk)
        while b'\n' in pending:
            line, _, rest = pending.partition(b'\n')
            pending = bytearray(rest)
            line = line.rstrip(b'\r')
            if line.startswith(b'data:'):
                data.append(line[5:].lstrip(b' '))
            elif not line and data:
                value = b'\n'.join(data)
                data.clear()
                if value == b'[DONE]':
                    continue
                try:
                    event = json.loads(value)
                except (ValueError, UnicodeDecodeError):
                    raise RuntimeError('Malformed interview provider event') from None
                if not isinstance(event, dict):
                    raise RuntimeError('Malformed interview provider event')
                yield event


async def stream_reply(*, view, prompt, schema, model, effort, budget, base_url, api_key,
                       publisher, fence, metadata, timeout, on_delta=None,
                       issue14_admission=None, transport=None):
    check_issue14_dispatch(issue14_admission, role='collector', correlation=metadata)
    correlation = normalise_correlation(metadata)
    # Responses metadata allows sixteen entries; retain the prompt pins first.
    metadata = {key: correlation[key] for key in (
        'prompt_sha256', 'schema_sha256', 'manifest_sha256', 'generation_name', 'trace_name',
        'request_id', 'run_id', 'case_id', 'application_revision', 'contract_version',
        'round_id', 'trace_id', 'observation_id', 'job_id', 'checkpoint_id', 'variant') if key in correlation}
    endpoint = urlsplit(base_url)
    if (not api_key or endpoint.scheme not in {'http', 'https'} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('Interview provider is not configured')
    body = dict(model=model, input=reply_messages(view, prompt), store=False, stream=True,
        tools=[], tool_choice='none', parallel_tool_calls=False,
        reasoning=dict(effort=effort or os.getenv('MEMORY_SPARK_LLM_REASONING_EFFORT', 'low'), context='all_turns'),
        max_output_tokens=budget.output_headroom,
        prompt_cache_key='memoir-reply-v2-' + hashlib.sha256(
            str(fence.identity.owner_id).encode()).hexdigest()[:32],
        metadata=metadata,
        text=dict(verbosity='low', format=dict(type='json_schema', name='memoir_reply', strict=True, schema=schema)))
    # Keep the schema's field order: acknowledgement streams before private work.
    encoded = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > budget.input_budget:
        raise ValueError('Interview provider request exceeds the input budget')
    request = ReplyRequestBody(encoded, publisher=publisher,
        fence=fence.model_dump(mode='json'), issue14_admission=issue14_admission)
    return await stream_document(request=request, content_length=len(encoded), base_url=base_url,
        api_key=api_key, timeout=timeout, on_delta=on_delta, transport=transport)


async def stream_document(*, request, content_length, base_url, api_key, timeout,
                          on_delta=None, transport=None, max_response_bytes=None):
    """Consume a bounded completed JSON document through its caller's guarded body."""
    deltas = []
    try:
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(transport=transport, timeout=timeout,
                                        trust_env=False, follow_redirects=False) as client:
                async with client.stream('POST', base_url.rstrip('/') + '/responses', content=request,
                    headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json',
                             'Content-Length': str(content_length), 'Accept': 'text/event-stream'}) as response:
                    response.raise_for_status()
                    async for event in _events(response, max_response_bytes=max_response_bytes):
                        kind = event.get('type')
                        if kind == 'response.output_text.delta':
                            delta = event.get('delta')
                            if not isinstance(delta, str):
                                raise RuntimeError('Malformed interview provider delta')
                            deltas.append(delta)
                            if on_delta:
                                await on_delta(delta)
                        elif kind == 'response.completed':
                            value = event.get('response')
                            try:
                                text = completed_response_text(value)
                            except (ValueError, TypeError, KeyError):
                                raise CodexTurnIncomplete('Interview provider document did not complete') from None
                            if any(not isinstance(item, dict) or item.get('type') not in {'message', 'reasoning'}
                                   for item in value['output']):
                                raise RuntimeError('Interview provider returned an unexpected tool or output')
                            if deltas and ''.join(deltas) != text:
                                raise CodexTurnIncomplete('Interview provider final document differs from its stream')
                            if api_key in text:
                                raise RuntimeError('Unsafe interview provider response')
                            return text, dict(response_id=value['id'], model=value.get('model'),
                                              usage=value.get('usage'))
                        elif kind in {'response.incomplete', 'response.cancelled'}:
                            raise CodexTurnIncomplete('Interview provider document did not complete')
                        elif kind in {'response.failed', 'error'}:
                            raise RuntimeError('Interview provider generation failed')
        raise CodexTurnIncomplete('Interview provider stream ended without completion')
    finally:
        await request.aclose()
