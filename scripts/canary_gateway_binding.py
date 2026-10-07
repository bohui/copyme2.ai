"""Task-local binding for the audited codex-lb HTTP send path.

This module never reads credentials, changes gateway settings, or starts a server.
The existing authenticated gateway supplies its already-selected account/token.
Only an isolated runtime may bind it; the shared gateway must stay unchanged.
"""
import asyncio
from contextlib import aclosing, asynccontextmanager, contextmanager
from copy import deepcopy
import codecs
import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from scripts.canary_send_guard import CanaryStopped


UPSTREAM_ENDPOINT = 'https://chatgpt.com/backend-api/codex/responses'
GUARD_ERROR_CODE = 'canary_guard_stopped'
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SOURCE_SHA256 = {
    'modules/proxy/_service/streaming/helpers.py': 'd2bb9b6b8b564fd838343d9fbab3b3e1ede3a71faa88ffb7c9f8e162fb034dbc',
    'core/clients/proxy.py': 'e96458cb775a5cf6d83837070d955dbfcf4d066b9a1cf701d099dc73449dbdb1',
    'modules/proxy/service.py': '6fcda2484ee89f47a7bb139992c0e9b2214cf0ffff29f7c72b8edf7948cefb94',
    'modules/proxy/_service/streaming/mixin.py': 'c1afb639084934142e04ab478c62a8919a60e7d796c9600cfe4cc6f400801419',
}


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, '[REDACTED]')
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


def _redact_sse(body, secret):
    # Parse JSON so escaped credentials are redacted too. Preserve non-data SSE
    # fields, comments and the terminal marker, with literal redaction as well.
    result = []
    for event in body.replace('\r\n', '\n').split('\n\n'):
        lines = event.splitlines()
        data = '\n'.join(line[5:].lstrip() for line in lines if line.startswith('data:'))
        if data and data != '[DONE]':
            sanitized = json.dumps(_redact(json.loads(data), secret), ensure_ascii=True)
            other = [_redact(line, secret) for line in lines if not line.startswith('data:')]
            result.append('\n'.join(other + ['data: ' + sanitized]))
        else:
            result.append(_redact(event, secret))
    return '\n\n'.join(result)


def _text_only(payload):
    """No built-in remote tools, images, audio, URLs for image fetching or paid tier."""
    if not isinstance(payload, dict) or payload.get('stream') is not True:
        return False
    if payload.get('service_tier') not in (None, 'auto', 'default'):
        return False
    tools = payload.get('tools', [])
    if not isinstance(tools, list) or any(not isinstance(tool, dict) or
            tool.get('type') not in {'function', 'custom'} for tool in tools):
        return False
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if value.get('type') in {'input_image', 'input_audio', 'image_url',
                    'image_generation', 'input_file', 'computer', 'computer_use'}:
                return False
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return True


class _BufferedContent:
    def __init__(self, body):
        self._body = body

    async def iter_chunked(self, size):
        for offset in range(0, len(self._body), size):
            yield self._body[offset:offset + size]


class _BufferedResponse:
    def __init__(self, body, headers):
        self.status = 200
        self.headers = httpx.Headers(headers)
        self.content = _BufferedContent(body)


