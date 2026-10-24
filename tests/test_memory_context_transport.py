"""Direct JSON lane phases retain canonical packets and the HTTP boundary."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from uuid import UUID

import httpx
import pytest

from apps.api.background_profile import profile_packet
from apps.api.codex_agent import CodexTurnIncomplete
from apps.api.issue14_execution_admission import AdmissionDenied, Issue14Admission
from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input, lane_contract, run_bounded_lane
from apps.api.lifetime_memory_publication import PublicationUnavailable
from apps.api.lifetime_memory_summary import summary_packet
from test_background_profile import profile_page
from test_conversation_reply_transport import events, sse
from test_lifetime_memory_lane_engine import BUDGET, page, packet_for


PHASES = ['extract', 'profile', 'summarize', 'prepare', 'draft', 'review']


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.delenv('MEMOIR_LIFETIME_GENERATION_PAUSED', raising=False)


def bounded(phase):
    if phase in {'prepare', 'draft', 'review'}:
        current = page('composer')
        packet = packet_for(current, phase)
    elif phase == 'extract':
        current = page()
        packet = packet_for(current, phase)
    elif phase == 'profile':
        current = profile_page()
        packet = profile_packet(current)
    else:
        current = page()
        source = current['source']
        current['memory_summary'] = dict(maintenance_id=str(UUID(int=8)), revision=0,
            through_sequence=current['source_high_water'] - 1, sequence=source['sequence'],
            char_start=source['char_start'], char_end=source['char_end'], status='active',
            work_mode='extract', prior={'items': []})
        packet = summary_packet(current)
    return build_bounded_lane_input(current, phase=phase, packet=packet, budget=BUDGET)


class Publisher:
    def __init__(self):
        self.active = False
        self.stale = False
        self.fences = []

    @asynccontextmanager
    async def guard(self, fence):
        if self.stale:
            raise PublicationUnavailable('Stale profile authority')
        self.fences.append(deepcopy(fence))
        self.active = True
        try:
            yield
        finally:
            self.active = False


class Provider(httpx.AsyncBaseTransport):
    def __init__(self, publisher, output, before_body=None):
        self.publisher, self.output, self.before_body = publisher, output, before_body
        self.bodies = []

    async def handle_async_request(self, request):
        if self.before_body:
            self.before_body()
        raw = bytearray()
        async for chunk in request.stream:
            assert self.publisher.active
            raw.extend(chunk)
        assert not self.publisher.active
        assert len(raw) == int(request.headers['Content-Length'])
        self.bodies.append(json.loads(raw))
        return httpx.Response(200, content=sse(self.output))


def run(tmp_path, current, publisher, provider, **kwargs):
    return asyncio.run(run_bounded_lane(command=['must-not-start'], home_root=tmp_path / 'homes',
        base_url='https://provider.invalid/v1', api_key='fixture-memory-key', model=BUDGET.model,
        bounded_lane=current, publisher=publisher, provider_transport=provider, timeout=1, **kwargs))


@pytest.mark.parametrize('phase', PHASES)
def test_direct_calls_keep_prompt_packet_schema_effort_budget_and_actual_send_guard(tmp_path, phase):
    current = bounded(phase)
    publisher = Publisher()
    reply = json.dumps({'events': []} if phase == 'extract' else
        {'profile_patch': []} if phase == 'profile' else {'items': []})
    provider = Provider(publisher, events(reply))
    result = run(tmp_path, current, publisher, provider, effort='high')
    body, = provider.bodies
    instructions, schema = lane_contract(phase, current.fence.locale, fence=current.fence)
    assert body['instructions'] == instructions and body['input'] == current.packet
    assert body['text']['format']['schema'] == schema and body['text']['format']['strict']
    assert body['model'] == BUDGET.model and body['reasoning'] == {'effort': 'high', 'summary': 'auto'}
    assert body['max_output_tokens'] == BUDGET.output_headroom
    assert body['tools'] == [] and body['tool_choice'] == 'none' and not body['parallel_tool_calls']
    assert body['store'] is False and body['stream'] is True
    assert body['metadata']['generation_name'] == ('memoir-memory-context' if phase == 'profile'
        else 'memoir-author-timeline' if phase in {'extract', 'summarize'} else 'memoir-composer')
    assert all(len(body['metadata'][key]) == 64 for key in ('prompt_sha256', 'schema_sha256', 'manifest_sha256'))
    assert publisher.fences == [current.fence.model_dump(mode='json')]
    assert result == dict(thread_id='resp_gateway_id==', reply=reply, artifacts=[])
    assert not (tmp_path / 'homes').exists()


@pytest.mark.parametrize('phase', PHASES)
@pytest.mark.parametrize('fault', ['stale', 'issue14', 'paused_at_send'])
def test_unavailable_authority_releases_no_provider_body(tmp_path, monkeypatch, phase, fault):
    publisher = Publisher()
    callback = None
    kwargs = {}
    if fault == 'stale':
        publisher.stale = True
    elif fault == 'issue14':
        kwargs['issue14_admission'] = Issue14Admission.deny_only(run_id=str(UUID(int=9)), source_revision='a' * 40)
    else:
        callback = lambda: monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED', 'true')
    provider = Provider(publisher, events('{}'), callback)
    with pytest.raises((PublicationUnavailable, AdmissionDenied)):
        run(tmp_path, bounded(phase), publisher, provider, **kwargs)
    assert provider.bodies == [] and not publisher.active


@pytest.mark.parametrize('phase', PHASES)
@pytest.mark.parametrize('fault', ['incomplete', 'mismatch', 'tool', 'duplicate', 'credential', 'invalid_json'])
def test_partial_unsafe_or_non_json_output_cannot_return_a_proposal(tmp_path, phase, fault):
    publisher = Publisher()
    output = events('{}')
    if fault == 'incomplete':
        output = output[:1]
    elif fault == 'mismatch':
        output = events('{}', final_text='{"changed":true}')
    elif fault == 'tool':
        output[-1]['response']['output'].append(dict(type='function_call', name='web_search'))
    else:
        output = events({'duplicate': '{"items":[],"items":[]}', 'credential': 'fixture-memory-key',
            'invalid_json': 'not JSON'}[fault])
    provider = Provider(publisher, output)
    with pytest.raises((RuntimeError, ValueError, CodexTurnIncomplete)):
        run(tmp_path, bounded(phase), publisher, provider)
    assert len(provider.bodies) == 1 and not publisher.active


@pytest.mark.parametrize('phase', ['extract', 'profile', 'review'])
def test_cancelled_provider_stream_closes_without_a_native_session(tmp_path, phase):
    publisher = Publisher()
    current = bounded(phase)
    opened = asyncio.Event()
    closed = []

    class Waiting(httpx.AsyncByteStream):
        async def __aiter__(self):
            opened.set()
            await asyncio.Event().wait()
            yield b''

        async def aclose(self):
            closed.append(True)

    class Transport(Provider):
        async def handle_async_request(self, request):
            await super().handle_async_request(request)
            return httpx.Response(200, stream=Waiting())

    async def exercise():
        task = asyncio.create_task(run_bounded_lane(command=['must-not-start'], home_root=tmp_path / 'homes',
            base_url='https://provider.invalid/v1', api_key='fixture-memory-key', model=BUDGET.model,
            bounded_lane=current, publisher=publisher,
            provider_transport=Transport(publisher, events('{}')), timeout=10))
        await asyncio.wait_for(opened.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert closed and not publisher.active and not (tmp_path / 'homes').exists()


def test_direct_response_byte_budget_is_bounded(tmp_path):
    class Oversized(Provider):
        async def handle_async_request(self, request):
            await super().handle_async_request(request)
            return httpx.Response(200, content=b'x' * 2_000_001)

    publisher = Publisher()
    with pytest.raises(RuntimeError, match='exceeds its byte limit'):
        run(tmp_path, bounded('profile'), publisher, Oversized(publisher, events('{}')))
    assert not publisher.active
