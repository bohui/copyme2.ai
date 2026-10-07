"""Narrow authenticated task ingress for the installed gateway.

Construction is dependency-injected so offline tests never import the installed
runtime or read its credentials. Native bootstrap must pass the existing factory
and required-auth dependencies after verifying their exact installed source.
"""
from pathlib import Path
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, '/app')

from dataclasses import replace
import re

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Security

from scripts.canary_gateway_binding import _text_only, fingerprint


def build_task_gateway_app(*, binding, api, get_proxy_context,
        validate_required_proxy_api_key, consumer_binding, selected_account_id):
    """Preserve existing consumer auth/policy/accounting, narrow run and routing.

    This function does not start a listener, import runtime auth, manufacture a
    key, change stored assignments or activate a binding. The native bootstrap
    owns those in-process lifecycle steps and the isolated actor's source proof.
    """
    if (not re.fullmatch('[a-f0-9]{64}', consumer_binding)
            or fingerprint(selected_account_id) != binding.guard.account_binding):
        raise ValueError('Explicit existing consumer and account binding are required')
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post('/v1/responses')
    async def responses(request: Request, raw: dict = Body(...),
            context=Depends(get_proxy_context),
            api_key=Security(validate_required_proxy_api_key)):
        # Required existing auth is evaluated even after the task stops. Never
        # replace it with a no-auth loopback assumption or task-generated key.
        key_id = getattr(api_key, 'id', None)
        if not isinstance(key_id, str) or fingerprint(key_id) != consumer_binding:
            raise HTTPException(403, 'canary_consumer_mismatch')
        denial = await api._required_capability_http_transport_denial(request, api_key)
        if denial is not None:
            return denial
        if not binding.readiness()['accepting_requests']:
            raise HTTPException(429, 'canary_not_accepting_requests')
        if (raw.get('model') != binding.guard.model or not _text_only(raw)
                or not isinstance(raw.get('client_metadata'), dict)
                or raw['client_metadata'].get('run_id') != binding.guard.run_id):
            raise HTTPException(400, 'canary_payload_forbidden')
        if (getattr(api_key, 'enforced_model', None) not in (None, binding.guard.model)
                or getattr(api_key, 'enforced_service_tier', None) not in (None, 'auto', 'default')
                or getattr(api_key, 'enforced_reasoning_effort', None) not in (None, 'low')):
            raise HTTPException(403, 'canary_existing_policy_incompatible')
        if (api_key.account_assignment_scope_enabled
                and selected_account_id not in api_key.assigned_account_ids):
            raise HTTPException(403, 'canary_account_not_authorized')
        # This is a transient narrowing of an already-authorized consumer's
        # account set, never an expansion or database/API-key configuration write.
        scoped_key = replace(api_key, account_assignment_scope_enabled=True,
            assigned_account_ids=[selected_account_id])
        try:
            payload = api.normalize_responses_request_payload(raw, openai_compat=True)
        except Exception:
            raise HTTPException(400, 'canary_payload_invalid') from None
        if payload.model != binding.guard.model:
            raise HTTPException(400, 'canary_model_mismatch')
        raw_model = api._effective_optional_model_for_api_key(scoped_key, payload.model)
        source_selection = await api._select_responses_model_source(payload.model,
            scoped_key, raw_model=raw_model, require_streaming=True)
        if source_selection is not None:
            # Reject, rather than silently falling back from a configured paid
            # model-source route to a different provider/account contract.
            raise HTTPException(409, 'canary_paid_source_forbidden')
        # Use the original authenticated subscription processing and ordinary
        # usage reservation/settlement. Explicit false avoids bridge/owner
        # forwarding, compaction triggers, WS prewarm and server recovery loops.
        return await api._stream_responses(request, payload, context, scoped_key,
            codex_session_affinity=False, openai_cache_affinity=False,
            prefer_http_bridge=False, skip_limit_enforcement=False,
            api_key_policy_already_applied=False, enforce_openai_sdk_contract=True)

    return app


