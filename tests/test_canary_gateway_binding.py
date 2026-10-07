"""Actual loopback HTTP contacts, with synthetic credentials only."""
import asyncio
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.canary_send_guard import CanarySendGuard, CanaryStopped


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def completed():
    return 'data: ' + json.dumps({'type': 'response.completed', 'response': {
        'id': 'resp_test', 'model': 'gpt-5.6-luna',
        'usage': {'input_tokens': 3, 'output_tokens': 2}}}) + '\n\n'


@contextmanager
def server(*, status=200, body=None, location=None):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream')
            if location:
                self.send_header('Location', location)
            raw = (completed() if body is None else body).encode()
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}/codex/responses', seen
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


def guard_at(tmp_path, **kwargs):
    return CanarySendGuard(reservation=tmp_path / 'guard.jsonl', run_id=str(uuid4()),
        source_revision='291622826cdfb776e946dcd92b65d2fdaf4923ad',
        account_binding=digest('selected-row'), model='gpt-5.6-luna', **kwargs)


def test_final_http_boundary_counts_calls_and_blocks_exhausted_before_contact(tmp_path):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    with server() as (endpoint, seen):
        async def run():
            async with guard_at(tmp_path, maximum_requests=1) as guard:
                async with GuardedHTTPSession.controlled(guard=guard, endpoint=endpoint,
                        account_id='selected-upstream', access_token='synthetic-secret') as session:
                    for index in range(2):
                        cm = session.post(endpoint, json={'model': 'gpt-5.6-luna', 'stream': True},
                            headers={'Authorization': 'Bearer synthetic-secret',
                                'ChatGPT-Account-ID': 'selected-upstream'})
                        if index == 1:
                            with pytest.raises(CanaryStopped, match='request_limit'):
                                async with cm:
                                    pytest.fail('Exhausted request entered')
                        else:
                            async with cm as response:
                                assert response.status == 200
                                chunks = [c async for c in response.content.iter_chunked(17)]
                                assert b''.join(chunks).decode() == completed()
                            assert guard.receipt()['completed'] == 1
                assert guard.receipt()['guarded_send_entries'] == 1
        asyncio.run(run())
        assert len(seen) == 1
    assert 'synthetic-secret' not in (tmp_path / 'guard.jsonl').read_text()


@pytest.mark.parametrize('change', ['url', 'account', 'auth', 'duplicate_auth', 'model', 'tools', 'photo'])
def test_binding_mismatch_is_terminal_and_makes_zero_contacts(tmp_path, change):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    with server() as (endpoint, seen):
        async def run():
            async with guard_at(tmp_path) as guard:
                async with GuardedHTTPSession.controlled(guard=guard, endpoint=endpoint,
                        account_id='selected-upstream', access_token='synthetic-secret') as session:
                    url = endpoint
                    headers = {'Authorization': 'Bearer synthetic-secret', 'ChatGPT-Account-ID': 'selected-upstream'}
                    payload = {'model': 'gpt-5.6-luna', 'stream': True}
                    if change == 'url': url += '/compact'
                    if change == 'account': headers['ChatGPT-Account-ID'] = 'another-account'
                    if change == 'auth': headers['Authorization'] = 'Bearer different-secret'
                    if change == 'duplicate_auth': headers['authorization'] = 'Bearer different-secret'
                    if change == 'model': payload['model'] = 'other'
                    if change == 'tools': payload['tools'] = [{'type': 'web_search'}]
                    if change == 'photo': payload['input'] = [{'content': [{'type': 'input_image', 'image_url': 'https://example.com/a.png'}]}]
                    with pytest.raises(CanaryStopped):
                        async with session.post(url, json=payload, headers=headers):
                            pass
                    with pytest.raises(CanaryStopped):
                        async with session.post(endpoint, json={'model': 'gpt-5.6-luna'}, headers={
                                'Authorization': 'Bearer synthetic-secret', 'ChatGPT-Account-ID': 'selected-upstream'}):
                            pass
                assert guard.receipt()['guarded_send_entries'] == 0
        asyncio.run(run())
        assert seen == []


