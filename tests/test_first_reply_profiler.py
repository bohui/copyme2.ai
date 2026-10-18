"""HTTP profiler boundaries: fresh identities, useful timings and safe output."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from scripts.profile_first_reply import first_turn


def test_http_profiler_uses_fresh_identity_and_stops_at_saved_boundary(monkeypatch, capsys):
    requests = []
    client_class = httpx.AsyncClient
    clock = iter([10, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6])
    monkeypatch.setattr('scripts.profile_first_reply.time',
        SimpleNamespace(perf_counter=lambda: next(clock)))

    def handle(request):
        requests.append(request)
        if request.url.path.endswith('/config'):
            return httpx.Response(200, json={'supabase_url': 'https://auth.example',
                'supabase_publishable_key': 'public-fixture'})
        if request.url.path == '/auth/v1/signup':
            return httpx.Response(200, json={'access_token': 'private-fixture-token',
                'user': {'id': 'fresh-user'}})
        if request.url.path.endswith('/projects'):
            return httpx.Response(201, json={'id': 'project_fresh'})
        assert request.headers['authorization'] == 'Bearer private-fixture-token'
        assert request.headers['accept'] == 'application/x-ndjson'
        assert json.loads(request.content)['project_id'] == 'project_fresh'
        events = [{'type': 'started'}, {'type': 'text_delta', 'text': ''},
            {'type': 'text_delta', 'text': 'Private fixture reply'}, {'type': 'reply_complete'},
            {'type': 'conversation_saved', 'data': {'private': 'Private saved reply'}},
            {'type': 'error', 'message': 'Optional tail is outside the measurement'}]
        return httpx.Response(200, content='\n'.join(json.dumps(event) for event in events))

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        client_class(transport=httpx.MockTransport(handle), **kwargs))
    asyncio.run(first_turn('http://localhost:3010', 10))
    output = capsys.readouterr().out
    summary = json.loads(output.splitlines()[-1])
    assert summary['kind'] == 'first_turn_summary'
    assert summary['timings']['headers_s'] == 0.1
    assert summary['timings']['first_visible_text_s'] == 0.4
    assert summary['timings']['reply_complete'] == 0.5
    assert summary['timings']['conversation_saved'] == 0.6
    assert 'private-fixture-token' not in output and 'Private' not in output
    assert len(requests) == 4


def test_http_profiler_does_not_retry_failed_signup(monkeypatch, capsys):
    calls = []
    client_class = httpx.AsyncClient

    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/config'):
            return httpx.Response(200, json={'supabase_url': 'https://auth.example',
                'supabase_publishable_key': 'public-fixture'})
        return httpx.Response(403, json={'error': 'Private backend detail'})

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        client_class(transport=httpx.MockTransport(handle), **kwargs))
    with pytest.raises(RuntimeError, match='Profiling request failed'):
        asyncio.run(first_turn('http://localhost:3010', 10))
    output = capsys.readouterr().out
    assert '403' in output and 'Private backend detail' not in output
    assert len(calls) == 2
