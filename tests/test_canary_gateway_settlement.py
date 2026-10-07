"""Exact installed settlement AST + original classifiers, synthetic dependencies.

This is deliberately stronger than a fake gateway, but is not a native runtime
or consumer-auth test. The source snapshot records the audited full-file hashes.
"""
import asyncio
import json
from pathlib import Path
import time
from types import SimpleNamespace as NS
import typing

import pytest

from scripts.canary_gateway_binding import InstalledGatewayBinding, GUARD_ERROR_CODE
from scripts.canary_send_guard import CanaryStopped
from test_canary_gateway_binding import guard_at, fake_gateway


SNAPSHOT = json.loads((Path(__file__).parent / 'fixtures/canary_installed_stream_settlement.json').read_text())


class FailureMetadata:
    def __getattr__(self, name): return None


class Lease:
    def __init__(self, *args, **kwargs): pass
    def release(self): pass


class TerminalStreamError(Exception):
    def __init__(self, code, error): self.code, self.error = code, error


class ProxyResponseError(Exception): pass
class UpstreamProxyRouteError(Exception): pass


class Parsed(NS):
    def __getattr__(self, name): return None


def parsed(value):
    if isinstance(value, dict):
        return Parsed(**{key: parsed(item) for key, item in value.items()})
    return value


def load_exact_settlement(facade):
    def forbidden(*args, **kwargs):
        pytest.fail('Unexpected health, refresh, failover or continuity rewrite')
    scope = dict(asyncio=asyncio, time=time, cast=typing.cast,
        PERMANENT_FAILURE_CODES={'synthetic_permanent_error': 'synthetic'},
        _StreamingServiceProtocol=object, _header_account_id=lambda value: value,
        _owner_lookup_session_id_from_headers=lambda headers: None,
        _RequestLogFailureMetadata=FailureMetadata,
        UpstreamProxyRouteTrace=FailureMetadata, _WebSocketUpstreamControl=FailureMetadata,
        AdmissionLease=Lease, _ApiKeyReservationTouchState=lambda **kw: NS(**kw),
        _facade=lambda: facade, aiohttp=NS(ClientError=OSError),
        ProxyResponseError=ProxyResponseError, UpstreamProxyRouteError=UpstreamProxyRouteError,
        _TerminalStreamError=TerminalStreamError,
        _finalize_ttft_latency_ms=lambda *a: None,
        _maybe_log_proxy_service_tier_trace=lambda *a, **kw: None,
        parse_sse_data_json=lambda raw: json.loads(raw.removeprefix('data: ').strip()),
        classify_event_type=lambda value: value.get('type'),
        parse_sse_event_payload=parsed,
        _LIFECYCLE_EVENT_TYPES={'response.failed'},
        _rewrite_malformed_stream_error_event=lambda **kw: None,
        _normalize_error_code=lambda code, error_type: code or error_type,
        _raw_stream_error_code_or_upstream=lambda kind, value, code: code,
        _upstream_error_from_openai=lambda error: vars(error), UpstreamError=dict,
        _rewrite_tool_call_line=lambda line, value, event: (line, value, event, value['type']),
        mark_duplicate_tool_call_downstream_event=lambda *a, **kw: False,
        tool_call_response_id_from_payload=lambda value: None,
        format_sse_event=lambda value: 'data: ' + json.dumps(value) + '\n\n',
        _ttft_event_latency_ms=lambda *a: None,
        _record_continuity_fail_closed=forbidden)
    for key, fragment in SNAPSHOT['fragments'].items():
        exec(compile('from __future__ import annotations\n' + fragment,
            'audited-installed:' + key, 'exec'), scope)
    for key in ('_ACCOUNT_RECOVERY_RETRY_CODES', '_TRANSIENT_RETRY_CODES',
            '_should_retry_stream_error', '_should_penalize_stream_error',
            '_rewrite_previous_response_stream_error'):
        setattr(facade, key, scope[key])
    facade._is_previous_response_not_found_error = lambda **kw: False
    facade._is_missing_tool_output_error = lambda **kw: False
    facade._is_security_work_authorization_required_error = lambda *a: False
    facade._service_tier_from_event_payload = lambda payload: None
    facade._TEXT_DELTA_EVENT_TYPES = set()
    facade._should_suppress_text_done_event = lambda **kw: False
    facade.logger = NS(info=lambda *a, **kw: None)
    return scope['_stream_once']


