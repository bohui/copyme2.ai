"""Disposable numeric-loopback HTTP only; no provider/config/credential reads."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
import json
import os
import time
from uuid import uuid4

import httpx
import pytest

from scripts.issue14_subscription_transport import (
    MAX_REQUEST_BYTES,
    SubscriptionLimits,
    SubscriptionRun,
    SubscriptionStopped,
    SubscriptionTransport,
)


def run(tmp_path, **changes):
    return SubscriptionRun.create(reservation_root=tmp_path, run_id=str(uuid4()),
        source_revision='0' * 40, limits=SubscriptionLimits(**{
            'max_requests': 10, 'max_elapsed_seconds': 5, **changes}))


def payload():
    # No token/currency cap; continuation metadata may legitimately repeat.
    return {'model': 'synthetic-model', 'input': [{'role': 'user', 'content': 'private 你好'}],
            'stream': True, 'previous_response_id': 'same-generation'}


def headers():
    return {'authorization': 'Bearer synthetic-token', 'content-type': 'application/json',
            'x-client-request-id': 'same-generation', 'x-codex-turn-state': 'same-turn'}


class Server:
    def __init__(self):
        self.contacts = []
        self.handlers = set()
        self.arrived = asyncio.Event()
        self.release = asyncio.Event()
        self.mode = 'ok'
        self.active = 0
        self.max_active = 0

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            head = await reader.readuntil(b'\r\n\r\n')
            lines = head.decode().split('\r\n')
            pairs = [line.split(':', 1) for line in lines[1:] if ':' in line]
            h = {key.lower(): value.strip() for key, value in pairs}
            body = await reader.readexactly(int(h['content-length']))
            self.contacts.append({'line': lines[0], 'headers': h, 'body': body})
            self.arrived.set()
            if self.mode == 'wait':
                await self.release.wait()
            if self.mode == 'disconnect':
                return
            if self.mode == 'redirect':
                wire = b'HTTP/1.1 307 Temporary Redirect\r\nLocation: /again\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
            elif self.mode == 'failure':
                wire = b'HTTP/1.1 500 Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
            elif self.mode in {'partial', 'partial_disconnect'}:
                wire = b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: 1000\r\nConnection: close\r\n\r\ndata: '
            else:
                data = b'data: {"type":"response.completed","response":{"id":"fixture"}}\n\n'
                wire = (b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: '
                        + str(len(data)).encode() + b'\r\nConnection: close\r\n\r\n' + data)
            writer.write(wire)
            await writer.drain()
            if self.mode == 'partial':
                await self.release.wait()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.active -= 1
            self.handlers.discard(task)


@asynccontextmanager
async def server():
    fixture = Server()
    listener = await asyncio.start_server(fixture.handle, '127.0.0.1', 0)
    fixture.endpoint = 'http://127.0.0.1:%d/v1/responses' % listener.sockets[0].getsockname()[1]
    try:
        yield fixture
    finally:
        fixture.release.set()
        listener.close()
        await listener.wait_closed()
        if fixture.handlers:
            await asyncio.gather(*tuple(fixture.handlers), return_exceptions=True)


@asynccontextmanager
async def client(ledger, fixture):
    transport = SubscriptionTransport.controlled(run=ledger, endpoint=fixture.endpoint)
    assert transport.endpoint == fixture.endpoint
    assert transport.run_id == ledger.run_id
    async with httpx.AsyncClient(transport=transport, follow_redirects=True, timeout=None) as value:
        yield value


@pytest.mark.parametrize('changes', [
    {'max_requests': 0}, {'max_requests': -1}, {'max_requests': True},
    {'max_requests': 1.5}, {'max_requests': 2**53},
    {'max_elapsed_seconds': 0}, {'max_elapsed_seconds': -1},
    {'max_elapsed_seconds': True}, {'max_elapsed_seconds': float('inf')},
    {'max_elapsed_seconds': float('nan')}, {'max_elapsed_seconds': '5'},
])
def test_limits_require_explicit_positive_finite_values(changes):
    with pytest.raises(ValueError):
        SubscriptionLimits(**{'max_requests': 2, 'max_elapsed_seconds': 5, **changes})


def test_limits_and_run_binding_are_immutable(tmp_path):
    ledger = run(tmp_path)
    with pytest.raises(FrozenInstanceError):
        ledger.limits.max_requests = 100
    with pytest.raises(AttributeError):
        ledger.limits = SubscriptionLimits(100, 100)
    with pytest.raises(AttributeError):
        ledger.deadline = ledger.deadline + 100
    ledger.close()


def test_default_constructor_has_no_live_activation():
    with pytest.raises((TypeError, SubscriptionStopped)):
        SubscriptionTransport()


def test_every_duplicate_and_continuation_counts_at_exact_wire_boundary(tmp_path):
    async def check():
        ledger = run(tmp_path, max_requests=2)
        async with server() as fixture, client(ledger, fixture) as session:
            for _ in range(2):
                result = await session.post(fixture.endpoint, json=payload(), headers=headers())
                assert result.status_code == 200
            for _ in range(2):
                with pytest.raises(SubscriptionStopped, match='requests_limit'):
                    await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 2
        receipt = ledger.snapshot()
        assert receipt['client_requests_reserved'] == 2
        assert receipt['completed_http_responses'] == 2
        assert receipt['unresolved_requests'] == 0
        assert receipt['counted_boundary'] == 'client_to_existing_gateway_http_requests'
        assert receipt['actual_upstream_provider_requests'] is None
        assert receipt['hard_token_cap_verified'] is False
        assert receipt['hard_dollar_cap_verified'] is False
        assert receipt['upstream_cancellation_verified'] is False
        assert receipt['restart_allowed'] is False
        journal = next(tmp_path.glob('*.jsonl')).read_text()
        for private in ('private', '你好', 'synthetic-token', 'same-generation', 'same-turn'):
            assert private not in journal
        events = [json.loads(line) for line in journal.splitlines()]
        assert [event['event'] for event in events].count('send_reserved') == 2
        assert events[1]['event'] == 'send_reserved'
        assert next(tmp_path.glob('*.jsonl')).stat().st_mode & 0o777 == 0o600
        ledger.close()
    asyncio.run(check())


def test_shared_gate_serializes_multiple_transports_and_queued_calls(tmp_path):
    async def check():
        ledger = run(tmp_path, max_requests=3)
        async with server() as fixture:
            fixture.mode = 'wait'
            async with client(ledger, fixture) as first, client(ledger, fixture) as second:
                sessions = [first, second, first, second]
                tasks = [asyncio.create_task(session.post(fixture.endpoint,
                    json=payload(), headers=headers())) for session in sessions]
                await fixture.arrived.wait()
                await asyncio.sleep(.04)
                assert len(fixture.contacts) == 1
                assert ledger.snapshot()['client_requests_reserved'] == 1
                fixture.release.set()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                assert sum(isinstance(item, httpx.Response) for item in results) == 3
                assert sum(isinstance(item, SubscriptionStopped) for item in results) == 1
                assert len(fixture.contacts) == 3
                assert fixture.max_active == 1
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('mode', ['disconnect', 'redirect', 'failure', 'partial_disconnect'])
def test_uncertain_http_failure_stops_all_future_contacts(tmp_path, mode):
    async def check():
        ledger = run(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            fixture.mode = mode
            for _ in range(2):
                with pytest.raises(SubscriptionStopped):
                    await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 1
            receipt = ledger.snapshot()
            assert receipt['client_requests_reserved'] == receipt['unresolved_requests'] == 1
            assert receipt['completed_http_responses'] == 0
            assert receipt['stop_reason']
        ledger.close()
    asyncio.run(check())


def test_active_cancellation_retains_reservation_and_stops_future_calls(tmp_path):
    async def check():
        ledger = run(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            fixture.mode = 'wait'
            task = asyncio.create_task(session.post(fixture.endpoint, json=payload(), headers=headers()))
            await fixture.arrived.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(SubscriptionStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 1
            assert ledger.snapshot()['unresolved_requests'] == 1
        ledger.close()
    asyncio.run(check())


def test_waiting_cancellation_stops_shared_run_without_a_second_contact(tmp_path):
    async def check():
        ledger = run(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            fixture.mode = 'wait'
            first = asyncio.create_task(session.post(fixture.endpoint, json=payload(), headers=headers()))
            await fixture.arrived.wait()
            second = asyncio.create_task(session.post(fixture.endpoint, json=payload(), headers=headers()))
            await asyncio.sleep(.02)
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            fixture.release.set()
            with pytest.raises(SubscriptionStopped):
                await first
            with pytest.raises(SubscriptionStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 1
            assert ledger.snapshot()['unresolved_requests'] == 1
        ledger.close()
    asyncio.run(check())


def test_deadline_before_dispatch_has_zero_contacts(tmp_path):
    async def check():
        ledger = run(tmp_path, max_elapsed_seconds=.02)
        await asyncio.sleep(.03)
        async with server() as fixture, client(ledger, fixture) as session:
            for _ in range(2):
                with pytest.raises(SubscriptionStopped, match='elapsed_limit'):
                    await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert fixture.contacts == []
        ledger.close()
    asyncio.run(check())


def test_absolute_deadline_covers_full_response_and_queued_waiters(tmp_path):
    async def check():
        ledger = run(tmp_path, max_elapsed_seconds=.15)
        async with server() as fixture, client(ledger, fixture) as session:
            fixture.mode = 'partial'
            first = asyncio.create_task(session.post(fixture.endpoint, json=payload(), headers=headers()))
            await fixture.arrived.wait()
            second = asyncio.create_task(session.post(fixture.endpoint, json=payload(), headers=headers()))
            results = await asyncio.gather(first, second, return_exceptions=True)
            assert all(isinstance(result, SubscriptionStopped) for result in results)
            assert len(fixture.contacts) == 1
            assert ledger.snapshot()['unresolved_requests'] == 1
            assert ledger.snapshot()['stop_reason'] == 'elapsed_limit'
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('when', ['reserve', 'complete'])
def test_journal_failure_retains_uncertainty_and_restart_fence(tmp_path, monkeypatch, when):
    async def check():
        ledger = run(tmp_path)
        real_fsync = os.fsync
        writes = 0
        def fail(fd):
            nonlocal writes
            writes += 1
            if writes == (1 if when == 'reserve' else 2):
                raise OSError('synthetic private filesystem failure')
            return real_fsync(fd)
        monkeypatch.setattr(os, 'fsync', fail)
        async with server() as fixture, client(ledger, fixture) as session:
            for _ in range(2):
                with pytest.raises(SubscriptionStopped, match='journal_unavailable'):
                    await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == (0 if when == 'reserve' else 1)
            assert ledger.snapshot()['unresolved_requests'] == 1
            assert ledger.snapshot()['journal_durable'] is False
        with pytest.raises(SubscriptionStopped, match='reservation_exists'):
            SubscriptionRun.create(reservation_root=tmp_path, run_id=ledger.run_id,
                source_revision='0' * 40, limits=ledger.limits)
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('change', ['url', 'method', 'authorization', 'duplicate_authorization', 'transfer_encoding'])
def test_invalid_final_target_or_headers_never_contact(tmp_path, change):
    async def check():
        ledger = run(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            request = session.build_request('POST', fixture.endpoint, json=payload(), headers=headers())
            if change == 'url':
                request.url = httpx.URL(fixture.endpoint + '?unexpected=1')
            elif change == 'method':
                request.method = 'GET'
            elif change == 'authorization':
                request.headers['authorization'] = 'Bearer different'
            elif change == 'duplicate_authorization':
                request.headers = httpx.Headers([*request.headers.raw, (b'authorization', b'Bearer synthetic-token')])
            else:
                request.headers['transfer-encoding'] = 'chunked'
            with pytest.raises(SubscriptionStopped):
                await session.send(request)
            assert fixture.contacts == []
            assert ledger.snapshot()['client_requests_reserved'] == 0
        ledger.close()
    asyncio.run(check())


def test_private_request_freezes_mutated_fields_and_drops_caller_extensions(tmp_path):
    async def check():
        ledger = run(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            raw = json.dumps(payload()).encode()
            request = session.build_request('POST', fixture.endpoint, content=raw, headers=headers())
            trace_called = False
            async def trace(*args):
                nonlocal trace_called
                trace_called = True
                raise AssertionError('caller hook must not reach private transport')
            class MutatingBody(httpx.AsyncByteStream):
                async def __aiter__(self):
                    request.url = httpx.URL('http://127.0.0.1:1/forbidden')
                    request.method = 'DELETE'
                    request.headers['authorization'] = 'Bearer altered'
                    request.headers['host'] = 'forbidden.example'
                    request.extensions['trace'] = trace
                    request.extensions['sni_hostname'] = 'forbidden.example'
                    request.extensions['timeout'] = {'connect': 10000}
                    yield raw
            request.stream = MutatingBody()
            request.extensions['trace'] = trace
            result = await session.send(request)
            assert result.status_code == 200
            assert trace_called is False
            assert len(fixture.contacts) == 1
            contact = fixture.contacts[0]
            assert contact['line'] == 'POST /v1/responses HTTP/1.1'
            assert contact['headers']['authorization'] == 'Bearer synthetic-token'
            assert contact['body'] == raw
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('kind', ['mutable', 'oversize', 'invalid_json', 'duplicate_json', 'array', 'stream_failure'])
def test_invalid_body_never_contacts_and_permanently_stops(tmp_path, kind):
    async def check():
        ledger = run(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            raw = json.dumps(payload()).encode()
            if kind == 'oversize':
                raw = b' ' * (MAX_REQUEST_BYTES + 1)
            elif kind == 'invalid_json':
                raw = b'{'
            elif kind == 'duplicate_json':
                raw = b'{"model":"one","model":"two"}'
            elif kind == 'array':
                raw = b'[]'
            request = session.build_request('POST', fixture.endpoint, content=raw, headers=headers())
            if kind in {'mutable', 'stream_failure'}:
                class BadBody(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        if kind == 'stream_failure':
                            raise RuntimeError('private stream failure')
                        yield bytearray(raw)
                request.stream = BadBody()
            with pytest.raises(SubscriptionStopped):
                await session.send(request)
            with pytest.raises(SubscriptionStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert fixture.contacts == []
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('endpoint', ['http://localhost:4000/v1/responses',
    'http://192.168.66.1:4000/v1/responses', 'http://127.0.0.1/v1/responses',
    'http://127.0.0.1:4000/v1/responses?x=1', 'https://127.0.0.1:4000/v1/responses',
    'http://user@127.0.0.1:4000/v1/responses'])
def test_controlled_constructor_accepts_only_numeric_disposable_loopback(tmp_path, endpoint):
    ledger = run(tmp_path)
    with pytest.raises(SubscriptionStopped, match='target_forbidden'):
        SubscriptionTransport.controlled(run=ledger, endpoint=endpoint)
    ledger.close()


def test_transport_close_does_not_reset_shared_counter(tmp_path):
    async def check():
        ledger = run(tmp_path, max_requests=1)
        async with server() as fixture:
            async with client(ledger, fixture) as first:
                await first.post(fixture.endpoint, json=payload(), headers=headers())
            async with client(ledger, fixture) as second:
                with pytest.raises(SubscriptionStopped, match='requests_limit'):
                    await second.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 1
        ledger.close()
        with pytest.raises(SubscriptionStopped, match='reservation_exists'):
            SubscriptionRun.create(reservation_root=tmp_path, run_id=ledger.run_id,
                source_revision='0' * 40, limits=ledger.limits)
    asyncio.run(check())


def test_exhausted_run_does_not_read_another_caller_body(tmp_path):
    async def check():
        ledger = run(tmp_path, max_requests=1)
        async with server() as fixture, client(ledger, fixture) as session:
            await session.post(fixture.endpoint, json=payload(), headers=headers())
            touched = False
            class Body(httpx.AsyncByteStream):
                async def __aiter__(self):
                    nonlocal touched
                    touched = True
                    yield b'{}'
            request = session.build_request('POST', fixture.endpoint, content=b'{}', headers=headers())
            request.stream = Body()
            with pytest.raises(SubscriptionStopped, match='requests_limit'):
                await session.send(request)
            assert touched is False
            assert len(fixture.contacts) == 1
        ledger.close()
    asyncio.run(check())


def test_body_buffering_consumes_original_deadline(tmp_path):
    async def check():
        ledger = run(tmp_path, max_elapsed_seconds=.06)
        async with server() as fixture, client(ledger, fixture) as session:
            class SlowBody(httpx.AsyncByteStream):
                async def __aiter__(self):
                    await asyncio.sleep(.2)
                    yield b'{}'
            request = session.build_request('POST', fixture.endpoint, content=b'{}', headers=headers())
            request.stream = SlowBody()
            with pytest.raises(SubscriptionStopped, match='elapsed_limit'):
                await session.send(request)
            assert fixture.contacts == []
            assert ledger.snapshot()['client_requests_reserved'] == 0
        ledger.close()
    asyncio.run(check())


def test_durable_reservation_delay_cannot_extend_deadline_or_contact(tmp_path, monkeypatch):
    async def check():
        ledger = run(tmp_path, max_elapsed_seconds=.08)
        fsync = os.fsync
        def slow_fsync(fd):
            time.sleep(.1)
            return fsync(fd)
        monkeypatch.setattr(os, 'fsync', slow_fsync)
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(SubscriptionStopped, match='elapsed_limit'):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert fixture.contacts == []
            snapshot = ledger.snapshot()
            assert snapshot['client_requests_reserved'] == 1
            assert snapshot['client_requests_started'] == 0
            assert snapshot['unresolved_requests'] == 1
        ledger.close()
    asyncio.run(check())


def test_directory_durability_failure_still_fences_restart(tmp_path, monkeypatch):
    run_id = str(uuid4())
    fsync = os.fsync
    calls = 0
    def fail_directory(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('synthetic directory durability failure')
        return fsync(fd)
    monkeypatch.setattr(os, 'fsync', fail_directory)
    for reason in ('journal_unavailable', 'reservation_exists'):
        with pytest.raises(SubscriptionStopped, match=reason):
            SubscriptionRun.create(reservation_root=tmp_path, run_id=run_id,
                source_revision='0' * 40, limits=SubscriptionLimits(1, 1))


def test_partial_journal_write_stops_without_contact(tmp_path, monkeypatch):
    async def check():
        ledger = run(tmp_path)
        write = os.write
        calls = 0
        def partial(fd, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                return write(fd, data[:7])
            raise OSError('synthetic private write failure')
        monkeypatch.setattr(os, 'write', partial)
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(SubscriptionStopped, match='journal_unavailable'):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert fixture.contacts == []
            assert ledger.snapshot()['unresolved_requests'] == 1
        with pytest.raises(SubscriptionStopped, match='reservation_exists'):
            SubscriptionRun.create(reservation_root=tmp_path, run_id=ledger.run_id,
                source_revision='0' * 40, limits=ledger.limits)
        ledger.close()
    asyncio.run(check())


def test_cancellation_is_preserved_when_stop_journaling_fails(tmp_path, monkeypatch):
    async def check():
        ledger = run(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            fixture.mode = 'wait'
            task = asyncio.create_task(session.post(fixture.endpoint, json=payload(), headers=headers()))
            await fixture.arrived.wait()
            def fail(fd):
                raise OSError('synthetic journal unavailable during cancellation')
            monkeypatch.setattr(os, 'fsync', fail)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(SubscriptionStopped, match='journal_unavailable'):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 1
            assert ledger.snapshot()['unresolved_requests'] == 1
            assert ledger.snapshot()['journal_durable'] is False
        ledger.close()
    asyncio.run(check())


def test_proxy_environment_is_not_used(tmp_path, monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('ALL_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('NO_PROXY', '')
    async def check():
        ledger = run(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            assert (await session.post(fixture.endpoint, json=payload(), headers=headers())).status_code == 200
            assert len(fixture.contacts) == 1
        ledger.close()
    asyncio.run(check())
