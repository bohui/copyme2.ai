import json
import logging
from pathlib import Path
from uuid import UUID

import pytest

from apps.api.codex_worker_service import WorkerTurnInput
from apps.api.diagnostics import failure_class, log_diagnostic, new_request_id


def test_request_ids_are_bounded_and_failure_classes_are_stable():
    assert new_request_id("diag:test-1") == "diag:test-1"
    generated = new_request_id("bad id with spaces")
    assert len(generated) == 36
    assert failure_class(status_code=504) == "timeout"
    assert failure_class(status_code=502) == "upstream_unavailable"


def test_diagnostic_log_allowlist_excludes_private_values(caplog):
    logger = logging.getLogger("tests.diagnostics")
    with caplog.at_level(logging.INFO, logger="tests.diagnostics"):
        log_diagnostic(
            logger,
            "synthetic_failure",
            "diag-test",
            component="memoir.test",
            status="failed",
            failure_class="timeout",
            prompt="private storyteller text",
            reply="private model reply",
        )
    record = json.loads(caplog.records[0].message.split(" ", 1)[1])
    assert record == {
        "component": "memoir.test",
        "event": "synthetic_failure",
        "failure_class": "timeout",
        "request_id": "diag-test",
        "status": "failed",
    }


def test_worker_input_accepts_only_bounded_diagnostic_id():
    payload = WorkerTurnInput(
        user_id=UUID(int=1),
        text="synthetic",
        diagnostic_request_id="diag-worker-1",
    )
    assert payload.diagnostic_request_id == "diag-worker-1"


def _caught_parser_error(filename=None, function='_persist_workspace'):
    """Controlled traceback: no model, transport or source-file execution."""
    filename = filename or str(Path(__file__).resolve().parents[1] / 'apps/api/codex_runtime.py')
    scope = {'json': json}
    code = f'def {function}():\n    private_local = "LOCAL_SECRET"\n    raise json.JSONDecodeError("MESSAGE_SECRET", "DOCUMENT_SECRET", 4)\n'
    exec(compile(code, filename, 'exec'), scope)
    try:
        scope[function]()
    except json.JSONDecodeError as error:
        return error


def test_json_failure_details_keep_location_without_exception_contents():
    from apps.api.diagnostics import json_failure_details
    error = _caught_parser_error()
    error.parser_boundary = 'postgres_rest_json_record'
    error.json_line, error.json_column, error.json_position = 7, 13, 105
    error.__cause__ = RuntimeError('CHAIN_SECRET')
    safe = json_failure_details(error)
    assert safe == {
        'error_type': 'JSONDecodeError', 'parser_boundary': 'postgres_rest_json_record',
        'json_line': 7, 'json_column': 13, 'json_position': 105,
        'frames': [{'filename': 'apps/api/codex_runtime.py', 'function': '_persist_workspace', 'line': 3}],
    }
    encoded = json.dumps(safe)
    for private in ('MESSAGE_SECRET', 'DOCUMENT_SECRET', 'LOCAL_SECRET', 'CHAIN_SECRET', 'raise json',
                    str(Path(__file__).resolve().parents[1])):
        assert private not in encoded


def test_json_failure_details_fallback_and_unknown_error_types_are_narrow():
    from apps.api.diagnostics import json_failure_details
    error = _caught_parser_error('/private/SECRET/apps/api/codex_runtime.py')
    error.parser_boundary = 'SECRET_BOUNDARY'
    error.json_line = 999
    assert json_failure_details(error) == {
        'error_type': 'JSONDecodeError', 'parser_boundary': 'json_decode',
        'json_line': 1, 'json_column': 5, 'json_position': 4,
    }
    assert json_failure_details(RuntimeError('MESSAGE_SECRET')) == {}
    assert json_failure_details(_caught_parser_error(function='SECRET_FUNCTION')).get('frames') is None


@pytest.mark.parametrize('filename,function', [
    ('apps/api/codex_runtime.py', 'consume_worker_stream'),
    ('apps/api/codex_agent.py', 'receive'),
    ('scripts/issue14_subscription_session.py', 'handle_async_request'),
])
def test_known_inner_json_parsers_keep_exact_safe_frame_locations(filename, function):
    from apps.api.diagnostics import json_failure_details
    path = str(Path(__file__).resolve().parents[1] / filename)
    details = json_failure_details(_caught_parser_error(path, function))
    assert details['frames'] == [{'filename': filename, 'function': function, 'line': 3}]
    assert details['parser_boundary'] == 'json_decode'
    assert path not in json.dumps(details)
    assert json_failure_details(_caught_parser_error(path, '_unknown_parser')).get('frames') is None


