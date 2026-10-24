"""Two model steps, grounding, webpage validation and durable host handoff."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from apps.api.story_game_runtime import (GamePublication, build_game, game_ui,
    generate_story_game, propose_game, validate_scenes)
from apps.api.story_game_webpage import validate_webpage

GAME, TOKEN, CHAPTER = (str(uuid4()) for _ in range(3))


def packet():
    return dict(game_id=GAME, authority={'locale': 'en-AU', 'verified': 'database'},
        chapters=[dict(chapter_id=CHAPTER, event_ids=['event-father', 'event-mother'], blocks=[
            dict(text='My father tended the garden.'), dict(text='My mother repaired a bicycle.')])],
        timeline=[{'id': 'event-father'}, {'id': 'event-mother'}])


def proposal():
    return {'scenes': [dict(chapter_id=CHAPTER, block_index=i, person=person, title=person,
        quote=text, event_ids=['event-' + person]) for i, (person, text) in enumerate([
            ('father', 'My father tended the garden.'), ('mother', 'My mother repaired a bicycle.')])]}


def webpage(locale='en-AU'):
    text = (Path(__file__).parents[1] / 'skills/memoir-story-game/tests/fixtures/webpage.html').read_text()
    if locale == 'zh-CN':
        for key in ('title', 'interact', 'textVersion'):
            text = text.replace(game_ui('en-AU')[key], game_ui(locale)[key])
    return {'html': text}


def receipt(phase='scenes'):
    return dict(status='completed', response_id='resp-' + phase, model='controlled-' + phase)


class Broker:
    def __init__(self, status='running'):
        self.calls = []
        self.status = status

    async def rpc(self, name, **values):
        self.calls.append((name, values))
        if name == 'claim_story_game': return {'status': self.status, 'token': TOKEN}
        if name == 'read_story_game_input': return packet()
        if name == 'stage_story_game': return {'game_id': GAME, 'status': 'published'}
        if name == 'fail_story_game': return None
        raise AssertionError(name)


def test_chapters_and_timeline_to_scenes_then_webpage_then_host_save():
    broker, steps = Broker(), []
    async def scenes(value):
        assert value == packet()
        steps.append('scenes')
        return proposal(), receipt()
    async def build(value):
        assert value == proposal() and steps == ['scenes']
        steps.append('webpage')
        return webpage(), receipt('webpage')
    result = asyncio.run(generate_story_game(broker, GAME, provider=scenes, builder=build))
    assert result['status'] == 'published' and steps == ['scenes', 'webpage']
    assert [name for name, _ in broker.calls] == ['claim_story_game', 'read_story_game_input', 'stage_story_game']
    staged = broker.calls[-1][1]
    assert staged['p_token'] == TOKEN and staged['p_proposal'] == {**proposal(), **webpage()}
    assert staged['p_model_receipt']['steps'] == {'scenes': receipt(), 'webpage': receipt('webpage')}


@pytest.mark.parametrize('status', ['busy', 'published'])
def test_replay_and_busy_jobs_do_not_dispatch_again(status):
    broker = Broker(status)
    async def forbidden(_): raise AssertionError('provider_must_not_run')
    assert asyncio.run(generate_story_game(broker, GAME, provider=forbidden, builder=forbidden))['status'] == status
    assert len(broker.calls) == 1


@pytest.mark.parametrize('change', ['quote', 'event', 'coverage', 'block', 'chapter'])
def test_invalid_scene_plan_never_reaches_astra_or_staging(change):
    value = proposal()
    if change == 'quote': value['scenes'][0]['quote'] += ' An invented medal.'
    elif change == 'event': value['scenes'][0]['event_ids'] = ['invented-event']
    elif change == 'coverage': value['scenes'].pop()
    elif change == 'block': value['scenes'][0]['block_index'] = 7
    else: value['scenes'][0]['chapter_id'] = 'invented-chapter'
    broker = Broker()
    async def scenes(_): return value, receipt()
    async def forbidden(_): raise AssertionError('builder_must_not_run')
    with pytest.raises(ValueError):
        asyncio.run(generate_story_game(broker, GAME, provider=scenes, builder=forbidden))
    assert [name for name, _ in broker.calls] == ['claim_story_game', 'read_story_game_input', 'fail_story_game']


def test_single_scene_without_a_second_person_is_supported():
    current, value = packet(), proposal()
    current['timeline'].pop()
    value['scenes'] = value['scenes'][:1]
    value['scenes'][0]['person'] = None
    assert validate_scenes(current, value) == value


def test_full_timeline_can_exceed_sixteen_scenes():
    chapters = [dict(chapter_id=f'chapter-{i}', event_ids=[f'event-{i}'],
        blocks=[{'text': f'At eight I planted bed {i}.'}]) for i in range(50)]
    current = dict(chapters=chapters, timeline=[{'id': f'event-{i}'} for i in range(50)])
    value = {'scenes': [dict(chapter_id=c['chapter_id'], block_index=0, title='planted',
        person=None, quote=c['blocks'][0]['text'], event_ids=c['event_ids']) for c in chapters]}
    assert validate_scenes(current, value) == value


def test_failed_or_invalid_webpage_does_not_publish_half_a_game():
    broker = Broker()
    async def scenes(_): return proposal(), receipt()
    async def build(_): return {'html': '<script>fetch("https://outside.invalid")</script>'}, receipt('webpage')
    with pytest.raises(ValueError):
        asyncio.run(generate_story_game(broker, GAME, provider=scenes, builder=build))
    assert broker.calls[-1][0] == 'fail_story_game'
    assert not any(name == 'stage_story_game' for name, _ in broker.calls)


@pytest.mark.parametrize('change', ['script', 'event-handler', 'iframe', 'css-url', 'css-import',
    'css-escape', 'link', 'meta', 'text', 'controls', 'summary', 'duplicate-root'])
def test_webpage_validation_rejects_active_content_and_broken_controls(change):
    html = webpage()['html']
    if change == 'script': html = html.replace('</head>', '<script>alert(1)</script></head>')
    elif change == 'event-handler': html = html.replace('<body>', '<body onload="alert(1)">')
    elif change == 'iframe': html = html.replace('</main>', '<iframe src="https://outside.invalid"></iframe></main>')
    elif change == 'css-url': html = html.replace('<style>', '<style>body{background:url(https://outside.invalid)}')
    elif change == 'css-import': html = html.replace('<style>', '<style>@import "https://outside.invalid";')
    elif change == 'css-escape': html = html.replace('<style>', '<style>body{background:u\\72l(https://outside.invalid)}')
    elif change == 'link': html = html.replace('</main>', '<a href="https://outside.invalid">Go</a></main>')
    elif change == 'meta': html = html.replace('</head>', '<meta http-equiv="refresh" content="0;url=https://outside.invalid"></head>')
    elif change == 'text': html = html.replace('</main>', '<p>Your father won a medal.</p></main>')
    elif change == 'controls': html = html.replace('data-game-move="1"', 'data-game-move="2"')
    elif change == 'summary': html = html.replace('<summary>', '<p>').replace('</summary>', '</p>')
    else: html = html.replace('</main>', '<div id="memoir-game"></div></main>')
    with pytest.raises(ValueError): validate_webpage(html, game_ui('en-AU'))


def test_complete_static_page_is_accepted():
    assert validate_webpage(webpage()['html'], game_ui('en-AU')) == webpage()['html']


@pytest.mark.parametrize('phase', ['scenes', 'webpage'])
@pytest.mark.parametrize('bad', [None, 'duplicate_json', 'missing_receipt', 'incomplete', 'credential'])
def test_model_calls_use_distinct_prompts_and_astra_for_webpage(monkeypatch, phase, bad):
    @asynccontextmanager
    async def admitted(self, fence):
        assert fence['game_id'] == GAME and fence['token'] == TOKEN
        yield
    monkeypatch.setattr(GamePublication, 'guard', admitted)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', 'controlled-admission')
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL', 'https://gateway.test/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'private-game-test-key')
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'configured-scene-model')
    monkeypatch.delenv('MEMORY_SPARK_STORY_GAME_BUILD_MODEL', raising=False)
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT', ' high ')
    result = proposal() if phase == 'scenes' else webpage()
    output = json.dumps(result)
    if bad == 'duplicate_json': output *= 2
    if bad == 'credential': output = 'private-game-test-key'
    response = {'id': None if bad == 'missing_receipt' else 'resp-test', 'model': 'served-model',
        'status': 'incomplete' if bad == 'incomplete' else 'completed', 'reasoning': {'effort': 'high'},
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}]}
    client_type = httpx.AsyncClient
    def transport(request):
        sent = json.loads(request.content)
        assert sent['model'] == ('gpt-6-astra' if phase == 'webpage' else 'configured-scene-model')
        assert sent['reasoning'] == {'effort': 'high'} and sent['store'] is False
        assert sent['text']['format']['strict'] is True
        assert sent['metadata']['generation_name'] == 'memoir-story-game-' + phase
        payload = json.loads(sent['input'])
        assert 'authority' not in payload and 'game_id' not in payload
        if phase == 'scenes':
            assert payload['chapters'] == packet()['chapters'] and payload['timeline'] == packet()['timeline']
        else:
            assert 'chapter_id' not in payload['scenes'][0] and 'event_ids' not in payload['scenes'][0]
            assert 'Astra' in sent['instructions']
        return httpx.Response(200, json=response)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(transport=httpx.MockTransport(transport), **kwargs))
    call = propose_game(packet(), token=TOKEN) if phase == 'scenes' else build_game(packet(), proposal(), token=TOKEN)
    if bad:
        with pytest.raises(ValueError): asyncio.run(call)
    else:
        actual, observed = asyncio.run(call)
        assert actual == result and observed['status'] == 'completed'


def test_game_routes_require_auth_and_reject_browser_supplied_authority(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.story_game_routes import router
    monkeypatch.setenv('SUPABASE_URL', 'https://auth.test')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-test')
    app = FastAPI()
    app.include_router(router, prefix='/v1/agent')
    root = '/v1/agent/projects/project'
    with TestClient(app) as client:
        assert client.post(root + '/story-game', json={'request_id': GAME}).status_code == 401
        assert client.get(root + '/story-game/' + GAME).status_code == 401
        assert client.post(root + '/story-game', json={
            'request_id': GAME, 'owner_id': GAME, 'chapters': [], 'timeline': []}).status_code == 422
