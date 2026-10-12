import asyncio
from contextlib import asynccontextmanager
import pytest
from apps.api.lifetime_memory_publication import GovernedRequestBody
from test_lifetime_memory_transport import FENCE


class Publisher:
    def __init__(self):self.held=False;self.current=1
    @asynccontextmanager
    async def guard(self,value):
        if value['policy_epoch']!=self.current:raise ValueError('stale')
        self.held=True
        try:yield
        finally:self.held=False


def test_http_body_guard_spans_actual_consumer_write_and_releases_before_response():
    async def run():
        publisher=Publisher();body=GovernedRequestBody(b'private packet',publisher=publisher,fence=FENCE)
        iterator=body.__aiter__()
        assert await anext(iterator)==b'private packet' and publisher.held
        # Socket consumer sends this chunk while held, then asks for the next.
        with pytest.raises(StopAsyncIteration):await anext(iterator)
        assert not publisher.held
        await body.aclose()
    asyncio.run(run())


def test_http_stale_dispatch_never_yields_and_abandoned_body_releases():
    async def run():
        publisher=Publisher();body=GovernedRequestBody(b'private',publisher=publisher,fence=FENCE)
        publisher.current=2
        with pytest.raises(ValueError):await anext(body.__aiter__())
        assert not publisher.held
        publisher.current=1;body=GovernedRequestBody(b'private',publisher=publisher,fence=FENCE)
        await anext(body.__aiter__());assert publisher.held
        await body.aclose();assert not publisher.held
    asyncio.run(run())
