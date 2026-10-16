from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.api.agent_routes import TurnInput, read_pending_turn
from apps.api.conversation_recovery import pending_turn_input

TURN = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
PHOTO = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


@pytest.fixture
def storage():
    accepted = {'source_version': 1, 'source': {'status': 'active', 'version': 1,
        'text': 'Original narration', 'kind': 'narrator_transcript', 'language': 'zh-CN'},
        'photo_context': [{'kind': 'private_upload', 'photo_id': 'upload:' + PHOTO,
            'content_url': 'private-display-url', 'title': 'Private metadata'}],
        'consumed_photo_key': 'public-photo', 'consumed_photo_revision': 'r1',
        'collector': {'private': 'must not return'}}
    return SimpleNamespace(user_id='verified-owner',
        request=Mock(return_value=SimpleNamespace(json=lambda: [{'client_turn_id': TURN}])),
        agent_turn_by_id=Mock(return_value=None),
        interview_turn_by_id=Mock(return_value=accepted), client=Mock())


def test_pending_recovery_preserves_original_input_and_photo_identity_with_owner_scope(storage):
    pending = pending_turn_input(storage, 'project-a')
    TurnInput.model_validate(pending)
    assert pending['client_turn_id'] == TURN
    assert pending['conversation_text'] == 'Original narration'
    assert pending['source_kind'] == 'narrator_transcript'
    assert pending['uploaded_photo_ids'] == [PHOTO]
    assert pending['photo_selection'] == {'key': 'public-photo', 'revision': 'r1'}
    assert 'collector' not in pending and 'private-display-url' not in str(pending)
    storage.request.assert_called_once_with('GET', '/rest/v1/user_interview_turn', params={
        'select': 'client_turn_id', 'user_id': 'eq.verified-owner',
        'project_id': 'eq.project-a', 'order': 'sequence.desc', 'limit': '1'})


@pytest.mark.parametrize('state', ['saved', 'withdrawn', 'corrected', 'missing'])
def test_pending_recovery_cannot_retry_completed_or_invalid_originals(storage, state):
    if state == 'saved':
        storage.agent_turn_by_id.return_value = {'id': 'saved-reply'}
    elif state == 'withdrawn':
        storage.interview_turn_by_id.return_value['source']['status'] = 'withdrawn'
    elif state == 'corrected':
        storage.interview_turn_by_id.return_value['source']['version'] = 2
    else:
        storage.interview_turn_by_id.return_value = None
    assert pending_turn_input(storage, 'project-a') is None


def test_pending_route_uses_canonical_read_publication_and_closes_storage(storage, monkeypatch):
    from apps.api import agent_routes, lifetime_memory_reads
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda auth: storage)
    calls = []
    def snapshot(service, project, reader):
        calls.append((service, project))
        return reader(object())
    monkeypatch.setattr(lifetime_memory_reads, 'snapshot_lifetime_read', snapshot)
    result = read_pending_turn('project-a', 'Bearer synthetic')
    assert result['turn']['client_turn_id'] == TURN
    assert calls == [(storage, 'project-a')]
    storage.client.close.assert_called_once()


def test_pending_route_does_not_adopt_an_unmapped_project(storage, monkeypatch):
    from apps.api import agent_routes, lifetime_memory_reads
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda auth: storage)
    monkeypatch.setattr(lifetime_memory_reads, 'snapshot_lifetime_read', lambda service, project, reader: reader(None))
    assert read_pending_turn('legacy-project', 'Bearer synthetic') == {'turn': None}
    storage.request.assert_not_called()