class GuardedHTTPSession:
    """Minimal installed aiohttp-session protocol backed by one-shot HTTPX.

    The installed core builds the final authenticated headers/payload and calls
    post(). This object verifies those exact values before invoking its private
    transport. Redirects, connection retries, proxies and persistent keepalive
    are disabled. The complete bounded SSE response settles before being handed
    back to core, whose SSE consumer stops at the first terminal event.
    """
    def __init__(self, *, guard, endpoint=UPSTREAM_ENDPOINT, account_id,
                 access_token, correlation=None):
        if endpoint != UPSTREAM_ENDPOINT:
            raise ValueError('Only the audited existing subscription endpoint is permitted')
        self._configure(guard, endpoint, account_id, access_token, correlation)

    @classmethod
    def controlled(cls, *, guard, endpoint, account_id, access_token, correlation=None):
        """Disposable external-protocol tests only; never accepts a runtime token."""
        url = urlsplit(endpoint)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
                or url.port < 1024 or url.path != '/codex/responses'
                or url.username or url.password or url.query or url.fragment
                or not access_token.startswith('synthetic-')):
            raise ValueError('Controlled tests require a loopback endpoint and synthetic token')
        instance = cls.__new__(cls)
        instance._configure(guard, endpoint, account_id, access_token, correlation)
        return instance

    def _configure(self, guard, endpoint, account_id, access_token, correlation):
        if not isinstance(account_id, str) or not account_id or not isinstance(access_token, str) or not access_token:
            raise ValueError('Authenticated runtime account context is required')
        self.guard, self.endpoint = guard, endpoint
        self._account_id, self._access_token = account_id, access_token
        self._correlation = deepcopy(correlation)
        self._client = None
        self._closed = False

    async def __aenter__(self):
        if self._client is not None or self._closed:
            raise CanaryStopped('session_reuse_forbidden')
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        self._client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(
            retries=0, verify=True, trust_env=False, http1=True, http2=False, limits=limits),
            follow_redirects=False, trust_env=False, timeout=self.guard.request_seconds)
        return self

    async def __aexit__(self, *args):
        self._closed = True
        if self._client is not None:
            await self._client.aclose()
        self._account_id = self._access_token = None

    def _stop(self, reason):
        self.guard.stop(reason)
        raise CanaryStopped(reason)

    def _unsupported(self, *args, **kwargs):
        self._stop('gateway_dispatch_forbidden')

    get = request = ws_connect = _unsupported

    @asynccontextmanager
    async def post(self, url, *, json, headers, timeout=None, **kwargs):
        if self._client is None or self._closed:
            self._stop('gateway_session_unavailable')
        if url != self.endpoint or kwargs:
            self._stop('gateway_target_forbidden')
        if not isinstance(headers, dict):
            self._stop('gateway_auth_mismatch')
        lowered = {}
        for key, value in headers.items():
            if not isinstance(key, str) or not isinstance(value, str) or key.lower() in lowered:
                self._stop('gateway_auth_mismatch')
            lowered[key.lower()] = value
        if (not hmac.compare_digest(lowered.get('authorization', '').encode(), ('Bearer ' + self._access_token).encode())
                or not hmac.compare_digest(lowered.get('chatgpt-account-id', '').encode(), self._account_id.encode())):
            self._stop('gateway_auth_mismatch')
        if not _text_only(json):
            self._stop('gateway_payload_forbidden')
        chunks, response_headers = [], {}
        async def wire(payload):
            nonlocal response_headers
            # HTTPTransport retries=0, redirect following and trust_env disabled.
            async with self._client.stream('POST', self.endpoint, json=payload,
                    headers=dict(headers)) as response:
                if response.status_code != 200:
                    raise CanaryStopped('upstream_failed_or_incomplete')
                if response.headers.get('content-type', '').split(';')[0].strip() != 'text/event-stream':
                    raise CanaryStopped('wire_protocol_invalid')
                response_headers = dict(response.headers)
                size = 0
                decoder = codecs.getincrementaldecoder('utf-8')('strict')
                async for raw in response.aiter_bytes():
                    size += len(raw)
                    if size > MAX_RESPONSE_BYTES:
                        raise CanaryStopped('wire_event_too_large')
                    yield decoder.decode(raw)
                tail = decoder.decode(b'', final=True)
                if tail:
                    yield tail
        async for block in self.guard.stream(wire, payload=json, transport='http',
                account_binding=self.guard.account_binding, correlation=self._correlation):
            chunks.append(block)
        # No live bytes are exposed until usage is settled. A core parser that
        # breaks on response.completed therefore cannot leave an open reservation.
        body = _redact_sse(''.join(chunks), self._access_token)
        safe_headers = {key: _redact(value, self._access_token)
            for key, value in response_headers.items()
            if key.lower() not in {'authorization', 'proxy-authorization', 'set-cookie'}}
        yield _BufferedResponse(body.encode(), safe_headers)


