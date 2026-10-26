"""Two model steps, grounding, webpage validation and durable host handoff."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from apps.api.story_game_runtime import (GamePublication, compose_game_brief, game_ui,
    generate_story_game, propose_game, validate_scenes)
from apps.api.story_game_selection import validate_pool
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


def pool():
    return {'scenes': [{**scene, 'recommended': i == 0, 'reason': 'A supported playable memory.'}
        for i, scene in enumerate(proposal()['scenes'])]}


def build_packet():
    current = packet()
    current.update(scene_pool={'scenes': [{**s, 'id': f'scene-{i+1}', 'life_stage': 'childhood'}
        for i,s in enumerate(pool()['scenes'])]}, selection={'scene_ids': ['scene-1']},
        selection_digest='a'*64, brief=None)
    return current


class Broker:
    def __init__(self, status='running', phase='scenes'):
        self.calls, self.status, self.phase = [], status, phase

    async def rpc(self, name, **values):
        self.calls.append((name, values))
        if name == 'claim_story_game': return {'status': self.status, 'token': TOKEN, 'phase': self.phase}
        if name == 'read_story_game_input': return packet() if self.phase == 'scenes' else build_packet()
        if name == 'save_story_game_pool': return {'game_id': GAME, 'status': 'selection_required'}
        if name == 'save_story_game_brief': return None
        if name == 'stage_story_game': return {'game_id': GAME, 'status': 'published'}
        if name == 'fail_story_game': return None
        raise AssertionError(name)


def test_pool_stops_for_human_selection_without_composing_or_building():
    broker = Broker()
    async def scenes(value): return pool(), receipt()
    async def forbidden(*_): raise AssertionError('human_confirmation_required')
    result = asyncio.run(generate_story_game(broker, GAME, provider=scenes, composer=forbidden, builder=forbidden))
    assert result['status'] == 'selection_required'
    assert [name for name, _ in broker.calls] == ['claim_story_game', 'read_story_game_input', 'save_story_game_pool']
    assert broker.calls[-1][1]['p_pool'] == pool()


def test_confirmed_subset_is_composed_and_built_without_unselected_memories():
    broker, steps = Broker(phase='build'), []
    async def forbidden(*_): raise AssertionError('pool_must_not_regenerate')
    async def compose(packet, selected):
        assert selected['scenes'] == proposal()['scenes'][:1]
        steps.append('brief')
        return {'design_brief': 'Quiet garden journey.', 'scene_indices': [0]}, receipt('brief')
    async def build(selected):
        assert selected['scenes'] == proposal()['scenes'][:1] and steps == ['brief']
        steps.append('higgsfield')
        return webpage(), receipt('higgsfield')
    result = asyncio.run(generate_story_game(broker, GAME, provider=forbidden, composer=compose, builder=build))
    assert result['status'] == 'published' and steps == ['brief', 'higgsfield']
    assert [n for n,_ in broker.calls] == ['claim_story_game', 'read_story_game_input', 'save_story_game_brief', 'stage_story_game']
    assert broker.calls[-1][1]['p_model_receipt']['selection_digest'] == 'a'*64


def test_build_retry_reuses_the_saved_brief():
    class SavedBrief(Broker):
        async def rpc(self, name, **values):
            value = await super().rpc(name, **values)
            if name == 'read_story_game_input':
                value['brief'] = {'design_brief': 'Already composed.', 'scene_indices': [0]}
            return value
    broker = SavedBrief(phase='build')
    async def forbidden(*_): raise AssertionError('saved_brief_must_not_regenerate')
    async def build(_): return webpage(), receipt('higgsfield')
    assert asyncio.run(generate_story_game(broker, GAME, composer=forbidden, builder=build))['status'] == 'published'
    assert 'save_story_game_brief' not in [n for n,_ in broker.calls]


@pytest.mark.parametrize('status', ['busy', 'published', 'selection_required'])
def test_replay_and_busy_jobs_do_not_dispatch_again(status):
    broker = Broker(status)
    async def forbidden(*_): raise AssertionError('provider_must_not_run')
    assert asyncio.run(generate_story_game(broker, GAME, provider=forbidden, builder=forbidden))['status'] == status
    assert len(broker.calls) == 1


@pytest.mark.parametrize('change', ['quote', 'event', 'coverage', 'block', 'chapter', 'duplicate', 'recommendation'])
def test_invalid_pool_never_reaches_confirmation_or_build(change):
    value = pool()
    if change == 'quote': value['scenes'][0]['quote'] += ' An invented medal.'
    elif change == 'event': value['scenes'][0]['event_ids'] = ['invented-event']
    elif change == 'coverage': value['scenes'].pop()
    elif change == 'block': value['scenes'][0]['block_index'] = 7
    elif change == 'chapter': value['scenes'][0]['chapter_id'] = 'invented-chapter'
    elif change == 'duplicate': value['scenes'].append(value['scenes'][0])
    else: value['scenes'][0]['recommended'] = False
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


def test_pool_uses_supplied_timeline_order_before_owner_confirmation():
    value=pool()
    value['scenes'].reverse()
    result=validate_pool(packet(),value)
    assert [s['event_ids'][0] for s in result['scenes']]==['event-father','event-mother']


def test_paraphrased_display_title_becomes_a_source_excerpt():
    value = proposal()
    value['scenes'][0]['title'] = 'Learning to garden'
    prepared = validate_scenes(packet(), value)
    assert prepared['scenes'][0]['title'] == 'My father tended the garden.'
    assert prepared['scenes'][0]['quote'] == value['scenes'][0]['quote']


def test_full_timeline_can_exceed_sixteen_scenes():
    chapters = [dict(chapter_id=f'chapter-{i}', event_ids=[f'event-{i}'],
        blocks=[{'text': f'At eight I planted bed {i}.'}]) for i in range(50)]
    current = dict(chapters=chapters, timeline=[{'id': f'event-{i}'} for i in range(50)])
    value = {'scenes': [dict(chapter_id=c['chapter_id'], block_index=0, title='planted',
        person=None, quote=c['blocks'][0]['text'], event_ids=c['event_ids']) for c in chapters]}
    assert validate_scenes(current, value) == value


def test_full_age_eight_pool_covers_every_event_without_selecting_it_for_the_owner():
    current = json.loads((Path(__file__).parents[1] / 'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())['input']
    options = []
    for i, chapter in enumerate(current['chapters']):
        quote = chapter['blocks'][0]['text'][:390].rsplit('. ', 1)[0] + '.'
        options.append(dict(chapter_id=chapter['chapter_id'], block_index=0, person=None, title=quote[:40],
            quote=quote, event_ids=chapter['event_ids'], recommended=i < 3, reason='A distinct, supported interaction.'))
    prepared = validate_pool(current, {'scenes': options})
    assert len(prepared['scenes']) == 10
    assert sum(s['recommended'] for s in prepared['scenes']) == 3
    assert {id for s in prepared['scenes'] for id in s['event_ids']} == {e['id'] for e in current['timeline']}


def test_every_life_stage_needs_a_recommendation_and_cannot_be_invented():
    current = packet()
    current['timeline'][0]['life_stage'] = 'childhood'
    current['timeline'][1]['life_stage'] = 'midlife'
    with pytest.raises(ValueError, match='stage_recommendation'):
        validate_pool(current, pool())
    options = pool()
    options['scenes'][1]['recommended'] = True
    assert validate_pool(current, options) == options


def test_failed_or_invalid_webpage_does_not_publish_half_a_game():
    broker = Broker(phase='build')
    async def compose(*_): return {'design_brief': 'Garden.', 'scene_indices': [0]}, receipt('brief')
    async def build(_): return {'html': '<script>fetch("https://outside.invalid")</script>'}, receipt('higgsfield')
    with pytest.raises(ValueError):
        asyncio.run(generate_story_game(broker, GAME, composer=compose, builder=build))
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


@pytest.mark.parametrize('phase', ['scenes', 'brief'])
@pytest.mark.parametrize('bad', [None, 'duplicate_json', 'missing_receipt', 'incomplete', 'credential'])
def test_both_planning_calls_use_sol_max_and_distinct_managed_prompts(monkeypatch, phase, bad):
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
    result = pool() if phase == 'scenes' else {'design_brief': 'Quiet garden journey.', 'scene_indices': [0, 1]}
    output = json.dumps(result)
    if bad == 'duplicate_json': output *= 2
    if bad == 'credential': output = 'private-game-test-key'
    response = {'id': None if bad == 'missing_receipt' else 'resp-test', 'model': 'gpt-6.1-sol',
        'status': 'incomplete' if bad == 'incomplete' else 'completed', 'reasoning': {'effort': 'max'},
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': output}]}]}
    client_type = httpx.AsyncClient
    def transport(request):
        sent = json.loads(request.content)
        assert sent['model'] == 'gpt-6.1-sol'
        assert sent['reasoning'] == {'effort': 'max'} and sent['store'] is False and sent['stream'] is True
        assert sent['text']['format']['strict'] is True
        assert sent['metadata']['generation_name'] == 'memoir-story-game-' + phase
        payload = json.loads(sent['input'])
        assert 'authority' not in payload and 'game_id' not in payload
        if phase == 'scenes':
            assert payload['chapters'] == packet()['chapters'] and payload['timeline'] == packet()['timeline']
        else:
            assert 'chapter_id' not in payload['scenes'][0] and 'event_ids' not in payload['scenes'][0]
            assert 'NovelToGame' in sent['instructions']
        return httpx.Response(200,text='data: '+json.dumps({'type':'response.completed','response':response})+'\n\n',
            headers={'Content-Type':'text/event-stream'})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(**{**kwargs,'transport':httpx.MockTransport(transport)}))
    call = propose_game(packet(), token=TOKEN) if phase == 'scenes' else compose_game_brief(packet(), proposal(), token=TOKEN)
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


@pytest.mark.parametrize('status', ['pending', 'published'])
@pytest.mark.parametrize('phase',['scenes','build'])
def test_job_response_is_sent_before_long_scene_planning_or_building(monkeypatch, status, phase):
    from fastapi import FastAPI
    from types import SimpleNamespace
    from apps.api import story_game_routes, story_game_runtime, memory_event_worker
    app = FastAPI()
    app.include_router(story_game_routes.router)
    async def storage(*_): return SimpleNamespace(client=SimpleNamespace(close=lambda: None))
    async def rpc(*args, **values): return dict(game_id=GAME, status=status, phase=phase)
    async def close(): pass
    monkeypatch.setattr(story_game_routes, 'owned_storage', storage)
    monkeypatch.setattr(story_game_routes, 'rpc', rpc)
    monkeypatch.setattr(memory_event_worker, 'MemoirLaneBroker', lambda: SimpleNamespace(client=SimpleNamespace(aclose=close)))

    async def scenario():
        delivered, release, started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        sent = []
        async def build(*_):
            assert delivered.is_set(), 'A slow build must not hold the confirmation response open'
            started.set()
            await release.wait()
        monkeypatch.setattr(story_game_runtime, 'generate_story_game', build)
        body = json.dumps(dict(expected_pool_digest='a'*64, scene_ids=['scene-1']) if phase=='build' else dict(request_id=GAME)).encode()
        consumed = False
        async def receive():
            nonlocal consumed
            if consumed: return {'type':'http.disconnect'}
            consumed = True
            return {'type':'http.request','body':body,'more_body':False}
        async def send(value):
            sent.append(value)
            if value['type']=='http.response.body' and not value.get('more_body'):
                delivered.set()
        scope = dict(type='http', asgi={'version':'3.0'}, http_version='1.1', method='POST',
            scheme='http', root_path='', path='/projects/project/story-game'+('/'+GAME+'/selection' if phase=='build' else ''),
            query_string=b'', headers=[(b'content-type',b'application/json')])
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(delivered.wait(), 2)
            assert sent[0]['status'] == 202
            if status == 'pending':
                await asyncio.wait_for(started.wait(), 2)
                assert not task.done()
            else:
                await task
                assert not started.is_set()
        finally:
            release.set()
            await task
    asyncio.run(scenario())
