from unittest.mock import Mock
from fastapi.testclient import TestClient
from apps.api import agent_routes
from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.conversation_phase import PhaseState


def test_control_api_is_typed_and_not_a_narrator_turn(monkeypatch):
    storage=Mock(); storage.conversation_phase.return_value=PhaseState().model_dump(mode='json')
    storage.change_conversation_phase.return_value=PhaseState(phase='shape',selection='explicit',preferred_phase='shape',revision=1,reason='narrator_choice').model_dump(mode='json')
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:storage)
    client=TestClient(create_app(MemoryStore()))
    url='/v1/agent/projects/project/conversation-phase'
    assert client.get(url).json()['conversation_phase']['phase']=='comfort'
    assert client.patch(url,json={'action':'shape','expected_revision':0}).json()['conversation_phase']['phase']=='shape'
    storage.change_conversation_phase.assert_called_once_with('project','shape',0)
    storage.accept_interview_turn.assert_not_called(); storage.commit_agent_turn.assert_not_called()
    for data in ({'action':'trust','expected_revision':1},{'action':'shape','expected_revision':-1},{'action':'pause','expected_revision':0,'owner':'other'}):
        assert client.patch(url,json=data).status_code==422
