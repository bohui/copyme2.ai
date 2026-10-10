"""Exercise the real REST facade with synthetic SQL output, without services."""
import json
from types import SimpleNamespace

import httpx
import pytest

from memoir_postgres_workflow import PostgresRest


OWNER = '00000000-0000-4000-8000-000000000001'


def adapter(stdout, *, returncode=0, stderr='', service=False):
    calls = []
    def sql(query, *, check=True):
        calls.append({'query': query, 'check': check})
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return PostgresRest(sql, OWNER, service=service), calls


def request():
    return httpx.Request('GET', 'http://synthetic.invalid/rest/v1/user_profile')


@pytest.mark.parametrize('separator', ['\u0085', '\u2028', '\u2029', '\u0085\u2028\u2029'])
@pytest.mark.parametrize('ending', ['\n', '\r\n', ''])
def test_successful_sql_unicode_line_separators_remain_inside_json_strings(separator, ending):
    expected = [{'profile': {'synthetic': 'alpha' + separator + 'omega',
                            'other': '原样保留'}}]
    raw = json.dumps(expected, ensure_ascii=False)
    rest, calls = adapter('SET\nSET\n' + raw + ending)
    response = rest.handle(request())
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/json'
    assert response.json() == expected
    assert len(calls) == 1 and calls[0]['check'] is False
    assert "set role authenticated;" in calls[0]['query']
    assert "set request.jwt.claim.sub='" + OWNER + "'" in calls[0]['query']


@pytest.mark.parametrize('value', [None, [], {}, True, False, 0, 3.25,
    'string', '\u0085\u2028\u2029', {'text': 'first\nsecond\rthird\tend'}])
@pytest.mark.parametrize('ending', ['\n', '\r\n', ''])
def test_json_scalars_collections_and_escaped_controls_round_trip(value, ending):
    rest, calls = adapter(json.dumps(value, ensure_ascii=False) + ending)
    response = rest.handle(request())
    assert response.json() == value
    assert len(calls) == 1


@pytest.mark.parametrize('stdout', ['\n', '\r\n', 'SET\nSET\n\n', 'SET\r\nSET\r\n\r\n'])
def test_blank_physical_sql_null_record_retains_existing_null_mapping(stdout):
    rest, calls = adapter(stdout)
    response = rest.handle(request())
    assert response.status_code == 200 and response.json() is None
    assert len(calls) == 1


@pytest.mark.parametrize('raw', ['{"private":"never disclose",', '[1, 2',
    '{"private": broken}', '"unterminated', '{"a": 1} trailing',
    '{"private":"raw\rcontrol"}', '{"private":"raw\u0085text", bad}',
    'null\u2028', '\u0085null', 'SET', ''])
def test_malformed_or_missing_json_remains_failure_with_safe_numeric_metadata(raw):
    # Empty stdout means no record. A framed empty record is separately SQL NULL.
    stdout = raw + '\n' if raw else ''
    rest, calls = adapter(stdout)
    with pytest.raises(json.JSONDecodeError) as expected:
        json.loads(raw)
    with pytest.raises(json.JSONDecodeError) as actual:
        rest.handle(request())
    assert type(actual.value) is json.JSONDecodeError
    safe = {key: getattr(actual.value, key) for key in
        ('parser_boundary', 'json_line', 'json_column', 'json_position')}
    assert safe == {'parser_boundary': 'postgres_rest_json_record',
        'json_line': expected.value.lineno, 'json_column': expected.value.colno,
        'json_position': expected.value.pos}
    assert all(type(safe[key]) is int for key in ('json_line', 'json_column', 'json_position'))
    assert 'private' not in json.dumps(safe) and 'never disclose' not in json.dumps(safe)
    assert len(calls) == 1


def test_truncated_final_record_never_reuses_previous_valid_json():
    rest, calls = adapter('{"previous":"valid"}\n{"last":\n')
    with pytest.raises(json.JSONDecodeError) as error:
        rest.handle(request())
    assert error.value.parser_boundary == 'postgres_rest_json_record'
    assert len(calls) == 1


def test_sql_error_still_uses_actual_sqlstate_without_success_parser():
    rest, calls = adapter('not JSON\u2028', returncode=1,
        stderr='ERROR: 42501: synthetic permission failure')
    response = rest.handle(request())
    assert response.status_code == 403
    assert response.json()['code'] == '42501'
    assert len(calls) == 1


def test_service_role_and_rpc_sql_unchanged():
    rest, calls = adapter('null\n', service=True)
    response = rest.handle(httpx.Request('POST',
        'http://synthetic.invalid/rest/v1/rpc/read_memoir_lane_state',
        json={'p_lane_id': 'synthetic-lane'}))
    assert response.json() is None
    assert len(calls) == 1
    assert 'set role service_role;' in calls[0]['query']
    assert "select to_jsonb(public.read_memoir_lane_state(p_lane_id=>'synthetic-lane'));" in calls[0]['query']
