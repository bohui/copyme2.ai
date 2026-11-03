"""Actual Codex binary, scripted loopback provider, two persistent interview turns."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import shutil
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.codex_agent import CodexConnection
from apps.api.conversation_reply import reply_packet
from apps.api.conversation_reply_session import open_interview
from apps.api.interview_context_tools import InterviewContextTools
from test_interview_native_session import admission, packets


@pytest.mark.skipif(not shutil.which('codex'), reason='Codex app-server is not installed')
@pytest.mark.parametrize('streamed', [False, True])
def test_native_deepseek_busy_response_does_not_repeat_until_timeout(tmp_path, streamed):
    requests = []
    first, _, _, _ = packets()
    class BusyProvider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(self.headers.get('x-litellm-num-retries'))
            wire = json.dumps(dict(error=dict(type='service_unavailable_error',
                code='service_unavailable_error', message='Service is too busy.'))).encode()
            if streamed:
                wire = ('data: ' + json.dumps(dict(type='error', code='server_error',
                    message='Service is too busy.')) + '\n\n').encode()
            self.send_response(200 if streamed else 503)
            self.send_header('Content-Type', 'text/event-stream' if streamed else 'application/json')
            self.send_header('Content-Length', str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)
    server = ThreadingHTTPServer(('127.0.0.1', 0), BusyProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    async def run():
        async with open_interview(root=tmp_path, packet=first, view=reply_packet(first),
            schema={'type': 'object'}, model='deepseek-v4.1-flash-1017', effort='low',
            base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key='synthetic-loopback-key',
            command=[shutil.which('codex'), 'app-server'], timeout=12,
            admission=admission, connection_factory=CodexConnection) as (session, connection):
            await connection.turn(session.thread_id, first.current.narrator.original)
    try:
        with pytest.raises((RuntimeError, TimeoutError)) as failure:
            asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert requests == ['0']
    assert not isinstance(failure.value, TimeoutError)
    assert not list(tmp_path.glob('.interview-*.json'))


@pytest.mark.skipif(not shutil.which('codex'), reason='Codex app-server is not installed')
@pytest.mark.parametrize('model', ['gpt-6.1-sol', 'deepseek-v4.1-flash-1017'])
@pytest.mark.parametrize('retrieval', [False, True])
def test_native_interview_preserves_the_model_prefix_across_process_restarts(tmp_path, retrieval, model):
    requests = []
    first, second, _, delivered = packets()
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.headers.get('Transfer-Encoding') == 'chunked':
                chunks = []
                while size := int(self.rfile.readline().strip(), 16):
                    chunks.append(self.rfile.read(size))
                    self.rfile.read(2)
                self.rfile.readline()
                raw = b''.join(chunks)
            else:
                raw = self.rfile.read(int(self.headers['Content-Length']))
            body = json.loads(raw)
            requests.append(body)
            ordinal = len(requests)
            item = dict(type='message', id=f'message-{ordinal}', role='assistant', status='completed',
                phase='final_answer', content=[dict(type='output_text', text=json.dumps({'reply': delivered}), annotations=[])])
            if retrieval and ordinal == 1:
                item = dict(type='function_call', id='read-context', call_id='read-context',
                    name='memoir_read_context', status='completed', arguments=json.dumps(dict(
                        collection='sources', after=None, query=None, event_id=None)))
            response = dict(id=f'resp-{ordinal}', object='response', status='completed',
                model='gpt-6.1-sol', output=[item], usage=dict(input_tokens=100, output_tokens=20, total_tokens=120))
            events = [dict(type='response.created', response={**response, 'status': 'in_progress', 'output': []}),
                dict(type='response.output_item.added', output_index=0, item=item),
                dict(type='response.output_item.done', output_index=0, item=item),
                dict(type='response.completed', response=response)]
            wire = ''.join('data: ' + json.dumps(event) + '\n\n' for event in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(wire)))
            self.end_headers()
            self.wfile.write(wire)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    schema = dict(type='object', properties=dict(reply=dict(type='string')), required=['reply'], additionalProperties=False)
    reads = []
    async def run():
        for index, packet in enumerate((first, second)):
            tools = InterviewContextTools(SimpleNamespace(), packet.fence)
            tools.read = AsyncMock(return_value={'records': [], 'complete': True})
            reads.append(tools.read)
            async with open_interview(root=tmp_path, packet=packet, view=reply_packet(packet), schema=schema,
                model=model, effort='low', base_url=f'http://127.0.0.1:{server.server_port}/v1',
                api_key='synthetic-loopback-key', command=[shutil.which('codex'), 'app-server'], timeout=20,
                admission=admission, connection_factory=CodexConnection, tools=tools) as (session, connection):
                assert session.resumed == bool(index)
                output = await connection.turn(session.thread_id, packet.current.narrator.original,
                    output_schema=schema, effort='low', max_response_bytes=4096)
                assert json.loads(output)['reply'] == delivered
                session.accept(delivered)
    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert len(requests) == (3 if retrieval else 2)
    assert requests[-1]['input'][:len(requests[0]['input'])] == requests[0]['input']
    assert requests[0]['text'] == requests[-1]['text']
    assert requests[0]['tools'] == requests[-1]['tools']
    assert requests[0].get('prompt_cache_key') == requests[-1].get('prompt_cache_key')
    assert sum(read.await_count for read in reads) == int(retrieval)
    messages = [item for item in requests[-1]['input'] if item.get('type') == 'message']
    assert any(item.get('role') == 'assistant' and delivered in json.dumps(item) for item in messages)
    assert sum(first.current.narrator.original in json.dumps(item) for item in messages) == 1


@pytest.mark.parametrize('streamed', [False, True])
def test_native_response_limit_counts_utf8_bytes_before_publication(streamed):
    class Protocol(CodexConnection):
        def __init__(self):
            self._issue14_admission = None
            self.events = []
            self.progress = self.trajectory = None
            self.timeout = 1

        async def request(self, method, params):
            return {'turn': {'id': 'turn'}}

        async def receive(self):
            params = dict(threadId='thread', turnId='turn')
            if streamed:
                return dict(method='item/agentMessage/delta', params={**params, 'itemId': 'message', 'delta': '你好'})
            return dict(method='item/completed', params={**params,
                'item': dict(type='agentMessage', id='message', text='你好', phase='final_answer')})
    delivered = AsyncMock()
    with pytest.raises(RuntimeError, match='byte limit'):
        asyncio.run(Protocol().turn('thread', 'A memory', on_delta=delivered, max_response_bytes=3))
    delivered.assert_not_awaited()
