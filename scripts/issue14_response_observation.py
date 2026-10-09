"""Bounded content-free HTTP/SSE observations; never authorize completion."""
from copy import deepcopy
import json
import math
import time
import httpx
from apps.api.diagnostics import failure_class

MAX_SSE_EVENT_BYTES = 256 * 1024
_COUNT_MAX = 2**53 - 1
_TERMINAL = frozenset({'response.completed', 'response.failed', 'response.incomplete', 'error'})
_EVENTS = frozenset({'response.created', 'response.in_progress', 'response.output_item.added',
    'response.output_item.done', 'response.content_part.added', 'response.content_part.done',
    'response.output_text.delta', 'response.output_text.done', 'response.refusal.delta',
    'response.refusal.done', 'response.reasoning_summary_text.delta',
    'response.reasoning_summary_text.done', 'response.function_call_arguments.delta',
    'response.function_call_arguments.done'}) | _TERMINAL


def _object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate field')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite value')
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Nonfinite value')
        return number
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=finite)
    if type(value) is not dict or type(value.get('type')) is not str:
        raise ValueError('Typed object required')
    return value['type']


class ResponseObservation:
    def __init__(self):
        self.data = {'schema_version':'memoir-response-observation/1', 'phase':'awaiting_headers',
            'headers_received_at_monotonic':None, 'http_status':None,
            'first_byte_at_monotonic':None, 'last_byte_at_monotonic':None,
            'response_bytes_seen':0, 'response_chunks_seen':0, 'sse_enabled':False,
            'sse_event_counts':{name:0 for name in sorted(_EVENTS)}, 'sse_unknown_events':0,
            'sse_invalid_events':0, 'sse_omitted_events':0, 'counts_truncated':False,
            'terminal_sse_category':None, 'terminal_sse_at_monotonic':None,
            'last_terminal_sse_at_monotonic':None, 'eof_at_monotonic':None,
            'eof_observed':False,
            'failure_phase':None, 'failure_class':None, 'cleanup_status':'not_received',
            'cleanup_failure_class':None, 'timestamps_valid':True}
        self._line = bytearray()
        self._data = bytearray()
        self._event = None
        self._discard = False
        self._line_nonempty = False
        self._skip_lf = False
        self._sealed = False
        self._last_stamp = None
        self._first_line = True

    @property
    def buffered_bytes(self):
        return len(self._line) + len(self._data)

    def _count(self, key, amount=1, target=None):
        target = self.data if target is None else target
        value = target[key] + amount
        if value > _COUNT_MAX:
            self.data['counts_truncated'] = True
        target[key] = min(value, _COUNT_MAX)

    def _stamp(self):
        value = time.monotonic()
        if (type(value) not in (int,float) or not 0 <= value < 2**53 or not math.isfinite(value)
                or self._last_stamp is not None and value < self._last_stamp):
            self.data['timestamps_valid'] = False
            return None
        self._last_stamp = value
        return value

    def headers(self, status, sse):
        if self._sealed:
            return
        self.data.update(headers_received_at_monotonic=self._stamp(),
            http_status=status if type(status) is int and 100 <= status <= 599 else None,
            sse_enabled=sse if type(sse) is bool else False, phase='reading_body', cleanup_status='pending')

    def chunk(self, block):
        if self._sealed:
            return
        self._count('response_chunks_seen')
        self._count('response_bytes_seen', len(block))
        stamp = self._stamp()
        if block:
            if self.data['first_byte_at_monotonic'] is None:
                self.data['first_byte_at_monotonic'] = stamp
            self.data['last_byte_at_monotonic'] = stamp
        if not self.data['sse_enabled']:
            return
        # Scan without splitting a large block into an unbounded list of lines.
        offset = 0
        while offset < len(block):
            if self._skip_lf:
                self._skip_lf = False
                if block[offset] == 10:
                    offset += 1
                    continue
            cr, lf = block.find(b'\r', offset), block.find(b'\n', offset)
            ends = [index for index in (cr,lf) if index >= 0]
            end = min(ends) if ends else len(block)
            length = end - offset
            self._line_nonempty = self._line_nonempty or length > 0
            if not self._discard:
                if len(self._line) + length > MAX_SSE_EVENT_BYTES:
                    self._discard = True
                    self._line.clear(); self._data.clear()
                else:
                    self._line.extend(block[offset:end])
            if end == len(block):
                break
            # Empty line dispatches one complete SSE frame; never dispatch at EOF.
            if not self._line_nonempty:
                self._dispatch(stamp)
            elif not self._discard:
                self._field(bytes(self._line))
            self._line.clear()
            self._line_nonempty = False
            self._skip_lf = block[end] == 13
            offset = end + 1

    def _field(self, line):
        if self._first_line:
            line = line.removeprefix(b'\xef\xbb\xbf')
            self._first_line = False
        if line.startswith(b':'):
            return
        key, _, value = line.partition(b':')
        if value.startswith(b' '):
            value = value[1:]
        if key == b'data':
            if len(self._data) + len(value) + 1 > MAX_SSE_EVENT_BYTES:
                self._discard = True
                self._data.clear()
            else:
                self._data.extend(value); self._data.append(10)
        elif key == b'event':
            # Retain only fixed enum names, never arbitrary event fields.
            self._event = next((name for name in _EVENTS if value == name.encode()), '')

    def _dispatch(self, stamp):
        try:
            if self._discard:
                self._count('sse_omitted_events')
                return
            if not self._data:
                return
            raw = bytes(self._data[:-1])
            if raw == b'[DONE]':
                name = 'done_marker'
            else:
                try:
                    name = _object(raw)
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    self._count('sse_invalid_events')
                    return
                if self._event is not None and self._event != name:
                    self._count('sse_invalid_events')
                    return
                if name not in _EVENTS:
                    self._count('sse_unknown_events')
                    return
                self._count(name, target=self.data['sse_event_counts'])
            if name in _TERMINAL or name == 'done_marker':
                previous = self.data['terminal_sse_category']
                self.data.update(terminal_sse_category=(name if previous in (None,name) else 'conflicting'),
                    last_terminal_sse_at_monotonic=stamp, phase='awaiting_eof')
                if previous is None:
                    self.data['terminal_sse_at_monotonic'] = stamp
        finally:
            self._data.clear(); self._event = None; self._discard = False

    def eof(self):
        if self._sealed:
            return
        if self._line or self._data or self._discard:
            self._count('sse_omitted_events' if self._discard else 'sse_invalid_events')
        self._line.clear(); self._data.clear()
        self.data.update(eof_observed=True, eof_at_monotonic=self._stamp(), phase='eof')

    def failed(self, classification):
        if not self._sealed:
            self.data.update(failure_phase=self.data['phase'], failure_class=classification)

    def close(self):
        self._sealed = True
        self._line.clear(); self._data.clear()

    def snapshot(self):
        return deepcopy(self.data)


class ObservedResponseStream(httpx.AsyncByteStream):
    """Delegate unchanged chunks/close; observe EOF before HTTPX auto-close."""
    def __init__(self, stream, observation):
        self._stream, self._observation = stream, observation

    async def __aiter__(self):
        async for block in self._stream:
            yield block
        self._observation.eof()

    async def aclose(self):
        data = self._observation.data
        eof = data['eof_observed']
        if eof and data['failure_phase'] is None:
            data['phase'] = 'closing_response'
        try:
            await self._stream.aclose()
        except BaseException as error:
            data.update(cleanup_status='failed', cleanup_failure_class=failure_class(error))
            raise
        data['cleanup_status'] = 'closed'
        if eof and data['failure_phase'] is None:
            data['phase'] = 'eof'
