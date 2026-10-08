"""Inactive actual-send protocol adapter for issue #14.

The only executable route is disposable 127.0.0.1 HTTP with fixed synthetic
identities. No credentials/configuration are read. There is no live opt-in.
This implements the contract intended for a future independently reviewed
binding at GuardedHTTPSession.post, without altering/installing that binding.
"""
import asyncio
import json
import math
from urllib.parse import urlsplit

import httpx

from scripts.issue14_provider_budget import BudgetStopped, ProviderBudget, ROLES


MODEL = 'synthetic-byte-model-v1'
ACCOUNT = 'synthetic-account'
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _json(raw):
    def invalid(value):
        raise ValueError('nonfinite JSON')
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('nonfinite JSON')
        return result
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=invalid,
        parse_float=finite_float)


def _payload(value, output_cap):
    if (type(value) is not dict
            or set(value) - {'model', 'input', 'instructions', 'tools', 'reasoning',
                'stream', 'max_output_tokens'}
            or value.get('model') != MODEL or value.get('stream') is not True
            or type(value.get('max_output_tokens')) is not int
            or value['max_output_tokens'] != output_cap
            or type(value.get('input')) is not list or not value['input']):
        return False
    if 'instructions' in value and type(value['instructions']) is not str:
        return False
    if 'reasoning' in value and (type(value['reasoning']) is not dict
            or set(value['reasoning']) != {'effort'}
            or value['reasoning']['effort'] not in {'low', 'medium', 'high'}):
        return False
    for item in value['input']:
        if type(item) is not dict:
            return False
        kind = item.get('type', 'message')
        if kind == 'message':
            if (set(item) - {'type', 'role', 'content'}
                    or item.get('role') not in {'user', 'assistant', 'system', 'developer'}
                    or type(item.get('content')) is not str):
                return False
        elif kind == 'function_call':
            if (set(item) != {'type', 'call_id', 'name', 'arguments'}
                    or not all(type(v) is str for v in item.values())):
                return False
        elif kind == 'function_call_output':
            if (set(item) != {'type', 'call_id', 'output'}
                    or not all(type(v) is str for v in item.values())):
                return False
        else:
            return False
    tools = value.get('tools', [])
    if type(tools) is not list:
        return False
    for tool in tools:
        if (type(tool) is not dict or set(tool) != {'type', 'name', 'description', 'parameters'}
                or tool['type'] != 'function' or type(tool['name']) is not str
                or type(tool['description']) is not str or type(tool['parameters']) is not dict):
            return False
    return True


def _completion(raw, output_cap):
    """Consume the whole SSE body, including late failures and duplicates."""
    text = raw.decode('utf-8', errors='strict').replace('\r\n', '\n')
    if not text.endswith('\n\n'):
        raise BudgetStopped('protocol_invalid')
    completed = None
    for block in text.split('\n\n'):
        if not block:
            continue
        names, data = [], []
        for line in block.split('\n'):
            if line.startswith(':') or not line:
                continue
            if line.startswith('event:'):
                names.append(line[6:].strip())
            elif line.startswith('data:'):
                data.append(line[5:].lstrip())
            else:
                raise BudgetStopped('protocol_invalid')
        if not data:
            if names:
                raise BudgetStopped('protocol_invalid')
            continue
        event = _json('\n'.join(data))
        if (type(event) is not dict or set(event) != {'type', 'response'}
                or any(name != event.get('type') for name in names)):
            raise BudgetStopped('protocol_invalid')
        if event.get('type') != 'response.completed' or completed is not None:
            raise BudgetStopped('protocol_invalid')
        completed = event.get('response')
    if (type(completed) is not dict
            or set(completed) != {'id', 'status', 'model', 'account', 'max_output_tokens', 'usage'}
            or completed.get('status') != 'completed'
            or completed.get('model') != MODEL or completed.get('account') != ACCOUNT
            or type(completed.get('max_output_tokens')) is not int
            or completed['max_output_tokens'] != output_cap
            or completed.get('error') is not None or completed.get('incomplete_details') is not None):
        raise BudgetStopped('protocol_invalid')
    usage = completed.get('usage')
    if (type(usage) is not dict
            or set(usage) != {'input_tokens', 'output_tokens', 'total_tokens', 'output_tokens_details'}
            or any(type(usage.get(k)) is not int or usage[k] < 0
                for k in ('input_tokens', 'output_tokens', 'total_tokens'))
            or usage['total_tokens'] != usage['input_tokens'] + usage['output_tokens']
            or type(usage.get('output_tokens_details')) is not dict
            or set(usage['output_tokens_details']) != {'reasoning_tokens'}
            or type(usage['output_tokens_details'].get('reasoning_tokens')) is not int):
        raise BudgetStopped('usage_invalid')
    return dict(response_id=completed.get('id'), input_tokens=usage['input_tokens'],
        output_tokens=usage['output_tokens'],
        reasoning_tokens=usage['output_tokens_details']['reasoning_tokens'])


