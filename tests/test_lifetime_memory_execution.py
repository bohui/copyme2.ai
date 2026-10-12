import asyncio
from uuid import uuid4

import pytest
from apps.api.lifetime_memory_execution import open_execution, ExecutionStateUnavailable


class Connection:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    async def request(self, method, params):
        self.calls.append((method, params))
        if method == 'thread/resume' and self.failure:
            raise self.failure
        return {'thread': {'id':'fresh' if method == 'thread/start' else params['threadId']}}


@pytest.mark.parametrize('reason', ['missing', 'corrupt', 'incompatible'])
def test_disposable_thread_failure_cold_resumes_once_preserving_product_turn(reason):
    connection = Connection(ExecutionStateUnavailable(reason))
    identity = dict(conversation_id=str(uuid4()), client_turn_id=str(uuid4()), generation=3)
    result = asyncio.run(open_execution(connection, thread_id='old', compatible=True,
        start_params={'baseInstructions':'authorized canonical packet'}, identity=identity))
    assert result['thread_id'] == 'fresh' and result['identity'] == identity
    assert [method for method,_ in connection.calls] == ['thread/resume','thread/start']
    assert result['cold_resume_reason'] == reason
    assert connection.calls[1][1]['baseInstructions'] == 'authorized canonical packet'


def test_auth_provider_failure_is_explicit_not_retried_as_corruption():
    connection = Connection(PermissionError('provider authentication failed'))
    with pytest.raises(PermissionError):
        asyncio.run(open_execution(connection, thread_id='old', compatible=True,
            start_params={}, identity={'client_turn_id':'same'}))
    assert len(connection.calls) == 1


def test_stale_epoch_or_missing_volume_never_resumes_old_harness():
    connection = Connection()
    result = asyncio.run(open_execution(connection, thread_id='old', compatible=False,
        start_params={'baseInstructions':'current canonical packet'}, identity={'client_turn_id':'same'}))
    assert [method for method,_ in connection.calls] == ['thread/start']
    assert result['cold_resume_reason'] == 'incompatible'


def test_corrupt_resume_result_falls_back_once_and_bad_start_is_explicit():
    class Corrupt(Connection):
        async def request(self, method, params):
            self.calls.append((method,params))
            return {'thread':{}}
    connection = Corrupt()
    with pytest.raises(ExecutionStateUnavailable):
        asyncio.run(open_execution(connection, thread_id='old', compatible=True, start_params={}, identity={}))
    assert [method for method,_ in connection.calls] == ['thread/resume','thread/start']
