import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, Request
from fastapi.responses import Response

from scripts.canary_gateway_binding import fingerprint


@dataclass(frozen=True)
class Key:
    id: str = 'existing-consumer'
    account_assignment_scope_enabled: bool = False
    assigned_account_ids: list = field(default_factory=list)


class Payload:
    model = 'gpt-5.6-luna'
    stream = True
    def __init__(self, raw): self.raw = raw
    def to_payload(self): return self.raw


def fixture_app(*, source=None, key=None):
    from scripts.canary_gateway_actor import build_task_gateway_app
    calls = []
    class Binding:
        guard = SimpleNamespace(run_id=str(uuid4()), model='gpt-5.6-luna',
            account_binding=fingerprint('selected-row'), stop_reason=None)
        def readiness(self): return {'accepting_requests': self.guard.stop_reason is None}
    binding = Binding()
    async def validate(request: Request):
        if request.headers.get('authorization') != 'Bearer synthetic-consumer':
            raise HTTPException(401)
        return key or Key()
    async def context(): return SimpleNamespace(service='existing-authenticated-service')
    async def selected(*args, **kwargs): return source
    async def admit(*args): return None
    async def stream(request, payload, context, api_key, **kwargs):
        calls.append((context, api_key, kwargs))
        return Response('data: [DONE]\n\n', media_type='text/event-stream')
    api = SimpleNamespace(_required_capability_http_transport_denial=admit, normalize_responses_request_payload=lambda raw, **kwargs: Payload(raw),
        _select_responses_model_source=selected, _stream_responses=stream,
        _effective_optional_model_for_api_key=lambda key, model: model)
    app = build_task_gateway_app(binding=binding, api=api,
        get_proxy_context=context, validate_required_proxy_api_key=validate,
        consumer_binding=fingerprint('existing-consumer'), selected_account_id='selected-row')
    return app, binding, calls


def test_actor_keeps_required_auth_and_only_mounts_responses():
    app, binding, calls = fixture_app()
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            payload = {'model': 'gpt-5.6-luna', 'stream': True,
                'client_metadata': {'run_id': binding.guard.run_id}}
            assert (await client.post('/v1/responses', json=payload)).status_code == 401
            for path in ('/v1/responses/compact', '/v1/images/generations', '/models', '/health', '/docs'):
                assert (await client.post(path, json=payload)).status_code == 404
            response = await client.post('/v1/responses', json=payload,
                headers={'Authorization': 'Bearer synthetic-consumer'})
            assert response.status_code == 200
            assert len(calls) == 1
            _, scoped_key, options = calls[0]
            assert scoped_key.account_assignment_scope_enabled is True
            assert scoped_key.assigned_account_ids == ['selected-row']
            assert options['prefer_http_bridge'] is False
            assert options['codex_session_affinity'] is False
            assert options['skip_limit_enforcement'] is False
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['paid_source', 'wrong_consumer', 'excluded_account', 'stopped', 'wrong_run', 'wrong_model', 'photo'])
def test_actor_rejects_before_subscription_or_paid_dispatch(kind):
    key = Key(id='wrong-consumer') if kind == 'wrong_consumer' else Key(
        account_assignment_scope_enabled=True, assigned_account_ids=['other-row']) if kind == 'excluded_account' else None
    app, binding, calls = fixture_app(source=object() if kind == 'paid_source' else None, key=key)
    if kind == 'stopped': binding.guard.stop_reason = 'request_limit'
    payload = {'model': 'gpt-5.6-luna', 'stream': True,
        'client_metadata': {'run_id': binding.guard.run_id}}
    if kind == 'wrong_run': payload['client_metadata']['run_id'] = str(uuid4())
    if kind == 'wrong_model': payload['model'] = 'other'
    if kind == 'photo': payload['input'] = [{'type': 'input_image', 'image_url': 'https://example.com/image'}]
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/v1/responses', json=payload,
                headers={'Authorization': 'Bearer synthetic-consumer'})
            assert response.status_code in (400, 403, 409, 429)
            assert calls == []
    asyncio.run(run())


