"""Policy transport failures retain a safe cause without logging narration."""
import asyncio
import json
import logging
from types import SimpleNamespace

import httpx
import psycopg
import pytest

from apps.api import policy_review
from apps.api.lifetime_memory_policy import PolicyUnavailable


@pytest.mark.parametrize('kind,classification,status', [
    ('http', 'upstream_unavailable', 503),
    ('timeout', 'timeout', None),
    ('database', 'exception', None),
    ('validation', 'exception', None),
])
def test_pending_review_logs_underlying_failure_without_private_details(
        monkeypatch, caplog, kind, classification, status):
    private = 'PRIVATE_SOURCE_AND_CREDENTIAL'
    request = httpx.Request('POST', 'https://provider.invalid/' + private)
    errors = {
        'http': httpx.HTTPStatusError(private, request=request,
            response=httpx.Response(503, json={'detail': private}, request=request)),
        'timeout': httpx.ReadTimeout(private, request=request),
        'database': psycopg.OperationalError(private),
        'validation': ValueError(private),
    }
    error = errors[kind]
    logger = logging.getLogger('tests.policy_review_diagnostics')
    monkeypatch.setattr(policy_review, 'diagnostic_logger', logger)

    class Lease:
        lease_token = 'synthetic-lease'

        async def io(self, *args, **kwargs):
            raise error

    storage = SimpleNamespace(lifetime_rpc=lambda *args, **kwargs: None)
    conversation = '00000000-0000-4000-8000-000000000001'
    with caplog.at_level(logging.INFO, logger=logger.name), pytest.raises(PolicyUnavailable) as caught:
        asyncio.run(policy_review.review_pending_policy(storage, Lease(), conversation))

    assert caught.value.__cause__ is error
    records = [json.loads(record.message.split(' ', 1)[1]) for record in caplog.records
               if record.name == logger.name]
    assert len(records) == 1
    assert records[0] == {
        'event': 'policy_review_failed', 'request_id': conversation,
        'component': 'memoir.policy_review', 'status': 'failed', 'call_type': 'review',
        'failure_class': classification, 'error_code': type(error).__name__,
        **({'http_status': status} if status is not None else {}),
    }
    assert private not in caplog.text
    assert private not in str(caught.value)


def test_review_reports_cached_request_signature_mismatch_before_dispatch(monkeypatch, caplog):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', 'postgresql://unused.invalid/db')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', 'high')
    logger = logging.getLogger('tests.policy_review_diagnostics')
    monkeypatch.setattr(policy_review, 'diagnostic_logger', logger)

    # A live source pull can leave this startup import cached while the review
    # module is first imported from the newer checkout on the next turn.
    async def cached_request(name, payload, schema, *, model=None, base_url=None,
            api_key=None, trace_name=None, diagnostic_request_id=None, body_factory=None):
        pytest.fail('Signature mismatch must fail before provider dispatch')

    monkeypatch.setattr(policy_review, 'complete_json', cached_request)

    class Lease:
        lease_token = 'synthetic-lease'

        async def io(self, operation, name, **kwargs):
            if name == 'capture_lifetime_fence':
                return {}
            assert name == 'read_lifetime_policy_review'
            return {'text': 'PRIVATE_SOURCE', 'client_turn_id': 'synthetic-turn'}

    storage = SimpleNamespace(user_id='00000000-0000-4000-8000-000000000001',
                              lifetime_rpc=lambda *args, **kwargs: None)
    with caplog.at_level(logging.INFO, logger=logger.name), pytest.raises(PolicyUnavailable) as caught:
        asyncio.run(policy_review.review_pending_policy(storage, Lease(), 'synthetic-conversation',
                                                       model='synthetic-model'))
    assert isinstance(caught.value.__cause__, TypeError)
    assert "unexpected keyword argument 'effort'" in str(caught.value.__cause__)
    record = json.loads(caplog.records[-1].message.split(' ', 1)[1])
    assert record['event'] == 'policy_review_failed' and record['error_code'] == 'TypeError'
    assert 'PRIVATE_SOURCE' not in caplog.text