@pytest.mark.parametrize('status,body', [(307, None), (500, None), (200, 'data: {"type":"response.failed"}\n\n'), (200, '')])
def test_redirects_and_provider_failure_never_retry(tmp_path, status, body):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    with server() as (target, target_seen), server(status=status, body=body, location=target) as (endpoint, seen):
        async def run():
            async with guard_at(tmp_path) as guard:
                async with GuardedHTTPSession.controlled(guard=guard, endpoint=endpoint,
                        account_id='selected-upstream', access_token='synthetic-secret') as session:
                    for _ in range(2):
                        with pytest.raises(CanaryStopped):
                            async with session.post(endpoint, json={'model': 'gpt-5.6-luna', 'stream': True},
                                    headers={'Authorization': 'Bearer synthetic-secret', 'ChatGPT-Account-ID': 'selected-upstream'}):
                                pass
                assert guard.receipt()['guarded_send_entries'] == 1
        asyncio.run(run())
        assert len(seen) == 1
        assert target_seen == []


def test_all_unsupported_session_dispatchers_fail_before_contact(tmp_path):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    async def run():
        async with guard_at(tmp_path) as guard:
            async with GuardedHTTPSession.controlled(guard=guard,
                    endpoint='http://127.0.0.1:12345/codex/responses',
                    account_id='selected-upstream', access_token='synthetic-secret') as session:
                for name in ('get', 'request', 'ws_connect'):
                    with pytest.raises(CanaryStopped):
                        getattr(session, name)('http://127.0.0.1:12345/forbidden')
            assert guard.receipt()['guarded_send_entries'] == 0
    asyncio.run(run())


def test_production_session_rejects_loopback_and_unapproved_upstream(tmp_path):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    async def run():
        async with guard_at(tmp_path) as guard:
            for endpoint in ('http://127.0.0.1:12345/codex/responses', 'https://example.com/codex/responses'):
                with pytest.raises(ValueError):
                    GuardedHTTPSession(guard=guard, endpoint=endpoint,
                        account_id='selected-upstream', access_token='synthetic-secret')
    asyncio.run(run())


def fake_gateway(tmp_path, request_ids, *, callback=None):
    async def original(payload, headers, access_token, account_id, **kwargs):
        assert kwargs['upstream_stream_transport_override'] == 'http'
        if callback:
            callback(kwargs)
        yield 'installed-path-called'
    core = SimpleNamespace(stream_responses=original, get_request_id=lambda: request_ids.pop(0),
        format_sse_event=lambda value: 'data: ' + json.dumps(value) + '\n\n',
        response_failed_event=lambda code, message, **kwargs: {'type': 'response.failed',
            'response': {'id': kwargs['response_id'], 'status': 'failed',
                'error': {'code': code, 'message': message, 'type': kwargs['error_type']}}},
        get_settings=lambda: SimpleNamespace(upstream_base_url='https://chatgpt.com/backend-api'))
    service = SimpleNamespace(core_stream_responses=original,
        _ACCOUNT_RECOVERY_RETRY_CODES=frozenset({'other'}),
        _TRANSIENT_RETRY_CODES=frozenset({'transient'}),
        _should_retry_stream_error=lambda code: code == 'other',
        _should_penalize_stream_error=lambda code: code in {'other', 'transient'},
        _rewrite_previous_response_stream_error=lambda **kwargs: None if kwargs.get('error_code') == 'canary_guard_stopped' else ('rewritten',))
    return core, service


def test_installed_binding_rejects_replay_and_account_failover_before_core(tmp_path):
    from scripts.canary_gateway_binding import InstalledGatewayBinding
    called = []
    async def run():
        async with guard_at(tmp_path) as guard:
            core, service = fake_gateway(tmp_path, ['request-1', 'request-1'], callback=called.append)
            binding = InstalledGatewayBinding(guard=guard, core=core, service=service)
            payload = SimpleNamespace(to_payload=lambda: {'model': 'gpt-5.6-luna', 'stream': True})
            args = (payload, {}, 'synthetic-token', 'selected-upstream')
            binding._seen_requests.add('request-1')
            output = [x async for x in binding.stream_responses(*args, codex_lb_account_id='selected-row')]
            assert 'canary_guard_stopped' in ''.join(output)
            assert guard.stop_reason == 'gateway_replay_forbidden'
        assert len(called) == 0
    asyncio.run(run())


