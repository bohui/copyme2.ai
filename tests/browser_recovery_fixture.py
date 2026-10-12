"""Synthetic storage used by the real browser recovery/project API fixtures."""
from unittest.mock import Mock

from apps.api.agent_storage import UserStorage


RECOVERY_OWNER = '60a00000-0000-4000-8000-000000000001'
RECOVERY_GUEST = '60a00000-0000-4000-8000-000000000002'
NAVIGATION_USERS = {'guest': '60b00000-0000-4000-8000-000000000001',
                    'other': '60b00000-0000-4000-8000-000000000002'}


def unmapped_identity_reader(owns_project):
    def read(name, **parameters):
        assert name == 'read_lifetime_project_identity', 'Unexpected lifetime operation in browser fixture'
        assert set(parameters) == {'p_project_id'}, 'Unexpected identity arguments'
        project_id = parameters['p_project_id']
        assert project_id is None or owns_project(project_id), 'Unexpected identity project'
        return None
    return read


def set_recovery_principal(storage, *, guest=False):
    storage.user_id = RECOVERY_GUEST if guest else RECOVERY_OWNER
    storage.user = {'id': storage.user_id, 'is_anonymous': guest}
    storage.is_anonymous = guest


def account_recovery_storage(history_kind, adapter, rounds):
    project_id = 'project_saved'
    storage = Mock(spec=UserStorage)
    set_recovery_principal(storage)
    storage.client = Mock()
    storage.lifetime_rpc.side_effect = unmapped_identity_reader(lambda value: value == project_id)
    storage.profile.return_value = {'name': 'Fixture narrator', 'preferred_language': 'en-AU'}
    storage.recall_rounds_completed.return_value = rounds
    storage.story_entitlement.return_value = None
    storage.all_memories.return_value = [{
        'id': 'saved-turn', 'kind': 'agent', 'project_id': project_id, 'created_at': '2026-10-07',
        'content': 'Storyteller: My saved childhood\nMemory Spark: Tell me about the garden.',
    }]
    def request(method, path, *, params):
        assert method == 'GET'
        assert path in {'/rest/v1/user_memoir_project', '/rest/v1/user_memory',
                        '/rest/v1/user_conversation_attachment'}, 'Unexpected recovery storage endpoint'
        assert params['user_id'] == 'eq.' + storage.user_id
        if params.get('project_id', 'eq.' + project_id) != 'eq.' + project_id:
            return Mock(json=lambda: [])
        rows = []
        if path == '/rest/v1/user_memoir_project' and history_kind == 'memory':
            rows = [{'project_id': project_id}]
        elif path == '/rest/v1/user_conversation_attachment' and (history_kind == 'attachment' or adapter == 'transferred-guest'):
            if 'workspace->>guest_user_id' in params:
                assert params['workspace->>guest_user_id'] == 'eq.' + RECOVERY_GUEST
            rows = [{'id': 'legacy-attachment', 'project_id': project_id, 'created_at': '2026-10-07',
                     'workspace': {'guest_user_id': RECOVERY_GUEST},
                     'messages': [{'role': 'user', 'text': 'My saved childhood'},
                                  {'role': 'assistant', 'text': 'Tell me about the garden.'}]
                                 if history_kind == 'attachment' else []}]
        return Mock(json=lambda: rows)
    storage.request.side_effect = request
    if history_kind == 'attachment':
        storage.all_memories.return_value = []
    storage.saved_memoir_draft.return_value = {
        'status': 'ready', 'preview': {'kind': 'sample_storyline', 'title': 'My reviewed sample',
                                      'text': 'A familiar garden from my childhood.'},
        'revision': 2, 'covered_round': 10, 'updating': True, 'error': None,
    }
    return storage


def navigation_storage(principal, projects):
    service = Mock(spec=UserStorage)
    service.client = Mock()
    service.user_id = NAVIGATION_USERS[principal]
    service.is_anonymous = principal == 'guest'
    service.user = {'id': service.user_id, 'is_anonymous': service.is_anonymous}
    service.profile.return_value = {'preferred_language': 'zh-CN'}
    service.lifetime_rpc.side_effect = unmapped_identity_reader(
        lambda project_id: projects.get(project_id, {}).get('supabase_owner_id') == service.user_id)
    def request(method, path, *, params):
        assert method == 'GET'
        assert path in {'/rest/v1/user_memoir_project', '/rest/v1/user_memory',
                        '/rest/v1/user_conversation_attachment'}, 'Unexpected navigation storage endpoint'
        assert params['user_id'] == 'eq.' + service.user_id
        return Mock(json=lambda: [])
    service.request.side_effect = request
    return service
