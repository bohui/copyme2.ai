from copy import deepcopy
from unittest.mock import Mock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes
from apps.api.main import create_app
from apps.api.store import MemoryStore


def _unmapped_identity(name, **parameters):
    assert name == 'read_lifetime_project_identity', 'Unexpected lifetime operation in legacy fixture'
    assert set(parameters) == {'p_project_id'}
    return None


def test_profile_settings_merge_clear_and_preserve_private_context(monkeypatch):
    saved = {'name': '慧博', 'preferred_language': 'zh-CN', 'avatar_style': 'male',
             'story_focus': {'where': '开封'}, 'story_flow': {'chapter': 2}}
    storage = Mock()
    storage.user_id = '11111111-1111-4111-8111-111111111111'
    storage.lifetime_rpc = Mock(side_effect=_unmapped_identity)
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


@pytest.mark.parametrize('patch', [
    {'profile_automation': {'stopped': False}}, {'profile': {'name': 'Unsafe'}},
    {'story_focus': {}}, {'avatar_style': 'other'}, {'birth_date_expression': 'x' * 121},
    {'birth_year': True}, {'birth_year': '1960'}, {'profile_confirm_all': 'true'},
    {'profile_auto_enabled': 1}, {'profile_release_fields': ['preferred_language']},
    {'profile_release_fields': ['name', 'name']}, {'profile_release_fields': None},
    {'profile_release_fields': ['name'], 'name': 'A'},
    {'profile_confirm_all': True, 'profile_auto_enabled': True},
    {'profile_confirm_all': True, 'profile_release_fields': ['name']},
])
def test_profile_settings_reject_arbitrary_state_and_ambiguous_controls(monkeypatch, patch):
    authenticate = Mock()
    monkeypatch.setattr(agent_routes, 'authenticated_storage', authenticate)
    response = TestClient(create_app(MemoryStore())).patch('/v1/agent/profile', json=patch)
    assert response.status_code == 422
    authenticate.assert_not_called()


def test_profile_settings_canonical_controls_and_read_only_authority(monkeypatch):
    from apps.api import lifetime_memory_reads
    automation = {'schema_version': 1, 'revision': 7, 'auto_enabled': False,
                  'stopped': True, 'manual_complete': True, 'field_locks': {'name': 'manual'},
                  'progress': {'requested_round': 10, 'requested_frontier': 12, 'active_round': 10,
                               'source_frontier': 12, 'covered_round': 5, 'covered_frontier': 7,
                               'skipped_round': 0, 'status': 'pending', 'pending_source_changes': False}}
    saved = {'name': 'Avery', 'birth_date_expression': 'around 1960', 'avatar_style': 'female',
             'private_context': 'not a setting', 'profile_automation': {**automation, 'revision': 1, 'progress': None}}
    storage = Mock(user_id='11111111-1111-4111-8111-111111111111')
    storage.profile.side_effect = lambda: deepcopy(saved)
    storage.acquire_agent_turn_lease.return_value = True
    storage.renew_agent_turn_lease.return_value = True
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: storage)
    monkeypatch.setattr(lifetime_memory_reads, 'find_lifetime_read_identity',
                        lambda *_: SimpleNamespace(project_id='owned'))
    reading = []
    def snapshot(_storage, _project, reader):
        reading.append(True)
        try:
            return reader(None)
        finally:
            reading.pop()
    def rpc(name, **kwargs):
        if name == 'read_lifetime_profile_automation':
            assert reading and not kwargs
            return deepcopy(automation)
        assert name == 'set_lifetime_profile_settings'
        return deepcopy(saved)
    storage.lifetime_rpc.side_effect = rpc
    monkeypatch.setattr(lifetime_memory_reads, 'snapshot_lifetime_read', snapshot)
    client = TestClient(create_app(MemoryStore()))
    response = client.get('/v1/agent/profile')
    assert response.status_code == 200
    assert response.json()['profile_automation'] == automation
    assert response.json()['avatar_style'] == 'female'
    assert 'private_context' not in response.json()
    for patch in [
        {'name': None, 'birth_date_expression': '  around 1960  ', 'avatar_style': 'male'},
        {'profile_confirm_all': True}, {'profile_auto_enabled': True},
        {'profile_release_fields': ['name', 'avatar_style']},
    ]:
        response = client.patch('/v1/agent/profile', json=patch)
        assert response.status_code == 200
        call = [call for call in storage.lifetime_rpc.call_args_list
                if call.args == ('set_lifetime_profile_settings',)][-1]
        assert call.args == ('set_lifetime_profile_settings',)
        assert call.kwargs['p_patch'] == {key: value.strip() if isinstance(value, str) else value
                                          for key, value in patch.items()}
        assert call.kwargs['p_lease_token']
        assert response.json()['profile_automation'] == automation
        assert not set(response.json()) & {'profile_confirm_all', 'profile_auto_enabled', 'profile_release_fields'}
    storage.save_profile.assert_not_called()


def test_legacy_profile_settings_accept_new_fields_without_storing_control_keys(monkeypatch):
    saved = {'story_flow': {'chapter': 2}}
    storage = Mock(user_id='11111111-1111-4111-8111-111111111111')
    storage.lifetime_rpc = Mock(side_effect=_unmapped_identity)
    storage.profile.side_effect = lambda: deepcopy(saved)
    storage.save_profile.side_effect = lambda value: (saved.clear(), saved.update(value))
    storage.acquire_agent_turn_lease.return_value = True
    storage.renew_agent_turn_lease.return_value = True
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: storage)
    client = TestClient(create_app(MemoryStore()))
    response = client.patch('/v1/agent/profile', json={'birth_date_expression': ' around 1960 ', 'avatar_style': 'female'})
    assert response.status_code == 200
    assert saved == {'story_flow': {'chapter': 2}, 'birth_date_expression': 'around 1960', 'avatar_style': 'female'}
    for patch in [{'profile_confirm_all': True}, {'profile_auto_enabled': True}, {'profile_release_fields': ['name']}]:
        storage.save_profile.reset_mock()
        assert client.patch('/v1/agent/profile', json=patch).status_code == 409
        storage.save_profile.assert_not_called()
    assert client.patch('/v1/agent/profile', json={'avatar_style': None, 'birth_date_expression': ''}).status_code == 200
    assert saved == {'story_flow': {'chapter': 2}}


def test_explicit_locale_preserves_first_reply_and_blocks_stale_workspace_write(monkeypatch):
    from apps.api import supabase_routes
    from apps.api.conversation_locale import record
    saved={'preferred_language':'zh-CN','conversation_language':record('zh-CN',source='first_reply',detected='zh-CN')}
    storage=Mock();storage.user_id='11111111-1111-4111-8111-111111111111'
    storage.lifetime_rpc = Mock(side_effect=_unmapped_identity)
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
