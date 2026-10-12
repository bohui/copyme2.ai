"""Clearance failures never invent acceptance or discard accepted testimony."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException

from apps.api.lifetime_memory_runtime import lifetime_http_turn, run_lifetime_turn


@pytest.mark.parametrize('detail,expected_code', [
    ({'code': '55000', 'message': 'LIFETIME_REALTIME_CLEARANCE_REQUIRED'},
     'LIFETIME_REALTIME_CLEARANCE_REQUIRED'),
    ({'code': '55000', 'message': 'private unrelated database detail'}, None),
    ({'code': '42501', 'message': 'LIFETIME_REALTIME_CLEARANCE_REQUIRED'}, None),
])
def test_preaccept_clearance_has_no_accepted_receipt(monkeypatch, detail, expected_code):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', 'synthetic-unopened-dsn')
    response = httpx.Response(400, json=detail, request=httpx.Request('POST', 'https://db.invalid/rpc/resolve'))
    error = httpx.HTTPStatusError('private database diagnostics', request=response.request, response=response)
    storage = SimpleNamespace(lifetime_rpc=Mock(side_effect=error), user_id='00000000-0000-0000-0000-000000000060', client=Mock())
    async def turn(storage, text, lifetime_context):
        return await run_lifetime_turn(None, storage, text, publication=lifetime_context)
    runtime = SimpleNamespace(turn=turn)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(lifetime_http_turn(runtime, storage, 'My name is Joan', accept='application/json', options={}))
    actual = caught.value
    if expected_code:
        assert actual.status_code == 503
        assert actual.headers['X-Error-Code'] == expected_code
        assert 'accepted' not in str(actual.detail).lower()
    else:
        assert actual.status_code == 409
        assert not actual.headers or 'X-Error-Code' not in actual.headers
    assert 'private' not in str(actual.detail).lower()
    storage.client.close.assert_called_once()