class ControlledBudgetTransport(httpx.AsyncBaseTransport):
    """Own the one-shot socket transport and reserve immediately before it.

    Fixture input tokens are exactly the byte length of the complete final JSON
    request, including instructions, tools, history and reasoning configuration.
    A real tokenizer's framing, images, server context, tool fees, rates, output
    enforcement and subscription semantics have NOT been established here.
    """

    def __init__(self, *args, **kwargs):
        raise BudgetStopped('live_provider_unverified')

    @classmethod
    def controlled(cls, *, ledger, endpoint):
        try:
            url = urlsplit(endpoint)
            valid = (type(endpoint) is str and url.scheme == 'http'
                and url.hostname == '127.0.0.1' and url.port is not None and 1024 <= url.port <= 65535
                and endpoint == f'http://127.0.0.1:{url.port}/codex/responses')
        except (ValueError, TypeError):
            valid = False
        if not valid or type(ledger) is not ProviderBudget:
            raise BudgetStopped('target_forbidden')
        self = object.__new__(cls)
        self._ledger, self._endpoint = ledger, endpoint
        self._closed = False
        self._wire = httpx.AsyncHTTPTransport(retries=0, trust_env=False, http1=True,
            http2=False, limits=httpx.Limits(max_connections=100, max_keepalive_connections=0))
        return self

    def _reject(self, reason):
        self._ledger.stop(reason)
        raise BudgetStopped(reason)

    async def handle_async_request(self, request):
        if self._closed:
            self._reject('closed')
        if request.method != 'POST' or str(request.url) != self._endpoint:
            self._reject('target_forbidden')
        try:
            pairs = request.headers.multi_items()
            headers = dict(pairs)
            allowed = {'host', 'accept', 'accept-encoding', 'connection', 'user-agent',
                'content-length', 'content-type', 'authorization', 'chatgpt-account-id',
                'x-issue14-request-id', 'x-issue14-role'}
            if len(headers) != len(pairs) or set(headers) - allowed:
                self._reject('identity_mismatch')
            if (headers.get('authorization') != 'Bearer synthetic-token'
                    or headers.get('chatgpt-account-id') != ACCOUNT
                    or headers.get('host') != urlsplit(self._endpoint).netloc):
                self._reject('identity_mismatch')
            if headers.get('x-issue14-role') not in ROLES:
                self._reject('role_forbidden')
            if headers.get('content-type') != 'application/json':
                self._reject('protocol_invalid')
            # Bound request buffering too, before reservation or socket contact.
            chunks, size = [], 0
            async with asyncio.timeout(2):
                async for block in request.stream:
                    size += len(block)
                    if size > MAX_REQUEST_BYTES:
                        self._reject('protocol_invalid')
                    chunks.append(block)
            raw = b''.join(chunks)
            if headers.get('content-length') != str(len(raw)):
                self._reject('protocol_invalid')
            if not _payload(_json(raw), self._ledger.limits.output_tokens_per_request):
                self._reject('protocol_invalid')
        except BudgetStopped:
            raise
        except (ValueError, TypeError, KeyError, RecursionError, TimeoutError):
            self._reject('protocol_invalid')
        except BaseException as error:
            # No socket has been touched yet, but cancellation still revokes
            # the run. Preserve cancellation instead of leaking body errors.
            try:
                self._ledger.stop('send_interrupted_or_failed')
            finally:
                if not isinstance(error, Exception):
                    raise error
            raise BudgetStopped('send_interrupted_or_failed') from None
        # Do not forward the caller-owned request: its asynchronous body stream
        # could have mutated its URL, method, headers, or extensions after the
        # initial checks. Build a private request from only validated snapshots.
        # No caller transport/trace extension or callback crosses this boundary.
        outgoing = httpx.Request('POST', self._endpoint, headers=headers, content=raw,
            extensions={'timeout': dict.fromkeys(('connect', 'read', 'write', 'pool'), 2)})
        ticket = self._ledger.reserve(request_id=headers.get('x-issue14-request-id'),
            role=headers['x-issue14-role'], payload_bytes=len(raw))
        response = None
        try:
            async with asyncio.timeout(5):
                response = await self._wire.handle_async_request(outgoing)
                if (response.status_code != 200
                        or response.headers.get('content-type', '').split(';')[0].strip() != 'text/event-stream'
                        or response.headers.get('content-encoding', 'identity') != 'identity'):
                    raise BudgetStopped('protocol_invalid')
                chunks, size = [], 0
                async for block in response.aiter_raw():
                    size += len(block)
                    if size > MAX_RESPONSE_BYTES:
                        raise BudgetStopped('protocol_invalid')
                    chunks.append(block)
                body = b''.join(chunks)
                await response.aclose()
                response = None
                completion = _completion(body, self._ledger.limits.output_tokens_per_request)
                self._ledger.settle(ticket, **completion)
            # Buffer all bytes and settle durably before exposing any result.
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=body)
        except BaseException as error:
            reason = str(error) if isinstance(error, BudgetStopped) and str(error) in {
                'protocol_invalid', 'usage_invalid', 'response_replay', 'ticket_invalid',
                'journal_unavailable', 'closed'} else 'send_interrupted_or_failed'
            try:
                self._ledger.stop(reason)
            finally:
                if isinstance(error, (asyncio.CancelledError, GeneratorExit, KeyboardInterrupt, SystemExit)):
                    raise error
            raise BudgetStopped(reason) from None
        finally:
            if response is not None:
                try:
                    async with asyncio.timeout(1):
                        await response.aclose()
                except (Exception, asyncio.CancelledError):
                    pass

    async def aclose(self):
        # Closing a client never resets or closes the shared run's ledger.
        self._closed = True
        await self._wire.aclose()