@pytest.mark.parametrize('options', [dict(codex_lb_account_id='wrong-row'), dict(route=object()),
    dict(codex_client=object()), dict(upstream_stream_transport_override='websocket'), dict(session=object())])
def test_installed_binding_rejects_uncovered_paths_before_core(tmp_path, options):
    from scripts.canary_gateway_binding import InstalledGatewayBinding
    called = []
    async def run():
        async with guard_at(tmp_path) as guard:
            core, service = fake_gateway(tmp_path, ['request-1'], callback=called.append)
            binding = InstalledGatewayBinding(guard=guard, core=core, service=service)
            payload = SimpleNamespace(to_payload=lambda: {'model': 'gpt-5.6-luna', 'stream': True})
            args = dict(codex_lb_account_id='selected-row')
            args.update(options)
            output = [x async for x in binding.stream_responses(payload, {}, 'synthetic-token',
                'selected-upstream', **args)]
            assert 'canary_guard_stopped' in ''.join(output)
            assert guard.stop_reason
        assert called == []
    asyncio.run(run())


def test_binding_installation_requires_exact_audited_files_and_does_not_patch_on_mismatch(tmp_path):
    from scripts.canary_gateway_binding import InstalledGatewayBinding
    async def run():
        async with guard_at(tmp_path) as guard:
            core, service = fake_gateway(tmp_path, ['request-1'])
            core.__file__ = str(tmp_path / 'missing.py')
            service.__file__ = str(tmp_path / 'also-missing.py')
            original = service.core_stream_responses
            binding = InstalledGatewayBinding(guard=guard, core=core, service=service)
            with pytest.raises(CanaryStopped, match='gateway_source_mismatch'):
                with binding.install():
                    pytest.fail('Unverified source installed')
            assert service.core_stream_responses is original
    asyncio.run(run())


def test_final_boundary_serializes_competing_calls(tmp_path):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    with server() as (endpoint, seen):
        async def run():
            async with guard_at(tmp_path, maximum_requests=1) as guard:
                async with GuardedHTTPSession.controlled(guard=guard, endpoint=endpoint,
                        account_id='selected-upstream', access_token='synthetic-secret') as session:
                    async def request():
                        async with session.post(endpoint, json={'model': 'gpt-5.6-luna', 'stream': True},
                                headers={'Authorization': 'Bearer synthetic-secret', 'ChatGPT-Account-ID': 'selected-upstream'}):
                            return 'completed'
                    results = await asyncio.gather(request(), request(), return_exceptions=True)
                    assert results[0] == 'completed'
                    assert isinstance(results[1], CanaryStopped)
                    assert guard.receipt()['guarded_send_entries'] == 1
        asyncio.run(run())
        assert len(seen) == 1


def test_unobserved_core_dispatch_cannot_report_success(tmp_path):
    from scripts.canary_gateway_binding import InstalledGatewayBinding
    async def run():
        async with guard_at(tmp_path) as guard:
            core, service = fake_gateway(tmp_path, ['request-1'])
            binding = InstalledGatewayBinding(guard=guard, core=core, service=service)
            payload = SimpleNamespace(to_payload=lambda: {'model': 'gpt-5.6-luna', 'stream': True})
            output = [x async for x in binding.stream_responses(payload, {}, 'synthetic-token',
                'selected-upstream', codex_lb_account_id='selected-row')]
            assert 'canary_guard_stopped' in ''.join(output)
            assert guard.stop_reason == 'gateway_boundary_unobserved'
            assert guard.receipt()['completed'] == 0
    asyncio.run(run())


