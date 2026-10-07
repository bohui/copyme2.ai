import asyncio
from unittest.mock import AsyncMock

import httpx

from apps.api.memory_event_worker import MemoryEventWorker


def test_provider_failure_logs_safe_timing_and_status_without_private_response(caplog):
    broker = AsyncMock()
    broker.rpc.side_effect = [
        {'skill': 'timeline', 'token': 'synthetic-claim', 'user_id': 'owner', 'project_id': 'project',
         'locale': 'en-AU', 'sources': [], 'context_sources': [], 'events': []},
        {'status': 'retry'},
    ]
    worker = MemoryEventWorker(broker, worker_url='http://worker.test', worker_secret='private-worker-secret',
        worker_transport=httpx.MockTransport(lambda _: httpx.Response(503, text='private-story-response')))
    assert asyncio.run(worker.execute_lane('opaque-lane')) == {'status': 'retry'}
    assert 'failure_type=HTTPStatusError http_status=503 elapsed_ms=' in caplog.text
    assert 'private-story-response' not in caplog.text
    assert 'private-worker-secret' not in caplog.text
