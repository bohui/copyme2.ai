"""Offline campaign budgets: synthetic requests, fake wire, no provider contact."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from scripts import issue14_subscription_transport as budget


CASE_IDS = ('harbour-copper-notebook', 'chengdu-tea-ledger',
    'perth-workshop-compass', 'kunming-garden-lanterns', 'sydney-platform-letters')
ENDPOINT = 'http://127.0.0.1:40123/v1/responses'


def campaign(tmp_path, *, global_requests=3000, global_seconds=36000,
             case_requests=600, case_seconds=7200, **changes):
    options = dict(reservation_root=tmp_path, run_id=str(uuid4()),
        source_revision='0' * 40,
        limits=budget.SubscriptionLimits(global_requests, global_seconds),
        case_ids=CASE_IDS, case_limits=budget.SubscriptionLimits(case_requests, case_seconds))
    options.update(changes)
    return budget.SubscriptionRun.create(**options)


class Body(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'{"synthetic":true}'


class FakeWire(httpx.AsyncBaseTransport):
    def __init__(self, run, mode='ok'):
        self.run, self.mode = run, mode
        self.contacts = []
        self.arrived, self.release = asyncio.Event(), asyncio.Event()

    async def handle_async_request(self, request):
        # Capture both counters exactly at wire entry.
        self.contacts.append(self.run.snapshot())
        self.arrived.set()
        if self.mode == 'wait':
            await self.release.wait()
        if self.mode == 'fail':
            raise httpx.ReadError('synthetic private error')
        return httpx.Response(200, stream=Body())


@asynccontextmanager
async def session(run, mode='ok'):
    transport = budget.SubscriptionTransport.controlled(run=run, endpoint=ENDPOINT)
    await transport._wire.aclose()
    transport._wire = wire = FakeWire(run, mode)
    async with httpx.AsyncClient(transport=transport, timeout=None) as client:
        yield client, wire


async def send(client):
    return await client.post(ENDPOINT, json={'previous_response_id': 'repeat-private'},
        headers={'authorization': 'Bearer synthetic-token'})


def journal(tmp_path):
    return [json.loads(line) for line in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]


def test_fixed_case_ids_match_original_dataset():
    dataset = Path(__file__).parent / 'evaluation/memoir_five_case_inputs.json'
    assert tuple(case['id'] for case in json.loads(dataset.read_text())['cases']) == CASE_IDS
    assert budget.MEMOIR_FIVE_CASE_IDS == CASE_IDS


@pytest.mark.parametrize('changes', [
    {'case_ids': None}, {'case_limits': None}, {'case_ids': list(CASE_IDS)},
    {'case_ids': CASE_IDS[::-1]}, {'case_ids': CASE_IDS[:-1]},
    {'case_ids': (*CASE_IDS[:-1], 'other')}, {'case_ids': (CASE_IDS[0],) * 5},
    {'case_limits': {'max_requests': 600, 'max_elapsed_seconds': 7200}},
    {'case_limits': budget.SubscriptionLimits(601, 7200)},
    {'case_limits': budget.SubscriptionLimits(600, 7201)},
    {'limits': budget.SubscriptionLimits(3001, 36000)},
    {'limits': budget.SubscriptionLimits(3000, 36001)},
])
def test_campaign_requires_explicit_complete_bounded_scope(tmp_path, changes):
    with pytest.raises(ValueError):
        campaign(tmp_path, **changes)
    assert list(tmp_path.iterdir()) == []


def test_default_run_remains_unscoped_with_historical_limits_and_receipt(tmp_path):
    run = budget.SubscriptionRun.create(reservation_root=tmp_path, run_id=str(uuid4()),
        source_revision='0' * 40, limits=budget.SubscriptionLimits(3001, 36001))
    assert type(run) is budget.SubscriptionRun
    assert run.case_ids is None and run.case_limits is None
    assert 'cases' not in run.snapshot()
    with pytest.raises(ValueError):
        run.start_case(CASE_IDS[0])
    assert run.snapshot()['stop_reason'] is None
    run.close()


def test_campaign_boundaries_are_read_only_and_durable(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    run = campaign(tmp_path)
    assert type(run) is budget.SubscriptionRun
    assert run.remaining_seconds() == 36000
    for name, value in [('case_ids', CASE_IDS[::-1]), ('case_limits', budget.SubscriptionLimits(1, 1)),
                        ('global_deadline', 1)]:
        with pytest.raises(AttributeError):
            setattr(run, name, value)
    now[0] = 400.0
    run.start_case(CASE_IDS[0])
    assert run.global_deadline == 36100
    assert run.deadline == 7600
    assert run.remaining_seconds() == 7200
    receipt = run.snapshot()
    assert receipt['active_case_id'] == CASE_IDS[0]
    assert receipt['case_ids'] == list(CASE_IDS)
    assert receipt['case_limits'] == {'max_requests': 600, 'max_elapsed_seconds': 7200}
    assert receipt['cases'][0]['started_at_monotonic'] == 400
    assert receipt['cases'][0]['deadline_monotonic'] == 7600
    assert receipt['global_deadline_monotonic'] == 36100
    assert receipt['effective_deadline_monotonic'] == 7600
    assert journal(tmp_path)[0]['case_ids'] == list(CASE_IDS)
    assert journal(tmp_path)[1]['event'] == 'case_started'
    run.close()


@pytest.mark.parametrize('operation', ['wrong_first', 'finish_pending', 'double_start',
    'wrong_finish', 'skip_next', 'reuse_finished', 'double_finish', 'after_all'])
def test_cases_are_sequential_single_use_and_lifecycle_errors_terminal(tmp_path, operation):
    run = campaign(tmp_path)
    with pytest.raises(budget.SubscriptionStopped, match='case_sequence_invalid'):
        if operation == 'wrong_first':
            run.start_case(CASE_IDS[1])
        elif operation == 'finish_pending':
            run.finish_case(CASE_IDS[0])
        elif operation == 'after_all':
            for case_id in CASE_IDS:
                run.start_case(case_id)
                run.finish_case(case_id)
            run.start_case(CASE_IDS[0])
        else:
            run.start_case(CASE_IDS[0])
            if operation == 'double_start':
                run.start_case(CASE_IDS[0])
            elif operation == 'wrong_finish':
                run.finish_case(CASE_IDS[1])
            else:
                run.finish_case(CASE_IDS[0])
                if operation == 'skip_next':
                    run.start_case(CASE_IDS[2])
                elif operation == 'reuse_finished':
                    run.start_case(CASE_IDS[0])
                else:
                    run.finish_case(CASE_IDS[0])
    with pytest.raises(budget.SubscriptionStopped):
        run.start_case(CASE_IDS[1])
    assert run.snapshot()['client_requests_reserved'] == 0
    run.close()


@pytest.mark.parametrize('after_finish', [False, True])
def test_no_provider_dispatch_outside_active_case(tmp_path, after_finish):
    async def check():
        run = campaign(tmp_path)
        if after_finish:
            run.start_case(CASE_IDS[0])
            run.finish_case(CASE_IDS[0])
        async with session(run) as (client, wire):
            with pytest.raises(budget.SubscriptionStopped, match='case_inactive'):
                await send(client)
            assert wire.contacts == []
            assert run.snapshot()['client_requests_reserved'] == 0
        run.close()
    asyncio.run(check())


def test_duplicate_continuations_reserve_both_counts_before_wire_and_keep_counts(tmp_path):
    async def check():
        run = campaign(tmp_path, case_requests=2)
        run.start_case(CASE_IDS[0])
        async with session(run) as (first, first_wire):
            await send(first)
        async with session(run) as (second, second_wire):
            await send(second)
            with pytest.raises(budget.SubscriptionStopped, match='case_requests_limit'):
                await send(second)
            assert len(first_wire.contacts) == len(second_wire.contacts) == 1
            for expected, receipt in enumerate(first_wire.contacts + second_wire.contacts, 1):
                assert receipt['client_requests_reserved'] == expected
                assert receipt['cases'][0]['client_requests_reserved'] == expected
                assert receipt['cases'][0]['client_requests_started'] == expected
                assert receipt['attempts'][-1]['case_id'] == CASE_IDS[0]
                assert receipt['attempts'][-1]['case_ordinal'] == expected
        receipt = run.snapshot()
        assert receipt['client_requests_reserved'] == 2
        assert receipt['cases'][0]['completed_http_responses'] == 2
        assert receipt['cases'][0]['unresolved_requests'] == 0
        events = journal(tmp_path)
        assert [event['case_ordinal'] for event in events if event['event'] == 'send_reserved'] == [1, 2]
        assert 'repeat-private' not in next(tmp_path.glob('*.jsonl')).read_text()
        run.close()
    asyncio.run(check())


def test_all_five_completions_keep_global_and_case_accounting(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    async def check():
        run = campaign(tmp_path)
        async with session(run) as (client, wire):
            for index, case_id in enumerate(CASE_IDS):
                now[0] += 10
                run.start_case(case_id)
                await send(client)
                now[0] += 5
                run.finish_case(case_id)
                receipt = run.snapshot()
                assert receipt['client_requests_reserved'] == index + 1
                assert receipt['active_case_id'] is None
                assert run.deadline == run.global_deadline == 36100
            assert len(wire.contacts) == 5
        run.close()
        receipt = run.snapshot()
        assert receipt['client_requests_reserved'] == receipt['completed_http_responses'] == 5
        assert all(case['status'] == 'completed' for case in receipt['cases'])
        assert all(case['client_requests_reserved'] == 1 for case in receipt['cases'])
        assert all(case['elapsed_seconds'] == 5 for case in receipt['cases'])
        assert len([event for event in journal(tmp_path) if event['event'] == 'case_finished']) == 5
        assert all(event['status'] == 'completed' and event['finished_at_monotonic'] is not None
            for event in journal(tmp_path) if event['event'] == 'case_finished')
        assert receipt['upstream_cancellation_verified'] is False
    asyncio.run(check())


def test_global_requests_remain_bounded_across_cases(tmp_path):
    async def check():
        run = campaign(tmp_path, global_requests=2, case_requests=2)
        async with session(run) as (client, wire):
            run.start_case(CASE_IDS[0])
            await send(client)
            run.finish_case(CASE_IDS[0])
            run.start_case(CASE_IDS[1])
            await send(client)
            with pytest.raises(budget.SubscriptionStopped, match='^requests_limit$'):
                await send(client)
            assert len(wire.contacts) == 2
            assert [case['client_requests_reserved'] for case in run.snapshot()['cases']] == [1, 1, 0, 0, 0]
        run.close()
    asyncio.run(check())


@pytest.mark.parametrize('global_seconds, case_seconds, elapsed, reason', [
    (100, 10, 10, 'case_elapsed_limit'), (10, 100, 10, 'elapsed_limit')])
def test_deadlines_bound_non_send_work_and_case_completion(tmp_path, monkeypatch,
        global_seconds, case_seconds, elapsed, reason):
    now = [100.0]
    monkeypatch.setattr(budget, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    run = campaign(tmp_path, global_seconds=global_seconds, case_seconds=case_seconds)
    run.start_case(CASE_IDS[0])
    assert run.deadline == 110
    now[0] += elapsed
    with pytest.raises(budget.SubscriptionStopped, match=reason):
        run.remaining_seconds()
    with pytest.raises(budget.SubscriptionStopped, match=reason):
        run.finish_case(CASE_IDS[0])
    assert run.snapshot()['cases'][0]['status'] == 'incomplete'
    run.close()


def test_later_case_gets_only_remaining_global_time(tmp_path, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(budget, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    run = campaign(tmp_path, global_seconds=30, case_seconds=20)
    run.start_case(CASE_IDS[0])
    now[0] += 15
    run.finish_case(CASE_IDS[0])
    now[0] += 5
    run.start_case(CASE_IDS[1])
    assert run.remaining_seconds() == 10
    assert run.snapshot()['cases'][1]['deadline_monotonic'] == 130
    run.close()


@pytest.mark.parametrize('mode', ['fail', 'cancel', 'timeout'])
def test_failures_and_cancellation_preserve_both_uncertain_counts(tmp_path, mode):
    async def check():
        run = campaign(tmp_path, case_seconds=.1 if mode == 'timeout' else 10)
        run.start_case(CASE_IDS[0])
        async with session(run, 'fail' if mode == 'fail' else 'wait') as (client, wire):
            task = asyncio.create_task(send(client))
            await wire.arrived.wait()
            if mode == 'cancel':
                task.cancel()
            with pytest.raises(asyncio.CancelledError if mode == 'cancel' else budget.SubscriptionStopped):
                await task
            receipt = run.snapshot()
            for counts in (receipt, receipt['cases'][0]):
                assert counts['client_requests_reserved'] == counts['client_requests_started'] == 1
                assert counts['completed_http_responses'] == 0
                assert counts['unresolved_requests'] == 1
            assert receipt['upstream_cancellation_verified'] is False
            if mode == 'timeout':
                assert receipt['stop_reason'] == 'case_elapsed_limit'
            with pytest.raises(budget.SubscriptionStopped):
                run.finish_case(CASE_IDS[0])
            with pytest.raises(budget.SubscriptionStopped):
                await send(client)
            assert len(wire.contacts) == 1
        run.close()
    asyncio.run(check())


def test_case_cannot_finish_or_switch_while_dispatch_active(tmp_path):
    async def check():
        run = campaign(tmp_path)
        run.start_case(CASE_IDS[0])
        async with session(run, 'wait') as (client, wire):
            task = asyncio.create_task(send(client))
            await wire.arrived.wait()
            with pytest.raises(budget.SubscriptionStopped, match='case_inflight'):
                run.finish_case(CASE_IDS[0])
            wire.release.set()
            with pytest.raises(budget.SubscriptionStopped):
                await task
            assert run.snapshot()['cases'][0]['unresolved_requests'] == 1
        run.close()
    asyncio.run(check())


@pytest.mark.parametrize('event', ['case_started', 'send_reserved', 'case_finished'])
def test_journal_failure_at_campaign_boundary_is_terminal(tmp_path, monkeypatch, event):
    async def check():
        run = campaign(tmp_path)
        original = run._write
        def fail(selected, **fields):
            if selected == event:
                monkeypatch.setattr(budget.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('private')))
            return original(selected, **fields)
        monkeypatch.setattr(run, '_write', fail)
        async with session(run) as (client, wire):
            with pytest.raises(budget.SubscriptionStopped, match='journal_unavailable'):
                run.start_case(CASE_IDS[0])
                await send(client)
                run.finish_case(CASE_IDS[0])
            receipt = run.snapshot()
            assert receipt['journal_durable'] is False
            assert receipt['cases'][0]['status'] == 'incomplete'
            expected = 0 if event == 'case_started' else 1
            assert receipt['client_requests_reserved'] == expected
            assert receipt['cases'][0]['client_requests_reserved'] == expected
            assert len(wire.contacts) == (1 if event == 'case_finished' else 0)
        run.close()
    asyncio.run(check())


@pytest.mark.parametrize('event, reserved, started, completed', [
    ('case_started', 0, 0, 0), ('send_reserved', 1, 0, 0),
    ('http_response_completed', 1, 1, 0), ('case_finished', 1, 1, 1)])
def test_durable_writes_cannot_extend_active_case_deadline(tmp_path, monkeypatch,
        event, reserved, started, completed):
    now = [100.0]
    monkeypatch.setattr(budget, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    async def check():
        run = campaign(tmp_path, case_seconds=10)
        original = run._write
        def delayed(selected, **fields):
            original(selected, **fields)
            if selected == event:
                now[0] += 10
        monkeypatch.setattr(run, '_write', delayed)
        async with session(run) as (client, wire):
            with pytest.raises(budget.SubscriptionStopped, match='case_elapsed_limit'):
                run.start_case(CASE_IDS[0])
                await send(client)
                run.finish_case(CASE_IDS[0])
            receipt = run.snapshot()
            for counts in (receipt, receipt['cases'][0]):
                assert counts['client_requests_reserved'] == reserved
                assert counts['client_requests_started'] == started
                assert counts['completed_http_responses'] == completed
                assert counts['unresolved_requests'] == reserved - completed
            assert len(wire.contacts) == started
            assert receipt['cases'][0]['status'] == 'incomplete'
            assert receipt['cases'][0]['deadline_monotonic'] == 110
        run.close()
    asyncio.run(check())


def test_active_case_expires_during_caller_body_buffering_before_reservation(tmp_path):
    async def check():
        run = campaign(tmp_path, case_seconds=.1)
        run.start_case(CASE_IDS[0])
        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                await asyncio.sleep(1)
                yield b'{}'
        async with session(run) as (client, wire):
            request = client.build_request('POST', ENDPOINT, content=b'{}',
                headers={'authorization': 'Bearer synthetic-token', 'content-type': 'application/json'})
            request.stream = SlowBody()
            with pytest.raises(budget.SubscriptionStopped, match='case_elapsed_limit'):
                await client.send(request)
            assert wire.contacts == []
            assert run.snapshot()['cases'][0]['client_requests_reserved'] == 0
        run.close()
    asyncio.run(check())


def test_case_deadline_covers_response_stream_and_queued_request(tmp_path):
    async def check():
        run = campaign(tmp_path, case_seconds=.1)
        run.start_case(CASE_IDS[0])
        class SlowBody(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{'
                await asyncio.sleep(1)
                yield b'}'
        async with session(run) as (client, wire):
            original = wire.handle_async_request
            async def stream(request):
                await original(request)
                return httpx.Response(200, stream=SlowBody())
            wire.handle_async_request = stream
            first = asyncio.create_task(send(client))
            await wire.arrived.wait()
            second = asyncio.create_task(send(client))
            results = await asyncio.gather(first, second, return_exceptions=True)
            assert all(isinstance(result, budget.SubscriptionStopped) for result in results)
            assert len(wire.contacts) == 1
            receipt = run.snapshot()
            assert receipt['stop_reason'] == 'case_elapsed_limit'
            assert receipt['cases'][0]['unresolved_requests'] == 1
            assert receipt['upstream_cancellation_verified'] is False
        run.close()
    asyncio.run(check())


def test_cancelling_waiter_does_not_refund_or_misattribute_active_request(tmp_path):
    async def check():
        run = campaign(tmp_path)
        run.start_case(CASE_IDS[0])
        async with session(run, 'wait') as (client, wire):
            first = asyncio.create_task(send(client))
            await wire.arrived.wait()
            second = asyncio.create_task(send(client))
            await asyncio.sleep(0)
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            wire.release.set()
            with pytest.raises(budget.SubscriptionStopped):
                await first
            assert len(wire.contacts) == 1
            receipt = run.snapshot()
            assert receipt['client_requests_reserved'] == receipt['unresolved_requests'] == 1
            assert receipt['cases'][0]['unresolved_requests'] == 1
            assert receipt['cases'][1]['client_requests_reserved'] == 0
            assert receipt['upstream_cancellation_verified'] is False
            with pytest.raises(budget.SubscriptionStopped):
                run.start_case(CASE_IDS[1])
        run.close()
    asyncio.run(check())


def test_campaign_snapshot_is_detached_and_restart_remains_fenced(tmp_path):
    run = campaign(tmp_path)
    run.start_case(CASE_IDS[0])
    receipt = run.snapshot()
    receipt['case_ids'].reverse()
    receipt['cases'][0].update(status='completed', client_requests_reserved=-1,
        deadline_monotonic=10**20)
    receipt['case_limits']['max_requests'] = 10**20
    current = run.snapshot()
    assert current['cases'][0]['status'] == 'active'
    assert current['cases'][0]['client_requests_reserved'] == 0
    assert current['case_limits']['max_requests'] == 600
    assert run.case_ids == CASE_IDS
    run.close()
    with pytest.raises(budget.SubscriptionStopped, match='reservation_exists'):
        campaign(tmp_path, run_id=run.run_id)


def test_global_and_case_reservation_are_durable_before_socket_boundary(tmp_path):
    async def check():
        run = campaign(tmp_path)
        run.start_case(CASE_IDS[0])
        async with session(run) as (client, wire):
            original = wire.handle_async_request
            async def inspect(request):
                events = journal(tmp_path)
                assert events[-2]['event'] == 'send_reserved'
                assert events[-1]['event'] == 'send_started'
                assert events[-1]['ordinal'] == events[-1]['case_ordinal'] == 1
                assert events[-1]['case_id'] == CASE_IDS[0]
                assert events[-2]['reserved_at_monotonic'] <= events[-1]['started_at_monotonic']
                assert run.snapshot()['cases'][0]['client_requests_reserved'] == 1
                return await original(request)
            wire.handle_async_request = inspect
            await send(client)
        run.close()
    asyncio.run(check())


@pytest.mark.parametrize('case_count, expected_reason', [(1, 'case_requests_limit'), (5, 'requests_limit')])
def test_exact_600_case_and_3000_global_reservation_boundaries(tmp_path, case_count, expected_reason):
    run = campaign(tmp_path)
    for index in range(case_count):
        run.start_case(CASE_IDS[index])
        for _ in range(600):
            entry = run._reserve(2)
            run._starting(entry)
            run._complete(entry, 200, 2)
        if index < case_count - 1:
            run.finish_case(CASE_IDS[index])
    with pytest.raises(budget.SubscriptionStopped, match=expected_reason):
        run._reserve(2)
    receipt = run.snapshot()
    assert receipt['client_requests_reserved'] == receipt['completed_http_responses'] == 600 * case_count
    assert all(case['client_requests_reserved'] == case['completed_http_responses'] == 600
        for case in receipt['cases'][:case_count])
    assert len([event for event in journal(tmp_path) if event['event'] == 'send_reserved']) == 600 * case_count
    run.close()


@pytest.mark.parametrize('terminal', ['closed', 'stopped', 'case_timeout'])
def test_terminal_partial_receipts_mark_active_case_incomplete_without_reset(tmp_path, monkeypatch, terminal):
    now = [100.0]
    monkeypatch.setattr(budget, 'time', SimpleNamespace(monotonic=lambda: now[0]))
    run = campaign(tmp_path, case_seconds=10)
    run.start_case(CASE_IDS[0])
    entry = run._reserve(2)
    run._starting(entry)
    before = run.snapshot()
    if terminal == 'closed':
        run.close()
    elif terminal == 'stopped':
        run.stop('send_interrupted_or_failed')
    else:
        now[0] += 10
        with pytest.raises(budget.SubscriptionStopped, match='case_elapsed_limit'):
            run.remaining_seconds()
    receipt = run.snapshot()
    assert receipt['active_case_id'] is None
    assert receipt['cases'][0]['status'] == 'incomplete'
    assert [case['status'] for case in receipt['cases'][1:]] == ['pending'] * 4
    for key in ['client_requests_reserved', 'client_requests_started',
                'completed_http_responses', 'unresolved_requests', 'started_at_monotonic']:
        assert receipt[key] == before[key]
        assert receipt['cases'][0][key] == before['cases'][0][key]
    for key in ['global_deadline_monotonic', 'effective_deadline_monotonic']:
        assert receipt[key] == before[key]
    assert receipt['cases'][0]['deadline_monotonic'] == before['cases'][0]['deadline_monotonic']
    assert receipt['upstream_cancellation_verified'] is False
    assert run.timeout_reason() == 'case_elapsed_limit'
    run.close()
    assert run.snapshot()['cases'][0]['status'] == 'incomplete'


def test_public_timeout_reason_preserves_global_deadline_priority(tmp_path):
    run = campaign(tmp_path, global_seconds=10, case_seconds=100)
    assert run.timeout_reason() == 'elapsed_limit'
    run.start_case(CASE_IDS[0])
    assert run.timeout_reason() == 'elapsed_limit'
    run.close()
    assert run.timeout_reason() == 'elapsed_limit'
