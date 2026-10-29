"""Gateway requests retain the application's OpenTelemetry parent context."""
import asyncio
from contextlib import contextmanager
import json

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from apps.api import llm_tracing
from apps.api.model_request import complete_json
from test_llm_tracing import FakeLangfuse, FakeObservation


TRACE_ID = '1234567890abcdef1234567890abcdef'
SPAN_ID = '1234567890abcdef'


class ApplicationTracer(FakeLangfuse):
    @contextmanager
    def start_as_current_observation(self, **fields):
        observation = FakeObservation(fields)
        offset = len(self.observations)
        observation.trace_id = format(int(TRACE_ID, 16) + offset, '032x')
        observation.id = format(int(SPAN_ID, 16) + offset, '016x')
        self.observations.append(observation)
        parent = trace.SpanContext(trace_id=int(observation.trace_id, 16), span_id=int(observation.id, 16),
            is_remote=False, trace_flags=trace.TraceFlags.SAMPLED)
        with trace.use_span(trace.NonRecordingSpan(parent)):
            yield observation


def test_structured_gateway_call_joins_application_span(monkeypatch):
    tracer = ApplicationTracer()
    monkeypatch.setattr(llm_tracing, '_client_cache', tracer)
    payload = {'source': {'text': 'Private test memory.'}}
    requests = []

    def gateway(request):
        requests.append(request)
        parent = trace.get_current_span(TraceContextTextMapPropagator().extract(
            dict(request.headers))).get_span_context()
        assert parent.trace_id == int(TRACE_ID, 16)
        assert parent.span_id == int(SPAN_ID, 16)
        assert parent.is_remote
        body = json.loads(request.content)
        assert json.loads(body['input']) == payload
        assert int(request.headers['Content-Length']) == len(request.content)
        assert body['metadata']['generation_name'] == 'memoir-interviewer'
        return httpx.Response(200, json={'id': 'response-same-request', 'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{}'}]}]})

    output, receipt = asyncio.run(complete_json(
        'memoir/skills/memoir-interviewer/policy-review', payload, {},
        model='configured-model', effort='low', trace_name='memoir-interviewer',
        diagnostic_request_id='same-request', base_url='https://gateway.invalid/v1',
        api_key='test-key', transport=httpx.MockTransport(gateway)))

    assert output == {} and receipt['response_id'] == 'response-same-request'
    assert len(requests) == len(tracer.observations) == 1
    observation = tracer.observations[0]
    assert observation.fields['as_type'] == 'span'
    assert observation.fields['input'] == {'kind': 'structured_input'}
    assert 'Private test memory.' not in json.dumps(observation.fields, default=str)


def test_gateway_scope_restores_parent_after_failure_and_does_not_forward_baggage(monkeypatch):
    from opentelemetry import baggage, context
    tracer = ApplicationTracer()
    monkeypatch.setattr(llm_tracing, '_client_cache', tracer)
    token = context.attach(baggage.set_baggage('private-memory', 'private words'))
    try:
        assert llm_tracing.gateway_trace_headers() == {}
        with pytest.raises(RuntimeError, match='provider failure'):
            with llm_tracing.trace_llm_call('gateway', 'model', gateway=True):
                assert llm_tracing.gateway_trace_headers() == {'traceparent': f'00-{TRACE_ID}-{SPAN_ID}-01'}
                raise RuntimeError('provider failure')
        assert llm_tracing.gateway_trace_headers() == {}
        with llm_tracing.trace_llm_call('direct-speech', 'model'):
            assert llm_tracing.gateway_trace_headers() == {}
        assert tracer.observations[-1].fields['as_type'] == 'generation'
    finally:
        context.detach(token)


@pytest.mark.parametrize('failure', ['unconfigured', 'startup', 'propagation'])
def test_unavailable_tracing_keeps_provider_request_working(monkeypatch, failure):
    class BrokenTracer:
        def start_as_current_observation(self, **fields):
            raise RuntimeError('Tracing unavailable')
    client = None if failure == 'unconfigured' else BrokenTracer() if failure == 'startup' else ApplicationTracer()
    monkeypatch.setattr(llm_tracing, '_client_cache', client)
    if failure == 'propagation':
        def unavailable(*args, **kwargs):
            raise RuntimeError('Propagation unavailable')
        monkeypatch.setattr(TraceContextTextMapPropagator, 'inject', unavailable)
    calls = []
    def gateway(request):
        calls.append(request)
        assert 'traceparent' not in request.headers
        return httpx.Response(200, json={'id': 'untraced-response', 'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{}'}]}]})
    output, _ = asyncio.run(complete_json('memoir/skills/memoir-interviewer/policy-review', {}, {},
        model='model', effort='low', base_url='https://gateway.invalid/v1', api_key='test-key',
        transport=httpx.MockTransport(gateway)))
    assert output == {} and len(calls) == 1


def test_streaming_gateway_call_keeps_the_application_parent(monkeypatch):
    from apps.api.conversation_reply_transport import stream_reply
    from test_conversation_reply_transport import options, events, sse
    tracer = ApplicationTracer()
    monkeypatch.setattr(llm_tracing, '_client_cache', tracer)
    def gateway(request):
        parent = trace.get_current_span(TraceContextTextMapPropagator().extract(
            dict(request.headers))).get_span_context()
        assert format(parent.trace_id, '032x') == TRACE_ID
        assert format(parent.span_id, '016x') == SPAN_ID
        return httpx.Response(200, content=sse(events('{"ok":true}')))
    async def run():
        with llm_tracing.trace_llm_call('memoir.collector', 'model', gateway=True):
            return await stream_reply(**options(), transport=httpx.MockTransport(gateway))
    output, _ = asyncio.run(run())
    assert output == '{"ok":true}'


def test_concurrent_gateway_calls_keep_independent_trace_parents(monkeypatch):
    tracer = ApplicationTracer()
    monkeypatch.setattr(llm_tracing, '_client_cache', tracer)
    parents = {}
    async def gateway(request):
        body = json.loads(request.content)
        parent = trace.get_current_span(TraceContextTextMapPropagator().extract(
            dict(request.headers))).get_span_context()
        parents[body['metadata']['request_id']] = (format(parent.trace_id, '032x'), format(parent.span_id, '016x'))
        await asyncio.sleep(0)
        return httpx.Response(200, json={'id': 'concurrent-response', 'status': 'completed',
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{}'}]}]})
    async def run():
        await asyncio.gather(*(complete_json('memoir/skills/memoir-interviewer/policy-review', {}, {},
            model='model', effort='low', base_url='https://gateway.invalid/v1', api_key='test-key',
            diagnostic_request_id='request-' + str(index), transport=httpx.MockTransport(gateway))
            for index in range(2)))
    asyncio.run(run())
    assert len(set(parents.values())) == 2
    for index, observation in enumerate(tracer.observations):
        assert parents['request-' + str(index)] == (observation.trace_id, observation.id)
    assert llm_tracing.gateway_trace_headers() == {}