class InstalledGatewayBinding:
    """Keep the existing ProxyService selection, auth, formatting and accounting.

    The service's exact audited facade calls this wrapper. Its original core
    stream receives an owned guarded session; this is not a second direct pilot.
    Call install() only in a newly started task process, never a shared daemon.
    The task ingress must expose only authenticated Responses HTTP for this run.
    """
    def __init__(self, *, guard, core, service):
        self.guard, self.core, self.service = guard, core, service
        self._original = core.stream_responses
        self._seen_requests = set()
        self._stream_lock = asyncio.Lock()
        self._installed = False
        self._sources_verified = False
        # The installed facade filters optional kwargs using the signature.
        from functools import wraps
        @wraps(self._original)
        async def stream(*args, **kwargs):
            async with self._stream_lock:
                try:
                    async with aclosing(self._stream_responses(*args, **kwargs)) as stream:
                        async for block in stream:
                            yield block
                except Exception as error:
                    if not isinstance(error, CanaryStopped):
                        try:
                            self.guard.stop('upstream_failed_or_incomplete')
                        except Exception:
                            # Even an unavailable journal cannot enable another
                            # dispatch or escape through success settlement.
                            self.guard.stop_reason = 'upstream_failed_or_incomplete'
                    # A generic exception before the first core block makes the
                    # installed _stream_once log success. Use its terminal SSE
                    # settlement path, whose original pinned classifiers treat this
                    # sentinel as terminal and account-neutral.
                    yield self.core.format_sse_event(self.core.response_failed_event(
                        GUARD_ERROR_CODE, self.guard.stop_reason or 'closed',
                        error_type='invalid_request_error', response_id=self.guard.run_id))
        self.stream_responses = stream

    def _stop(self, reason):
        self.guard.stop(reason)
        raise CanaryStopped(reason)

    async def _stream_responses(self, payload, headers, access_token, account_id,
                               **kwargs):
        if self.guard.closed or self.guard.stop_reason:
            raise CanaryStopped(self.guard.stop_reason or 'closed')
        if (kwargs.get('route') is not None or kwargs.get('codex_client') is not None
                or kwargs.get('session') is not None
                or kwargs.get('upstream_stream_transport_override') not in (None, 'http')):
            self._stop('gateway_dispatch_forbidden')
        row_id = kwargs.get('codex_lb_account_id')
        if not isinstance(row_id, str) or fingerprint(row_id) != self.guard.account_binding:
            self._stop('gateway_account_mismatch')
        if not isinstance(account_id, str) or not account_id or not isinstance(access_token, str) or not access_token:
            self._stop('gateway_auth_mismatch')
        base = UPSTREAM_ENDPOINT.removesuffix('/codex/responses')
        if (self.core.get_settings().upstream_base_url.rstrip('/') != base
                or kwargs.get('base_url') not in (None, base)):
            self._stop('gateway_target_forbidden')
        request_id = self.core.get_request_id()
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', request_id):
            self._stop('gateway_request_id_unavailable')
        if request_id in self._seen_requests:
            self._stop('gateway_replay_forbidden')
        raw = payload.to_payload()
        if not _text_only(raw) or raw.get('model') != self.guard.model:
            self._stop('gateway_payload_forbidden')
        metadata = raw.get('client_metadata', {})
        if not isinstance(metadata, dict) or metadata.get('run_id', self.guard.run_id) != self.guard.run_id:
            self._stop('correlation_forbidden')
        correlation = {'run_id': self.guard.run_id, 'request_id': request_id}
        for key in ('case_id', 'round_id', 'trace_id', 'observation_id', 'job_id', 'checkpoint_id', 'role', 'phase'):
            if key in metadata:
                value = metadata[key]
                if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', value):
                    self._stop('correlation_forbidden')
                correlation[key] = value
        self._seen_requests.add(request_id)
        before = len(self.guard.entries)
        try:
            async with GuardedHTTPSession(guard=self.guard, account_id=account_id,
                    access_token=access_token, correlation=correlation) as session:
                kwargs.update(session=session, upstream_stream_transport_override='http')
                async with aclosing(self._original(payload, headers, access_token, account_id, **kwargs)) as stream:
                    async for block in stream:
                        # Settlement precedes all core-visible bytes. Reject any
                        # apparent success from an unobserved alternate dispatcher.
                        if (len(self.guard.entries) != before + 1
                                or self.guard.entries[-1]['status'] != 'completed'):
                            self._stop('gateway_boundary_unobserved')
                        yield block
            if len(self.guard.entries) != before + 1:
                self._stop('gateway_boundary_unobserved')
        except (asyncio.CancelledError, GeneratorExit):
            self.guard.stop('upstream_failed_or_incomplete')
            raise
        except Exception:
            self.guard.stop('upstream_failed_or_incomplete')
            raise CanaryStopped(self.guard.stop_reason or 'upstream_failed_or_incomplete') from None

    def readiness(self):
        """Safe task-ingress state, not an authorization or live-test certificate."""
        accepting = (self._installed and self._sources_verified and not self.guard.closed
            and not self.guard.stop_reason and time.monotonic() < self.guard.deadline
            and len(self.guard.entries) < self.guard.maximum_requests)
        return {'run_id': self.guard.run_id, 'source_revision': self.guard.source_revision,
            'installed': self._installed, 'sources_verified': self._sources_verified,
            'accepting_requests': bool(accepting), 'native_actor_verified': False,
            'live_ready': False, 'transport': 'http',
            'remaining_request_reservations': max(0, self.guard.maximum_requests - len(self.guard.entries)),
            'stop_reason': self.guard.stop_reason}

    def receipt(self):
        return {**self.guard.receipt(), 'binding': self.readiness(),
            'installed_source_sha256': dict(SOURCE_SHA256)}

    async def stop(self):
        await self.guard.aclose()
        return self.receipt()

    def _verify_sources(self):
        try:
            root = Path(self.core.__file__).resolve().parents[2]
            expected_paths = {
                'modules/proxy/_service/streaming/helpers.py': root / 'modules/proxy/_service/streaming/helpers.py',
                'core/clients/proxy.py': Path(self.core.__file__).resolve(),
                'modules/proxy/service.py': Path(self.service.__file__).resolve(),
                'modules/proxy/_service/streaming/mixin.py': root / 'modules/proxy/_service/streaming/mixin.py',
            }
            for relative, path in expected_paths.items():
                if (path != root / relative or hashlib.sha256(path.read_bytes()).hexdigest()
                        != SOURCE_SHA256[relative]):
                    self._stop('gateway_source_mismatch')
            if self.service.core_stream_responses is not self._original:
                self._stop('gateway_source_mismatch')
            if not callable(self.core.get_request_id):
                self._stop('gateway_source_mismatch')
            self._sources_verified = True
        except (AttributeError, OSError, IndexError):
            self._stop('gateway_source_mismatch')

    def _forbidden(self, *args, **kwargs):
        self._stop('gateway_dispatch_forbidden')

    @contextmanager
    def install(self):
        """Install/restore process-local facade exports after exact source checks."""
        self._verify_sources()
        if self._installed:
            self._stop('gateway_dispatch_forbidden')
        exports = [
            (self.core, ['compact_responses', 'codex_control_request', 'thread_goal_request', 'transcribe_audio']),
            (self.service, ['core_compact_responses', 'core_codex_control_request',
                'core_thread_goal_request', 'core_transcribe_audio', 'core_create_file',
                'core_finalize_file', 'connect_live_websocket', 'connect_responses_websocket']),
        ]
        if (GUARD_ERROR_CODE in self.service._ACCOUNT_RECOVERY_RETRY_CODES
                or GUARD_ERROR_CODE in self.service._TRANSIENT_RETRY_CODES
                or self.service._should_retry_stream_error(GUARD_ERROR_CODE)
                or self.service._should_penalize_stream_error(GUARD_ERROR_CODE)):
            self._stop('gateway_source_mismatch')
        replacements = [(self.core, 'stream_responses', self.stream_responses),
            (self.service, 'core_stream_responses', self.stream_responses)]
        for module, names in exports:
            for name in names:
                if not hasattr(module, name):
                    self._stop('gateway_source_mismatch')
                replacements.append((module, name, self._forbidden))
        saved = [(module, name, getattr(module, name)) for module, name, _ in replacements]
        self._installed = True
        try:
            for module, name, replacement in replacements:
                setattr(module, name, replacement)
            yield self
        finally:
            for module, name, original in saved:
                setattr(module, name, original)
            self._installed = False
