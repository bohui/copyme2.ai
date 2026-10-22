"""Inspect actual Responses HTTP bodies and streamed completion boundaries."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json

import httpx
import pytest

from apps.api import conversation_reply_transport as transport
from apps.api.codex_agent import CodexTurnIncomplete
from apps.api.issue14_execution_admission import AdmissionDenied, Issue14Admission
from apps.api.lifetime_memory_contracts import ContextBudget
from apps.api.lifetime_memory_engine import GOVERNED_TURN_PROMPT
from test_lifetime_memory_engine import BUDGET, FENCE, FakePublisher, fixture


def events(text, *, final_text=None, output=None, status='completed'):
    message = dict(type='message', status='completed', role='assistant',
                   content=[dict(type='output_text', text=final_text or text)])
    value = dict(id='resp_gateway_id==', status=status, model='fixture-model',
                 output=output or [message], usage=dict(input_tokens=1200, output_tokens=40))
    return [dict(type='response.output_text.delta', delta=text),
            dict(type='response.' + status, response=value)]


def sse(values):
    return b''.join(b'data: ' + json.dumps(v, ensure_ascii=False).encode() + b'\r\n\r\n' for v in values)


def install_reply_provider(monkeypatch, replies):
    """Run the real serializer and SSE decoder against an in-process provider."""
    captured = []
    original = transport.stream_reply

    def provider(request):
        body = json.loads(request.content)
        captured.append(body)
        output = replies[len(captured)-1]
        if callable(output):
            output = output(body)
        text = output if isinstance(output, str) else json.dumps(output)
        return httpx.Response(200, content=sse(events(text)), headers={'Content-Type':'text/event-stream'})

    async def send(**kwargs):
        return await original(**kwargs, transport=httpx.MockTransport(provider))

    monkeypatch.setattr(transport, 'stream_reply', send)
    return captured


def options(**changes):
    from apps.api.conversation_reply import reply_packet
    from apps.api.lifetime_memory_engine import validate_governed_context
    governed, context = fixture()
    view = reply_packet(validate_governed_context(governed, context))
    return dict(view=view, prompt=GOVERNED_TURN_PROMPT, schema=dict(type='object'),
        model=BUDGET.model, effort='low', budget=BUDGET, base_url='https://provider.invalid/v1',
        api_key='fixture-secret-key', publisher=FakePublisher(), fence=FENCE,
        metadata={'generation_name':'memoir-interviewer'}, timeout=1, **changes)


def test_messages_keep_static_prefix_and_complete_current_evidence_last():
    first = options()['view']
    second = deepcopy(first)
    second['current']['narrator']['original'] = '不同的叙述😀'
    second['preferences']['chosen_name'] = '小林'
    before = deepcopy(first)
    a, b = [transport.reply_messages(v, GOVERNED_TURN_PROMPT) for v in (first, second)]
    assert a[0] == b[0]
    assert [v['role'] for v in a] == ['developer', 'user', 'user']
    assert json.loads(a[-1]['content']) == {'current': first['current']}
    assert 'current' not in json.loads(a[1]['content'])
    assert first == before


def test_actual_request_is_tools_free_scoped_and_keeps_schema_and_route():
    captured = []
    def provider(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, content=sse(events('{"ok":true}')))
    value, receipt = asyncio.run(transport.stream_reply(**options(), transport=httpx.MockTransport(provider)))
    body = captured[0]
    assert value == '{"ok":true}' and receipt['response_id'] == 'resp_gateway_id=='
    assert body['model'] == BUDGET.model and body['reasoning'] == {'effort':'low', 'context':'all_turns'}
    assert body['text']['verbosity'] == 'low'
    assert body['tools'] == [] and body['tool_choice'] == 'none'
    assert body['text']['format']['strict'] and body['text']['format']['schema'] == {'type':'object'}
    assert body['metadata']['generation_name'] == 'memoir-interviewer'
    assert body['max_output_tokens'] == BUDGET.output_headroom
    assert all(item.get('type') != 'additional_tools' for item in body['input'])
    assert 'skills_instructions' not in json.dumps(body) and 'environment_context' not in json.dumps(body)
    assert 'fixture-secret-key' not in json.dumps(body)
    assert len(body['prompt_cache_key']) < 64


def test_request_preserves_the_reviewed_output_field_order():
    captured = []
    schema = dict(type='object', properties=dict(acknowledgement={}, question={}, reason={}, hint={}, quote={}, work={}))
    def provider(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, content=sse(events('{"ok":true}')))
    asyncio.run(transport.stream_reply(**{**options(), 'schema':schema}, transport=httpx.MockTransport(provider)))
    assert list(captured[0]['text']['format']['schema']['properties']) == list(schema['properties'])


def test_metadata_is_allowlisted_and_bounded_without_losing_prompt_pins():
    names = ('run_id', 'case_id', 'application_revision', 'dataset', 'skill_hash',
        'generation_name', 'trace_name', 'evaluator_version', 'dataset_version', 'rubric_version',
        'judge_rubric_version', 'model', 'provider', 'variant', 'request_id', 'round_id', 'trace_id',
        'observation_id', 'job_id', 'checkpoint_id', 'contract_version', 'prompt_sha256',
        'schema_sha256', 'manifest_sha256')
    metadata = {name:'fixture-' + name for name in names}
    metadata['private_unknown_field'] = 'must-not-cross-boundary'
    captured = []
    def provider(request):
        captured.append(json.loads(request.content)['metadata'])
        return httpx.Response(200, content=sse(events('{"ok":true}')))
    asyncio.run(transport.stream_reply(**{**options(), 'metadata':metadata}, transport=httpx.MockTransport(provider)))
    assert len(captured[0]) <= 16 and 'private_unknown_field' not in captured[0]
    for key in ('prompt_sha256', 'schema_sha256', 'manifest_sha256'):
        assert captured[0][key] == metadata[key]


def test_fragmented_unicode_sse_stream_delivers_text_before_completion():
    sent = []
    text = '{"acknowledgement":"种豆子😀"}'
    class Fragmented(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index, event in enumerate(events(text)):
                if index:
                    assert sent == [text]
                for byte in sse([event]):
                    yield bytes([byte])
    async def delta(value):
        sent.append(value)
    provider = httpx.MockTransport(lambda request: httpx.Response(200, stream=Fragmented()))
    result, _ = asyncio.run(transport.stream_reply(**{**options(), 'on_delta':delta}, transport=provider))
    assert result == text and sent == [text]


def test_cache_key_is_stable_for_owner_and_separates_other_owners():
    keys = []
    def provider(request):
        keys.append(json.loads(request.content)['prompt_cache_key'])
        return httpx.Response(200, content=sse(events('{"ok":true}')))
    async def run():
        for owner in (1, 1, 2):
            from uuid import UUID
            fence = FENCE.model_copy(update={'identity':FENCE.identity.model_copy(update={'owner_id':UUID(int=owner)})})
            publisher = FakePublisher()
            publisher.current_fence = fence.model_dump(mode='json')
            await transport.stream_reply(**{**options(), 'fence':fence, 'publisher':publisher},
                                         transport=httpx.MockTransport(provider))
    asyncio.run(run())
    assert keys[0] == keys[1] and keys[0] != keys[2]


@pytest.mark.parametrize('values,error', [
    ([], CodexTurnIncomplete),
    ([dict(type='response.output_text.delta', delta='{"ok":')], CodexTurnIncomplete),
    (events('{"ok":true}', status='incomplete'), CodexTurnIncomplete),
    (events('{"ok":true}', final_text='{"ok":false}'), CodexTurnIncomplete),
    ([dict(type='response.failed')], RuntimeError),
    ([dict(type='error', message='private provider detail')], RuntimeError),
    (events('{"ok":true}', output=[dict(type='function_call', name='exec')]), CodexTurnIncomplete),
])
def test_incomplete_failed_and_mismatched_streams_never_succeed_or_retry(values, error):
    calls = []
    def provider(request):
        calls.append(True)
        return httpx.Response(200, content=sse(values))
    with pytest.raises(error):
        asyncio.run(transport.stream_reply(**options(), transport=httpx.MockTransport(provider)))
    assert len(calls) == 1


def test_tool_output_is_rejected_even_alongside_a_valid_message():
    output = [dict(type='function_call', name='exec'),
        dict(type='message', status='completed', content=[dict(type='output_text', text='{"ok":true}')])]
    provider = httpx.MockTransport(lambda request: httpx.Response(200, content=sse(events('{"ok":true}', output=output))))
    with pytest.raises(RuntimeError, match='unexpected tool'):
        asyncio.run(transport.stream_reply(**options(), transport=provider))


@pytest.mark.parametrize('fault', ['request_limit', 'response_limit', 'http', 'malformed'])
def test_provider_limits_and_failures_are_bounded(fault, monkeypatch):
    calls = []
    def provider(request):
        calls.append(True)
        if fault == 'http':
            return httpx.Response(502)
        return httpx.Response(200, content=b'data: not-json\n\n' if fault == 'malformed' else sse(events('{"ok":true}')))
    opts = options()
    if fault == 'request_limit':
        opts['budget'] = ContextBudget(model=BUDGET.model, context_window=1000,
            input_budget=100, output_headroom=100, framing_headroom=100)
    if fault == 'response_limit':
        monkeypatch.setattr(transport, 'MAX_RESPONSE_BYTES', 8)
    with pytest.raises((ValueError, RuntimeError, httpx.HTTPStatusError)):
        asyncio.run(transport.stream_reply(**opts, transport=httpx.MockTransport(provider)))
    assert len(calls) == (0 if fault == 'request_limit' else 1)


def test_actual_body_send_holds_fence_but_generation_does_not():
    class Publisher:
        held = False
        @asynccontextmanager
        async def guard(self, fence):
            assert fence == FENCE.model_dump(mode='json')
            self.held = True
            try:
                yield
            finally:
                self.held = False
    publisher = Publisher()
    class Provider(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            async for chunk in request.stream:
                assert publisher.held and chunk
            assert not publisher.held
            return httpx.Response(200, content=sse(events('{"ok":true}')))
    asyncio.run(transport.stream_reply(**{**options(), 'publisher':publisher}, transport=Provider()))
    assert not publisher.held


def test_abandoned_body_releases_publication_guard():
    held = []
    class Publisher:
        @asynccontextmanager
        async def guard(self, fence):
            held.append('entered')
            try:
                yield
            finally:
                held.append('released')
    async def run():
        body = transport.ReplyRequestBody(b'packet', publisher=Publisher(), fence=FENCE.model_dump(mode='json'))
        iterator = body.__aiter__()
        assert await anext(iterator) == b'packet'
        assert held == ['entered']
        await body.aclose()
        assert held == ['entered', 'released']
        with pytest.raises(RuntimeError, match='replayed'):
            body.__aiter__()
    asyncio.run(run())


def test_stale_fence_and_generation_pause_send_no_body(monkeypatch):
    from apps.api import lifetime_memory_lane_engine
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    calls = []
    async def run():
        class Publisher:
            @asynccontextmanager
            async def guard(self, fence):
                raise PublicationUnavailable('stale')
                yield
        body = transport.ReplyRequestBody(b'packet', publisher=Publisher(), fence=FENCE.model_dump(mode='json'))
        with pytest.raises(PublicationUnavailable):
            async for chunk in body:
                calls.append(chunk)
        def paused():
            raise lifetime_memory_lane_engine.LaneGenerationPaused('paused')
        monkeypatch.setattr(lifetime_memory_lane_engine, 'check_lane_generation', paused)
        body = transport.ReplyRequestBody(b'packet', publisher=FakePublisher(), fence=FENCE.model_dump(mode='json'))
        with pytest.raises(lifetime_memory_lane_engine.LaneGenerationPaused):
            async for chunk in body:
                calls.append(chunk)
    asyncio.run(run())
    assert calls == []


def test_deny_only_admission_blocks_before_contacting_provider():
    from uuid import uuid4
    admission = Issue14Admission.deny_only(run_id=str(uuid4()), source_revision='f'*40)
    calls = []
    with pytest.raises(AdmissionDenied):
        asyncio.run(transport.stream_reply(**{**options(), 'issue14_admission':admission},
            transport=httpx.MockTransport(lambda request: calls.append(request))))
    assert calls == []


def test_worker_uses_http_only_after_full_governed_validation(tmp_path, monkeypatch):
    from apps.api import codex_worker_service, lifetime_memory_engine
    from apps.api.conversation_reply import reply_instructions
    from test_conversation_reply import proposal
    from test_lifetime_memory_engine import IDENTITY, encode
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    monkeypatch.setenv('MEMOIR_TWO_LANES', '1')
    monkeypatch.setattr(lifetime_memory_engine, 'ProviderPublication', lambda *args, **kwargs: FakePublisher())
    def forbidden(*args, **kwargs):
        raise AssertionError('General Codex agent launched')
    monkeypatch.setattr(codex_worker_service, 'CodexConnection', forbidden)
    governed, context = fixture()
    context.update(reply_contract='reply-v2', two_lane_memory=True)
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        k:v for k,v in context.items() if k not in {'source', 'sources'}})
    captured = install_reply_provider(monkeypatch, [proposal()])
    worker = codex_worker_service.CodexWorker(home_root=tmp_path, model=BUDGET.model,
        base_url='https://provider.invalid/v1', api_key='fixture-secret-key')
    payload = codex_worker_service.WorkerTurnInput(user_id=IDENTITY.owner_id, project_id='p',
        model=BUDGET.model, governed=encode(packet), interview_context=context)
    result = asyncio.run(worker.turn(payload))
    assert json.loads(result['reply']) == proposal() and len(captured) == 1
    payload.interview_context['source']['version'] = 99
    with pytest.raises(ValueError):
        asyncio.run(worker.turn(payload))
    assert len(captured) == 1


def test_incomplete_http_retry_preserves_the_visible_acknowledgement(monkeypatch, tmp_path):
    from apps.api.conversation_reply import reply_instructions
    from apps.api.lifetime_memory_engine import run_governed_collector
    from test_conversation_reply import proposal
    from test_lifetime_memory_engine import encode
    governed, context = fixture()
    context.update(reply_contract='reply-v2', two_lane_memory=True)
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        k:v for k,v in context.items() if k not in {'source', 'sources'}})
    raw = json.dumps(proposal())
    prefix = raw[:raw.index(', "question"')]
    visible, requests = [], []
    class FirstStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse([dict(type='response.output_text.delta', delta=prefix)])
            assert visible == [json.dumps({'acknowledgement':proposal()['acknowledgement']}, ensure_ascii=False)]
            yield sse([dict(type='response.incomplete')])
    def provider(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, stream=FirstStream())
        assert body['text']['format']['schema']['properties']['acknowledgement']['enum'] == [proposal()['acknowledgement']]
        assert 'INCOMPLETE_PROVIDER_OUTPUT' in body['input'][0]['content'][1]['text']
        return httpx.Response(200, content=sse(events(raw)))
    original = transport.stream_reply
    async def send(**kwargs):
        return await original(**kwargs, transport=httpx.MockTransport(provider))
    async def delta(value):
        visible.append(value)
    monkeypatch.setattr(transport, 'stream_reply', send)
    result = asyncio.run(run_governed_collector(command=['forbidden-codex'], home_root=tmp_path,
        base_url='https://provider.invalid/v1', api_key='fixture-secret-key', model=BUDGET.model,
        governed=encode(packet), interview_context=context, on_delta=delta, publisher=FakePublisher()))
    assert json.loads(result['reply']) == proposal() and len(requests) == 2
    assert len(visible) == 1


def test_completed_invalid_json_uses_the_existing_validation_repair_budget(monkeypatch, tmp_path):
    from apps.api.conversation_reply import reply_instructions
    from apps.api.lifetime_memory_engine import run_governed_collector
    from test_conversation_reply import proposal
    from test_lifetime_memory_engine import encode
    governed, context = fixture()
    context.update(reply_contract='reply-v2', two_lane_memory=True)
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        k:v for k,v in context.items() if k not in {'source', 'sources'}})
    captured = install_reply_provider(monkeypatch, ['not json', 'still not json', proposal()])
    result = asyncio.run(run_governed_collector(command=['forbidden-codex'], home_root=tmp_path,
        base_url='https://provider.invalid/v1', api_key='fixture-secret-key', model=BUDGET.model,
        governed=encode(packet), interview_context=context, publisher=FakePublisher()))
    assert json.loads(result['reply']) == proposal() and len(captured) == 3
    assert 'INVALID_JSON' in captured[2]['input'][0]['content'][1]['text']


@pytest.mark.parametrize('code,expected', [
    ('CONTRACT_24', 'precise absolute offsets'),
    ('CONTRACT_09', 'not the negated alternative'),
    ('INVALID_JSON', 'Return valid JSON.'),
    ('INCOMPLETE_PROVIDER_OUTPUT', 'Return one complete structured object.'),
    ('SCHEMA_FIELD_work', 'typed schema'),
    ('SCHEMA_OR_OTHER_CONTRACT', 'typed schema'),
    ('UNKNOWN_CODE', 'typed schema'),
])
def test_repair_sends_only_relevant_rule_and_retains_catalog_provenance(monkeypatch, tmp_path, code, expected):
    from apps.api import lifetime_memory_engine as engine
    from apps.api.conversation_reply import reply_instructions
    from test_conversation_reply import proposal
    from test_lifetime_memory_engine import encode
    governed, context = fixture()
    context.update(reply_contract='reply-v2', two_lane_memory=True)
    packet = json.loads(governed.packet)
    packet.update(instructions=reply_instructions(), interview_context={
        key:value for key,value in context.items() if key not in {'source', 'sources'}})
    captured = install_reply_provider(monkeypatch, [proposal()])
    manifests = []
    original = engine.instruction_manifest
    def manifest(*args, **kwargs):
        value = original(*args, **kwargs)
        manifests.append(value)
        return value
    monkeypatch.setattr(engine, 'instruction_manifest', manifest)
    asyncio.run(engine._run_governed_collector_once(command=['forbidden-codex'], home_root=tmp_path,
        base_url='https://provider.invalid/v1', api_key='fixture-secret-key', model=BUDGET.model,
        governed=encode(packet), interview_context=context, publisher=FakePublisher(), repair_reason=code))
    prompt = captured[0]['input'][0]['content'][1]['text']
    assert code in prompt and expected in prompt
    assert 'CONTRACT_01' not in prompt
    assert ('CONTRACT_09' in prompt) == (code == 'CONTRACT_09')
    assert 'clear question evidence/candidate anchors' in prompt
    assert 'infer no unstated time/place links' in prompt
    assert len(prompt) < 1000
    assert any(item['name'] == 'memoir/skills/memoir-interviewer/repair-codes'
               for item in manifests[0]['artifacts'])
