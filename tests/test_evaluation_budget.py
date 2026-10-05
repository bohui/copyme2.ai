import asyncio
import httpx

import pytest


def test_worker_deadline_covers_response_body_after_headers_and_closes_stream():
    from scripts.evaluation_budget import RequestLimitedTransport

    closed = []
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(.15)
            yield b'Synthetic response'
        async def aclose(self):
            closed.append(True)
    async def worker(request):
        return httpx.Response(200, stream=SlowBody())
    async def scenario():
        transport = RequestLimitedTransport(httpx.MockTransport(worker),
            max_requests=2, max_elapsed_seconds=.03)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(client.get('http://synthetic.invalid/worker'), .5)
            with pytest.raises(httpx.RequestError, match='time cap'):
                await client.get('http://synthetic.invalid/worker')
        assert closed == [True]
        assert transport.requests_started == 1
    asyncio.run(scenario())


def test_worker_time_ceiling_cancels_inflight_request_and_blocks_every_role_afterwards():
    from scripts.evaluation_budget import RequestLimitedTransport

    contacted, cancelled = [], []
    async def worker(request):
        contacted.append(request.url.path)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    async def scenario():
        transport = RequestLimitedTransport(httpx.MockTransport(worker),
            max_requests=5, max_elapsed_seconds=.03)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(client.post('http://synthetic.invalid/collector'), 1)
            with pytest.raises(httpx.RequestError, match='time cap'):
                await client.post('http://synthetic.invalid/composer')
        assert contacted == ['/collector']
        assert cancelled == [True]
        assert transport.requests_started == 1
    asyncio.run(scenario())


def test_elapsed_time_cap_cancels_external_provider_and_keeps_reserved_usage():
    from scripts.evaluation_budget import BudgetExceeded, BudgetLimits, BudgetedProvider

    contacted, cancelled = [], []
    async def provider(*, max_output_tokens):
        contacted.append(max_output_tokens)
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    async def scenario():
        budget = BudgetedProvider(BudgetLimits(5, 100, 100, 5), max_elapsed_seconds=.03)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(budget.call(provider, input_tokens_upper_bound=4), 1)
        with pytest.raises(BudgetExceeded):
            await budget.call(provider, input_tokens_upper_bound=4)
        assert contacted == [5]
        assert cancelled == [True]
        assert budget.receipt()['input_tokens_accounted'] == 4
        assert budget.receipt()['output_tokens_accounted'] == 5
        assert budget.receipt()['blocked_reason'] == 'provider_call_interrupted_or_failed'
    asyncio.run(scenario())


def test_worker_request_cap_covers_shared_clients_before_dispatch():
    from scripts.evaluation_budget import RequestLimitedTransport

    contacted = []
    async def worker(request):
        contacted.append(request.url.path)
        return httpx.Response(200, json={'reply': 'Synthetic response'})
    async def scenario():
        transport = RequestLimitedTransport(httpx.MockTransport(worker), max_requests=1)
        async with httpx.AsyncClient(transport=transport) as collector:
            assert (await collector.post('http://synthetic.invalid/internal/codex/turn')).status_code == 200
        async with httpx.AsyncClient(transport=transport) as composer:
            with pytest.raises(httpx.RequestError, match='request cap'):
                await composer.post('http://synthetic.invalid/internal/codex/turn')
        assert transport.requests_started == 1
    asyncio.run(scenario())
    assert contacted == ['/internal/codex/turn']


def test_model_budget_refuses_the_next_request_before_contacting_provider():
    from scripts.evaluation_budget import BudgetExceeded, BudgetLimits, BudgetedProvider

    contacted = []

    async def provider(*, max_output_tokens):
        contacted.append(max_output_tokens)
        return {'reply': 'Synthetic reply', 'usage': {'input_tokens': 3, 'output_tokens': 2}}

    async def scenario():
        client = BudgetedProvider(BudgetLimits(max_requests=1, max_input_tokens=20,
            max_output_tokens=10, max_output_tokens_per_request=5))
        result = await client.call(provider, input_tokens_upper_bound=4)
        assert result['reply'] == 'Synthetic reply'
        with pytest.raises(BudgetExceeded):
            await client.call(provider, input_tokens_upper_bound=4)
        assert contacted == [5]
        assert client.receipt()['requests_started'] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize('bad', [-1, True, 1.5, float('nan'), '10'])
