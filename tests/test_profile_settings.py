from copy import deepcopy
from unittest.mock import Mock

from fastapi.testclient import TestClient

from apps.api import agent_routes
from apps.api.main import create_app
from apps.api.store import MemoryStore


def test_profile_settings_merge_clear_and_preserve_private_context(monkeypatch):
    saved = {'name': '慧博', 'preferred_language': 'zh-CN', 'avatar_style': 'male',
             'story_focus': {'where': '开封'}, 'story_flow': {'chapter': 2}}
    storage = Mock()
    storage.user_id = 'profile-user'
    storage.profile.side_effect = lambda: deepcopy(saved)
    storage.save_profile.side_effect = lambda profile: (saved.clear(), saved.update(profile))
    storage.acquire_agent_turn_lease.return_value = True
    storage.renew_agent_turn_lease.return_value = True
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda auth: storage)
    client = TestClient(create_app(MemoryStore()))
    response = client.get('/v1/agent/profile')
    assert response.status_code == 200
    assert response.json()['name'] == '慧博'
    assert 'story_flow' not in response.json()
    response = client.patch('/v1/agent/profile', json={'preferred_language': 'en-AU', 'birth_year': 1983})
    assert response.status_code == 200
    assert saved['preferred_language'] == 'en-AU'
    assert saved['name'] == '慧博'
    assert saved['avatar_style'] == 'male'
    assert saved['story_flow'] == {'chapter': 2}
    assert client.patch('/v1/agent/profile', json={'preferred_language': None, 'name': ''}).status_code == 200
    assert 'preferred_language' not in saved and 'name' not in saved
    assert client.patch('/v1/agent/profile', json={'preferred_language': 'invalid'}).status_code == 422
    assert client.patch('/v1/agent/profile', json={'birth_year': 1700}).status_code == 422
    storage.acquire_agent_turn_lease.return_value = False
    storage.save_profile.reset_mock()
    assert client.patch('/v1/agent/profile', json={'name': 'Changed'}).status_code == 409
    storage.save_profile.assert_not_called()


def test_profile_settings_require_authentication(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    client = TestClient(create_app(MemoryStore()))
    assert client.get('/v1/agent/profile').status_code == 401
    assert client.patch('/v1/agent/profile', json={'name': 'A'}).status_code == 401


def test_explicit_locale_preserves_first_reply_and_blocks_stale_workspace_write(monkeypatch):
    from apps.api import supabase_routes
    from apps.api.conversation_locale import record
    saved={'preferred_language':'zh-CN','conversation_language':record('zh-CN',source='first_reply',detected='zh-CN')}
    storage=Mock();storage.user_id='owner'
    storage.profile.side_effect=lambda:deepcopy(saved)
    storage.save_profile.side_effect=lambda p:(saved.clear(),saved.update(p))
    storage.acquire_agent_turn_lease.return_value=True;storage.renew_agent_turn_lease.return_value=True
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:storage)
    monkeypatch.setattr(supabase_routes,'storage',lambda _:storage)
    client=TestClient(create_app(MemoryStore()))
    response=client.patch('/v1/agent/profile',json={'preferred_language':'en-AU'})
    assert response.status_code==200 and response.json()['conversation_language']['revision']==2
    assert saved['conversation_language']['first_reply_locale']=='zh-CN'
    assert saved['conversation_language']['source']=='explicit'
    response=client.put('/v1/user/profile',json={'preferred_language':'zh-CN','conversation_language':{'version':1},'name':'Synthetic name'})
    assert response.status_code==200 and saved['preferred_language']=='en-AU'
    assert saved['conversation_language']['revision']==2 and saved['name']=='Synthetic name'
    client.patch('/v1/agent/profile',json={'preferred_language':None})
    assert saved['conversation_language']['locale']=='zh-CN' and saved['conversation_language']['revision']==3
