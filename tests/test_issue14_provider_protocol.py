"""Real disposable HTTP server; no provider credentials or external model calls."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
import sys
from uuid import uuid4

import httpx
import pytest

from scripts.issue14_provider_budget import BudgetStopped, Limits, ProviderBudget
from scripts.issue14_provider_transport import ControlledBudgetTransport


def payload(**changes):
    return {'model': 'synthetic-byte-model-v1', 'stream': True,
            'input': [{'role': 'user', 'content': 'synthetic bilingual 你好'}],
            'max_output_tokens': 10, **changes}


def headers(**changes):
    return {'authorization': 'Bearer synthetic-token',
            'chatgpt-account-id': 'synthetic-account',
            'x-issue14-request-id': str(uuid4()),
            'x-issue14-role': 'collector', **changes}


def budget(tmp_path, **changes):
    return ProviderBudget.create(reservation_root=tmp_path, run_id=str(uuid4()),
        source_revision='0' * 40, limits=Limits(**{
            'requests': 100, 'input_tokens': 100000, 'output_tokens': 1000,
            'reasoning_tokens': 1000, 'output_tokens_per_request': 10,
            'currency_micros': 1000000, **changes}))


class Server:
    def __init__(self):
        self.contacts = []
        self.handlers = set()
        self.mode = 'ok'
        self.release = asyncio.Event()
        self.arrived = asyncio.Event()
        self.response_id = None

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        try:
            head = await reader.readuntil(b'\r\n\r\n')
            lines = head.decode().split('\r\n')
            h = {k.lower(): v.strip() for k, v in
                 (line.split(':', 1) for line in lines[1:] if ':' in line)}
            raw = await reader.readexactly(int(h['content-length']))
            body = json.loads(raw)
            self.contacts.append({'raw': raw, 'headers': h, 'body': body})
            self.arrived.set()
            if self.mode == 'wait':
                await self.release.wait()
            if self.mode == 'disconnect':
                return
            if self.mode == 'redirect':
                writer.write(b'HTTP/1.1 307 Temporary Redirect\r\nLocation: /again\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                await writer.drain()
                return
            # The fixture protocol defines one token per final UTF-8 body byte,
            # and independently caps all generated tokens, including reasoning.
            output = min(100, body['max_output_tokens'])
            response = {'id': self.response_id or str(uuid4()), 'status': 'completed',
                'model': body['model'], 'account': 'synthetic-account',
                'max_output_tokens': body['max_output_tokens'],
                'usage': {'input_tokens': len(raw), 'output_tokens': output,
                    'total_tokens': len(raw) + output,
                    'output_tokens_details': {'reasoning_tokens': 3}}}
            if self.mode == 'missing':
                del response['usage']
            elif self.mode == 'invalid':
                response['usage']['input_tokens'] = True
            elif self.mode == 'over_input':
                response['usage']['input_tokens'] += 1
                response['usage']['total_tokens'] += 1
            elif self.mode == 'under_input':
                response['usage']['input_tokens'] -= 1
                response['usage']['total_tokens'] -= 1
            elif self.mode == 'over_output':
                response['usage']['output_tokens'] += 1
                response['usage']['total_tokens'] += 1
            elif self.mode == 'over_reasoning':
                response['usage']['output_tokens_details']['reasoning_tokens'] = 11
            elif self.mode == 'missing_reasoning':
                del response['usage']['output_tokens_details']
            elif self.mode == 'bad_total':
                response['usage']['total_tokens'] += 1
            elif self.mode == 'wrong_model':
                response['model'] = 'another-model'
            elif self.mode == 'wrong_account':
                response['account'] = 'another-account'
            elif self.mode == 'missing_cap':
                del response['max_output_tokens']
            elif self.mode == 'wrong_cap':
                response['max_output_tokens'] += 1
            elif self.mode == 'negative':
                response['usage']['output_tokens_details']['reasoning_tokens'] = -1
            elif self.mode == 'float':
                response['usage']['input_tokens'] = float(len(raw))
            elif self.mode == 'unknown_billing':
                response['usage']['tool_fee'] = 100
            event = {'type': 'response.completed', 'response': response}
            if self.mode == 'event_error':
                event['error'] = {'message': 'synthetic private error'}
            wire = ('data: ' + json.dumps(event) + '\n\n').encode()
            if self.mode == 'duplicate':
                wire *= 2
            elif self.mode == 'late_error':
                wire += b'data: {"type":"error"}\n\n'
            elif self.mode == 'trailing':
                wire += b'data: {"type":'
            elif self.mode == 'duplicate_key':
                wire = wire.replace(b'"status": "completed"', b'"status": "failed", "status": "completed"')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nContent-Length: '
                + str(len(wire)).encode() + b'\r\nConnection: close\r\n\r\n' + wire)
            await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.handlers.discard(task)


@asynccontextmanager
async def server():
    fixture = Server()
    listener = await asyncio.start_server(fixture.handle, '127.0.0.1', 0)
    fixture.endpoint = 'http://127.0.0.1:%d/codex/responses' % listener.sockets[0].getsockname()[1]
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
    transport = ControlledBudgetTransport.controlled(ledger=ledger, endpoint=fixture.endpoint)
    async with httpx.AsyncClient(transport=transport, follow_redirects=True, timeout=1) as value:
        yield value


def test_exact_wire_accounting_and_private_journal(tmp_path):
    async def check():
        ledger = budget(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            result = await session.post(fixture.endpoint, json=payload(
                instructions='private-synthetic-instruction',
                tools=[{'type': 'function', 'name': 'lookup', 'description': 'fixture',
                        'parameters': {'type': 'object'}}],
                reasoning={'effort': 'high'}), headers=headers())
            assert result.status_code == 200
            assert len(fixture.contacts) == 1
        receipt = ledger.receipt()
        assert receipt['accounted']['input_tokens'] == len(fixture.contacts[0]['raw'])
        assert receipt['accounted']['output_tokens'] == 10
        assert receipt['accounted']['reasoning_tokens'] == 3
        assert receipt['accounted']['currency_micros'] == len(fixture.contacts[0]['raw']) * 2 + 50
        assert receipt['live_ready'] is False
        assert receipt['actual_provider_requests'] is None
        journal = next(tmp_path.glob('*.jsonl')).read_text()
        for secret in ['private-synthetic-instruction', 'synthetic bilingual', 'synthetic-token', '你好']:
            assert secret not in journal
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('cap,value', [('requests', 0), ('input_tokens', 0),
    ('output_tokens', 9), ('reasoning_tokens', 9), ('currency_micros', 1)])
def test_exhausted_budget_has_zero_contacts(tmp_path, cap, value):
    async def check():
        ledger = budget(tmp_path, **{cap: value})
        async with server() as fixture, client(ledger, fixture) as session:
            for _ in range(2):
                with pytest.raises(BudgetStopped):
                    await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert fixture.contacts == []
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('limiting_cap', ['requests', 'input_tokens', 'output_tokens',
                                        'reasoning_tokens', 'currency_micros'])
def test_concurrent_reservations_shared_across_clients(tmp_path, limiting_cap):
    async def check():
        raw = json.dumps(payload(), ensure_ascii=False, separators=(',', ':')).encode()
        caps = {'requests': 3, 'input_tokens': len(raw) * 3, 'output_tokens': 30,
                'reasoning_tokens': 30, 'currency_micros': (len(raw) * 2 + 50) * 3}
        ledger = budget(tmp_path, **{limiting_cap: caps[limiting_cap]})
        async with server() as fixture:
            fixture.mode = 'wait'
            async def send():
                async with client(ledger, fixture) as session:
                    return await session.post(fixture.endpoint, content=raw,
                        headers={**headers(), 'content-type': 'application/json'})
            tasks = [asyncio.create_task(send()) for _ in range(20)]
            await fixture.arrived.wait()
            for _ in range(100):
                if len(fixture.contacts) == 3:
                    break
                await asyncio.sleep(.001)
            assert len(fixture.contacts) == 3
            assert ledger.receipt()['reserved_requests'] == 3
            assert ledger.receipt()['accounted']['output_tokens'] == 30
            fixture.release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert sum(isinstance(x, httpx.Response) for x in results) == 3
            assert sum(isinstance(x, BudgetStopped) for x in results) == 17
            assert len(fixture.contacts) == 3
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('mode', ['missing', 'invalid', 'over_input', 'under_input', 'over_output',
    'over_reasoning', 'missing_reasoning', 'bad_total', 'wrong_model', 'wrong_account',
    'missing_cap', 'wrong_cap', 'negative', 'float', 'unknown_billing', 'event_error',
    'duplicate', 'late_error', 'trailing', 'disconnect', 'redirect', 'duplicate_key'])
def test_ambiguous_usage_retains_reservation_and_fences_run(tmp_path, mode):
    async def check():
        ledger = budget(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            fixture.mode = mode
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            before = ledger.receipt()
            assert before['unresolved_requests'] == 1
            assert before['accounted']['output_tokens'] == 10
            assert before['accounted']['reasoning_tokens'] == 10
            fixture.mode = 'ok'
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 1
            assert ledger.receipt()['accounted'] == before['accounted']
        ledger.close()
    asyncio.run(check())


def test_cancellation_and_restart_cannot_reset_reservations(tmp_path):
    async def check():
        ledger = budget(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            fixture.mode = 'wait'
            task = asyncio.create_task(session.post(fixture.endpoint, json=payload(), headers=headers()))
            await fixture.arrived.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert ledger.receipt()['unresolved_requests'] == 1
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 1
        ledger.close()
        with pytest.raises(BudgetStopped, match='reservation_exists'):
            ProviderBudget.create(reservation_root=tmp_path, run_id=ledger.run_id,
                source_revision='0' * 40, limits=ledger.limits)
    asyncio.run(check())


def test_journal_failure_before_send_has_zero_contacts(tmp_path, monkeypatch):
    async def check():
        ledger = budget(tmp_path)
        def unavailable(*args):
            raise OSError('private failure detail')
        monkeypatch.setattr('scripts.issue14_provider_budget.os.fsync', unavailable)
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(BudgetStopped, match='journal_unavailable'):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert fixture.contacts == []
            assert ledger.receipt()['unresolved_requests'] == 1
        monkeypatch.undo()
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('change', [
    {'x-issue14-role': 'judge'}, {'x-issue14-role': 'photo'},
    {'authorization': 'Bearer not-a-fixture-token'}, {'chatgpt-account-id': 'other'},
])
def test_unapproved_role_or_identity_denied_before_contact(tmp_path, change):
    async def check():
        ledger = budget(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers(**change))
            assert fixture.contacts == []
        ledger.close()
    asyncio.run(check())


def test_live_transport_cannot_be_enabled(tmp_path):
    ledger = budget(tmp_path)
    with pytest.raises(BudgetStopped, match='live_provider_unverified'):
        ControlledBudgetTransport()
    for endpoint in ['https://chatgpt.com/backend-api/codex/responses',
                     'http://localhost:9000/codex/responses',
                     'http://127.0.0.1:9000/other']:
        with pytest.raises(BudgetStopped):
            ControlledBudgetTransport.controlled(ledger=ledger, endpoint=endpoint)
    ledger.close()


@pytest.mark.parametrize('kind', ['request', 'response'])
def test_duplicate_ids_are_rejected_across_clients(tmp_path, kind):
    async def check():
        ledger = budget(tmp_path)
        identity = headers()
        async with server() as fixture:
            fixture.response_id = str(uuid4()) if kind == 'response' else None
            async with client(ledger, fixture) as first:
                await first.post(fixture.endpoint, json=payload(), headers=identity)
            async with client(ledger, fixture) as second:
                with pytest.raises(BudgetStopped, match=kind + '_replay'):
                    await second.post(fixture.endpoint, json=payload(),
                        headers=identity if kind == 'request' else headers())
                with pytest.raises(BudgetStopped):
                    await second.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == (1 if kind == 'request' else 2)
            assert ledger.receipt()['settled_requests'] == 1
            assert ledger.receipt()['unresolved_requests'] == (0 if kind == 'request' else 1)
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('key', ['requests', 'input_tokens', 'output_tokens',
                                'reasoning_tokens', 'currency_micros'])
def test_exact_remaining_cap_blocks_next_actual_send(tmp_path, key):
    async def check():
        raw = json.dumps(payload(), ensure_ascii=False, separators=(',', ':')).encode()
        caps = {'requests': 1, 'input_tokens': len(raw), 'output_tokens': 10,
                'reasoning_tokens': 10, 'currency_micros': len(raw) * 2 + 50}
        ledger = budget(tmp_path, **{key: caps[key]})
        async with server() as fixture, client(ledger, fixture) as session:
            await session.post(fixture.endpoint, content=raw,
                headers={**headers(), 'content-type': 'application/json'})
            assert len(fixture.contacts) == 1
            for _ in range(2):
                with pytest.raises(BudgetStopped):
                    await session.post(fixture.endpoint, content=raw,
                        headers={**headers(), 'content-type': 'application/json'})
            assert len(fixture.contacts) == 1
        ledger.close()
    asyncio.run(check())


@pytest.mark.parametrize('change', [
    {'max_output_tokens': None}, {'max_output_tokens': True}, {'max_output_tokens': 11},
    {'model': 'gpt-5.6-luna'}, {'previous_response_id': 'server-side-context'},
    {'tools': [{'type': 'web_search'}]}, {'input': [{'type': 'input_image', 'url': 'private'}]},
])
def test_unbounded_payload_denied_before_contact(tmp_path, change):
    async def check():
        ledger = budget(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, json=payload(**change), headers=headers())
            assert fixture.contacts == []
        ledger.close()
    asyncio.run(check())


def test_wrong_host_is_denied_before_contact(tmp_path):
    async def check():
        ledger = budget(tmp_path)
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers(host='different-host'))
            assert fixture.contacts == []
        ledger.close()
    asyncio.run(check())


def test_settlement_journal_failure_retains_full_reservation(tmp_path, monkeypatch):
    async def check():
        ledger = budget(tmp_path)
        original = os.fsync
        calls = 0
        def fail_second(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('private journal error')
            return original(fd)
        monkeypatch.setattr('scripts.issue14_provider_budget.os.fsync', fail_second)
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(BudgetStopped, match='journal_unavailable'):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            receipt = ledger.receipt()
            assert receipt['reported']['currency_micros'] == 0
            assert receipt['accounted']['reasoning_tokens'] == 10
            assert receipt['unresolved_requests'] == 1
            assert not receipt['journal_durable']
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert len(fixture.contacts) == 1
        monkeypatch.undo()
        ledger.close()
    asyncio.run(check())


def test_zero_length_journal_write_fails_closed(tmp_path, monkeypatch):
    async def check():
        ledger = budget(tmp_path)
        monkeypatch.setattr('scripts.issue14_provider_budget.os.write', lambda *args: 0)
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(BudgetStopped, match='journal_unavailable'):
                await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert fixture.contacts == []
            assert not ledger.receipt()['journal_durable']
        monkeypatch.undo()
        ledger.close()
    asyncio.run(check())


def test_process_crash_after_contact_cannot_resume(tmp_path):
    async def check():
        run_id = str(uuid4())
        async with server() as fixture:
            fixture.mode = 'wait'
            program = '''
import asyncio, sys, httpx
from scripts.issue14_provider_budget import ProviderBudget, Limits
from scripts.issue14_provider_transport import ControlledBudgetTransport
from uuid import uuid4
ledger = ProviderBudget.create(reservation_root=sys.argv[1], run_id=sys.argv[2],
    source_revision='0'*40, limits=Limits(10,10000,100,100,10,100000))
async def run():
    transport=ControlledBudgetTransport.controlled(ledger=ledger, endpoint=sys.argv[3])
    async with httpx.AsyncClient(transport=transport) as client:
        await client.post(sys.argv[3],json={'model':'synthetic-byte-model-v1',
            'stream':True,'input':[{'role':'user','content':'synthetic crash fixture'}],
            'max_output_tokens':10}, headers={'authorization':'Bearer synthetic-token',
            'chatgpt-account-id':'synthetic-account','x-issue14-role':'collector',
            'x-issue14-request-id':str(uuid4())})
asyncio.run(run())
'''
            child = await asyncio.create_subprocess_exec(sys.executable, '-c', program,
                str(tmp_path), run_id, fixture.endpoint, stderr=asyncio.subprocess.PIPE)
            try:
                await asyncio.wait_for(fixture.arrived.wait(), 5)
                child.kill()
                await child.communicate()
                assert len(fixture.contacts) == 1
                with pytest.raises(BudgetStopped, match='reservation_exists'):
                    ProviderBudget.create(reservation_root=tmp_path, run_id=run_id,
                        source_revision='0' * 40, limits=Limits(10, 10000, 100, 100, 10, 100000))
                events = [json.loads(line) for line in (tmp_path / (run_id + '.jsonl')).read_text().splitlines()]
                assert [event['event'] for event in events] == ['created', 'send_reserved']
            finally:
                if child.returncode is None:
                    child.kill()
                    await child.communicate()
    asyncio.run(check())


def test_cancellation_during_payload_buffering_fences_run(tmp_path):
    async def check():
        ledger = budget(tmp_path)
        ready = asyncio.Event()
        class WaitingBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                ready.set()
                await asyncio.Event().wait()
                yield b'never'
        async with server() as fixture:
            transport = ControlledBudgetTransport.controlled(ledger=ledger, endpoint=fixture.endpoint)
            request = httpx.Request('POST', fixture.endpoint, stream=WaitingBody(),
                headers={**headers(), 'host': fixture.endpoint.split('/')[2],
                    'content-type': 'application/json', 'content-length': '5'})
            task = asyncio.create_task(transport.handle_async_request(request))
            await ready.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            async with client(ledger, fixture) as session:
                with pytest.raises(BudgetStopped):
                    await session.post(fixture.endpoint, json=payload(), headers=headers())
            assert fixture.contacts == []
            await transport.aclose()
        ledger.close()
    asyncio.run(check())


def test_nonfinite_json_schema_denied_before_contact(tmp_path):
    async def check():
        ledger = budget(tmp_path)
        body = payload(tools=[{'type': 'function', 'name': 'fixture',
            'description': 'fixture', 'parameters': {'maximum': 'REPLACE'}}])
        raw = json.dumps(body).replace('"REPLACE"', '1e999').encode()
        async with server() as fixture, client(ledger, fixture) as session:
            with pytest.raises(BudgetStopped):
                await session.post(fixture.endpoint, content=raw,
                    headers={**headers(), 'content-type': 'application/json'})
            assert fixture.contacts == []
        ledger.close()
    asyncio.run(check())


def test_limits_are_immutable(tmp_path):
    ledger = budget(tmp_path)
    with pytest.raises(AttributeError):
        ledger.limits = Limits(1000, 100000, 10000, 10000, 10, 1000000)
    with pytest.raises(AttributeError):
        ledger.limits.requests = 1000
    ledger.close()


def test_caller_request_mutation_cannot_change_the_inspected_wire_target(tmp_path):
    async def check():
        ledger = budget(tmp_path)
        raw = json.dumps(payload()).encode()
        buffering, release = asyncio.Event(), asyncio.Event()
        class DelayedBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                buffering.set()
                await release.wait()
                yield raw
        async with server() as intended, server() as alternate:
            transport = ControlledBudgetTransport.controlled(ledger=ledger, endpoint=intended.endpoint)
            original_headers = {**headers(), 'host': intended.endpoint.split('/')[2],
                'content-type': 'application/json', 'content-length': str(len(raw))}
            request = httpx.Request('POST', intended.endpoint, stream=DelayedBody(), headers=original_headers)
            task = asyncio.create_task(transport.handle_async_request(request))
            await buffering.wait()
            request.url = httpx.URL(alternate.endpoint)
            request.headers['host'] = alternate.endpoint.split('/')[2]
            request.headers['authorization'] = 'Bearer mutated'
            request.method = 'PUT'
            request.headers['x-issue14-role'] = 'judge'
            trace_calls = []
            async def trace(*args):
                trace_calls.append(args)
            request.extensions['trace'] = trace
            release.set()
            response = await task
            assert response.status_code == 200
            assert len(intended.contacts) == 1
            assert alternate.contacts == []
            assert intended.contacts[0]['raw'] == raw
            assert intended.contacts[0]['headers']['authorization'] == 'Bearer synthetic-token'
            assert intended.contacts[0]['headers']['x-issue14-role'] == 'collector'
            assert trace_calls == []
            await transport.aclose()
        ledger.close()
    asyncio.run(check())


def test_ledger_rejects_underreported_exact_input_without_refund(tmp_path):
    ledger = budget(tmp_path, input_tokens=200)
    ticket = ledger.reserve(request_id=str(uuid4()), role='collector', payload_bytes=200)
    with pytest.raises(BudgetStopped, match='usage_invalid'):
        ledger.settle(ticket, response_id=str(uuid4()), input_tokens=0,
            output_tokens=0, reasoning_tokens=0)
    receipt = ledger.receipt()
    assert receipt['accounted']['input_tokens'] == 200
    assert receipt['accounted']['currency_micros'] == 450
    assert receipt['unresolved_requests'] == 1
    with pytest.raises(BudgetStopped):
        ledger.reserve(request_id=str(uuid4()), role='collector', payload_bytes=200)
    ledger.close()


def test_caller_trace_callback_cannot_strip_wire_output_cap(tmp_path):
    async def check():
        ledger = budget(tmp_path)
        original = json.dumps(payload()).encode()
        altered = json.dumps(payload(max_output_tokens=900)).encode()
        calls = []
        async def trace(name, info):
            calls.append(name)
            if name == 'http11.send_request_headers.started':
                core_request = info['request']
                core_request.stream = httpx.ByteStream(altered)
                core_request.headers = [
                    (key, value) for key, value in core_request.headers
                    if key.lower() != b'content-length'] + [
                        (b'content-length', str(len(altered)).encode())]
        async with server() as fixture, client(ledger, fixture) as session:
            await session.post(fixture.endpoint, content=original,
                headers={**headers(), 'content-type': 'application/json'},
                extensions={'trace': trace})
            assert len(fixture.contacts) == 1
            assert fixture.contacts[0]['raw'] == original
            assert fixture.contacts[0]['body']['max_output_tokens'] == 10
            assert calls == []
        ledger.close()
    asyncio.run(check())
