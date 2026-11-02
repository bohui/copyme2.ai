import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.interview_context_tools import InterviewContextTools
from test_lifetime_memory_engine import FENCE


def request(**changes):
    return dict(tool='memoir_read_context', arguments=dict(
        collection='sources', query=None, after=None, event_id=None, **changes))


def test_retrieval_exposes_only_bounded_owned_collections():
    tools = InterviewContextTools(SimpleNamespace(), FENCE)
    tools.read = AsyncMock(return_value={'records': [], 'complete': True})
    result = asyncio.run(tools.call(request()))
    assert result['success'] is True
    assert set(tools.specs()[0]['inputSchema']['properties']) == {'collection', 'query', 'after', 'event_id'}
    tools.read.assert_awaited_once()


@pytest.mark.parametrize('changes', [dict(owner_id='another-owner'), dict(project_id='another-project'),
    dict(collection='user_profile'), dict(query='x' * 81), dict(event_id='unscoped-event')])
def test_model_cannot_choose_an_owner_project_rpc_or_unbounded_query(changes):
    tools = InterviewContextTools(SimpleNamespace(), FENCE)
    tools.read = AsyncMock()
    value = request()
    value['arguments'].update(changes)
    with pytest.raises(ValueError):
        asyncio.run(tools.call(value))
    tools.read.assert_not_awaited()


def test_tool_result_and_call_budgets_are_enforced():
    tools = InterviewContextTools(SimpleNamespace(), FENCE, max_bytes=10)
    tools.read = AsyncMock(return_value={'records': ['too much material']})
    with pytest.raises(ValueError, match='byte limit'):
        asyncio.run(tools.call(request()))
    tools = InterviewContextTools(SimpleNamespace(), FENCE)
    tools.read = AsyncMock(return_value={})
    async def run():
        for _ in range(4):
            await tools.call(request())
        with pytest.raises(ValueError, match='call limit'):
            await tools.call(request())
    asyncio.run(run())
