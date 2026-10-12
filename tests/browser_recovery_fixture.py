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
        'id': '60a00000-0000-4000-8000-000000000010', 'kind': 'agent', 'project_id': project_id, 'created_at': '2026-10-07T12:00:00+00:00',
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
    bind_project_history(storage,
        lambda value: value == project_id and storage.user_id == RECOVERY_OWNER,
        lambda _: storage.all_memories.return_value)
    return storage


def navigation_storage(principal, projects, history=None):
    service = Mock(spec=UserStorage)
    service.client = Mock()
    service.user_id = NAVIGATION_USERS[principal]
    service.is_anonymous = principal == 'guest'
    service.user = {'id': service.user_id, 'is_anonymous': service.is_anonymous}
    service.profile.return_value = {'preferred_language': 'zh-CN'}
    service.lifetime_rpc.side_effect = unmapped_identity_reader(
        lambda project_id: project_id in projects)
    def request(method, path, *, params):
        assert method == 'GET'
        assert path in {'/rest/v1/user_memoir_project', '/rest/v1/user_memory',
                        '/rest/v1/user_conversation_attachment'}, 'Unexpected navigation storage endpoint'
        assert params['user_id'] == 'eq.' + service.user_id
        return Mock(json=lambda: [])
    service.request.side_effect = request
    bind_project_history(service,
        lambda project_id: projects.get(project_id, {}).get('supabase_owner_id') == service.user_id,
        lambda project_id: (history or {}).get(project_id, []))
    return service


def bind_project_history(service, owns_project, rows_for_project):
    """Supply only the scenario's owned ledger rows to the real history DTO."""
    from copy import deepcopy
    from datetime import datetime

    def project(project_id):
        if not owns_project(project_id):
            return None
        return {'project_id': project_id, 'policy_epoch': 1}

    def rows(project_id):
        assert owns_project(project_id), 'History read crossed its fixture owner/project'
        return sorted(rows_for_project(project_id),
            key=lambda row: (row['created_at'], row['id']), reverse=True)

    def page(project_id, limit, boundary):
        assert type(limit) is int and 2 <= limit <= 101
        values = rows(project_id)
        if boundary is not None:
            keys = [(datetime.fromisoformat(row['created_at']).isoformat(), row['id']) for row in values]
            if boundary not in keys:
                raise ValueError('Unknown fixture history cursor boundary')
            values = values[keys.index(boundary) + 1:]
        return deepcopy(values[:limit])

    def sources(project_id, turn_ids):
        values = rows(project_id)
        known = {row.get('client_turn_id') or row['id'] for row in values}
        assert set(turn_ids) <= known, 'Unexpected narrator-source turn lookup'
        return [deepcopy(row['_source']) for row in values
                if row.get('_source') and (row.get('client_turn_id') or row['id']) in turn_ids]

    def interview(project_id, turn_id):
        assert any((row.get('client_turn_id') or row['id']) == turn_id for row in rows(project_id))
        return None  # These scenarios do not have an interview/photo-plan receipt.

    service.memoir_project.side_effect = project
    service.project_conversation_page.side_effect = page
    service.narrator_sources_by_turns.side_effect = sources
    service.interview_turn_by_id.side_effect = interview


def forward_project_history(route, client, known_projects, requests):
    """Forward named history reads, including their original auth and cursor.

    The browser fixtures have a finite server-created project registry. Invalid
    routes and methods never turn into a successful generic JSON object.
    """
    import re
    from urllib.parse import parse_qs, urlsplit

    url = urlsplit(route.request.url)
    path = url.path.split('/api/v1/memoir', 1)[-1]
    if path != '/user/projects' and not path.startswith('/user/projects/'):
        return False
    match = re.fullmatch(r'/user/projects/([A-Za-z0-9][A-Za-z0-9_-]{0,127})/history', path)
    status, detail = None, None
    query = parse_qs(url.query, keep_blank_values=True)
    if not match or match[1] not in known_projects:
        status, detail = 404, 'Unknown fixture project history'
    elif route.request.method != 'GET':
        status, detail = 405, 'History is read-only'
    elif (set(query) - {'limit', 'cursor'} or any(len(values) != 1 for values in query.values())
          or 'limit' in query and (not query['limit'][0].isascii() or not query['limit'][0].isdigit()
                                   or not 1 <= int(query['limit'][0]) <= 100)
          or 'cursor' in query and not query['cursor'][0]):
        status, detail = 422, 'Unexpected fixture history query'
    if status is not None:
        requests.append((route.request.method, path, status))
        route.fulfill(status=status, json={'detail': detail})
        return True
    response = client.get('/v1' + path + ('?' + url.query if url.query else ''),
        headers={key: value for key, value in route.request.headers.items()
                 if key in {'authorization', 'content-type'}})
    requests.append((route.request.method, path, response.status_code))
    route.fulfill(status=response.status_code, content_type='application/json', body=response.text)
    return True


def save_navigation_turn(history, project_id, packet, reply):
    """Commit only the one controlled stream scenario that emits a saved event."""
    from uuid import UUID

    assert packet['project_id'] == project_id
    turn_id = str(UUID(packet['client_turn_id']))
    assert turn_id == packet['client_turn_id']
    narrator = packet['conversation_text']
    row = {'id': '60b00000-0000-4000-8000-000000000010', 'client_turn_id': turn_id,
           'project_id': project_id, 'kind': 'agent', 'created_at': '2026-10-07T12:00:00+00:00',
           'source_sequence': 1, 'content': 'Storyteller: ' + narrator + '\nMemory Spark: ' + reply,
           '_source': {'id': '60b00000-0000-4000-8000-000000000011', 'client_turn_id': turn_id,
                       'project_id': project_id, 'kind': 'narrator_chat', 'sequence': 1,
                       'version': 1, 'status': 'active', 'text': narrator}}
    assert not history.get(project_id), 'This fixture saves only one controlled turn'
    history[project_id] = [row]
    return row