def test_invalid_input_estimates_cannot_dispatch_a_provider_request(bad):
    from scripts.evaluation_budget import BudgetLimits, BudgetedProvider

    contacted = []

    async def provider(*, max_output_tokens):
        contacted.append(max_output_tokens)
        return {'usage': {'input_tokens': 0, 'output_tokens': 0}}

    async def scenario():
        client = BudgetedProvider(BudgetLimits(5, 100, 100, 5))
        with pytest.raises(ValueError):
            await client.call(provider, input_tokens_upper_bound=bad)
        assert contacted == []

    asyncio.run(scenario())


def test_invalid_limits_are_rejected_at_configuration_boundary():
    from scripts.evaluation_budget import BudgetLimits, BudgetedProvider

    with pytest.raises(ValueError):
        BudgetedProvider(BudgetLimits(True, 100, 100, 5))


@pytest.mark.parametrize('usage', [None, {}, {'input_tokens': -1, 'output_tokens': 1},
    {'input_tokens': 3, 'output_tokens': 6}, {'input_tokens': True, 'output_tokens': 1},
    {'input_tokens': 5, 'output_tokens': 1}])
def test_missing_or_invalid_usage_blocks_further_provider_requests(usage):
    from scripts.evaluation_budget import BudgetExceeded, BudgetLimits, BudgetedProvider

    contacted = []

    async def provider(*, max_output_tokens):
        contacted.append(max_output_tokens)
        return {'usage': usage}

    async def scenario():
        client = BudgetedProvider(BudgetLimits(5, 100, 100, 5))
        with pytest.raises(BudgetExceeded):
            await client.call(provider, input_tokens_upper_bound=4)
        with pytest.raises(BudgetExceeded):
            await client.call(provider, input_tokens_upper_bound=4)
        assert contacted == [5]
        assert client.receipt()['blocked_reason']
        assert client.receipt()['input_tokens_accounted'] == 4
        assert client.receipt()['output_tokens_accounted'] == 5

    asyncio.run(scenario())


def test_inflight_output_reservations_prevent_concurrent_overspending():
    from scripts.evaluation_budget import BudgetExceeded, BudgetLimits, BudgetedProvider

    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        contacted = []

        async def provider(*, max_output_tokens):
            contacted.append(max_output_tokens)
            started.set()
            await finish.wait()
            return {'usage': {'input_tokens': 3, 'output_tokens': 2}}

        client = BudgetedProvider(BudgetLimits(5, 20, 5, 5))
        first = asyncio.create_task(client.call(provider, input_tokens_upper_bound=4))
        await started.wait()
        try:
            with pytest.raises(BudgetExceeded):
                await asyncio.wait_for(client.call(provider, input_tokens_upper_bound=4), .2)
        finally:
            finish.set()
            await first
        assert contacted == [5]
        assert client.receipt()['output_tokens_reported'] == 2

    asyncio.run(scenario())


def test_input_tokens_are_reserved_before_the_next_provider_call():
    from scripts.evaluation_budget import BudgetExceeded, BudgetLimits, BudgetedProvider

    contacted = []

    async def provider(*, max_output_tokens):
        contacted.append(max_output_tokens)
        return {'usage': {'input_tokens': 3, 'output_tokens': 2}}

    async def scenario():
        client = BudgetedProvider(BudgetLimits(5, 6, 20, 5))
        await client.call(provider, input_tokens_upper_bound=4)
        with pytest.raises(BudgetExceeded):
            await client.call(provider, input_tokens_upper_bound=4)
        assert contacted == [5]
        assert client.receipt()['input_tokens_reported'] == 3

    asyncio.run(scenario())