def test_runtime_token_is_redacted_from_completed_sse_and_headers(tmp_path):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    raw = completed().replace('"response": {', '"response": {"output_text": "synthetic-secret",')
    with server(body=raw) as (endpoint, seen):
        async def run():
            async with guard_at(tmp_path) as guard:
                async with GuardedHTTPSession.controlled(guard=guard, endpoint=endpoint,
                        account_id='selected-upstream', access_token='synthetic-secret') as session:
                    async with session.post(endpoint, json={'model': 'gpt-5.6-luna', 'stream': True},
                            headers={'Authorization': 'Bearer synthetic-secret', 'ChatGPT-Account-ID': 'selected-upstream'}) as response:
                        body = b''.join([c async for c in response.content.iter_chunked(65536)]).decode()
                        assert 'synthetic-secret' not in body
                        assert '[REDACTED]' in body
                    assert guard.receipt()['completed'] == 1
        asyncio.run(run())


def test_binding_installs_restores_only_owned_process_exports(tmp_path, monkeypatch):
    from scripts.canary_gateway_binding import InstalledGatewayBinding
    async def run():
        async with guard_at(tmp_path) as guard:
            core, service = fake_gateway(tmp_path, ['request-1'])
            original = core.stream_responses
            names = ['compact_responses', 'codex_control_request', 'thread_goal_request', 'transcribe_audio']
            other_names = ['core_compact_responses', 'core_codex_control_request', 'core_thread_goal_request',
                'core_transcribe_audio', 'core_create_file', 'core_finalize_file',
                'connect_live_websocket', 'connect_responses_websocket']
            sentinel = object()
            for name in names: setattr(core, name, sentinel)
            for name in other_names: setattr(service, name, sentinel)
            binding = InstalledGatewayBinding(guard=guard, core=core, service=service)
            monkeypatch.setattr(binding, '_verify_sources', lambda: None)
            with binding.install():
                assert core.stream_responses is service.core_stream_responses
                assert core.stream_responses is not original
                assert service._should_retry_stream_error('canary_guard_stopped') is False
                assert service._should_penalize_stream_error('canary_guard_stopped') is False
                assert service._rewrite_previous_response_stream_error(error_code='canary_guard_stopped') is None
                assert service._should_retry_stream_error('other') is True
                assert service._should_penalize_stream_error('other') is True
                assert service._rewrite_previous_response_stream_error(error_code='other') == ('rewritten',)
                with pytest.raises(CanaryStopped, match='gateway_dispatch_forbidden'):
                    service.connect_responses_websocket()
            assert core.stream_responses is original
            assert service.core_stream_responses is original
            assert all(getattr(core, name) is sentinel for name in names)
            assert all(getattr(service, name) is sentinel for name in other_names)
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['timeout', 'cancel'])
def test_actual_http_stall_closes_connection_and_cannot_replay(tmp_path, mode):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    async def run():
        entered, disconnected = asyncio.Event(), asyncio.Event()
        contacts = []
        async def handler(reader, writer):
            try:
                headers = await reader.readuntil(b'\r\n\r\n')
                length = next(int(line.split(b':', 1)[1]) for line in headers.split(b'\r\n')
                    if line.lower().startswith(b'content-length:'))
                await reader.readexactly(length)
                contacts.append(1)
                entered.set()
                assert await reader.read() == b''
                disconnected.set()
            finally:
                writer.close()
                await writer.wait_closed()
        server = await asyncio.start_server(handler, '127.0.0.1', 0)
        endpoint = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/codex/responses'
        try:
            async with guard_at(tmp_path, request_seconds=.2) as guard:
                async with GuardedHTTPSession.controlled(guard=guard, endpoint=endpoint,
                        account_id='selected-upstream', access_token='synthetic-secret') as session:
                    async def request():
                        async with session.post(endpoint, json={'model': 'gpt-5.6-luna', 'stream': True},
                                headers={'Authorization': 'Bearer synthetic-secret', 'ChatGPT-Account-ID': 'selected-upstream'}):
                            pytest.fail('Stalled response was released')
                    task = asyncio.create_task(request())
                    await asyncio.wait_for(entered.wait(), 2)
                    if mode == 'cancel':
                        await guard.aclose()
                        with pytest.raises(asyncio.CancelledError):
                            await task
                    else:
                        with pytest.raises(CanaryStopped):
                            await task
                    await asyncio.wait_for(disconnected.wait(), 2)
                    with pytest.raises(CanaryStopped):
                        await request()
                    assert guard.receipt()['guarded_send_entries'] == 1
                    assert guard.receipt()['completed'] == 0
            assert len(contacts) == 1
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_binding_receipt_readiness_and_stop_do_not_claim_native_verification(tmp_path):
    from scripts.canary_gateway_binding import InstalledGatewayBinding
    async def run():
        guard = guard_at(tmp_path)
        core, service = fake_gateway(tmp_path, ['request-1'])
        binding = InstalledGatewayBinding(guard=guard, core=core, service=service)
        state = binding.readiness()
        assert state['accepting_requests'] is False
        assert state['sources_verified'] is False
        assert state['native_actor_verified'] is False
        assert state['live_ready'] is False
        receipt = await binding.stop()
        assert receipt['boundary_verified'] is False
        assert receipt['cleanup']['closed'] is True
        assert receipt['guarded_send_entries'] == 0
        assert receipt['binding']['stop_reason'] == 'closed'
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['failed_status', 'error_object', 'incomplete_details',
    'error_before_completion', 'error_after_completion',
    'named_error_before_completion', 'named_error_after_completion', 'conflicting_event_name'])