@pytest.mark.parametrize('bad', [True, -1, 2**100, '123', 1.5, None])
def test_json_failure_numeric_metadata_is_bounded_exact_integer_only(bad):
    from apps.api.diagnostics import json_failure_details
    error = _caught_parser_error()
    error.parser_boundary = 'postgres_rest_json_record'
    error.json_line = error.json_column = error.json_position = bad
    details = json_failure_details(error)
    assert not {'json_line', 'json_column', 'json_position'} & details.keys()


def test_serialized_failure_details_are_revalidated_not_blindly_copied():
    from apps.api.diagnostics import sanitize_json_failure_details
    source = {
        'error_type': 'JSONDecodeError', 'parser_boundary': 'postgres_rest_json_record',
        'json_line': 2, 'json_column': 5, 'json_position': 12,
        'message': 'MESSAGE_SECRET', 'doc': 'DOCUMENT_SECRET', 'locals': {'key': 'LOCAL_SECRET'},
        'frames': [
            {'filename': 'apps/api/codex_runtime.py', 'function': '_persist_workspace',
             'line': 42, 'source': 'SOURCE_SECRET', 'locals': {'key': 'LOCAL_SECRET'}},
            {'filename': '/private/SECRET/apps/api/codex_runtime.py', 'function': 'turn', 'line': 2},
            {'filename': 'apps/api/codex_runtime.py', 'function': 'SECRET_FUNCTION', 'line': 2},
            {'filename': 'apps/api/codex_runtime.py', 'function': 'turn', 'line': True},
        ],
    }
    assert sanitize_json_failure_details(source) == {
        'error_type': 'JSONDecodeError', 'parser_boundary': 'postgres_rest_json_record',
        'json_line': 2, 'json_column': 5, 'json_position': 12,
        'frames': [{'filename': 'apps/api/codex_runtime.py', 'function': '_persist_workspace', 'line': 42}],
    }
    source.update(parser_boundary='SECRET_BOUNDARY', error_type='SECRET_ERROR')
    assert sanitize_json_failure_details(source) == {}


def test_sanitized_frame_list_is_small_and_keeps_innermost_locations():
    from apps.api.diagnostics import sanitize_json_failure_details
    result = sanitize_json_failure_details({'error_type': 'JSONDecodeError', 'frames': [
        {'filename': 'apps/api/codex_runtime.py', 'function': 'turn', 'line': number}
        for number in range(1, 20)]})
    assert [frame['line'] for frame in result['frames']] == [16, 17, 18, 19]


def test_postgres_parser_error_retains_innermost_exact_source_frame_offline():
    from types import SimpleNamespace
    import httpx
    from memoir_postgres_workflow import PostgresRest
    from apps.api.diagnostics import json_failure_details

    def sql(query, *, check):
        return SimpleNamespace(returncode=0, stdout='SET\n{"private":"DOCUMENT_SECRET",\n', stderr='')
    rest = PostgresRest(sql, '00000000-0000-4000-8000-000000000001')
    with pytest.raises(json.JSONDecodeError) as caught:
        rest.handle(httpx.Request('GET', 'http://synthetic.invalid/rest/v1/user_profile'))
    details = json_failure_details(caught.value)
    assert details['parser_boundary'] == 'postgres_rest_json_record'
    assert details['json_position'] == caught.value.json_position
    assert details['frames'][-1]['filename'] == 'tests/memoir_postgres_workflow.py'
    assert details['frames'][-1]['function'] == 'handle'
    assert type(details['frames'][-1]['line']) is int
    assert 'DOCUMENT_SECRET' not in json.dumps(details)
    assert 'private' not in json.dumps(details)


def test_sanitizer_never_stringifies_untrusted_metadata():
    from apps.api.diagnostics import sanitize_json_failure_details
    class Unprintable:
        def __str__(self):
            pytest.fail('Diagnostics must not stringify private values')
    private = Unprintable()
    assert sanitize_json_failure_details({'error_type': 'JSONDecodeError',
        'parser_boundary': private, 'json_line': private, 'json_column': private,
        'json_position': private, 'frames': [{'filename': private, 'function': private,
                                            'line': private}], 'message': private}) == {
        'error_type': 'JSONDecodeError'}