# The actor is deliberately separate from app.main.lifespan: that lifespan
# migrates, creates bootstrap tokens, starts schedulers and purges bridge rows.
BOOTSTRAP_SOURCE_SHA256 = {
    'core/crypto.py': 'cd4cf6195a978a0cd7079cd7d838aad9c478d4a977edb06ac498999961a221c6',
    'core/config/settings.py': 'c1d3851c2b3a1e999f7f1a073011d15c73b9e9fa8044a2257bd97abc829ed0e6',
    'dependencies.py': '6a95fd1215b0b018e2117a010726d9b86cd61a725bf56fb82496500880470ede',
    'core/auth/dependencies.py': '2a97757d0a837cb3deca50da75a977111e143c16e64c41a30ce67a78e2b012c6',
    'db/session.py': '23b0561057c0808495819535691a292c0bff408dbf332e65f4518456b546a62e',
    'core/clients/http.py': '5c1ea55505f962556cee88b30462272d43f086d29da3f10bd4f3b8bec8de8258',
    'main.py': '8a7309d2c7de5b555c943408f84e4238fd6d65e424122a9d0fa3516e55f9cc7c',
    'modules/proxy/api.py': 'f396d8d0a2cb54d49f3ac757cdc91ca9ab7d823be3e8dd6b61715898645857dc',
    'modules/api_keys/service.py': '41cff971be2458647af65c9959ea1800468b7c9672319cd3414f3ad5431e7c5e',
}
# Keep a stopped actor's dispatch fence alive until its one-shot interpreter
# exits. Late cancelled tasks must never regain unguarded dispatch functions.
_RETAINED_DISPATCH_FENCES = []
_OWNED_PENDING_TASKS = set()

VERSION = 'memoir-canary-stdio/1'
MAX_FRAME_BYTES = 16 * 1024 * 1024


def expected_source_hashes():
    import hashlib
    from pathlib import Path
    from scripts.canary_gateway_binding import SOURCE_SHA256
    hashes = {**SOURCE_SHA256, **BOOTSTRAP_SOURCE_SHA256}
    root = Path(__file__).resolve().parents[1]
    for name in ('canary_send_guard.py', 'canary_gateway_binding.py', 'canary_gateway_actor.py'):
        hashes['scripts/' + name] = hashlib.sha256((root / 'scripts' / name).read_bytes()).hexdigest()
    return hashes


def verify_installed_sources(root):
    import hashlib
    from scripts.canary_gateway_binding import SOURCE_SHA256
    for relative, expected in {**SOURCE_SHA256, **BOOTSTRAP_SOURCE_SHA256}.items():
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Installed gateway source differs from reviewed source')


def require_existing_crypto(crypto, stack):
    """Read a pre-existing runtime key; replace creation fallback with read-only."""
    key_path = Path(crypto.get_settings().encryption_key_file)
    key = key_path.read_bytes()
    if not key:
        raise ValueError('Existing runtime encryption key unavailable')
    crypto.TokenEncryptor(key=key)  # nonempty explicit key never calls creator
    original = crypto._get_or_create_key
    def existing_only(path):
        target = Path(path)
        if target.resolve() != key_path.resolve() or target.read_bytes() != key:
            raise ValueError('Existing runtime encryption key changed or unavailable')
        return key
    crypto._get_or_create_key = existing_only
    stack.callback(setattr, crypto, '_get_or_create_key', original)


def restrict_owned_service(instance, core, guard, stack):
    """No refresh/resend or auxiliary archives in this isolated task service."""
    async def existing_account(account, *, force=False, **kwargs):
        if force or fingerprint(account.id) != guard.account_binding:
            guard.stop('upstream_failed_or_incomplete')
            raise RuntimeError('Task account refresh forbidden')
        # No freshness assertion: an expired token may fail its one guarded
        # request. It must never trigger token refresh, persistence or resend.
        return account
    for name in ('_ensure_fresh', '_ensure_fresh_with_budget'):
        original = getattr(instance, name)
        setattr(instance, name, existing_account)
        stack.callback(setattr, instance, name, original)
    for name in ('archive_json', 'archive_text'):
        original = getattr(core, name)
        setattr(core, name, lambda *args, **kwargs: None)
        stack.callback(setattr, core, name, original)