def frame(op, identity, **fields):
    import json
    from scripts.canary_gateway_actor import VERSION
    return (json.dumps({'version': VERSION, 'id': identity, 'op': op, **fields}) + '\n').encode()


def hello():
    return frame('init', 'init-1', run_id=str(uuid4()), source_revision='a' * 40,
        account_binding='b' * 64, consumer_authorization='Bearer synthetic-consumer',
        challenge='c' * 32, source_sha256={'actor': 'd' * 64})


class RuntimeDouble:
    source_sha256 = {'actor': 'd' * 64}
    consumer_binding = 'e' * 64
    def __init__(self):
        self.entered = asyncio.Event()
        self.cancelled = False
        self.closed = False
    def receipt(self): return {'cleanup': {'closed': self.closed, 'active_finished': self.cancelled}}
    async def responses(self, headers, body):
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True
    async def stop(self):
        self.closed = True
        return self.receipt()


@pytest.mark.parametrize('signal', ['eof', 'stop', 'concurrent', 'duplicate'])
def test_stdio_actor_cancels_active_generation_on_stop_eof_or_bad_frame(signal):
    from scripts.canary_gateway_actor import serve_frames
    import json
    async def run():
        queue = asyncio.Queue()
        output = []
        runtime = RuntimeDouble()
        async def factory(config): return runtime
        async def emit(raw): output.append(json.loads(raw))
        await queue.put(hello())
        await queue.put(frame('responses', 'request-1', headers={'authorization': 'Bearer synthetic-consumer'}, body={}))
        actor = asyncio.create_task(serve_frames(queue.get, emit, runtime_factory=factory))
        await asyncio.wait_for(runtime.entered.wait(), 2)
        if signal == 'eof': await queue.put(b'')
        elif signal == 'stop': await queue.put(frame('stop', 'stop-1'))
        elif signal == 'concurrent': await queue.put(frame('responses', 'request-2', headers={}, body={}))
        else: await queue.put(frame('receipt', 'request-1'))
        if signal in {'concurrent', 'duplicate'}:
            with pytest.raises(ValueError):
                await asyncio.wait_for(actor, 2)
        else:
            await asyncio.wait_for(actor, 2)
        assert runtime.closed and runtime.cancelled
        assert all(item['op'] != 'responses' for item in output)
        if signal == 'stop':
            assert output[-1]['op'] == 'stop'
            assert output[-1]['receipt']['cleanup'] == {'closed': True, 'active_finished': True}
        assert 'synthetic-consumer' not in json.dumps(output)
    asyncio.run(run())


def test_stdio_actor_sanitizes_by_refusing_echoed_credentials():
    from scripts.canary_gateway_actor import serve_frames
    async def run():
        queue = asyncio.Queue()
        output = []
        runtime = RuntimeDouble()
        runtime.source_sha256 = {'unsafe': 'synthetic-consumer'}
        async def factory(config): return runtime
        async def emit(raw): output.append(raw)
        await queue.put(hello())
        with pytest.raises(ValueError, match='unsafe'):
            await serve_frames(queue.get, emit, runtime_factory=factory)
        assert output == []
        assert runtime.closed
    asyncio.run(run())


