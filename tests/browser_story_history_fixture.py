"""Owned external-history seam for the provider-free stage/recall UI fixtures."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid5

import httpx

from apps.api.agent_storage import UserStorage
from apps.api.conversation_recovery import conversation_history
from browser_recovery_fixture import bind_project_history, forward_project_history, unmapped_identity_reader


STAGE_OWNER = '60c00000-0000-4000-8000-000000000001'
RECALL_OWNER = '60c00000-0000-4000-8000-000000000002'
BUSY_OWNER = '60c00000-0000-4000-8000-000000000003'


class StoryHistoryFixture:
    def __init__(self, owner_id, project_id, token):
        assert str(UUID(owner_id)) == owner_id
        self.owner_id, self.project_id, self.token = owner_id, project_id, token
        self.rows, self.requests = [], []
        self.storage = Mock(spec=UserStorage)
        self.storage.user_id = owner_id
        self.storage.is_anonymous = False
        self.storage.lifetime_rpc.side_effect = unmapped_identity_reader(lambda value: value == project_id)
        bind_project_history(self.storage, lambda value: value == project_id, lambda _: self.rows)

    def serve(self, route):
        return forward_project_history(route, self, {self.project_id}, self.requests)

    def get(self, path, *, headers):
        """The forwarding adapter preserves the actual token and scoped query."""
        parsed = urlsplit(path)
        assert parsed.path == '/v1/user/projects/' + self.project_id + '/history'
        if headers.get('authorization') != 'Bearer ' + self.token:
            return httpx.Response(401, json={'detail': 'Invalid synthetic history session'})
        query = parse_qs(parsed.query)
        try:
            result = conversation_history(self.storage, self.project_id,
                int(query.get('limit', ['50'])[0]), query.get('cursor', [None])[0])
        except ValueError:
            return httpx.Response(422, json={'detail': 'Invalid synthetic history cursor'})
        return httpx.Response(200, json=result.model_dump(mode='json'))

    def save(self, packet, reply):
        """Record the source and turn before emitting conversation_saved."""
        assert packet['project_id'] == self.project_id
        turn_id = packet['client_turn_id']
        assert str(UUID(turn_id)) == turn_id
        assert not any(row.get('client_turn_id') == turn_id for row in self.rows)
        sequence = len(self.rows) + 1
        namespace = UUID(self.owner_id)
        row = {'id': str(uuid5(namespace, self.project_id + ':memory:' + turn_id)),
               'client_turn_id': turn_id, 'project_id': self.project_id, 'kind': 'agent',
               'created_at': (datetime(2026, 10, 7, tzinfo=timezone.utc) + timedelta(seconds=sequence)).isoformat(),
               'source_sequence': sequence,
               'content': 'Storyteller: ' + packet['conversation_text'] + '\nMemory Spark: ' + reply,
               '_source': {'id': str(uuid5(namespace, self.project_id + ':source:' + turn_id)),
                           'client_turn_id': turn_id, 'project_id': self.project_id,
                           'sequence': sequence, 'version': 1, 'status': 'active',
                           'kind': 'narrator_chat', 'text': packet['conversation_text']}}
        self.rows.append(row)
        return row
