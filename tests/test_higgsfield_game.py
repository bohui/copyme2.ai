"""Only the confirmed subset reaches Astra and the installed game skill."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json

import httpx
import pytest

from apps.api.higgsfield_game import REQUIRED_FILES, run_higgsfield_game, skill_snapshot
from apps.api.story_game_runtime import GamePublication
from test_story_game_runtime import build_packet, GAME, TOKEN, webpage


@pytest.fixture
def installed(tmp_path):
    for name in REQUIRED_FILES:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('name: higgsfield-websites\n' if name == 'SKILL.md' else '# Controlled game guidance\n')
    return tmp_path


def response(output, index):
    return httpx.Response(200, json=dict(status='completed', id=f'resp-build-{index}', model='served-astra', output=output))


@pytest.mark.parametrize('failure', [None, 'deployment', 'path', 'unvalidated', 'unread'])
def test_separate_skill_tool_loop_is_bounded_and_uses_only_astra(installed, monkeypatch, failure):
    packet = build_packet()
    packet['brief'] = dict(design_brief='A reflective garden.', scene_indices=[0])
    html = webpage()['html']
    artifact = hashlib.sha256(html.encode()).hexdigest()
    requests = []

    @asynccontextmanager
    async def admitted(self, fence):
        assert str(fence['game_id']) == GAME and str(fence['token']) == TOKEN
        yield
    monkeypatch.setattr(GamePublication, 'guard', admitted)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', 'controlled-publication')
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL', 'https://gateway.test/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'unique-higgsfield-test-key')
    async def load(_): return packet

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body['model'] == 'gpt-6-astra' and body['store'] is False
        assert body['metadata']['generation_name'] == 'higgsfield-websites-game'
        assert 'mother repaired' not in body['input'][0]['content']
        assert 'chapter_id' not in body['input'][0]['content'] and 'event_ids' not in body['input'][0]['content']
        assert 'deploy' not in [t['name'] for t in body['tools']]
        if len(requests) == 1:
            tool = 'deploy' if failure == 'deployment' else 'read_skill_file'
            paths = ['../../secret'] if failure == 'path' else sorted(REQUIRED_FILES)
            if failure == 'unread':
                return response([dict(type='message', content=[dict(type='output_text', text=json.dumps({'artifact_sha256': artifact}))])], 1)
            return response([dict(type='function_call', name=tool, arguments=json.dumps({'paths': paths}), call_id='read')], 1)
        if len(requests) == 2 and failure != 'unvalidated':
            return response([dict(type='function_call', name='validate_game_webpage', arguments=json.dumps({'html': html}), call_id='validate')], 2)
        return response([dict(type='message', content=[dict(type='output_text', text=json.dumps({'artifact_sha256': artifact}))])], 3)

    call = run_higgsfield_game(dict(game_id=GAME, token=TOKEN, authority=packet['authority']),
        packet_loader=load, skill_path=installed, transport=httpx.MockTransport(transport))
    if failure:
        with pytest.raises(ValueError): asyncio.run(call)
    else:
        result = asyncio.run(call)
        assert result['webpage'] == {'html': html} and len(requests) == 3
        assert result['receipt']['requested_model'] == 'gpt-6-astra'
        assert result['receipt']['skill'] == 'higgsfield-websites'
        assert result['receipt']['skill_sha256'] == skill_snapshot(installed)[1]


def test_upstream_updates_change_the_next_build_digest_without_editing_memoir(installed):
    first = skill_snapshot(installed)
    (installed / 'references/game-design-system.md').write_text('# New upstream guidance\n')
    second = skill_snapshot(installed)
    assert first[1] != second[1] and first[0] != second[0]


def test_no_human_selection_never_dispatches_a_build(installed):
    packet = build_packet()
    packet['selection'] = None
    async def load(_): return packet
    with pytest.raises(ValueError, match='human_selection'):
        asyncio.run(run_higgsfield_game(dict(game_id=GAME, token=TOKEN, authority=packet['authority']),
            packet_loader=load, skill_path=installed))


def test_upgrade_switches_future_builds_and_keeps_active_snapshot_readable(tmp_path):
    from scripts.update_higgsfield_skill import activate
    destination = tmp_path / 'external'
    destination.mkdir()
    sources = []
    for revision in ('old', 'new'):
        source = tmp_path / revision
        source.mkdir()
        (source / 'SKILL.md').write_text(revision)
        sources.append(source)
    target = activate(sources[0], destination, 'a'*40)
    active = target.resolve()
    activate(sources[1], destination, 'b'*40)
    assert (active / 'SKILL.md').read_text() == 'old'
    assert (target / 'SKILL.md').read_text() == 'new'