@pytest.mark.parametrize('failure', ['provider', 'closed', 'wrong_account', 'replay'])
@pytest.mark.parametrize('previous_response', [False, True])
def test_exact_installed_path_records_guard_failure_without_health_or_retry(tmp_path, failure, previous_response):
    async def run():
        async with guard_at(tmp_path) as guard:
            core, facade = fake_gateway(tmp_path, ['request-1'])
            async def failed_original(*args, **kwargs):
                raise CanaryStopped('upstream_failed_or_incomplete')
                yield ''
            core.stream_responses = failed_original
            facade.core_stream_responses = failed_original
            binding = InstalledGatewayBinding(guard=guard, core=core, service=facade)
            facade.core_stream_responses = binding.stream_responses
            rows, output = [], []
            async def noop(*args, **kwargs): return None
            async def acquire(*args, **kwargs): return Lease()
            async def write(**kwargs): rows.append(kwargs)
            async def forbidden(*args, **kwargs): pytest.fail('Health/refresh/failover side effect')
            facade.effective_account_concurrency_caps = lambda: None
            facade._call_stream_with_supported_optional_kwargs = lambda function, *a, optional_kwargs, **kw: function(*a, **optional_kwargs, **kw)
            facade._stream_iterator_after_capacity_admission = lambda stream: stream
            execute = load_exact_settlement(facade)
            proxy = NS(_encryptor=NS(decrypt=lambda value: 'synthetic-token'),
                _resolve_upstream_route_for_account=noop,
                _acquire_account_response_create_lease_or_overload=acquire,
                _get_work_admission=lambda: NS(acquire_response_create=acquire),
                _load_balancer=NS(release_account_lease=noop, record_success=forbidden),
                _write_request_log=write, _handle_stream_error=forbidden,
                _ensure_fresh_with_budget=forbidden)
            account = NS(id='selected-row', access_token_encrypted='synthetic-encrypted',
                chatgpt_account_id='selected-upstream', codex_installation_id=None)
            payload = NS(model='gpt-5.6-luna', service_tier=None, reasoning=None,
                previous_response_id='resp_previous' if previous_response else None,
                to_payload=lambda: {'model': 'gpt-5.6-luna', 'stream': True})
            settlement = NS(downstream_visible=False, record_success=True)
            if failure == 'closed': await guard.aclose()
            if failure == 'wrong_account': account.id = 'wrong-row'
            if failure == 'replay': binding._seen_requests.add('request-1')
            try:
                async for line in execute(proxy, account, payload, {}, 'request-1', True,
                        request_started_at=time.monotonic(), api_key=None,
                        api_key_reservation=None, settlement=settlement,
                        suppress_text_done_events=False, upstream_stream_transport='http',
                        request_transport='http', preferred_account_id='selected-row' if previous_response else None):
                    output.append(line)
            except TerminalStreamError as error:
                assert error.code == GUARD_ERROR_CODE
                # Exact outer retry.py's _TerminalStreamError branch only calls
                # _handle_stream_error if this original classifier returns true.
                assert facade._should_penalize_stream_error(error.code) is False
            assert len(output) == 1
            assert 'response.failed' in output[0]
            assert len(rows) == 1
            assert rows[0]['status'] == 'error'
            assert rows[0]['error_code'] == GUARD_ERROR_CODE
            assert rows[0]['input_tokens'] is None and rows[0]['output_tokens'] is None
            assert settlement.record_success is False
            assert settlement.account_health_error is False
            assert not facade._should_retry_stream_error(GUARD_ERROR_CODE)
    asyncio.run(run())