class InstalledActorRuntime:
    """Existing authenticated gateway factory, owned process-only lifecycle.

    No Codex executable is assumed inside this Linux runtime. An authorized host
    bridge can relay existing gateway consumer authorization, but a credential
    for another destination must never be used here to discover compatibility.
    """
    @classmethod
    async def start(cls, config):
        import asyncio
        from contextlib import ExitStack
        import importlib
        from pathlib import Path
        from uuid import UUID
        import httpx
        from scripts.canary_gateway_binding import InstalledGatewayBinding
        from scripts.canary_send_guard import CanarySendGuard
        if (str(UUID(config['run_id'])) != config['run_id']
                or not re.fullmatch('[a-f0-9]{40}', config['source_revision'])
                or not re.fullmatch('[a-f0-9]{64}', config['account_binding'])
                or config['source_sha256'] != expected_source_hashes()):
            raise RuntimeError('Task identity or source mismatch')
        root = Path('/app/app')
        verify_installed_sources(root)
        self = cls()
        self._stack = ExitStack()
        self.binding = self.app = self.client = self.service_instance = None
        self._closed = False
        self._authorization = config['consumer_authorization']
        self.source_sha256 = expected_source_hashes()
        # These imports/read operations occur only inside the already-authorized
        # installed runtime after static source verification. No value is printed.
        self.db = importlib.import_module('app.db.session')
        self.http = importlib.import_module('app.core.clients.http')
        auth = importlib.import_module('app.core.auth.dependencies')
        deps = importlib.import_module('app.dependencies')
        api = importlib.import_module('app.modules.proxy.api')
        core = importlib.import_module('app.core.clients.proxy')
        service = importlib.import_module('app.modules.proxy.service')
        self.db.init_background_db()
        try:
            key = await auth.validate_required_proxy_api_key_authorization(self._authorization)
            self.consumer_binding = fingerprint(key.id)
            # Inspect IDs only; account ciphertext/auth is loaded later by the
            # unmodified selected-account service, exactly as ordinary inference.
            from sqlalchemy import select
            from app.db.models import Account
            async with self.db.get_background_session() as session:
                ids = (await session.execute(select(Account.id))).scalars().all()
            selected = [value for value in ids if isinstance(value, str)
                and fingerprint(value) == config['account_binding']]
            if len(selected) != 1 or (key.account_assignment_scope_enabled
                    and selected[0] not in key.assigned_account_ids):
                raise RuntimeError('Existing account authorization unavailable')
            crypto = importlib.import_module('app.core.crypto')
            require_existing_crypto(crypto, self._stack)
            state = Path('/tmp') / ('memoir-canary-' + config['run_id']) / 'runtime-state'
            state.mkdir(mode=0o700)  # exclusive; no resume/reuse of an old reservation
            self._state_dir = state
            guard = CanarySendGuard(reservation=state / 'reservation.jsonl',
                run_id=config['run_id'], source_revision=config['source_revision'],
                account_binding=config['account_binding'], model='gpt-5.6-luna',
                maximum_requests=80, request_seconds=60, wall_seconds=900)
            self.binding = InstalledGatewayBinding(guard=guard, core=core, service=service)
            self._stack.enter_context(self.binding.install())
            self.app = build_task_gateway_app(binding=self.binding, api=api,
                get_proxy_context=deps.get_proxy_context,
                validate_required_proxy_api_key=auth.validate_required_proxy_api_key,
                consumer_binding=self.consumer_binding, selected_account_id=selected[0])
            # Preserve the installed request ID, security, decompression and body
            # limit middleware. No dashboard, models, management or aliases mount.
            middleware = importlib.import_module('app.core.middleware')
            for name in ('add_request_decompression_middleware', 'add_request_body_limit_middleware',
                    'add_required_capability_http_middleware', 'add_request_id_middleware',
                    'add_api_firewall_middleware'):
                getattr(middleware, name)(self.app)
            importlib.import_module('app.core.handlers').add_exception_handlers(self.app)
            self.service_instance = deps.get_proxy_service_for_app(self.app)
            restrict_owned_service(self.service_instance, core, guard, self._stack)
            await self.http.init_http_client()
            # No forged localhost/trusted-proxy peer or forwarded client identity.
            # Existing firewall/auth may reject this untrusted stdio ingress; that
            # is a real blocker, never a reason to bypass an access restriction.
            self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,
                client=('0.0.0.0', 0)), base_url='http://canary-stdio.invalid',
                follow_redirects=False, trust_env=False)
            return self
        except BaseException:
            await self.stop()
            raise

    def receipt(self):
        if self.binding is None:
            return {'execution_started': False, 'boundary_verified': False,
                'provider_requests_started': 0, 'cleanup': {'closed': self._closed}}
        result = {**self.binding.receipt(), 'actor_cleanup': dict(getattr(self, '_cleanup', {})),
            'consumer_binding': self.consumer_binding}
        if getattr(self, '_active_operation_unfinished', False):
            result.setdefault('cleanup', {})['active_finished'] = False
            result['actor_cleanup'].update(active_operations_finished=False, finished=False)
        return result

    def mark_active_operation_unfinished(self):
        # Sticky uncertainty even if a deferred task happens to finish later.
        self._active_operation_unfinished = True
        if self.binding is not None:
            self.binding.guard.active_finished = False
        if hasattr(self, '_cleanup'):
            self._cleanup.update(active_operations_finished=False, finished=False)
        self._persist_cleanup_receipt()

    def _persist_cleanup_receipt(self):
        import json
        import os
        if not hasattr(self, '_state_dir'):
            return
        self._cleanup = getattr(self, '_cleanup', {})
        destination = self._state_dir / 'cleanup.json'
        temporary = self._state_dir / 'cleanup.json.tmp'
        try:
            self._cleanup['receipt_persisted'] = True
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as output:
                json.dump(self.receipt(), output, ensure_ascii=True, allow_nan=False)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            directory = os.open(self._state_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            self._cleanup.update(receipt_persisted=False, finished=False)


    async def responses(self, headers, body):
        import asyncio
        import hmac
        if self._closed or not self.binding.readiness()['accepting_requests']:
            return 429, {'content-type': 'application/json'}, '{"error":"canary_stopped"}'
        if (not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                for k, v in headers.items()) or len({k.lower() for k in headers}) != len(headers)):
            raise RuntimeError('Invalid request headers')
        lowered = {k.lower(): v for k, v in headers.items()}
        if not hmac.compare_digest(lowered.get('authorization', '').encode(), self._authorization.encode()):
            raise RuntimeError('Consumer authorization mismatch')
        # Forwarded origin fields cannot turn a stdio transport into a trusted
        # network peer. Existing required consumer auth remains mandatory.
        forbidden = {'forwarded', 'x-forwarded-for', 'x-real-ip', 'x-forwarded-host', 'x-forwarded-proto'}
        if forbidden & set(lowered):
            raise RuntimeError('Forwarded origin headers forbidden')
        async with asyncio.timeout(60):
            response = await self.client.post('/v1/responses', headers=headers, json=body)
        if response.status_code != 200:
            self.binding.guard.stop('upstream_failed_or_incomplete')
        content = _redact_http_body(response.text, response.headers.get('content-type', ''), self._authorization[7:])
        return response.status_code, {'content-type': response.headers.get('content-type', 'application/json')}, content

    async def stop(self):
        import asyncio
        self._closed = True  # ingress admission, not a successful-cleanup claim
        if getattr(self, '_cleanup_task', None) is None:
            self._cleanup = {'finished': False}
            if self.binding is not None:
                # Mark the guard terminal synchronously before any cleanup await.
                try:
                    self.binding.guard.stop('closed')
                except Exception:
                    self.binding.guard.stop_reason = 'closed'
            _RETAINED_DISPATCH_FENCES.append(self._stack.pop_all())
            self._cleanup_task = asyncio.create_task(self._cleanup_owned_resources())
        await _bounded_task(self._cleanup_task, 10)
        return self.receipt()

    async def _cleanup_owned_resources(self):
        stages = []
        if self.binding is not None:
            stages.append(('guard_closed', self.binding.stop, 5))
        if self.client is not None:
            stages.append(('client_closed', self.client.aclose, .5))
        if self.service_instance is not None:
            stages.append(('request_logs_drained', lambda:
                self.service_instance.drain_persistence_tasks(timeout_seconds=2), 2.5))
        stages.extend([('http_closed', self.http.close_http_client, .5),
            ('database_closed', self.db.close_db, .5)])
        for name, action, timeout in stages:
            try:
                import asyncio
                task = asyncio.create_task(action())
                complete, result = await _bounded_task(task, timeout)
                self._cleanup[name] = bool(complete and (result is not False))
                if name == 'request_logs_drained':
                    self._cleanup[name] = bool(complete and result is True)
                if name == 'guard_closed':
                    self._cleanup[name] = bool(complete and isinstance(result, dict)
                        and result.get('cleanup', {}).get('closed') is True
                        and result.get('cleanup', {}).get('active_finished') is True)
                if name == 'guard_closed' and not complete:
                    self.binding.guard.active_finished = False
            except BaseException:
                self._cleanup[name] = False
        self._authorization = None
        self._cleanup['finished'] = all(value is True for key, value in self._cleanup.items() if key != 'finished')
        self._cleanup['dispatch_fence_retained'] = self.binding is not None
        self._cleanup['active_operations_finished'] = not getattr(self, '_active_operation_unfinished', False)
        if not self._cleanup['active_operations_finished']:
            self._cleanup['finished'] = False
        self._persist_cleanup_receipt()


