"""Sample admission must distinguish queued work from an empty interview."""
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.agent_storage import UserStorage
from apps.api.story_routes import build_router


def preview_storage(**view):
    storage = Mock(spec=UserStorage)
    storage.user_id = 'owner'
    storage.recall_rounds_completed.return_value = 21
    storage.story_entitlement.return_value = None
    storage.profile.return_value = {'preferred_language': 'zh-CN'}
    storage.saved_memoir_draft.return_value = {
        'status': 'collecting', 'preview': None, 'revision': 0,
        'covered_round': 0, 'updating': False, 'error': None,
        'progress': {'composition': {'state': 'finished'},
                     'extraction': {'state': 'finished', 'pending_inputs': 0}},
        **view,
    }
    return storage


def preview_client(storage):
    app = FastAPI()
    app.include_router(build_router(lambda _: storage))
    return TestClient(app)


def test_empty_project_at_account_free_limit_does_not_poll_nonexistent_job():
    storage = preview_storage()
    with preview_client(storage) as client:
        response = client.post('/v1/story/preview', json={'project_id': 'empty-project'})
    assert response.status_code == 200
    assert response.json()['status'] == 'insufficient_context'
    storage.retry_memoir_lane.assert_not_called()


def test_reviewed_progressive_sample_is_returned_while_newer_work_is_pending():
    sample = {'title': 'Childhood', 'text': 'My saved memory.'}
    storage = preview_storage(preview=sample, status='ready', revision=2, covered_round=15, updating=True)
    with preview_client(storage) as client:
        response = client.post('/v1/story/preview', json={'project_id': 'saved-project'})
    assert response.status_code == 200
    assert response.json()['preview'] == sample
    assert response.json()['cached'] is True
    assert response.json()['updating'] is True
    storage.retry_memoir_lane.assert_not_called()


def test_real_pending_progressive_work_keeps_its_polling_reference():
    storage = preview_storage(updating=True)
    with preview_client(storage) as client:
        response = client.post('/v1/story/preview', json={'project_id': 'saved-project'})
    assert response.status_code == 202
    assert response.json()['status'] == 'pending'
    assert response.json()['job']['id'] == 'shared.zh-CN.saved-project'


def test_ineligible_sample_is_not_returned_or_polled_without_replacement_work():
    storage = preview_storage(status='stale', revision=2, covered_round=15)
    with preview_client(storage) as client:
        response = client.post('/v1/story/preview', json={'project_id': 'saved-project'})
    assert response.status_code == 200
    assert response.json()['status'] == 'stale'
    assert response.json()['preview'] is None
