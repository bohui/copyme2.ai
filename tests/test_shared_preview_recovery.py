"""Sample admission must distinguish queued work from an empty interview."""
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.api.agent_storage import UserStorage
from apps.api.story_routes import build_router


def preview_storage(**view):
    storage = Mock(spec=UserStorage)
    storage.user_id = '11111111-1111-4111-8111-111111111111'
    # Explicitly unmapped legacy account; do not let Mock invent a canonical identity.
    storage.lifetime_rpc.return_value = None
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


@pytest.mark.parametrize('completed,expected_status', [(19,409),(20,200)])
def test_extended_conversation_allowance_keeps_the_twenty_round_sample(monkeypatch,completed,expected_status):
    sample={'title':'Childhood','text':'A saved original memory.'}
    storage=preview_storage(preview=sample,status='ready',covered_round=20)
    storage.recall_rounds_completed.return_value=completed
    monkeypatch.setenv('MEMORY_SPARK_EVAL_RECALL_OWNER_ID',storage.user_id)
    monkeypatch.setenv('MEMORY_SPARK_EVAL_RECALL_LIMIT','50')
    with preview_client(storage) as client:
        response=client.get('/v1/story/preview/shared.en-AU.saved-project')
    assert response.status_code==expected_status
    if expected_status==200:assert response.json()['preview']==sample


def test_real_pending_progressive_work_keeps_its_polling_reference():
    storage = preview_storage(updating=True)
    with preview_client(storage) as client:
        response = client.post('/v1/story/preview', json={'project_id': 'saved-project'})
    assert response.status_code == 202
    assert response.json()['status'] == 'pending'
    assert response.json()['job']['id'] == 'shared.zh-CN.saved-project'


def test_sample_poll_exposes_failed_extraction_instead_of_pending_composition(monkeypatch):
    from apps.api import story_routes
    storage=preview_storage()
    storage.lifetime_rpc.return_value={
        'status':'pending','preview':None,'locale':'zh-CN','updating':True,'error':None,
        'progress':{'composition':{'state':'pending'},
                    'extraction':{'state':'retry_required','error':'MEMOIR_UNAVAILABLE','pending_inputs':5}},
    }
    monkeypatch.setattr(story_routes,'mapped_identity',lambda *_:{'project_id':'saved-project'})
    monkeypatch.setattr(story_routes,'read_mapped',lambda storage,project,reader,legacy:reader(None))
    with preview_client(storage) as client:
        response=client.get('/v1/story/preview/shared.zh-CN.saved-project')
    result=response.json()
    assert result['status']=='error' and result['updating'] is False
    assert result['job']['error']=='MEMOIR_UNAVAILABLE'
    assert result['job']['phase']=='extracting'


def test_initial_sample_check_does_not_reset_a_failed_canonical_lane(monkeypatch):
    from apps.api import story_routes
    storage=preview_storage()
    storage.lifetime_rpc.return_value={
        'status':'pending','preview':None,'locale':'zh-CN','updating':False,'error':'MEMOIR_UNAVAILABLE',
        'progress':{'composition':{'state':'pending'},
                    'extraction':{'state':'retry_required','error':'MEMOIR_UNAVAILABLE','pending_inputs':5}},
    }
    monkeypatch.setattr(story_routes,'mapped_identity',lambda *_:{'project_id':'saved-project'})
    monkeypatch.setattr(story_routes,'read_mapped',lambda storage,project,reader,legacy:reader(None))
    with preview_client(storage) as client:
        response=client.post('/v1/story/preview',json={'project_id':'saved-project','language':'zh-CN'})
    assert response.json()['status']=='error'
    storage.retry_memoir_lane.assert_not_called()
    assert not any(call.args[0]=='set_lifetime_draft_edition' for call in storage.lifetime_rpc.call_args_list)


@pytest.mark.parametrize('updating', [True, False])
def test_twentieth_round_distinguishes_pending_and_failed_replacements(monkeypatch, updating):
    from apps.api import story_routes

    storage = preview_storage()
    storage.recall_rounds_completed.return_value = 20
    storage.lifetime_rpc.return_value = {
        'status': 'insufficient_context', 'preview': None, 'locale': 'zh-CN',
        'coverage_round': 5, 'updating': updating, 'error': None,
        'progress': {'composition': {'state': 'pending' if updating else 'retry_required',
                                     'error': None if updating else 'MEMOIR_UNAVAILABLE'}},
    }
    monkeypatch.setattr(story_routes, 'mapped_identity', lambda *_: {'project_id': 'saved-project'})
    monkeypatch.setattr(story_routes, 'read_mapped', lambda storage, project, reader, legacy: reader(None))
    with preview_client(storage) as client:
        response = client.post('/v1/story/preview', json={'project_id': 'saved-project', 'language': 'zh-CN'})
    assert response.status_code in {200, 202}
    assert response.json()['status'] == ('pending' if updating else 'error')
    assert response.json()['job']['id'] == 'shared.zh-CN.saved-project'
    if not updating:
        assert response.json()['job']['error'] == 'MEMOIR_UNAVAILABLE'


@pytest.mark.parametrize('updating', [True, False])
def test_sample_admission_polls_a_composer_that_is_already_running(monkeypatch, updating):
    from apps.api import story_routes

    storage = preview_storage()
    storage.lifetime_rpc.return_value = {
        'status': 'pending', 'preview': None, 'locale': 'zh-CN', 'updating': updating, 'error': None,
    }
    monkeypatch.setattr(story_routes, 'mapped_identity', lambda *_: {'project_id': 'saved-project'})
    monkeypatch.setattr(story_routes, 'read_mapped', lambda storage, project, reader, legacy: reader(None))
    def busy(*_):
        raise HTTPException(409, 'Composer already running',
                            headers={'X-Error-Code': 'LIFETIME_DRAFT_RETRY_CONFLICT'})
    monkeypatch.setattr(story_routes, 'retry_draft', busy)
    with preview_client(storage) as client:
        response = client.post('/v1/story/preview', json={'project_id': 'saved-project', 'language': 'zh-CN', 'retry': True})
    if updating:
        assert response.status_code in {200, 202}
        assert response.json()['status'] == 'pending'
        assert response.json()['job']['id'] == 'shared.zh-CN.saved-project'
    else:
        assert response.status_code == 409


def test_ineligible_sample_is_not_returned_or_polled_without_replacement_work():
    storage = preview_storage(status='stale', revision=2, covered_round=15)
    with preview_client(storage) as client:
        response = client.post('/v1/story/preview', json={'project_id': 'saved-project'})
    assert response.status_code == 200
    assert response.json()['status'] == 'stale'
    assert response.json()['preview'] is None
