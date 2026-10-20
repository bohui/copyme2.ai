"""Real game dispatch boundaries with controlled provider transports."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from apps.api.story_game_runtime import generate_story_game, propose_game

GAME = str(uuid4())
TOKEN = str(uuid4())
CHAPTER = str(uuid4())


def proposal():
    return {'scenes': [dict(chapter_id=CHAPTER, block_index=0, person=person, title=person,
        quote='My ' + person + ' tended the garden.', art='generic-garden') for person in ('father', 'mother')]}


class Broker:
    def __init__(self, status='running'):
        self.calls = []
        self.status = status

    async def rpc(self, name, **values):
        self.calls.append((name, values))
        if name == 'claim_story_game': return {'status': self.status, 'token': TOKEN}
        if name == 'read_story_game_input': return {'game_id': GAME, 'authority': {'verified': 'database'}, 'chapters': []}
        if name == 'stage_story_game': return {'game_id': GAME, 'status': 'review_required'}
        if name == 'fail_story_game': return None
        raise AssertionError(name)


def test_only_claimed_database_packet_reaches_provider_and_review_is_not_publication():
    broker = Broker()
    async def provider(packet):
        assert packet['game_id'] == GAME and packet['authority'] == {'verified': 'database'}
        return proposal(), {'status': 'completed', 'response_id': 'resp-test', 'model': 'test-model'}
    result = asyncio.run(generate_story_game(broker, GAME, provider=provider))
    assert result['status'] == 'review_required'
    assert [name for name, _ in broker.calls] == ['claim_story_game', 'read_story_game_input', 'stage_story_game']
    assert broker.calls[-1][1]['p_token'] == TOKEN


@pytest.mark.parametrize('status', ['busy', 'review_required', 'published'])
def test_replay_and_busy_jobs_do_not_dispatch_again(status):
    broker = Broker(status)
    async def forbidden(_): raise AssertionError('provider_must_not_run')
    assert asyncio.run(generate_story_game(broker, GAME, provider=forbidden))['status'] == status
    assert len(broker.calls) == 1


def test_invalid_model_proposal_releases_the_same_job_without_staging():
    broker = Broker()
    async def invalid(_): return {'scenes': []}, {}
    with pytest.raises(ValueError): asyncio.run(generate_story_game(broker, GAME, provider=invalid))
    assert [name for name, _ in broker.calls] == ['claim_story_game', 'read_story_game_input', 'fail_story_game']


def test_game_routes_require_auth_and_do_not_accept_browser_authority(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.story_game_routes import router
    monkeypatch.setenv('SUPABASE_URL', 'https://auth.test')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-test')
    app = FastAPI()
    app.include_router(router, prefix='/v1/agent')
    root = '/v1/agent/projects/project'
    with TestClient(app) as client:
        for method, suffix, body in (
            ('GET', '/story-game', None), ('POST', '/story-game', {'request_id': GAME}),
            ('POST', '/formal-memoir/advance', {'run_id': GAME}), ('GET', '/story-game/' + GAME, None)):
            result = client.request(method, root + suffix, json=body)
            assert result.status_code == 401
        result = client.post(root + '/story-game', json={
            'request_id': GAME, 'composition_complete': True, 'owner_id': GAME, 'chapters': []})
        assert result.status_code == 422
        result = client.post(root + '/story-game/' + GAME + '/publish', json={
            'expected_digest': 'a' * 64, 'permissions': [], 'game': {'unreviewed': 'replacement'}})
        assert result.status_code == 422


@pytest.mark.parametrize('bad', ['duplicate_json', 'missing_receipt', 'incomplete', 'credential'])
def test_provider_reply_must_be_one_completed_schema_document(monkeypatch, bad):
    from contextlib import asynccontextmanager
    from apps.api.story_game_runtime import GamePublication

    @asynccontextmanager
    async def controlled_admission(self, fence):
        yield

    monkeypatch.setattr(GamePublication, 'guard', controlled_admission)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', 'controlled-admission')
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL', 'https://gateway.test/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'private-game-test-key')
    monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL', 'configured-model')
    output = json.dumps(proposal())
    if bad == 'duplicate_json': output *= 2
    if bad == 'credential': output = 'private-game-test-key'
    response = {'id': None if bad == 'missing_receipt' else 'resp-test', 'model': 'served-model',
        'status': 'incomplete' if bad == 'incomplete' else 'completed',
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}]}
    client_type = httpx.AsyncClient
    def transport(request):
        sent = json.loads(request.content)
        assert sent['store'] is False and sent['text']['format']['strict'] is True
        assert sent['metadata'] == {'generation_name': 'memoir-story-game', 'trace_name': 'memoir-story-game'}
        assert 'p_expected_digest' not in sent
        return httpx.Response(200, json=response)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(transport=httpx.MockTransport(transport), **kwargs))
    with pytest.raises(ValueError):
        asyncio.run(propose_game(dict(game_id=GAME, authority={}, chapters=[]), token=TOKEN))