def test_stdio_actor_rejects_duplicate_json_keys_before_runtime_import():
    from scripts.canary_gateway_actor import serve_frames
    async def run():
        async def read(): return b'{"version":"memoir-canary-stdio/1","id":"one","id":"two"}\n'
        async def emit(raw): pytest.fail('Invalid init emitted a frame')
        async def factory(config): pytest.fail('Invalid init reached runtime')
        with pytest.raises(ValueError, match='Duplicate'):
            await serve_frames(read, emit, runtime_factory=factory)
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['json', 'sse'])
def test_runtime_and_frame_redaction_removes_json_escaped_consumer_token(kind):
    from scripts.canary_gateway_actor import InstalledActorRuntime, serve_frames
    import json
    async def run():
        queue = asyncio.Queue()
        output = []
        escaped = '{"error":"\\u0073ynthetic-consumer"}'
        body = escaped if kind == 'json' else 'data: ' + escaped + '\n\n'
        content_type = 'application/json' if kind == 'json' else 'text/event-stream'
        class Runtime(InstalledActorRuntime):
            source_sha256 = {'actor': 'd' * 64}
            consumer_binding = 'e' * 64
            def __init__(self):
                self._authorization = 'Bearer synthetic-consumer'
                self._closed = False
                self.binding = SimpleNamespace(readiness=lambda: {'accepting_requests': True},
                    guard=SimpleNamespace(stop=lambda reason: None))
                self.client = httpx.AsyncClient(base_url='http://synthetic.invalid', transport=httpx.MockTransport(lambda request:
                    httpx.Response(400, text=body, headers={'content-type': content_type})))
            def receipt(self): return {'cleanup': {'closed': self._closed}}
            async def stop(self):
                self._closed = True
                await self.client.aclose()
                return self.receipt()
        runtime = Runtime()
        async def factory(config): return runtime
        async def emit(raw):
            value = json.loads(raw)
            output.append(value)
            if value['op'] == 'init':
                await queue.put(frame('responses', 'request-1', headers={'authorization': 'Bearer synthetic-consumer'}, body={}))
            elif value['op'] == 'responses':
                await queue.put(frame('stop', 'stop-1'))
        await queue.put(hello())
        await serve_frames(queue.get, emit, runtime_factory=factory)
        returned = next(value['body'] for value in output if value['op'] == 'responses')
        parsed = json.loads(returned.removeprefix('data: ').strip())
        assert parsed['error'] == '[REDACTED]'
        assert 'synthetic-consumer' not in parsed['error']
    asyncio.run(run())


def test_crypto_setup_requires_existing_key_and_never_calls_creator(tmp_path):
    from scripts.canary_gateway_actor import require_existing_crypto
    from contextlib import ExitStack
    key_path = tmp_path / 'missing' / 'key'
    calls = []
    crypto = SimpleNamespace(get_settings=lambda: SimpleNamespace(encryption_key_file=key_path),
        _get_or_create_key=lambda path: calls.append(path),
        TokenEncryptor=lambda **kwargs: kwargs)
    with ExitStack() as stack:
        with pytest.raises((FileNotFoundError, ValueError)):
            require_existing_crypto(crypto, stack)
    assert calls == [] and not key_path.parent.exists()
    key_path.parent.mkdir()
    key_path.write_bytes(b'synthetic-existing-key')
    with ExitStack() as stack:
        require_existing_crypto(crypto, stack)
        assert crypto._get_or_create_key(key_path) == b'synthetic-existing-key'
        with pytest.raises(ValueError): crypto._get_or_create_key(tmp_path / 'new-key')
    assert calls == [] and not (tmp_path / 'new-key').exists()


def test_owned_service_never_refreshes_or_archives(tmp_path):
    from scripts.canary_gateway_actor import restrict_owned_service
    from contextlib import ExitStack
    calls = []
    async def refresh(*args, **kwargs): calls.append('refresh')
    instance = SimpleNamespace(_ensure_fresh=refresh, _ensure_fresh_with_budget=refresh)
    core = SimpleNamespace(archive_json=lambda *a, **kw: calls.append('archive'),
        archive_text=lambda *a, **kw: calls.append('archive'))
    guard = SimpleNamespace(account_binding=fingerprint('selected-row'), stop=lambda reason: calls.append('stop'))
    async def run():
        with ExitStack() as stack:
            restrict_owned_service(instance, core, guard, stack)
            account = SimpleNamespace(id='selected-row')
            assert await instance._ensure_fresh_with_budget(account) is account
            with pytest.raises(RuntimeError): await instance._ensure_fresh(account, force=True)
            core.archive_json({'secret': 'synthetic-only'})
            core.archive_text('synthetic-only')
    asyncio.run(run())
    assert calls == ['stop']


