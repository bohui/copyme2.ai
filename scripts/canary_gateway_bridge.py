"""Owned Mac loopback → owned gateway-runtime stdio actor bridge.

Only an existing consumer Authorization is used, in memory. The upstream
account credential never crosses this bridge. No shared service is restarted,
no container port is published, and an ambiguous operation is never replayed.
"""
import asyncio
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import socket
import sys
import time
from uuid import UUID, uuid4
from scripts.run_codexlb_canary import APPROVED_ACCOUNT_BINDING

VERSION = 'memoir-canary-stdio/1'
MAX_FRAME_BYTES = 16 * 1024 * 1024
RUNTIME_CONTAINER = 'llm-provider-codex-lb-1'


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Nonfinite JSON value')


def strict_json(raw):
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_invalid_constant)


def _body_has_secret(body, secret):
    """SSE JSON may spell a credential using Unicode escapes."""
    if secret in body:
        return True
    for block in body.replace('\r\n', '\n').split('\n\n'):
        data = '\n'.join(line[5:].lstrip() for line in block.splitlines() if line.startswith('data:'))
        if not data or data == '[DONE]':
            continue
        try:
            if secret in json.dumps(strict_json(data), ensure_ascii=False):
                return True
        except (ValueError, TypeError):
            raise ValueError('Invalid actor SSE') from None
    return False


def _safe_identity(run_id, revision, account):
    if (str(UUID(run_id)) != run_id or not re.fullmatch('[a-f0-9]{40}', revision)
            or not re.fullmatch('[a-f0-9]{64}', account)):
        raise ValueError('Pinned task identities are required')


def _native_command(command, run_id):
    # The native owner copies reviewed source into this fresh task directory.
    # Do not accept a shell command, remote URL, shared entrypoint or arbitrary
    # executable disguised as a readiness service.
    if (not isinstance(command, (list, tuple)) or len(command) != 7
            or not Path(command[0]).is_absolute() or Path(command[0]).name != 'docker'
            or list(command[1:4]) != ['exec', '-i', RUNTIME_CONTAINER]
            or command[4] != '/app/.venv/bin/python'
            or command[5] != f'/tmp/memoir-canary-{run_id}/scripts/canary_gateway_actor.py'
            or command[6] != '--stdio'):
        raise ValueError('The reviewed task-owned installed actor command is required')
    return list(command)


