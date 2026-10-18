"""Private games through real conversation, immutable editions and disposable SQL."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest

from test_conversation_attribution import Conversation, empty, episode
from test_formal_memoir_postgres import completed, consent, service
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import attachment_database, private_database, event_database
from test_shared_memory_events_postgres import sql, rpc, literal
from test_agent_commit_postgres import OWNER, OTHER, as_user


@pytest.fixture
def ready(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch,
        lambda packet: {**empty(packet), 'events': [episode(packet, packet['sources'][0]['text'])]},
        strategy='shape')
    with conversation.client:
        for text in ('My father repaired bicycles in our shed.', 'My mother grew roses in the garden.'):
            conversation.say(text)
            conversation.drain()
        project = conversation.project
        edition = completed(sql, project, {'revision': 0})
        consent(sql, project, edition, 1)
        yield project, edition, conversation


def begin_game(sql, project, request=None, **kwargs):
    return rpc(sql, 'begin_story_game', f"{literal(project)},'{request or uuid4()}'", **kwargs)


def prepare(sql, project):
    game = begin_game(sql, project)
    claim = service(sql, 'claim_story_game', f"'{game['game_id']}'")
    packet = service(sql, 'read_story_game_input', f"'{game['game_id']}','{claim['token']}'")
    return game, claim, packet, proposal_from_packet(packet)


def proposal_from_packet(packet):
    proposal = {'scenes': []}
    for chapter in packet['chapters']:
        for index, block in enumerate(chapter['blocks']):
            person = next((p for p in ('father', 'mother') if p in block['text']), None)
            if person and not any(p['person'] == person for p in proposal['scenes']):
                proposal['scenes'].append(dict(chapter_id=chapter['chapter_id'], block_index=index,
                    title=person, person=person, quote=block['text'], art='generic-garden'))
    assert len(proposal['scenes']) == 2
    return proposal


def stage(sql, game, claim, proposal, **kwargs):
    return service(sql, 'stage_story_game', f"'{game['game_id']}','{claim['token']}',{literal(proposal)},"
        + literal(dict(status='completed', response_id='resp-controlled-game', model='controlled-model')), **kwargs)


def read(sql, project, game, review=False, **kwargs):
    return rpc(sql, 'read_story_game', f"{literal(project)},'{game['game_id']}',{str(review).lower()}", **kwargs)


def permissions(review):
    return [dict(person_id=p['person_id'], adult=True, permitted=True, distinct_person=True)
            for p in review['people']]


def publish(sql, project, game, digest, grants, **kwargs):
    return rpc(sql, 'publish_story_game', f"{literal(project)},'{game['game_id']}',{literal(digest)},{literal(grants)}", **kwargs)


def test_real_candidate_needs_exact_author_review_before_private_play(sql, ready):
    project, _, _ = ready
    game, claim, packet, proposal = prepare(sql, project)
    assert service(sql, 'claim_story_game', f"'{game['game_id']}'")['status'] == 'busy'
    staged = stage(sql, game, claim, proposal)
    assert staged['status'] == 'review_required'
    assert 'game' not in read(sql, project, game)
    review = read(sql, project, game, True)
    assert 'preview' in review and len(review['people']) == 2
    assert all('source_id' not in p and 'chapter_id' not in p for p in review['people'])
    assert publish(sql, project, game, '0' * 64, permissions(review), check=False).returncode
    assert publish(sql, project, game, review['candidate_digest'], [], check=False).returncode
    saved = publish(sql, project, game, review['candidate_digest'], permissions(review))
    assert saved['status'] == 'published'
    assert publish(sql, project, game, review['candidate_digest'], permissions(review)) == saved
    played = read(sql, project, game)
    assert played['game'] == review['preview']
    from jsonschema import validate
    schema = json.loads((Path(__file__).resolve().parents[1] / 'skills/memoir-story-game/schemas/game.schema.json').read_text())
    validate(played['game'], schema)
    assert len(played['game']['scenes']) == len(played['game']['npcs']) == 2
    assert 'people' not in played and 'authority' not in played
    assert read(sql, project, game, owner=OTHER, check=False).returncode


def test_status_reports_gates_without_claiming_or_generating(sql, ready):
    project, _, _ = ready
    status = rpc(sql, 'read_story_game_status', literal(project))
    assert status['eligibility']['available'] is True
    assert status['formal']['edition']['status'] == 'completed'
    assert status['adaptation'] is None
    assert sql('select count(*) from public.user_story_game;').stdout.strip() == '0'


@pytest.mark.parametrize('mutation', ['quote', 'person', 'chapter', 'null', 'injection', 'duplicate'])
def test_model_cannot_create_unsupported_people_or_dialogue(sql, ready, mutation):
    project, _, _ = ready
    game, claim, _, proposal = prepare(sql, project)
    if mutation == 'quote': proposal['scenes'][0]['quote'] += ' He won a medal.'
    elif mutation == 'person': proposal['scenes'][0]['person'] = 'invented friend'
    elif mutation == 'chapter': proposal['scenes'][0]['chapter_id'] = str(uuid4())
    elif mutation == 'null': proposal['scenes'][0]['quote'] = None
    elif mutation == 'injection': proposal['scenes'][0]['quote'] = '<script>alert(1)</script>'
    else: proposal['scenes'][1] = deepcopy(proposal['scenes'][0])
    assert stage(sql, game, claim, proposal, check=False).returncode
    assert read(sql, project, game)['status'] == 'running'


@pytest.mark.parametrize('when', ['generation', 'review', 'published'])
def test_consent_revocation_fences_generation_review_and_play(sql, ready, when):
    project, edition, _ = ready
    game, claim, _, proposal = prepare(sql, project)
    if when != 'generation':
        stage(sql, game, claim, proposal)
        review = read(sql, project, game, True)
        if when == 'published': publish(sql, project, game, review['candidate_digest'], permissions(review))
    consent(sql, project, edition, 2, 'revoke')
    assert read(sql, project, game, True, check=False).returncode
    assert stage(sql, game, claim, proposal, check=False).returncode
    assert sql('select count(*) from public.user_story_game where candidate is not null;').stdout.strip() == '0'


def test_source_change_purges_candidate_and_cannot_reuse_old_worker(sql, ready):
    project, _, conversation = ready
    game, claim, _, proposal = prepare(sql, project)
    stage(sql, game, claim, proposal)
    source = sql('select id from public.user_narrator_source order by sequence limit 1;').stdout.strip()
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{source}',1,'edit','I corrected that memory.'")
    assert read(sql, project, game, check=False).returncode
    assert sql('select count(*) from public.user_story_game where candidate is not null;').stdout.strip() == '0'
    assert stage(sql, game, claim, proposal, check=False).returncode


def test_browser_cannot_claim_stage_or_read_other_owners(sql, ready):
    project, _, _ = ready
    game, claim, _, proposal = prepare(sql, project)
    for role in ('anon', 'authenticated'):
        denied = sql(f"set role {role};select public.claim_story_game('{game['game_id']}');", check=False)
        assert denied.returncode
        assert sql(f'set role {role};select * from public.user_story_game;', check=False).returncode
    assert begin_game(sql, project, owner=OTHER, check=False).returncode


def test_replaced_lease_rejects_old_worker_and_attempts_are_bounded(sql, ready):
    project, _, _ = ready
    game, first, _, proposal = prepare(sql, project)
    sql(f"update public.user_story_game set lease_until=clock_timestamp()-interval '1 second' where id='{game['game_id']}';")
    second = service(sql, 'claim_story_game', f"'{game['game_id']}'")
    assert second['token'] != first['token'] and second['attempts'] == 2
    assert stage(sql, game, first, proposal, check=False).returncode
    service(sql, 'fail_story_game', f"'{game['game_id']}','{second['token']}'")
    third = service(sql, 'claim_story_game', f"'{game['game_id']}'")
    assert third['attempts'] == 3
    service(sql, 'fail_story_game', f"'{game['game_id']}','{third['token']}'")
    assert service(sql, 'claim_story_game', f"'{game['game_id']}'", check=False).returncode


def test_actual_http_send_holds_revocation_until_the_response_finishes(sql, ready, monkeypatch):
    import asyncio
    from apps.api.story_game_routes import StoryGameResponse
    project, edition, _ = ready
    game, claim, _, proposal = prepare(sql, project)
    stage(sql, game, claim, proposal)
    review = read(sql, project, game, True)
    publish(sql, project, game, review['candidate_digest'], permissions(review))
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)

    async def scenario():
        messages, revocation = [], None
        async def receive(): return {'type': 'http.disconnect'}
        async def send(message):
            nonlocal revocation
            messages.append(message)
            if message['type'] == 'http.response.start':
                revocation = asyncio.create_task(asyncio.to_thread(consent, sql, project, edition, 2, 'revoke'))
                await asyncio.sleep(.1)
                assert not revocation.done()
        await StoryGameResponse(OWNER, project, game['game_id'])({'type': 'http'}, receive, send)
        await revocation
        assert messages[0]['status'] == 200
        body = b''.join(m.get('body', b'') for m in messages)
        assert b'source_id' not in body and b'authority' not in body
        again = []
        async def collect(message): again.append(message)
        await StoryGameResponse(OWNER, project, game['game_id'])({'type': 'http'}, receive, collect)
        assert again[0]['status'] == 409
        assert b'My father' not in b''.join(m.get('body', b'') for m in again)
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['consent', 'source'])
def test_revocation_before_provider_body_send_transmits_no_manuscript(sql, ready, monkeypatch, change):
    import asyncio
    import httpx
    from apps.api.story_game_runtime import generate_story_game
    from test_background_profile_workflow import Broker

    project, edition, _ = ready
    game = begin_game(sql, project)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL', 'https://gateway.test/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL', 'controlled-game-model')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'controlled-game-key')

    async def scenario():
        before_send, release = asyncio.Event(), asyncio.Event()
        transmitted = bytearray()

        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                before_send.set()
                await release.wait()
                async for chunk in request.stream:
                    transmitted.extend(chunk)
                packet = json.loads(json.loads(transmitted)['input'])
                return httpx.Response(200, json=dict(id='resp-controlled', model='controlled', status='completed',
                    output=[dict(type='message', content=[dict(type='output_text', text=json.dumps(proposal_from_packet(packet)))])]))

        client_type = httpx.AsyncClient
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(transport=Transport(), **kwargs))
        pending = asyncio.create_task(generate_story_game(Broker(sql), game['game_id']))
        try:
            await asyncio.wait_for(before_send.wait(), 2)
            if change == 'consent':
                await asyncio.to_thread(consent, sql, project, edition, 2, 'revoke')
            else:
                source = sql('select id from public.user_narrator_source order by sequence limit 1;').stdout.strip()
                await asyncio.to_thread(rpc, sql, 'change_user_narrator_source',
                    f"{literal(project)},'{source}',1,'withdraw',null")
            release.set()
            with pytest.raises(Exception):
                await pending
            assert transmitted == b'', 'Revoked manuscript crossed the provider transport boundary'
        finally:
            release.set()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize('revoke_during_send', [False, True])
def test_provider_body_holds_authority_only_until_transmission_finishes(sql, ready, monkeypatch, revoke_during_send):
    import asyncio
    import httpx
    from apps.api.story_game_runtime import generate_story_game
    from test_background_profile_workflow import Broker

    project, edition, _ = ready
    game = begin_game(sql, project)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL', 'https://gateway.test/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL', 'controlled-game-model')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'controlled-game-key')

    async def scenario():
        transmitted = bytearray()
        revocation = None

        class Transport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request):
                nonlocal revocation
                async for chunk in request.stream:
                    transmitted.extend(chunk)
                    if revoke_during_send:
                        revocation = asyncio.create_task(asyncio.to_thread(consent, sql, project, edition, 2, 'revoke'))
                        async with asyncio.timeout(1):
                            while True:
                                blocked = await asyncio.to_thread(sql, "select exists(select 1 from pg_stat_activity "
                                    "where wait_event_type='Lock' and query like '%set_story_game_consent%');")
                                if blocked.stdout.strip() == 't': break
                                await asyncio.sleep(.01)
                        assert not revocation.done(), 'Revocation must wait for the active body send'
                # A provider may now take minutes. Authority locks must already be released.
                if revocation is not None:
                    await asyncio.wait_for(revocation, 1)
                assert len(transmitted) == int(request.headers['Content-Length'])
                packet = json.loads(json.loads(transmitted)['input'])
                assert 'token' not in packet
                return httpx.Response(200, json=dict(id='resp-controlled', model='controlled', status='completed',
                    output=[dict(type='message', content=[dict(type='output_text', text=json.dumps(proposal_from_packet(packet)))])]))

        client_type = httpx.AsyncClient
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client_type(transport=Transport(), **kwargs))
        try:
            if revoke_during_send:
                with pytest.raises(httpx.HTTPStatusError):
                    await generate_story_game(Broker(sql), game['game_id'])
            else:
                result = await generate_story_game(Broker(sql), game['game_id'])
                assert result['status'] == 'review_required'
            assert transmitted
        finally:
            if revocation is not None:
                await asyncio.gather(revocation, return_exceptions=True)

    asyncio.run(scenario())
