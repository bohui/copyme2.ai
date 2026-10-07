import asyncio
import json
from uuid import uuid4

import pytest


def completed(model='gpt-5.6-luna'):
    return 'data: ' + json.dumps({'type': 'response.completed', 'response': {
        'id': 'resp_synthetic', 'model': model,
        'usage': {'input_tokens': 3, 'output_tokens': 2}}}) + '\n\n'


def guard_at(path, maximum=2, **options):
    from scripts.canary_send_guard import CanarySendGuard
    return CanarySendGuard(reservation=path, run_id=str(uuid4()),
        source_revision='291622826cdfb776e946dcd92b65d2fdaf4923ad',
        account_binding='b' * 64, model='gpt-5.6-luna',
        maximum_requests=maximum, **options)


def test_one_reservation_counts_nested_http_and_websocket_generations(tmp_path):
    from scripts.canary_send_guard import CanaryStopped

    sent = []
    async def wire(payload):
        sent.append(payload)
        yield completed()

    async def run():
        guard = guard_at(tmp_path / 'fresh.jsonl')
        async with guard:
            for transport in ('http', 'websocket'):
                payload = {'model': 'gpt-5.6-luna', 'input': [], 'stream': True}
                if transport == 'websocket':
                    payload['type'] = 'response.create'
                assert [event async for event in guard.stream(wire, payload=payload,
                    transport=transport, account_binding='b' * 64,
                    correlation={'trace_id': 'a' * 32, 'round_id': 'case:1'})]
            with pytest.raises(CanaryStopped, match='request_limit'):
                _ = [event async for event in guard.stream(wire,
                    payload={'model': 'gpt-5.6-luna'}, transport='http',
                    account_binding='b' * 64)]
        receipt = guard.receipt()
        assert receipt['guarded_send_entries'] == 2
        assert receipt['completed'] == 2
        assert receipt['input_tokens_reported'] == 6
        assert receipt['output_tokens_reported'] == 4
        assert receipt['boundary_verified'] is False
        assert receipt['restart_allowed'] is False
        assert receipt['cleanup']['closed'] is True
    asyncio.run(run())
    assert len(sent) == 2
    assert sent[1]['type'] == 'response.create'


@pytest.mark.parametrize('payload,transport,binding,correlation,reason', [
    ({'model': 'other-model'}, 'http', 'b' * 64, {}, 'model_mismatch'),
    ({'model': 'gpt-5.6-luna'}, 'http', 'c' * 64, {}, 'account_mismatch'),
    ({'model': 'gpt-5.6-luna'}, 'compact', 'b' * 64, {}, 'transport_forbidden'),
    ({'model': 'gpt-5.6-luna', 'type': 'response.cancel'}, 'websocket', 'b' * 64,
        {}, 'websocket_operation_forbidden'),
    ({'model': 'gpt-5.6-luna'}, 'http', 'b' * 64,
        {'authorization': 'synthetic-private-token'}, 'correlation_forbidden'),
])
def test_native_binding_or_request_mismatch_stops_before_send(
        tmp_path, payload, transport, binding, correlation, reason):
    from scripts.canary_send_guard import CanaryStopped
    sent = []
    async def wire(payload):
        sent.append(payload)
        yield completed()
    async def run():
        guard = guard_at(tmp_path / 'fresh.jsonl')
        async with guard:
            with pytest.raises(CanaryStopped, match=reason):
                _ = [event async for event in guard.stream(wire, payload=payload,
                    transport=transport, account_binding=binding, correlation=correlation)]
            with pytest.raises(CanaryStopped):
                _ = [event async for event in guard.stream(wire,
                    payload={'model': 'gpt-5.6-luna'}, transport='http',
                    account_binding='b' * 64)]
        assert guard.receipt()['guarded_send_entries'] == 0
        assert 'synthetic-private-token' not in json.dumps(guard.receipt())
    asyncio.run(run())
    assert sent == []
    assert 'synthetic-private-token' not in (tmp_path / 'fresh.jsonl').read_text()


@pytest.mark.parametrize('blocks', [
    ['data: {"type":"response.failed","error":{"message":"synthetic-private-output"}}\n\n'],
    ['data: {"type":"response.incomplete"}\n\n'],
    ['data: {"type":"response.completed","response":{"usage":{}}}\n\n'],
    ['data: {"type":"response.completed","response":{"usage":{"input_tokens":true,"output_tokens":2}}}\n\n'],
    [completed('synthetic-private-output')],
    ['data: {"type":"response.output_text.delta","delta":"synthetic-private-output"}\n\n'],
    [completed(), completed()],
])
def test_failed_ambiguous_or_invalid_completion_blocks_replay(tmp_path, blocks):
    from scripts.canary_send_guard import CanaryStopped
    async def wire(payload):
        for block in blocks:
            yield block
    async def run():
        guard = guard_at(tmp_path / 'fresh.jsonl')
        async with guard:
            with pytest.raises(CanaryStopped):
                _ = [event async for event in guard.stream(wire,
                    payload={'model': 'gpt-5.6-luna'}, transport='http',
                    account_binding='b' * 64)]
            with pytest.raises(CanaryStopped):
                _ = [event async for event in guard.stream(wire,
                    payload={'model': 'gpt-5.6-luna'}, transport='http',
                    account_binding='b' * 64)]
        receipt = guard.receipt()
        assert receipt['guarded_send_entries'] == 1
        assert receipt['completed'] == 0
        assert 'synthetic-private-output' not in json.dumps(receipt)
    asyncio.run(run())
    assert 'synthetic-private-output' not in (tmp_path / 'fresh.jsonl').read_text()


