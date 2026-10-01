import asyncio
import copy
import json

import pytest
from fastapi.testclient import TestClient

from apps.api import memoir_preview
from apps.api.agent_lock import AgentTurnLease
from apps.api.main import create_app
from apps.api.store import MemoryStore
from test_recall import RecallStorage
from test_story_flow import _auth_headers


@pytest.mark.parametrize('reply', ['{"ready":true}', '```json\n{"ready":true}\n```', '```\n{"ready":true}\n```'])
def test_composer_json_may_have_a_markdown_envelope(reply):
    assert memoir_preview.json_reply(reply) == {'ready': True}


def test_composer_commentary_is_not_accepted_as_a_candidate():
    with pytest.raises(ValueError):
        memoir_preview.json_reply('Here is the result: {"ready":true}')


def fixture_storage(name='focused_trial', anonymous=False):
    original = json.loads((memoir_preview.SKILL / f'examples/{name}/request.json').read_text())
    storage = RecallStorage(completed=20, anonymous=anonymous)
    storage._memories = [{
        'id': source['id'], 'kind': 'agent',
        'content': f"Storyteller: {source['text']}\nMemory Spark: Invented assistant biography",
    } for source in original['sources']]
    return storage, original


def model_fixture(monkeypatch, name='focused_trial', *, review_ready=True):
    calls = []
    original = json.loads((memoir_preview.SKILL / f'examples/{name}/request.json').read_text())
    candidate = json.loads((memoir_preview.SKILL / f'examples/{name}/draft.json').read_text())

    async def call(runtime, storage, project_id, language, phase, packet):
        calls.append(phase)
        request = packet if phase == 'index' else packet['request']
        versions = {source['id']: source['version'] for source in request['sources']}

        def rewrite(value):
            if isinstance(value, dict):
                if 'source_id' in value:
                    value['version'] = versions[value['source_id']]
                for child in value.values():
                    rewrite(child)
            elif isinstance(value, list):
                for child in value:
                    rewrite(child)

        if phase == 'index':
            result = copy.deepcopy({key: original[key] for key in ['periods', 'events']})
            rewrite(result)
            assert all('Invented assistant biography' not in source['text'] for source in request['sources'])
            assert request['trigger']['free_round_limit'] == 20
            return result
        if phase == 'review':
            return {'ready_for_user_review': review_ready, 'publication_approved': False, 'findings': []}
        draft = copy.deepcopy(candidate)
        draft['questions_for_mira'] = []
        for chapter in draft['chapters']:
            chapter['blocks'] = [block for block in chapter['blocks'] if block['type'] != 'image']
        rewrite(draft)
        plan = packet['plan']
        draft.update(project_id=project_id, input_snapshot_id=request['snapshot']['id'],
                     input_fingerprint=plan['input_fingerprint'], counter=plan['counter'])
        return draft

    monkeypatch.setattr(memoir_preview, 'composer_call', call)
    return calls


@pytest.mark.parametrize('name,kind', [('focused_trial', 'sample_chapter'), ('broad_trial', 'sample_storyline')])
@pytest.mark.parametrize('anonymous', [False, True])
def test_free_preview_is_composed_reviewed_saved_and_cached(monkeypatch, name, kind, anonymous):
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '20')
    storage, _ = fixture_storage(name, anonymous)
    calls = model_fixture(monkeypatch, name)
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage))
    response = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'ready'
    assert result['preview']['kind'] == kind
    assert result['preview']['text']
    assert calls == ['index', 'draft', 'review']
    assert storage.completed == 20
    bundle = json.loads(storage._memories[-1]['content'])
    assert bundle['validation']['ok']
    assert bundle['markdown']
    repeat = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
    assert repeat.json()['cached'] is True
    assert len(calls) == 3
    assert not storage.held


def test_preview_is_not_started_before_backend_limit(monkeypatch):
    storage, _ = fixture_storage()
    storage.completed = 19
    calls = model_fixture(monkeypatch)
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage))
    response = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
    assert response.status_code == 409
    assert not calls


def test_failed_evidence_review_never_persists_preview(monkeypatch):
    storage, _ = fixture_storage()
    calls = model_fixture(monkeypatch, review_ready=False)

    async def run():
        async with AgentTurnLease(storage) as lease:
            await memoir_preview.compose_preview(storage, lease, 'project-preview')

    with pytest.raises(RuntimeError, match='composition review'):
        asyncio.run(run())
    assert calls == ['index', 'draft', 'review', 'draft', 'review', 'draft', 'review']
    assert not any(any(path.startswith('memoir-preview:') for path in row.get('source_paths', []))
                   for row in storage._memories)
    assert storage.completed == 20


def test_old_source_edit_invalidates_cached_preview(monkeypatch):
    storage, _ = fixture_storage()
    calls = model_fixture(monkeypatch)
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage))
    payload = {'project_id': 'project-preview'}
    first = client.post('/v1/story/preview', headers=_auth_headers(), json=payload).json()
    storage._memories[0]['content'] += ' Changed source.'
    # Edit the narrator portion, not the assistant portion.
    storage._memories[0]['content'] = storage._memories[0]['content'].replace('blue door', 'blue wooden door')
    second = client.post('/v1/story/preview', headers=_auth_headers(), json=payload).json()
    assert second['cached'] is False
    assert first['preview']['id'] != second['preview']['id']
    assert len(calls) == 6