@pytest.mark.parametrize('status', [401, 429, 500])
def test_runtime_api_failures_stop_run_before_another_app_request(status):
    from scripts.canary_gateway_actor import InstalledActorRuntime
    async def run():
        calls = []
        runtime = InstalledActorRuntime()
        runtime._closed = False
        runtime._authorization = 'Bearer synthetic-consumer'
        guard = SimpleNamespace(stop_reason=None)
        guard.stop = lambda reason: setattr(guard, 'stop_reason', reason)
        runtime.binding = SimpleNamespace(guard=guard,
            readiness=lambda: {'accepting_requests': guard.stop_reason is None})
        def respond(request):
            calls.append(1)
            return httpx.Response(status, json={'error': 'quota or auth unavailable'})
        async with httpx.AsyncClient(base_url='http://synthetic.invalid', transport=httpx.MockTransport(respond)) as client:
            runtime.client = client
            await runtime.responses({'authorization': 'Bearer synthetic-consumer'}, {})
            assert guard.stop_reason == 'upstream_failed_or_incomplete'
            await runtime.responses({'authorization': 'Bearer synthetic-consumer'}, {})
            assert len(calls) == 1
    asyncio.run(run())


def test_cleanup_keeps_dispatch_fenced_and_attempts_all_stages_after_failure():
    from scripts.canary_gateway_actor import InstalledActorRuntime, _RETAINED_DISPATCH_FENCES
    from contextlib import ExitStack, contextmanager
    async def run():
        state = {'installed': False}
        calls = []
        @contextmanager
        def fence():
            state['installed'] = True
            try: yield
            finally: state['installed'] = False
        runtime = InstalledActorRuntime()
        runtime._closed = False
        runtime._authorization = 'Bearer synthetic-consumer'
        runtime.consumer_binding = 'e' * 64
        runtime._stack = ExitStack()
        runtime._stack.enter_context(fence())
        guard = SimpleNamespace(stop_reason=None)
        guard.stop = lambda reason: setattr(guard, 'stop_reason', reason)
        async def guard_stop():
            assert state['installed']
            calls.append('guard')
            return {'cleanup': {'closed': True, 'active_finished': True}}
        runtime.binding = SimpleNamespace(guard=guard, stop=guard_stop,
            receipt=lambda: {'cleanup': {'closed': True, 'active_finished': True}})
        async def fail_client():
            assert state['installed']
            calls.append('client')
            raise RuntimeError('synthetic-private-close-error')
        async def drain(**kwargs):
            assert state['installed']
            calls.append('drain')
            return True
        async def http_close():
            assert state['installed']
            calls.append('http')
        async def db_close():
            assert state['installed']
            calls.append('db')
        runtime.client = SimpleNamespace(aclose=fail_client)
        runtime.service_instance = SimpleNamespace(drain_persistence_tasks=drain)
        runtime.http = SimpleNamespace(close_http_client=http_close)
        runtime.db = SimpleNamespace(close_db=db_close)
        before = len(_RETAINED_DISPATCH_FENCES)
        try:
            receipt = await runtime.stop()
            assert calls == ['guard', 'client', 'drain', 'http', 'db']
            assert receipt['actor_cleanup']['finished'] is False
            assert receipt['actor_cleanup']['client_closed'] is False
            assert receipt['actor_cleanup']['database_closed'] is True
            assert state['installed']
            await runtime.stop()
            assert calls == ['guard', 'client', 'drain', 'http', 'db']
        finally:
            for stack in _RETAINED_DISPATCH_FENCES[before:]: stack.close()
            del _RETAINED_DISPATCH_FENCES[before:]
    asyncio.run(run())