class NativeGatewayLease:
    """An owned process/socket lease, never reconstructed from a JSON receipt."""
    def __init__(self):
        raise TypeError('Use start_native or the separate controlled fixture factory')

    @classmethod
    def validate_native_target(cls, *, actor_command, run_id, source_revision, account_binding,
                               source_sha256):
        """Credential-free preflight; never spawns the runtime actor."""
        _safe_identity(run_id, source_revision, account_binding)
        if account_binding != APPROVED_ACCOUNT_BINDING:
            raise ValueError('The approved canary account binding is required')
        command = _native_command(actor_command, run_id)
        from scripts.canary_gateway_binding import SOURCE_SHA256
        actor = Path(__file__).resolve().with_name('canary_gateway_actor.py')
        if (not isinstance(source_sha256, dict) or any(source_sha256.get(k) != v for k, v in SOURCE_SHA256.items())
                or not actor.is_file() or source_sha256.get('scripts/canary_gateway_actor.py') !=
                hashlib.sha256(actor.read_bytes()).hexdigest()):
            raise ValueError('Exact installed and actor source pins are required')
        return command

    @classmethod
    async def start_native(cls, *, actor_command, run_id, source_revision, account_binding,
                           consumer_authorization, source_sha256):
        command = cls.validate_native_target(actor_command=actor_command, run_id=run_id,
            source_revision=source_revision, account_binding=account_binding, source_sha256=source_sha256)
        return await cls._start(command, run_id, source_revision, account_binding,
                                consumer_authorization, source_sha256, controlled=False)

    @classmethod
    async def controlled(cls, *, run_id, source_revision, account_binding, control, control_dir,
                         integrated_protocol=False):
        _safe_identity(run_id, source_revision, account_binding)
        if type(integrated_protocol) is not bool:
            raise ValueError('A boolean controlled protocol selector is required')
        path = Path(control_dir) / ('bridge-control-' + uuid4().hex + '.json')
        path.write_text(json.dumps(control), encoding='utf-8')
        fixture = Path(__file__).resolve().parents[1] / 'tests/fixtures' / (
            'canary_integrated_stdio_actor.py' if integrated_protocol else 'canary_stdio_actor.py')
        if integrated_protocol:
            from scripts.canary_gateway_actor import expected_source_hashes
            hashes = expected_source_hashes()
        else:
            hashes = {'actor': hashlib.sha256(fixture.read_bytes()).hexdigest()}
        return await cls._start([sys.executable, str(fixture), str(path)], run_id, source_revision,
            account_binding, 'Bearer synthetic-consumer-only', hashes, controlled=True,
            expected_boundary='installed_guarded_http' if integrated_protocol else 'controlled_fixture')

    @classmethod
    async def _start(cls, command, run_id, revision, account, authorization, hashes, *, controlled,
                     expected_boundary='installed_guarded_http'):
        if (not isinstance(authorization, str) or not authorization.startswith('Bearer ')
                or not 8 < len(authorization) <= 4096 or any(c in authorization for c in '\r\n\x00')):
            raise ValueError('An existing consumer Bearer authorization is required')
        if any(not isinstance(k, str) or not re.fullmatch('[a-f0-9]{64}', v) for k, v in hashes.items()):
            raise ValueError('Exact source hashes are required')
        self = object.__new__(cls)
        self.run_id, self.source_revision, self.account_binding = run_id, revision, account
        self.source_sha256 = dict(hashes)
        self._authorization = authorization
        self._controlled = controlled
        self._creator_pid = os.getpid()
        self._deadline = time.monotonic() + 900
        self._lock = asyncio.Lock()
        self._stopping = False
        self._failed = False
        self._stopped = False
        self._cached_receipt = {}
        self._forwarded = 0
        self._actor_pid = None
        self._server = self._server_task = self._socket = self._process = None
        self._handlers = set()
        self._stop_task = None
        self._cleanup = {}
        try:
            # No inherited service credentials enter argv or the subprocess
            # environment. Authorization travels only in the bounded stdin frame.
            env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'TMPDIR') if key in os.environ}
            spawning = asyncio.create_task(asyncio.create_subprocess_exec(*command, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True, limit=MAX_FRAME_BYTES + 1))
            try:
                self._process = await asyncio.shield(spawning)
            except asyncio.CancelledError:
                while not spawning.done():
                    try: await asyncio.shield(spawning)
                    except asyncio.CancelledError: pass
                self._process = spawning.result()
                raise
            challenge = uuid4().hex
            hello = await self._rpc('init', run_id=run_id, source_revision=revision,
                account_binding=account, consumer_authorization=authorization, challenge=challenge,
                source_sha256=dict(hashes))
            wanted = {'version', 'id', 'op', 'challenge', 'actor_pid', 'run_id', 'source_revision',
                      'source_sha256', 'account_binding', 'consumer_binding', 'boundary_mode', 'receipt'}
            if (set(hello) != wanted or hello['challenge'] != challenge or hello['run_id'] != run_id
                    or hello['source_revision'] != revision or hello['account_binding'] != account
                    or hello['source_sha256'] != hashes
                    or type(hello['actor_pid']) is not int or hello['actor_pid'] <= 0
                    or not re.fullmatch('[a-f0-9]{64}', hello['consumer_binding'])
                    or hello['boundary_mode'] != expected_boundary):
                raise RuntimeError('Actor identity handshake failed')
            self._actor_pid = hello['actor_pid']
            self._consumer_binding = hello['consumer_binding']
            await self._listen()
            return self
        except BaseException:
            self._failed = True
            await self.stop()
            raise RuntimeError('Canary gateway actor could not be established') from None

    async def _rpc(self, op, **payload):
        if self._process is None or self._process.returncode is not None or (self._failed and op != 'stop'):
            raise RuntimeError('Canary actor is unavailable')
        async with self._lock:
            if self._failed and op != 'stop':
                raise RuntimeError('Canary actor is stopped')
            remaining = self._deadline - time.monotonic()
            if remaining <= 0 and op != 'stop':
                self._failed = True
                raise RuntimeError('Canary deadline expired')
            request_id = uuid4().hex
            frame = {'version': VERSION, 'id': request_id, 'op': op, **payload}
            raw = (json.dumps(frame, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode()
            if len(raw) > MAX_FRAME_BYTES:
                self._failed = True
                raise RuntimeError('Canary frame exceeds its limit')
            try:
                async with asyncio.timeout(12 if op == 'stop' else min(65, remaining)):
                    if op == 'responses': self._forwarded += 1
                    self._process.stdin.write(raw)
                    await self._process.stdin.drain()
                    raw = await self._process.stdout.readline()
                    if not raw.endswith(b'\n') or len(raw) > MAX_FRAME_BYTES:
                        raise ValueError('Missing or oversized actor frame')
                    reply = strict_json(raw)
                    if (not isinstance(reply, dict) or reply.get('version') != VERSION
                            or reply.get('id') != request_id or reply.get('op') != op
                            or not isinstance(reply.get('receipt'), dict)):
                        raise ValueError('Ambiguous actor frame')
                    # Even errors and receipts may not export consumer auth.
                    serialized = json.dumps(reply, ensure_ascii=False)
                    if self._authorization in serialized or self._authorization[7:] in serialized:
                        raise ValueError('Actor returned consumer authentication')
                    self._cached_receipt = deepcopy(reply['receipt'])
                    if op in {'receipt', 'stop'} and set(reply) != {'version', 'id', 'op', 'receipt'}:
                        raise ValueError('Unexpected control-frame fields')
                    return reply
            except BaseException:
                self._failed = True
                raise RuntimeError('Canary actor operation failed; replay is forbidden') from None

    async def _listen(self):
        from fastapi import FastAPI, Request
        from fastapi.responses import Response
        import uvicorn
        app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
        @app.middleware('http')
        async def reject_unsupported_routes(request, call_next):
            if request.method != 'POST' or request.url.path != '/v1/responses' or request.url.query:
                if (len(request.headers.getlist('authorization')) == 1 and
                        hmac.compare_digest(request.headers.get('authorization', ''), self._authorization)):
                    self._failed = True
                return Response(status_code=404)
            return await call_next(request)
        @app.post('/v1/responses')
        async def responses(request: Request):
            if (len(request.headers.getlist('authorization')) != 1
                    or not hmac.compare_digest(request.headers.get('authorization', ''), self._authorization)):
                return Response(status_code=401)
            if self._failed or self._stopping or time.monotonic() >= self._deadline or self._terminal_receipt():
                return Response(status_code=503)
            task = asyncio.current_task()
            self._handlers.add(task)
            try:
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_FRAME_BYTES // 2:
                        raise ValueError('Request too large')
                data = strict_json(body)
                if (not isinstance(data, dict) or data.get('model') != 'gpt-5.6-luna'
                        or data.get('stream') is not True or not isinstance(data.get('client_metadata'), dict)
                        or data['client_metadata'].get('run_id') != self.run_id):
                    self._failed = True
                    return Response(status_code=400)
                headers = {key: value for key, value in request.headers.items() if key.lower() not in {
                    'host', 'connection', 'content-length', 'transfer-encoding', 'accept-encoding',
                    'proxy-authorization', 'proxy-connection', 'upgrade', 'keep-alive', 'te', 'trailer'}}
                if sum(len(k) + len(v) for k, v in headers.items()) > 32768:
                    raise ValueError('Headers too large')
                reply = await self._rpc('responses', headers=headers, body=data)
                if (set(reply) != {'version', 'id', 'op', 'status', 'headers', 'body', 'receipt'}
                        or type(reply['status']) is not int or reply['status'] not in {200, 400, 401, 403,
                            404, 408, 409, 413, 422, 429, 500, 502, 503, 504}
                        or not isinstance(reply['headers'], dict) or not isinstance(reply['body'], str)
                        or set(reply['headers']) - {'content-type'}
                        or any(not isinstance(v, str) or '\r' in v or '\n' in v for v in reply['headers'].values())):
                    raise ValueError('Invalid actor HTTP response')
                if _body_has_secret(reply['body'], self._authorization[7:]):
                    raise ValueError('Actor returned consumer authentication')
                if reply['status'] != 200 or self._cached_receipt.get('stop_reason'):
                    self._failed = True
                return Response(content=reply['body'], status_code=reply['status'], headers=reply['headers'])
            except BaseException:
                self._failed = True
                return Response(status_code=503)
            finally:
                self._handlers.discard(task)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(('127.0.0.1', 0))
        self._socket.setblocking(False)
        self._base_url = f'http://127.0.0.1:{self._socket.getsockname()[1]}/v1'
        self._server = uvicorn.Server(uvicorn.Config(app, lifespan='off', access_log=False,
            log_config=None, log_level='critical', timeout_graceful_shutdown=1))
        # The owning canary process handles cancellation. Uvicorn must not
        # replace/replay its SIGTERM handler while serving this internal socket.
        self._server.capture_signals = lambda: nullcontext()
        self._server_task = asyncio.create_task(self._server.serve(sockets=[self._socket]))
        async with asyncio.timeout(5):
            while not self._server.started:
                if self._server_task.done():
                    await self._server_task
                    raise RuntimeError('Task loopback listener did not start')
                await asyncio.sleep(.01)

    def assert_ready(self, *, run_id=None, source_revision=None, account_binding=APPROVED_ACCOUNT_BINDING):
        if account_binding != APPROVED_ACCOUNT_BINDING or self.account_binding != account_binding:
            raise ValueError('The lease account differs from the approved canary account')
        if (self._controlled or self._creator_pid != os.getpid() or self._stopped or self._stopping or self._failed
                or self._process is None or self._process.returncode is not None
                or self._server_task is None or self._server_task.done()
                or self._socket is None or self._socket.fileno() < 0
                or self._base_url != f'http://127.0.0.1:{self._socket.getsockname()[1]}/v1'
                or time.monotonic() >= self._deadline
                or self._terminal_receipt()
                or (run_id is not None and run_id != self.run_id)
                or (source_revision is not None and source_revision != self.source_revision)):
            raise ValueError('A live owned authenticated canary actor lease is required')
        return self.receipt()

    def _terminal_receipt(self):
        return (bool(self._cached_receipt.get('stop_reason'))
                or self._cached_receipt.get('cleanup', {}).get('closed') is True
                or self._cached_receipt.get('binding', {}).get('accepting_requests') is False)

    @property
    def base_url(self):
        return self._base_url

    def consumer_key_for_owned_worker(self):
        self.assert_ready()
        return self._authorization[7:]

    @property
    def deadline(self):
        return self._deadline

    def receipt(self):
        return {**deepcopy(self._cached_receipt), 'bridge_requests_forwarded': self._forwarded,
            'actor_pid': self._actor_pid, 'bridge_failed': self._failed,
            'bridge_controlled_fixture': self._controlled, 'bridge_cleanup': dict(self._cleanup),
            'upstream_cancellation': 'unverified', 'boundary_verified': False}

    async def refresh_receipt(self):
        await self._rpc('receipt')
        return self.receipt()

    async def stop(self):
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        while not self._stop_task.done():
            try:
                await asyncio.shield(self._stop_task)
            except asyncio.CancelledError:
                # Cleanup remains owned even if its awaiting caller is cancelled.
                pass
        return self._stop_task.result()

    async def _stop(self):
        if self._stopped:
            return self.receipt()
        self._stopping = True
        current = asyncio.current_task()
        for task in tuple(self._handlers):
            if task is not current: task.cancel()
        if self._server is not None:
            self._server.should_exit = True
        stop_confirmed = False
        if self._process is not None and self._process.returncode is None:
            try:
                await self._rpc('stop')
                stop_confirmed = True
            except (Exception, asyncio.CancelledError):
                pass
            self._process.stdin.close()
            try:
                async with asyncio.timeout(5):
                    await self._process.wait()
            except (TimeoutError, asyncio.CancelledError):
                try: os.killpg(self._process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try:
                    async with asyncio.timeout(2): await self._process.wait()
                except (TimeoutError, asyncio.CancelledError):
                    try: os.killpg(self._process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    await self._process.wait()
        self._cleanup['child_reaped'] = self._process is None or self._process.returncode is not None
        self._cleanup['actor_exit_verified'] = bool(stop_confirmed and self._process.returncode == 0)
        if self._server_task is not None:
            try:
                async with asyncio.timeout(3): await self._server_task
            except (TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
                await asyncio.gather(self._server_task, return_exceptions=True)
        if self._socket is not None: self._socket.close()
        self._cleanup['listener_closed'] = self._socket is None or self._socket.fileno() < 0
        self._stopped = True
        self._authorization = ''
        return self.receipt()
