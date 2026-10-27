import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from apps.api.memory_event_worker import MemoirLaneBroker, MemoryEventWorker


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
    'exact admitted background continuity evidence required',
    'background continuity identity conflict', 'exact current attribution evidence required',
    'profile commit deferred during interactive turn', 'exact current profile evidence required',
    'stale canonical profile admission', 'skill page changed',
    'question evidence span must match the referenced passage',
])
def test_canonical_rejection_diagnostics_keep_only_fixed_validator_reason(message):
    from apps.api.memory_event_worker import _safe_rpc_failure
    request=httpx.Request('POST','https://synthetic.invalid/rest/v1/rpc/commit_lifetime_memoir_lane_page')
    response=httpx.Response(400,request=request,json={'code':'22023','message':message+': private story and secret'})
    error=httpx.HTTPStatusError('private story and secret',request=request,response=response)
    assert _safe_rpc_failure(error)==('22023',message)


@pytest.mark.parametrize('code,message,status', [
    ('22023', 'exact admitted background continuity evidence required', 400),
    ('PT409', 'background continuity identity conflict', 409),
    ('22023', 'private unknown database message', 400),
])
def test_commit_failure_logs_actual_page_reason_and_retry_without_payload(monkeypatch, caplog, code, message, status):
    job = {'protocol': 'lifetime_composer_pages', 'skill': 'timeline', 'token': 'private-claim-token'}
    def database(request):
        name = request.url.path.rsplit('/', 1)[-1]
        if name == 'claim_memoir_lane':
            return httpx.Response(200, json=job)
        if name == 'commit_lifetime_memoir_lane_page':
            return httpx.Response(status, json={'code': code, 'message': message + ': private story',
                'details': 'private database details', 'hint': 'private database hint'})
        assert name == 'fail_memoir_lane'
        return httpx.Response(200, json={'status': 'retry'})
    async def commit(job, worker):
        return await worker.broker.rpc('commit_lifetime_memoir_lane_page',
            p_lane_id='opaque-lane', p_token=job['token'], p_page_number=3, p_page_digest='a' * 64,
            p_result={'continuity_updates': [{'data': {'text': 'private testimony'}}]})
    monkeypatch.setattr('apps.api.lifetime_memory_composer.execute_lifetime_lane', commit)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(database)) as client:
            broker = MemoirLaneBroker(url='http://database.test', key='private-service-key', client=client)
            return await MemoryEventWorker(broker, worker_url='http://worker.test',
                worker_secret='private-worker-secret').execute_lane('opaque-lane')
    assert asyncio.run(run()) == {'status': 'retry'}
    assert 'memoir_lane rpc_failure' in caplog.text
    assert 'rpc_name=commit_lifetime_memoir_lane_page' in caplog.text
    assert 'lane_id=opaque-lane page_number=3 page_digest=' + 'a' * 64 in caplog.text
    assert f'rpc_code={code} rpc_kind={message if not message.startswith("private") else None}' in caplog.text
    assert 'memoir_lane recovery lane_id=opaque-lane skill=timeline status=retry' in caplog.text
    for private in ('private story', 'private unknown database message', 'private database details',
            'private database hint', 'private-claim-token', 'private-service-key',
            'private-worker-secret', 'private testimony'):
        assert private not in caplog.text


@pytest.mark.parametrize('wrapped', [False, True])
def test_database_admission_reason_survives_publication_wrapper(wrapped):
    from psycopg.errors import SerializationFailure
    from apps.api.lifetime_memory_lane_engine import PublicationUnavailable
    from apps.api.memory_event_worker import _safe_rpc_failure
    error = SerializationFailure('stale canonical profile admission: private database detail')
    if wrapped:
        failure = PublicationUnavailable('private wrapper detail')
        failure.__cause__ = error
    else:
        failure = error
    assert _safe_rpc_failure(failure) == ('40001', 'stale canonical profile admission')


def test_progress_failure_logs_profile_phase_and_safe_database_reason(monkeypatch, caplog):
    from psycopg import AsyncConnection
    from psycopg.errors import SerializationFailure
    from apps.api.background_skills import _record
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', 'private-database-url')
    monkeypatch.setattr(AsyncConnection, 'connect', AsyncMock(side_effect=SerializationFailure(
        'stale canonical profile admission: private database detail')))
    fence = {'lane_id': 'opaque-lane', 'snapshot_id': 'opaque-snapshot', 'page_number': 3,
        'token': 'private-claim-token', 'source': {'text': 'private testimony'}}
    asyncio.run(_record('record_lifetime_skill_phase', (fence, 'profile', 'completed', 'invocation')))
    assert 'function=record_lifetime_skill_phase' in caplog.text
    assert 'lane_id=opaque-lane snapshot_id=opaque-snapshot page_number=3 phase=profile status=completed' in caplog.text
    assert 'rpc_code=40001 rpc_kind=stale canonical profile admission' in caplog.text
    for private in ('private-database-url', 'private database detail', 'private-claim-token', 'private testimony'):
        assert private not in caplog.text
