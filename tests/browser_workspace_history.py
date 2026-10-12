"""Controlled turn/history boundary for the workspace browser fixture only.

Project creation, project updates and memory sessions still use the real demo
API. This in-memory adapter models saved external collector replies, not SQL
privacy/RLS coverage. Only successfully created projects owned by the fixed demo
principal may receive or expose the fixture's exact original narrator text.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, NAMESPACE_URL, uuid5


OWNER = 'demo-storyteller'
AUTHORIZATION = 'Bearer browser-test-token'
PROJECT_PATH = '/api/v1/memoir/projects'
TURN_PATH = '/api/v1/memoir/agent/turn'
HISTORY_PATH = re.compile(r'^/api/v1/memoir/user/projects/([A-Za-z0-9][A-Za-z0-9_-]{0,127})/history$')


class FixtureRejected(ValueError):
    def __init__(self, status=400):
        super().__init__('Workspace fixture request is outside its recorded scope')
        self.status = status


def _reject(route, error):
    return route.fulfill(status=error.status, json={'detail': str(error)},
                         headers={'Cache-Control': 'no-store'})


class WorkspaceHistory:
    def __init__(self):
        self._projects = {}
        self._turns = {}
        self._cursors = {}

    def register_project(self, project):
        if (project.get('owner_id') != OWNER or project.get('storyteller_id') != OWNER
                or project.get('mode') != 'self' or project.get('requires_supabase_auth') is not False
                or not isinstance(project.get('id'), str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', project['id'])):
            raise FixtureRejected(403)
        self._projects.setdefault(project['id'], [])

    def project_request(self, route):
        # Register only the actual successful creation response, never an ID
        # supplied by a controlled turn or a local-storage/history read.
        headers = {key: value for key, value in route.request.headers.items()
                   if key.lower() != 'authorization'}
        headers['x-account-id'] = OWNER
        if route.request.method == 'POST' and urlsplit(route.request.url).path == PROJECT_PATH:
            response = route.fetch(headers=headers)
            if response.status == 201:
                self.register_project(response.json())
            return route.fulfill(response=response)
        return route.continue_(headers=headers)

    def _authorize(self, request, project_id):
        headers = {key.lower(): value for key, value in request.headers.items()}
        if (headers.get('authorization') != AUTHORIZATION
                or headers.get('x-account-id', OWNER) != OWNER):
            raise FixtureRejected(401)
        if not isinstance(project_id, str) or project_id not in self._projects:
            raise FixtureRejected(404)

    def turn_events(self, request, reply):
        if request.method != 'POST' or urlsplit(request.url).path != TURN_PATH:
            raise FixtureRejected()
        body = request.post_data_json
        if not isinstance(body, dict):
            raise FixtureRejected()
        project_id = body.get('project_id')
        self._authorize(request, project_id)
        client_id = body.get('client_turn_id')
        try:
            if str(UUID(client_id)) != client_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise FixtureRejected() from None
        # Never recover narration from text: it is the assembled worker prompt.
        narrator = body.get('conversation_text')
        if (not isinstance(narrator, str) or not narrator.strip()
                or body.get('source_kind') not in {'narrator_chat', 'narrator_transcript'}
                or body.get('language') not in {'en-AU', 'zh-CN'}
                or body.get('uploaded_photo_ids') or body.get('photo_selection')
                or not isinstance(reply, dict) or not isinstance(reply.get('reply'), str)):
            raise FixtureRejected()
        original = (project_id, narrator, body['source_kind'], body['language'])
        if client_id in self._turns:
            previous, events = self._turns[client_id]
            if previous != original:
                raise FixtureRejected(409)
            return deepcopy(events)
        sequence = len(self._projects[project_id]) + 1
        scope = f'workspace-fixture/{OWNER}/{project_id}/{client_id}'
        source_id, server_id = [str(uuid5(NAMESPACE_URL, scope + '/' + kind)) for kind in ('source', 'turn')]
        accepted = {'project_id': project_id, 'client_turn_id': client_id, 'accepted_source_id': source_id}
        saved = {**deepcopy(reply), **accepted, 'conversation_saved': True, 'server_turn_id': server_id}
        events = [{'type': 'source_accepted', 'data': accepted},
                  {'type': 'conversation_saved', 'data': saved}]
        # The saved fast path intentionally does not apply bundled workspace
        # fields. Match its separate event contract; terminal result decoding
        # strips these same fields to avoid repeating project writes.
        workspace = {key: deepcopy(reply[key]) for key in (
            'place_journey', 'place_journey_change', 'place_journeys', 'profile_updates',
            'family_context', 'family_context_update', 'family_features_enabled') if key in reply}
        if workspace:
            events.append({'type': 'workspace_update', 'data': workspace})
        events.append({'type': 'result', 'data': deepcopy(saved)})
        item = {'server_turn_id': server_id, 'client_turn_id': client_id, 'kind': 'agent',
                'created_at': (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=sequence)).isoformat(),
                'source_sequence': str(sequence), 'conversation_sequence': str(sequence),
                'source_id': source_id, 'source_version': '1', 'source_status': 'active',
                'narrator_text': narrator, 'reply': reply['reply']}
        self._projects[project_id].append(item)
        self._turns[client_id] = (original, deepcopy(events))
        return events

    def history(self, request):
        url = urlsplit(request.url)
        match = HISTORY_PATH.fullmatch(url.path)
        if request.method != 'GET' or not match:
            raise FixtureRejected()
        project_id = match[1]
        self._authorize(request, project_id)
        query = parse_qs(url.query, keep_blank_values=True)
        if set(query) - {'limit', 'cursor'} or any(len(values) != 1 for values in query.values()):
            raise FixtureRejected()
        limit = query.get('limit', ['100'])[0]
        if not limit.isdecimal() or not 1 <= int(limit) <= 100:
            raise FixtureRejected()
        rows = self._projects[project_id]
        end = len(rows)
        if 'cursor' in query:
            stored = self._cursors.get(query['cursor'][0])
            if stored is None or stored[0] != project_id:
                raise FixtureRejected()
            end = stored[1]
        start = max(0, end - int(limit))
        cursor = None
        if start:
            cursor = str(uuid5(NAMESPACE_URL, f'workspace-fixture/{OWNER}/{project_id}/before/{start}'))
            self._cursors[cursor] = (project_id, start)
        return {'schema_version': 1, 'project_id': project_id, 'policy_epoch': '1',
                'items': deepcopy(rows[start:end]), 'next_cursor': cursor}

    def history_request(self, route):
        try:
            body = self.history(route.request)
        except FixtureRejected as error:
            # Synthetic diagnostics only: omit authority, query, bearer and body.
            print(f'Workspace history fixture rejected {route.request.method} {urlsplit(route.request.url).path} ({error.status})')
            return _reject(route, error)
        return route.fulfill(json=body, headers={'Cache-Control': 'no-store'})


class _SavedTurnRoute:
    def __init__(self, route, history):
        self._route, self._history = route, history
        self.request = route.request

    def fulfill(self, **kwargs):
        # Explicit rejection fixtures retain their original status/body and do
        # not produce a fake saved receipt or history row.
        if kwargs.get('status', 200) != 200:
            return self._route.fulfill(**kwargs)
        try:
            reply = kwargs['json'] if 'json' in kwargs else json.loads(kwargs['body'])
            events = self._history.turn_events(self.request, reply)
        except FixtureRejected as error:
            return _reject(self._route, error)
        return self._route.fulfill(content_type='application/x-ndjson',
            headers={'Cache-Control': 'no-store'},
            body=''.join(json.dumps(event, ensure_ascii=False) + '\n' for event in events))


def mock_workspace_turn(page, handler):
    """Keep each test's original response/callback while recording saved input."""
    page.route('**/api/v1/memoir/agent/turn',
               lambda route: handler(_SavedTurnRoute(route, page.workspace_history)))