def test_stop_closes_runtime_even_when_generation_defers_cancellation():
    from scripts.canary_gateway_actor import serve_frames, _OWNED_PENDING_TASKS
    import json
    async def run():
        queue, output = asyncio.Queue(), []
        release = asyncio.Event()
        class DeferringRuntime(RuntimeDouble):
            async def responses(self, headers, body):
                self.entered.set()
                while not release.is_set():
                    try: await release.wait()
                    except asyncio.CancelledError: continue
                self.cancelled = True
                return 503, {'content-type': 'application/json'}, '{}'
        runtime = DeferringRuntime()
        async def factory(config): return runtime
        async def emit(raw): output.append(json.loads(raw))
        await queue.put(hello())
        await queue.put(frame('responses', 'request-1', headers={}, body={}))
        actor = asyncio.create_task(serve_frames(queue.get, emit, runtime_factory=factory))
        await runtime.entered.wait()
        await queue.put(frame('stop', 'stop-1'))
        try:
            await asyncio.wait_for(actor, 2)
            assert runtime.closed
            assert output[-1]['op'] == 'stop'
            assert output[-1]['receipt']['cleanup']['active_finished'] is False
        finally:
            release.set()
            if _OWNED_PENDING_TASKS:
                await asyncio.wait_for(asyncio.gather(*tuple(_OWNED_PENDING_TASKS), return_exceptions=True), 2)
    asyncio.run(run())


def test_real_runtime_marks_deferred_pre_guard_operation_cleanup_uncertain(tmp_path):
    from scripts.canary_gateway_actor import (InstalledActorRuntime, serve_frames,
        _OWNED_PENDING_TASKS, _RETAINED_DISPATCH_FENCES)
    from contextlib import ExitStack
    import json
    async def run():
        queue, output = asyncio.Queue(), []
        entered, release = asyncio.Event(), asyncio.Event()
        runtime = InstalledActorRuntime()
        runtime._closed = False
        runtime._authorization = 'Bearer synthetic-consumer'
        runtime._stack = ExitStack()
        runtime._state_dir = tmp_path
        runtime.source_sha256 = {'actor': 'd' * 64}
        runtime.consumer_binding = 'e' * 64
        guard = SimpleNamespace(stop_reason=None, active_finished=True)
        guard.stop = lambda reason: setattr(guard, 'stop_reason', reason)
        async def guard_stop():
            return {'cleanup': {'closed': True, 'active_finished': guard.active_finished}}
        runtime.binding = SimpleNamespace(guard=guard, stop=guard_stop,
            readiness=lambda: {'accepting_requests': guard.stop_reason is None},
            receipt=lambda: {'cleanup': {'closed': True, 'active_finished': guard.active_finished}})
        async def post(*args, **kwargs):
            entered.set()
            while not release.is_set():
                try: await release.wait()
                except asyncio.CancelledError: continue
            return httpx.Response(200, text='data: {}\n\n', headers={'content-type': 'text/event-stream'})
        async def close(): pass
        async def drain(**kwargs): return True
        runtime.client = SimpleNamespace(post=post, aclose=close)
        runtime.service_instance = SimpleNamespace(drain_persistence_tasks=drain)
        runtime.http = SimpleNamespace(close_http_client=close)
        runtime.db = SimpleNamespace(close_db=close)
        async def factory(config): return runtime
        async def emit(raw): output.append(json.loads(raw))
        await queue.put(hello())
        await queue.put(frame('responses', 'request-1', headers={'authorization': 'Bearer synthetic-consumer'}, body={}))
        before = len(_RETAINED_DISPATCH_FENCES)
        actor = asyncio.create_task(serve_frames(queue.get, emit, runtime_factory=factory))
        await entered.wait()
        await queue.put(frame('stop', 'stop-1'))
        try:
            await asyncio.wait_for(actor, 2)
            assert output[-1]['receipt']['cleanup']['active_finished'] is False
            assert output[-1]['receipt']['actor_cleanup']['finished'] is False
            saved = json.loads((tmp_path / 'cleanup.json').read_text())
            assert saved['cleanup']['active_finished'] is False
            assert saved['actor_cleanup']['finished'] is False
            assert _OWNED_PENDING_TASKS
        finally:
            release.set()
            await asyncio.wait_for(asyncio.gather(*tuple(_OWNED_PENDING_TASKS), return_exceptions=True), 2)
            for stack in _RETAINED_DISPATCH_FENCES[before:]: stack.close()
            del _RETAINED_DISPATCH_FENCES[before:]
    asyncio.run(run())