async def _bounded_task(task, seconds):
    """Bound waiting even when cancellation is deferred by a task/driver."""
    import asyncio
    done, _ = await asyncio.wait({task}, timeout=seconds)
    if not done:
        task.cancel()
        _OWNED_PENDING_TASKS.add(task)
        def completed(value):
            _OWNED_PENDING_TASKS.discard(value)
            if not value.cancelled():
                value.exception()  # observe without rendering any external text
        task.add_done_callback(completed)
        return False, None
    if task.cancelled():
        return False, None
    try:
        return True, task.result()
    except BaseException:
        return False, None


def _redact_http_body(body, content_type, secret):
    import json
    from scripts.canary_gateway_binding import _redact, _redact_sse
    kind = content_type.split(';', 1)[0].strip().lower()
    if kind == 'application/json':
        return json.dumps(_redact(_strict_json(body), secret), ensure_ascii=True, allow_nan=False)
    if kind == 'text/event-stream':
        return _redact_sse(body, secret)
    raise ValueError('Unsupported actor response content type')


def _strict_json(raw):
    import json
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError('Nonfinite JSON value')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)


async def serve_frames(readline, emit, *, runtime_factory=InstalledActorRuntime.start):
    """Serve one run; watch stop/EOF concurrently with an active generation.

    readline/emit are transport adapters so subprocess/EOF tests use no installed
    gateway, credentials or provider contacts. No operation is replayed.
    """
    import asyncio
    import json
    import os
    import time
    from uuid import UUID
    runtime, active, incoming = None, None, None
    seen = set()
    authorization = None
    unfinished_operation = False
    deadline = time.monotonic() + 900

    async def read():
        raw = await readline()
        if not raw:
            return None
        if len(raw) > MAX_FRAME_BYTES or not raw.endswith(b'\n'):
            raise ValueError('Invalid actor frame boundary')
        value = _strict_json(raw)
        if (not isinstance(value, dict) or value.get('version') != VERSION
                or not isinstance(value.get('id'), str)
                or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', value['id'])
                or value['id'] in seen):
            raise ValueError('Invalid actor frame identity')
        seen.add(value['id'])
        return value

    def mark_unfinished():
        nonlocal unfinished_operation
        unfinished_operation = True
        marker = getattr(runtime, 'mark_active_operation_unfinished', None)
        if marker is not None:
            marker()

    def checked_receipt(value):
        if unfinished_operation:
            from copy import deepcopy
            value = deepcopy(value)
            value.setdefault('cleanup', {})['active_finished'] = False
            value.setdefault('actor_cleanup', {}).update(active_operations_finished=False, finished=False)
        return value

    async def send(request, **fields):
        if 'receipt' in fields:
            fields['receipt'] = checked_receipt(fields['receipt'])
        if request['op'] == 'responses':
            fields['body'] = _redact_http_body(fields['body'], fields['headers'].get('content-type', ''), authorization[7:])
        reply = {'version': VERSION, 'id': request['id'], 'op': request['op'], **fields}
        raw = (json.dumps(reply, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode()
        if len(raw) > MAX_FRAME_BYTES or (authorization and authorization[7:].encode() in raw):
            raise ValueError('Actor response is unsafe')
        await emit(raw)

    try:
        hello = await asyncio.wait_for(read(), 30)
        required = {'version', 'id', 'op', 'run_id', 'source_revision', 'account_binding',
            'consumer_authorization', 'challenge', 'source_sha256'}
        if (hello is None or set(hello) != required or hello['op'] != 'init'
                or str(UUID(hello['run_id'])) != hello['run_id']
                or not re.fullmatch('[a-f0-9]{40}', hello['source_revision'])
                or not re.fullmatch('[a-f0-9]{64}', hello['account_binding'])
                or not isinstance(hello['challenge'], str)
                or not re.fullmatch('[a-f0-9]{32}', hello['challenge'])):
            raise ValueError('Invalid actor initialization')
        authorization = hello['consumer_authorization']
        if (not isinstance(authorization, str) or not authorization.startswith('Bearer ')
                or not 8 < len(authorization) <= 4096
                or any(c in authorization for c in '\r\n\x00')):
            raise ValueError('Existing consumer authorization required')
        runtime = await asyncio.wait_for(runtime_factory(hello), 30)
        await send(hello, challenge=hello['challenge'], actor_pid=os.getpid(),
            run_id=hello['run_id'], source_revision=hello['source_revision'],
            source_sha256=runtime.source_sha256, account_binding=hello['account_binding'],
            consumer_binding=runtime.consumer_binding, boundary_mode='installed_guarded_http',
            receipt=runtime.receipt())
        incoming = asyncio.create_task(read())
        active_frame = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Canary run deadline')
            waiting = {incoming} | ({active} if active is not None else set())
            completed, _ = await asyncio.wait(waiting, timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED)
            if not completed:
                raise TimeoutError('Canary run deadline')
            # EOF/stop takes priority even if a response completed simultaneously.
            if incoming in completed:
                request = incoming.result()
                incoming = None
                if request is None:
                    break
                if request['op'] == 'stop' and set(request) == {'version', 'id', 'op'}:
                    if active is not None:
                        active.cancel()
                        # Close the dispatch fence even if cancellation is deferred.
                        await _bounded_task(active, .5)
                        if not active.done():
                            mark_unfinished()
                        active = None
                    cleanup = asyncio.create_task(runtime.stop())
                    complete, receipt = await _bounded_task(cleanup, 10)
                    if not complete:
                        receipt = runtime.receipt()
                    await send(request, receipt=receipt)
                    return
                if active is not None:
                    raise ValueError('Concurrent actor operation forbidden')
                if request['op'] == 'receipt' and set(request) == {'version', 'id', 'op'}:
                    await send(request, receipt=runtime.receipt())
                elif request['op'] == 'responses' and set(request) == {'version', 'id', 'op', 'headers', 'body'}:
                    if not isinstance(request['headers'], dict) or not isinstance(request['body'], dict):
                        raise ValueError('Invalid Responses frame')
                    active_frame = request
                    active = asyncio.create_task(runtime.responses(request['headers'], request['body']))
                else:
                    raise ValueError('Unsupported actor operation')
                incoming = asyncio.create_task(read())
            if active is not None and active in completed:
                status, headers, body = active.result()
                active = None
                await send(active_frame, status=status, headers=headers, body=body,
                    receipt=runtime.receipt())
    finally:
        if incoming is not None:
            incoming.cancel()
            await asyncio.gather(incoming, return_exceptions=True)
        if active is not None:
            active.cancel()
            await _bounded_task(active, .5)
            if not active.done():
                mark_unfinished()
        if runtime is not None:
            await _bounded_task(asyncio.create_task(runtime.stop()), 10)
        authorization = None


def main():
    import argparse
    import asyncio
    import contextlib
    import logging
    import sys
    parser = argparse.ArgumentParser(description='Task-only authenticated installed gateway stdio actor')
    parser.add_argument('--stdio', action='store_true', required=True)
    parser.parse_args()
    # The protocol stream never includes ordinary runtime logging or print output.
    # The caller also discards stderr; no exception body or credential is emitted.
    output = sys.stdout.buffer
    logging.disable(logging.CRITICAL)
    async def run():
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=MAX_FRAME_BYTES + 1)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
        async def emit(raw):
            output.write(raw)
            output.flush()
        try:
            await serve_frames(reader.readline, emit)
        finally:
            transport.close()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            asyncio.run(run())
        return 0
    except BaseException:
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
