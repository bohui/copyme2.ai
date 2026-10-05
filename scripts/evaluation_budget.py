"""Reserve a run's model budget before any provider request is constructed.

The adapter must measure a conservative input bound and enforce the supplied
output limit at the actual provider boundary. This class cannot make an
unmetered private-worker request into a provider token/spend guarantee.
"""
from dataclasses import dataclass
from collections.abc import Mapping
import asyncio
import math
import time

import httpx


class RequestLimitedTransport(httpx.AsyncBaseTransport):
    """Share one worker-request ceiling across every client/role in a run.

    Worker HTTP requests are not model requests or token/cost measurements.
    The caller owns the underlying transport's lifetime; individual clients
    may close this wrapper without resetting its count or closing siblings.
    """
    def __init__(self, transport, *, max_requests, max_elapsed_seconds=None):
        if type(max_requests) is not int or max_requests < 0:
            raise ValueError('An explicit nonnegative worker request cap is required')
        if (max_elapsed_seconds is not None and
                (type(max_elapsed_seconds) not in (int, float)
                 or not math.isfinite(max_elapsed_seconds) or max_elapsed_seconds <= 0)):
            raise ValueError('A finite positive worker duration is required')
        self.deadline = None if max_elapsed_seconds is None else time.monotonic() + max_elapsed_seconds
        self.transport = transport
        self.max_requests = max_requests
        self.requests_started = 0

    async def handle_async_request(self, request):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise httpx.RequestError('Worker time cap reached', request=request)
        if self.requests_started >= self.max_requests:
            raise httpx.RequestError('Worker request cap reached', request=request)
        self.requests_started += 1
        remaining = None if self.deadline is None else max(0, self.deadline - time.monotonic())
        response = None
        try:
            async with asyncio.timeout(remaining):
                response = await self.transport.handle_async_request(request)
                # Worker replies are JSON. Buffer the complete body inside
                # the same absolute deadline, rather than returning headers
                # and leaving subsequent client consumption unbounded.
                await response.aread()
                return response
        except BaseException:
            if response is not None:
                try:
                    async with asyncio.timeout(5):
                        await response.aclose()
                except (Exception, asyncio.CancelledError):
                    pass
            raise


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class BudgetLimits:
    max_requests: int
    max_input_tokens: int
    max_output_tokens: int
    max_output_tokens_per_request: int


class BudgetedProvider:
    def __init__(self, limits: BudgetLimits, *, max_elapsed_seconds=None):
        values = (limits.max_requests, limits.max_input_tokens,
                  limits.max_output_tokens, limits.max_output_tokens_per_request)
        if any(type(value) is not int or value < 0 for value in values) or values[-1] == 0:
            raise ValueError('Explicit integer request/token caps are required')
        if (max_elapsed_seconds is not None and
                (type(max_elapsed_seconds) not in (int, float)
                 or not math.isfinite(max_elapsed_seconds) or max_elapsed_seconds <= 0)):
            raise ValueError('A finite positive provider duration is required')
        self.deadline = None if max_elapsed_seconds is None else time.monotonic() + max_elapsed_seconds
        self.limits = limits
        self.requests_started = 0
        self.input_tokens_accounted = 0
        self.input_tokens_reported = 0
        self.output_tokens_accounted = 0
        self.output_tokens_reported = 0
        self.blocked_reason = None

    async def call(self, provider, *, input_tokens_upper_bound: int):
        if type(input_tokens_upper_bound) is not int or input_tokens_upper_bound < 0:
            raise ValueError('A measured nonnegative integer input bound is required')
        if self.blocked_reason:
            raise BudgetExceeded('Provider accounting is blocked')
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.blocked_reason = 'provider_time_limit_reached'
            raise BudgetExceeded('Provider time limit reached')
        if self.requests_started >= self.limits.max_requests:
            raise BudgetExceeded('Model request limit reached')
        if self.input_tokens_accounted + input_tokens_upper_bound > self.limits.max_input_tokens:
            raise BudgetExceeded('Model input token limit reached')
        output_bound = self.limits.max_output_tokens_per_request
        if self.output_tokens_accounted + output_bound > self.limits.max_output_tokens:
            raise BudgetExceeded('Model output token limit reached')
        self.requests_started += 1
        self.input_tokens_accounted += input_tokens_upper_bound
        self.output_tokens_accounted += output_bound
        try:
            remaining = None if self.deadline is None else max(0, self.deadline - time.monotonic())
            async with asyncio.timeout(remaining):
                result = await provider(max_output_tokens=output_bound)
        except BaseException:
            self.blocked_reason = 'provider_call_interrupted_or_failed'
            raise
        usage = result.get('usage') if isinstance(result, Mapping) else None
        actual = usage.get('input_tokens') if isinstance(usage, Mapping) else None
        output = usage.get('output_tokens') if isinstance(usage, Mapping) else None
        if not (type(actual) is int and 0 <= actual <= input_tokens_upper_bound
                and type(output) is int and 0 <= output <= output_bound):
            self.blocked_reason = 'provider_usage_missing_invalid_or_over_bound'
            raise BudgetExceeded('Verified bounded provider usage is required')
        self.input_tokens_accounted -= input_tokens_upper_bound - actual
        self.input_tokens_reported += actual
        self.output_tokens_accounted -= output_bound - output
        self.output_tokens_reported += output
        return result

    def receipt(self):
        return {'requests_started': self.requests_started,
                'input_tokens_reported': self.input_tokens_reported,
                'output_tokens_reported': self.output_tokens_reported,
                'input_tokens_accounted': self.input_tokens_accounted,
                'output_tokens_accounted': self.output_tokens_accounted,
                'blocked_reason': self.blocked_reason}
