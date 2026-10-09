"""BOM position regressions use only content-free synthetic SSE observations."""
import pytest

from scripts.issue14_response_observation import ResponseObservation


@pytest.mark.parametrize('prefix', [b'', b'\n', b'\r\n', b'\r'])
@pytest.mark.parametrize('width', [1, 2, 64])
def test_only_stream_initial_bom_can_prefix_terminal_data(prefix, width):
    raw = prefix + b'\xef\xbb\xbfdata: {"type":"response.completed"}\n\n'
    observation = ResponseObservation()
    observation.headers(200, True)
    observation.chunk(b'')
    for offset in range(0, len(raw), width):
        observation.chunk(raw[offset:offset + width])
    result = observation.snapshot()
    assert result['terminal_sse_category'] == ('response.completed' if not prefix else None)
    assert result['sse_event_counts']['response.completed'] == (0 if prefix else 1)
    assert result['response_bytes_seen'] == len(raw)
    assert result['sse_invalid_events'] == 0
    assert observation.buffered_bytes == 0