def test_consumer_disconnect_closes_parked_stream_and_reservation(tmp_path):
    closed = []
    async def wire(payload):
        try:
            yield 'data: {"type":"response.output_text.delta","delta":"Story"}\n\n'
            yield completed()
        finally:
            closed.append(True)
    async def run():
        guard = guard_at(tmp_path / 'fresh.jsonl')
        stream = guard.stream(wire, payload={'model': 'gpt-5.6-luna'},
            transport='http', account_binding='b' * 64)
        await stream.__anext__()
        await guard.aclose()
        assert guard.receipt()['completed'] == 0
        assert guard.receipt()['cleanup'] == {'closed': True, 'active_finished': True}
        assert closed == [True]
    asyncio.run(run())


def test_complete_sse_can_arrive_in_fragments_and_wire_is_closed(tmp_path):
    closed = []
    async def wire(payload):
        try:
            raw = completed()
            yield raw[:15]
            yield raw[15:]
        finally:
            closed.append(True)
    async def run():
        guard = guard_at(tmp_path / 'fresh.jsonl')
        async with guard:
            output = [event async for event in guard.stream(wire,
                payload={'model': 'gpt-5.6-luna'}, transport='http',
                account_binding='b' * 64)]
            assert ''.join(output) == completed()
        assert guard.receipt()['completed'] == 1
    asyncio.run(run())
    assert closed == [True]


def test_request_timeout_and_explicit_cancellation_close_wire_and_forbid_replay(tmp_path):
    from scripts.canary_send_guard import CanaryStopped
    async def run():
        for kind in ('timeout', 'cancel'):
            entered, closed = asyncio.Event(), []
            async def wire(payload):
                try:
                    entered.set()
                    await asyncio.Event().wait()
                    yield completed()
                finally:
                    closed.append(True)
            guard = guard_at(tmp_path / (kind + '.jsonl'), request_seconds=.02)
            async def collect():
                return [event async for event in guard.stream(wire,
                    payload={'model': 'gpt-5.6-luna'}, transport='http',
                    account_binding='b' * 64)]
            task = asyncio.create_task(collect())
            await asyncio.wait_for(entered.wait(), 1)
            if kind == 'cancel':
                await asyncio.wait_for(guard.aclose(), 1)
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(CanaryStopped):
                    await asyncio.wait_for(task, 1)
                await guard.aclose()
            with pytest.raises(CanaryStopped):
                await collect()
            assert closed == [True]
            assert guard.receipt()['guarded_send_entries'] == 1
            assert guard.receipt()['completed'] == 0
            assert guard.receipt()['cleanup']['closed'] is True
    asyncio.run(run())


def test_fresh_reservation_refuses_invalid_caps_and_cannot_be_reopened(tmp_path):
    async def run():
        for maximum in (True, -1, 81, 1.5):
            created = []
            try:
                with pytest.raises(ValueError):
                    created.append(guard_at(tmp_path / str(maximum), maximum))
            finally:
                for guard in created:
                    await guard.aclose()
        async with guard_at(tmp_path / 'fresh.jsonl'):
            pass
        with pytest.raises(FileExistsError):
            guard_at(tmp_path / 'fresh.jsonl')
    asyncio.run(run())


def test_wire_exception_text_is_not_exposed_in_receipt_or_journal(tmp_path):
    from scripts.canary_send_guard import CanaryStopped
    async def wire(payload):
        raise CanaryStopped('synthetic-private-output')
        yield completed()
    async def run():
        guard = guard_at(tmp_path / 'fresh.jsonl')
        async with guard:
            with pytest.raises(CanaryStopped) as failure:
                _ = [event async for event in guard.stream(wire,
                    payload={'model': 'gpt-5.6-luna'}, transport='http',
                    account_binding='b' * 64)]
            assert 'synthetic-private-output' not in str(failure.value)
        assert 'synthetic-private-output' not in json.dumps(guard.receipt())
    asyncio.run(run())
    assert 'synthetic-private-output' not in (tmp_path / 'fresh.jsonl').read_text()
