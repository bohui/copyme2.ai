from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from test_conversation_attribution import Conversation


@pytest.mark.parametrize('short_delay', [True, False])
def test_replay_waits_only_for_brief_unclaimed_scheduling_delay(monkeypatch,short_delay):
    conversation=Conversation.__new__(Conversation)
    conversation.worker=NS(execute_lane=AsyncMock(side_effect=[{'status':'deferred'}, {'status':'finished','retrieval_complete':True}]))
    conversation.last_db_error=''
    def sql(query):
        if "skill='timeline'" in query:return NS(stdout='11111111-1111-4111-8111-111111111111')
        if "skill='guidance'" in query:return NS(stdout='')
        return NS(stdout='.4' if short_delay else '')
    conversation.sql=sql
    waited=[]
    monkeypatch.setattr('test_conversation_attribution.time.sleep',lambda seconds:waited.append(seconds))
    result=conversation.drain()
    assert result['status']==('finished' if short_delay else 'deferred')
    assert conversation.worker.execute_lane.await_count==(2 if short_delay else 1)
    assert bool(waited)==short_delay
