import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from apps.api.memory_event_worker import MemoryEventWorker


def test_retired_lane_protocol_cannot_dispatch_a_model():
    broker = AsyncMock()
    broker.rpc.side_effect = [
        {'skill': 'timeline', 'token': 'synthetic-claim'},
        {'status': 'retry'},
    ]
    def unexpected_request(request):
        raise AssertionError('A retired lane must never reach a model')
    worker = MemoryEventWorker(broker, worker_url='http://worker.test', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(unexpected_request))
    assert asyncio.run(worker.execute_lane('opaque-lane')) == {'status': 'retry'}
    assert broker.rpc.await_args_list[-1].kwargs['p_error'] == 'MEMOIR_UNAVAILABLE'


def test_provider_failure_logs_safe_timing_and_status_without_private_response(monkeypatch, caplog):
    async def fail(job, worker):
        response = httpx.Response(503, text="private-story-response", request=httpx.Request("POST", "http://worker.test"))
        response.raise_for_status()
    monkeypatch.setattr("apps.api.lifetime_memory_composer.execute_lifetime_lane", fail)
    broker = AsyncMock()
    broker.rpc.side_effect = [
        {'protocol': 'lifetime_composer_pages', 'skill': 'timeline', 'token': 'synthetic-claim', 'user_id': 'owner', 'project_id': 'project',
         'locale': 'en-AU', 'sources': [], 'context_sources': [], 'events': []},
        {'status': 'retry'},
    ]
    worker = MemoryEventWorker(broker, worker_url='http://worker.test', worker_secret='private-worker-secret',
        worker_transport=httpx.MockTransport(lambda _: httpx.Response(503, text='private-story-response')))
    assert asyncio.run(worker.execute_lane('opaque-lane')) == {'status': 'retry'}
    assert 'failure_type=HTTPStatusError http_status=503 elapsed_ms=' in caplog.text
    assert 'private-story-response' not in caplog.text
    assert 'private-worker-secret' not in caplog.text


def test_rejected_evidence_logs_a_safe_validation_reason_without_original_text(monkeypatch, caplog):
    async def fail(job, worker):
        raise ValueError("Evidence must match an authorised original source version")
    monkeypatch.setattr("apps.api.lifetime_memory_composer.execute_lifetime_lane", fail)
    broker = AsyncMock()
    broker.rpc.side_effect = [
        {'protocol': 'lifetime_composer_pages', 'skill': 'timeline', 'token': 'synthetic-claim', 'user_id': 'owner', 'project_id': 'project',
         'locale': 'zh-CN', 'sources': [], 'context_sources': [
             {'id': 'source', 'version': 1, 'text': 'private original testimony'}], 'events': []},
        {'status': 'retry'},
    ]
    proposal = {'events': [{'kind': 'event', 'title': 'private event title',
        'source_refs': [{'source_id': 'source', 'version': 1, 'quote': 'invented private quote'}]}]}
    worker = MemoryEventWorker(broker, worker_url='http://worker.test', worker_secret='private-worker-secret',
        worker_transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'reply': json.dumps(proposal)})))
    assert asyncio.run(worker.execute_lane('opaque-lane')) == {'status': 'retry'}
    assert 'validation_kind=evidence_mismatch' in caplog.text
    for private in ['private original testimony', 'private event title', 'invented private quote', 'private-worker-secret']:
        assert private not in caplog.text


@pytest.mark.parametrize('reply,kind', [
    ('private invalid response', 'invalid_json'),
    ('{"events":[{"title":"private invalid response"}]}', 'invalid_schema'),
])
def test_invalid_response_logs_category_without_private_validation_input(monkeypatch, caplog, reply, kind):
    async def fail(job, worker):
        from apps.api.memory_events import validate_extraction
        validate_extraction(json.loads(reply), [], [])
    monkeypatch.setattr("apps.api.lifetime_memory_composer.execute_lifetime_lane", fail)
    broker = AsyncMock()
    broker.rpc.side_effect = [
        {'protocol': 'lifetime_composer_pages', 'skill': 'timeline', 'token': 'synthetic-claim', 'user_id': 'owner', 'project_id': 'project',
         'locale': 'zh-CN', 'sources': [], 'context_sources': [], 'events': []},
        {'status': 'retry'},
    ]
    worker = MemoryEventWorker(broker, worker_url='http://worker.test', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'reply': reply})))
    assert asyncio.run(worker.execute_lane('opaque-lane')) == {'status': 'retry'}
    assert f'validation_kind={kind}' in caplog.text
    assert 'private invalid response' not in caplog.text


@pytest.mark.parametrize('message',[
    'summary evidence outside accepted inputs','bounded derived hints required',
    'grounded question hints required','invalid bounded strategy proposal',
])
def test_canonical_rejection_diagnostics_keep_only_fixed_validator_reason(message):
    from apps.api.memory_event_worker import _safe_rpc_failure
    request=httpx.Request('POST','https://synthetic.invalid/rest/v1/rpc/commit_lifetime_memoir_lane_page')
    response=httpx.Response(400,request=request,json={'code':'22023','message':message+': private story and secret'})
    error=httpx.HTTPStatusError('private story and secret',request=request,response=response)
    assert _safe_rpc_failure(error)==('22023',message)
