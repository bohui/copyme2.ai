"""Canonical SQL retry/commit fences with an explicitly controlled model seam."""
import asyncio
import json
import time
from types import SimpleNamespace

import httpx
from jsonschema import Draft202012Validator
import pytest

from apps.api.lifetime_memory_composer import _extract
from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, LanePublication, run_bounded_lane
from apps.api.lifetime_memory_publication import PublicationUnavailable
from test_agent_commit_postgres import database as base_database, OWNER, OTHER
from test_background_profile_workflow import Broker
from test_conversation_reply_transport import events, sse
from test_lifetime_composer_capacity import service, create_lane
from test_lifetime_memory_postgres import sql, resolve, event_database, private_database, attachment_database  # noqa: F401
from test_shared_memory_events_postgres import literal, rpc


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True, deadline=time.monotonic() + 300)


@pytest.mark.parametrize('quote,fault', [
    ('We folded a paper boat.', 'none'),
    ('我们折了一只纸船。', 'none'),
    ('We folded a paper boat.', 'source_before_send'),
    ('We folded a paper boat.', 'source_before_commit'),
    ('We folded a paper boat.', 'owner'),
    ('We folded a paper boat.', 'wrong_span'),
])
def test_failed_second_window_resumes_without_losing_first_commit_or_weakening_fences(sql, tmp_path, monkeypatch, quote, fault):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'synthetic-byte-bpe')
    identity = resolve(sql)
    first_quote = '🌱 I learned pottery.'
    text = first_quote + ' Catalog notes.' * 140 + ' ' + quote + ' ' + quote
    assert text.index(quote) > 2048
    source = rpc(sql, 'accept_user_narrator_source',
        f"{literal(identity['project_id'])},'00000000-0000-4000-8000-000000000001',{literal(text)}")
    lane = create_lane(sql, identity)
    current = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    publisher = LanePublication(sql.publication_dsn, authenticated_owner=OWNER)
    mode = 'reject'
    sent = []
    changed = False

    def withdraw():
        nonlocal changed
        rpc(sql, 'change_user_narrator_source', f"{literal(identity['project_id'])},'{source['id']}',1,'withdraw',null")
        changed = True

    class Provider(httpx.AsyncBaseTransport):
        def __init__(self, bounded):
            self.bounded = bounded

        async def handle_async_request(self, request):
            if mode == 'repair' and fault == 'source_before_send' and not changed:
                withdraw()
            body = json.loads(b''.join([chunk async for chunk in request.stream]))
            payload = json.loads(body['input'])['payload']
            window = payload['sources'][0]
            sent.append((self.bounded.fence.page_number, payload.get('retry_reason')))
            ref = dict(source_id=source['id'], version=1,
                quote=first_quote if self.bounded.fence.page_number == 0 else quote,
                char_start=None, char_end=None, attribution=None)
            if mode == 'repair' and payload.get('retry_reason') == 'PAGE_AMBIGUOUS':
                schema = body['text']['format']['schema']
                validator = Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/EvidenceRef'})
                assert not validator.is_valid(ref)
                row = next(row for row in payload['quote_occurrences']['quotes'] if row['quote'] == quote)
                ref.update(row['spans'][1])
                if fault == 'wrong_span':
                    ref['char_start'] += 1
                    assert validator.is_valid(ref), 'Schema alone cannot prove the quoted substring'
                else:
                    validator.validate(ref)
                    assert window['text'][ref['char_start']:ref['char_end']] == quote
            result = {'events': [dict(kind='event', title='First memory' if self.bounded.fence.page_number == 0 else 'Repeated memory', source_refs=[ref])]}
            return httpx.Response(200, content=sse(events(json.dumps(result))))

    async def worker(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])
        return httpx.Response(200, json=await run_bounded_lane(command=['must-not-start'], home_root=tmp_path,
            base_url='https://provider.invalid/v1', api_key='fixture-span-key', model=bounded.budget.model,
            bounded_lane=bounded, publisher=publisher, provider_transport=Provider(bounded), timeout=5))

    scope = SimpleNamespace(broker=Broker(sql), worker_url='https://worker.invalid', worker_secret='fixture',
        worker_transport=httpx.MockTransport(worker), lane_publisher=publisher)
    result = asyncio.run(_extract(current, scope))
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{current['token']}',0,{literal(result)}")
    current = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{current['token']}'")
    assert current['page_number'] == 1 and current['core_start'] == 2048
    assert current['source']['char_start'] == 1792
    with pytest.raises(ValueError, match='ambiguous'):
        asyncio.run(_extract(current, scope))
    assert sent == [(0, None), (1, None), (1, 'PAGE_AMBIGUOUS'), (1, 'PAGE_AMBIGUOUS')]
    assert sql('select next_offset from public.user_lifetime_source_extraction;').stdout.strip() == '2048'
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '1'
    first_id = rpc(sql, 'read_user_memory_events', literal(identity['project_id']))['events'][0]['id']
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{current['token']}'")
    resumed = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert resumed['token'] != current['token'] and resumed['page_number'] == 1
    mode = 'repair'
    if fault == 'owner':
        publisher = LanePublication(sql.publication_dsn, authenticated_owner=OTHER)
        scope.lane_publisher = publisher
    if fault in {'owner', 'source_before_send'}:
        with pytest.raises(PublicationUnavailable):
            asyncio.run(_extract(resumed, scope))
        assert len(sent) == 4, 'Unavailable authority must release no provider body'
        assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '1'
        return
    if fault == 'wrong_span':
        with pytest.raises(ValueError, match='ambiguous'):
            asyncio.run(_extract(resumed, scope))
        assert sent[-3:] == [(1, None), (1, 'PAGE_AMBIGUOUS'), (1, 'PAGE_AMBIGUOUS')]
        assert sql('select next_offset from public.user_lifetime_source_extraction;').stdout.strip() == '2048'
        assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '1'
        return
    result = asyncio.run(_extract(resumed, scope))
    assert sent[-2:] == [(1, None), (1, 'PAGE_AMBIGUOUS')]
    if fault == 'source_before_commit':
        withdraw()
        with pytest.raises(AssertionError):
            service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{resumed['token']}',1,{literal(result)}")
        assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '1'
        return
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{resumed['token']}',1,{literal(result)}")
    complete = service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{resumed['token']}'")
    assert complete['retrieval_complete']
    saved = rpc(sql, 'read_user_memory_events', literal(identity['project_id']))['events']
    assert len(saved) == 2 and first_id in {event['id'] for event in saved}
    selected = next(event for event in saved if event['id'] != first_id)['source_refs'][0]
    start = text.find(quote, text.index(quote) + 1)
    assert (selected['char_start'], selected['char_end']) == (start, start + len(quote))
    assert text[selected['char_start']:selected['char_end']] == quote
    assert sql('select processing_status from public.user_narrator_source;').stdout.strip() == 'succeeded'
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '2'
