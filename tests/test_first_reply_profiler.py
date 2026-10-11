"""Profiler boundaries: fresh identities, safe output, unprivileged trials."""
import asyncio
import json

import httpx
import pytest

from scripts.profile_first_reply import collector, first_turn
from test_name_only_opening import proposal


def test_http_profiler_uses_fresh_identity_and_stops_at_saved_boundary(monkeypatch, capsys):
    requests = []
    client_class = httpx.AsyncClient

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
        events = [{'type': 'started'}, {'type': 'text_delta', 'text': 'Private fixture reply'},
            {'type': 'conversation_saved', 'data': {'private': 'Private saved reply'}},
            {'type': 'error', 'message': 'Optional tail is outside the measurement'}]
        return httpx.Response(200, content='\n'.join(json.dumps(event) for event in events))

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        client_class(transport=httpx.MockTransport(handle), **kwargs))
    asyncio.run(first_turn('http://localhost:3010', 10))
    output = capsys.readouterr().out
    assert 'first_turn_summary' in output and 'conversation_saved' in output
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


@pytest.mark.parametrize('privileged', [False, True])
def test_collector_override_is_scoped_and_drops_supervisor_privileges(monkeypatch, capsys, privileged):
    import apps.api.codex_agent as agent
    import apps.api.codex_worker_files as files

    monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL', 'default-route')
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL', 'http://gateway.example/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'private-fixture-key')
    monkeypatch.setattr('scripts.profile_first_reply.os.geteuid', lambda: 0 if privileged else 501)
    monkeypatch.setattr('scripts.profile_first_reply.os.getuid', lambda: 501)
    configs, commands, efforts = [], [], []
    monkeypatch.setattr(files, 'write_config', lambda home, root, uid, content, **options:
        configs.append((uid, content, options)))

    class Connection:
        def __init__(self, command, home, **options): commands.append(command)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, options):
            assert method == 'thread/start' and options['model'] == 'low-route'
            return {'thread': {'id': 'fixture-thread'}}
        async def turn(self, thread, text, **options):
            efforts.append(options['effort'])
            value = json.dumps(proposal(), ensure_ascii=False)
            await options['on_delta'](value)
            return value

    monkeypatch.setattr(agent, 'CodexConnection', Connection)
    asyncio.run(collector(['low'], 10, model_override='low-route'))
    assert efforts == ['low']
    assert configs[0][0] == (65534 if privileged else 501)
    assert configs[0][2]['apply_owner'] == privileged
    assert ('--reuid=65534' in commands[0]) == privileged
    output = capsys.readouterr().out
    assert '"validated": true' in output and '"appserver_turns": 1' in output
    assert 'private-fixture-key' not in output and '韩凤江' not in output
