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


def test_transient_timeline_worker_error_is_retried_before_lane_failure():
    broker = AsyncMock()
    broker.rpc.side_effect = [
        {'skill': 'timeline', 'token': 'synthetic-claim', 'user_id': 'owner', 'project_id': 'project',
         'locale': 'en-AU', 'sources': [], 'context_sources': [], 'events': []},
        {'status': 'saved'},
    ]
    requests = []

    def transport(request):
        requests.append(request)
        if len(requests) <= 2:
            return httpx.Response(400, text='temporary upstream failure', request=request)
        return httpx.Response(200, json={'reply': '{"events": []}'}, request=request)

    worker = MemoryEventWorker(broker, worker_url='http://worker.test', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(transport))
    assert asyncio.run(worker.execute_lane('opaque-lane')) == {'status': 'saved'}
    assert len(requests) == 3
    assert not any(call.kwargs.get('p_error') == 'MEMOIR_UNAVAILABLE'
                   for call in broker.rpc.await_args_list)


def test_timeline_commit_contract_error_gets_a_fresh_model_attempt(caplog):
    broker = AsyncMock()
    commit_response = httpx.Response(400, json={
        'code': '22023', 'message': 'invalid temporal placement includes private source text in real failures'},
        request=httpx.Request('POST', 'http://supabase.test/rpc/finish_memoir_timeline'))
    broker.rpc.side_effect = [
        {'skill': 'timeline', 'token': 'synthetic-claim', 'user_id': 'owner', 'project_id': 'project',
         'locale': 'en-AU', 'sources': [], 'context_sources': [], 'events': []},
        httpx.HTTPStatusError('bad commit', request=commit_response.request, response=commit_response),
        {'status': 'saved'},
    ]
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(200, json={'reply': '{"events": []}'}, request=request)

    worker = MemoryEventWorker(broker, worker_url='http://worker.test', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(transport))
    assert asyncio.run(worker.execute_lane('opaque-lane')) == {'status': 'saved'}
    assert len(requests) == 2
    assert 'private source text' not in caplog.text