@pytest.mark.parametrize('worker_steps', [0, 512])
def test_workspace_parser_details_are_private_and_public_error_stays_type_only(monkeypatch, worker_steps):
    import asyncio
    from apps.api.codex_runtime import CodexRuntime
    from scripts.issue14_subscription_runner import _runtime_failure_summary, _runtime_readback, SubscriptionRunnerError
    from scripts.memoir_fifty_browser import _public_turn

    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)

    class Storage:
        user_id = 'parser-diagnostic-fixture'
        def acquire_agent_turn_lease(self, *args): return True
        def release_agent_turn_lease(self, *args): return True
        def renew_agent_turn_lease(self, *args): return True
        def agent_session(self): return None
        def memories(self): return []
        def profile(self): return {'preferred_language': 'en-AU'}
        def save_profile(self, profile): pass
        def commit_agent_turn(self, *args, **kwargs): return {'id': 'memory', 'source_sequence': 1}

    async def run():
        runtime, events, worker_calls = CodexRuntime(worker_url='http://controlled-worker'), [], []
        correlation = {'run_id': '00000000-0000-4000-8000-000000000001',
                       'case_id': 'parser-diagnostic-fixture', 'round_id': '1'}
        async def worker(**kwargs):
            worker_calls.append(kwargs.get('agent_role', 'collector'))
            return {'thread_id': 'collector', 'reply': 'Saved controlled reply.', 'artifacts': [],
                    'trajectory': {'steps': [{'action': 'synthetic.worker.completed',
                        'output': {'status': 'completed'}} for _ in range(worker_steps)]}}
        async def fail_workspace(*args, **kwargs):
            error = _caught_parser_error()
            error.parser_boundary = 'postgres_rest_json_record'
            error.json_line, error.json_column, error.json_position = 2, 7, 19
            raise error
        async def emit(event): events.append(event)
        monkeypatch.setattr(runtime, '_worker_turn', worker)
        monkeypatch.setattr(runtime, '_run_workspace_job', fail_workspace)
        result = await runtime.turn(Storage(), 'Controlled original input.', language='en-AU',
                                    on_event=emit, include_trajectory=True, evaluation=correlation)
        trajectory = result['trajectory']
        failure = trajectory['final']['state']['workspace_failure']
        assert failure['action'] == 'workspace.failed'
        assert failure['error_type'] == 'JSONDecodeError'
        assert failure['parser_boundary'] == 'postgres_rest_json_record'
        assert failure['json_position'] == 19
        assert failure['frames'][-1]['function'] == '_persist_workspace'
        steps = [step for step in trajectory['steps'] if step.get('action') == 'workspace.failed']
        if worker_steps:
            assert steps == []
            assert trajectory['limits']['observed_steps'] == trajectory['limits']['max_steps'] == 512
            assert trajectory['limits']['dropped_steps'] > 0 and trajectory['limits']['overflowed'] is True
        else:
            assert len(steps) == 1 and trajectory['limits']['overflowed'] is False
            assert failure == {'action': 'workspace.failed', **steps[0]['output']}
        assert _runtime_failure_summary(result, correlation) == failure
        # The synthetic source identifier only permits reaching the existing
        # background checks; no actual source, transport or storage is created.
        with pytest.raises(SubscriptionRunnerError, match='background_incomplete'):
            _runtime_readback({**result, 'accepted_source_id': str(UUID(int=2))}, correlation)
        public_result = _public_turn(result)
        assert 'trajectory' not in public_result
        assert 'workspace_failure' not in json.dumps(public_result)
        assert 'parser_boundary' not in json.dumps(public_result)
        public = next(event['data'] for event in events if event['type'] == 'workspace_error')
        assert public['error_type'] == 'JSONDecodeError'
        assert not {'frames', 'parser_boundary', 'json_line', 'json_column', 'json_position'} & public.keys()
        assert result['conversation_saved'] is True
        assert result['reply'] == 'Saved controlled reply.'
        assert result['trajectory']['final']['status'] == 'completed'
        assert worker_calls == ['collector']
        for secret in ('MESSAGE_SECRET', 'DOCUMENT_SECRET', 'LOCAL_SECRET', 'SOURCE_SECRET'):
            assert secret not in json.dumps(failure)
            assert secret not in json.dumps(public)
        async def successful_workspace(*args, **kwargs):
            return {'place_journey': None, 'place_journey_change': None, 'profile_updates': {},
                    'family_context': None, 'family_context_update': None,
                    'tasks': [], 'task_errors': [], 'source_paths': []}
        monkeypatch.setattr(runtime, '_run_workspace_job', successful_workspace)
        following = await runtime.turn(Storage(), 'A later controlled input.', language='en-AU',
            on_event=emit, include_trajectory=True, evaluation={**correlation, 'round_id': '2'})
        assert 'workspace_failure' not in following['trajectory']['final']['state']
        assert following['conversation_saved'] is True
        assert following['reply'] == 'Saved controlled reply.'
        assert worker_calls == ['collector', 'collector']
    asyncio.run(run())