def test_quota_error_and_contradictory_completion_stop_actual_http_replay(tmp_path, failure):
    from scripts.canary_gateway_binding import GuardedHTTPSession
    event = json.loads(completed().removeprefix('data: ').strip())
    quota = {'code': 'usage_limit_reached', 'message': 'synthetic-private-error'}
    if failure == 'failed_status': event['response']['status'] = 'failed'
    if failure == 'error_object': event['response']['error'] = quota
    if failure == 'incomplete_details': event['response']['incomplete_details'] = {'reason': 'max_output_tokens'}
    raw = 'data: ' + json.dumps(event) + '\n\n'
    envelope = 'data: ' + json.dumps({'error': quota}) + '\n\n'
    if failure == 'named_error_before_completion': raw = 'event: error\ndata: ' + json.dumps(quota) + '\n\n' + raw
    if failure == 'named_error_after_completion': raw += 'event: error\ndata: ' + json.dumps(quota) + '\n\n'
    if failure == 'conflicting_event_name': raw = 'event: response.failed\n' + raw
    if failure == 'error_before_completion': raw = envelope + raw
    if failure == 'error_after_completion': raw += envelope
    with server(body=raw) as (endpoint, seen):
        async def run():
            async with guard_at(tmp_path) as guard:
                async with GuardedHTTPSession.controlled(guard=guard, endpoint=endpoint,
                        account_id='selected-upstream', access_token='synthetic-secret') as session:
                    for _ in range(2):
                        with pytest.raises(CanaryStopped):
                            async with session.post(endpoint, json={'model': 'gpt-5.6-luna', 'stream': True},
                                    headers={'Authorization': 'Bearer synthetic-secret', 'ChatGPT-Account-ID': 'selected-upstream'}):
                                pytest.fail('Contradictory completion was returned')
                assert guard.receipt()['guarded_send_entries'] == 1
                assert guard.receipt()['completed'] == 0
                assert guard.stop_reason == 'upstream_failed_or_incomplete'
        asyncio.run(run())
        assert len(seen) == 1
    assert 'synthetic-private-error' not in (tmp_path / 'guard.jsonl').read_text()


def test_unexpected_pre_dispatch_validation_failure_is_terminal_sse(tmp_path):
    from scripts.canary_gateway_binding import InstalledGatewayBinding
    async def run():
        async with guard_at(tmp_path) as guard:
            core, service = fake_gateway(tmp_path, ['request-1'])
            binding = InstalledGatewayBinding(guard=guard, core=core, service=service)
            def bad_payload(): raise ValueError('synthetic-private-validation-text')
            output = [x async for x in binding.stream_responses(SimpleNamespace(to_payload=bad_payload),
                {}, 'synthetic-token', 'selected-upstream', codex_lb_account_id='selected-row')]
            assert len(output) == 1 and 'response.failed' in output[0]
            assert 'synthetic-private-validation-text' not in output[0]
            assert guard.stop_reason == 'upstream_failed_or_incomplete'
            assert guard.receipt()['guarded_send_entries'] == 0
    asyncio.run(run())
