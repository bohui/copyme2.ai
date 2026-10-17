"""Authenticated conversation → real timeline owner → persisted profile readback."""
import asyncio
from contextlib import asynccontextmanager
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes
from apps.api.codex_runtime import CodexRuntime
from apps.api.lifetime_memory_lane_engine import LanePublication
from apps.api.lifetime_memory_publication import PublicationUnavailable
from apps.api.main import create_app
from apps.api.memory_event_worker import MemoryEventWorker
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER, database as base_database
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_name_only_opening import proposal
from test_shared_memory_events_postgres import literal


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True)


def worker_response(request, output):
    result = {'reply': json.dumps(output), 'thread_id': 'synthetic', 'artifacts': []}
    if request.headers.get('accept') == 'application/x-ndjson':
        return httpx.Response(200, headers={'Content-Type': 'application/x-ndjson'},
            content=json.dumps({'type': 'result', 'data': result}) + '\n')
    return httpx.Response(200, json=result)


class FixturePublication(LanePublication):
    @asynccontextmanager
    async def guard(self, fence):
        try:
            async with super().guard(fence):
                yield
        except PublicationUnavailable as error:
            raise AssertionError('Disposable provider admission: ' + str(error.__cause__ or error)) from error


class Broker:
    def __init__(self, sql):
        self.sql = sql

    async def rpc(self, name, **parameters):
        arguments = ','.join(key + '=>' + literal(value) for key, value in parameters.items())
        query = 'set role service_role; select to_jsonb(public.' + name + '(' + arguments + '));'
        result = await asyncio.to_thread(self.sql, query, check=False)
        if result.returncode:
            request = httpx.Request('POST', 'http://disposable.invalid/rest/v1/rpc/' + name)
            response = httpx.Response(409, request=request, json={'code': '40001', 'message': 'stale profile page'})
            raise httpx.HTTPStatusError('Disposable SQL rejected the worker operation', request=request, response=response)
        value = result.stdout.strip()
        return json.loads(value.splitlines()[-1]) if value else None


@pytest.mark.parametrize('language,text', [('en-AU', '我记得小时候的花园。'),
                                         ('zh-CN', 'I remember the garden from childhood.')])
def test_explicit_ui_language_reaches_actual_collector_without_profile_language(sql, tmp_path, monkeypatch, language, text):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    calls = []
    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body.get('agent_role', 'collector') == 'collector'
        assert body['language'] == language
        output = proposal(mode='extract', name=None, question='What else do you remember?')
        output['plan']['conversation_phase'] = 'explore'
        return worker_response(request, output)
    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path,
        worker_url='http://controlled.invalid', worker_secret='synthetic', worker_transport=httpx.MockTransport(provider)))
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: PostgresRest(sql, OWNER).storage())) as client:
        response = client.post('/v1/agent/turn', json={'text': text, 'language': language, 'client_turn_id': str(uuid4())})
        assert response.status_code == 200, response.text
        read = client.get('/v1/agent/profile')
        assert read.status_code == 200 and read.json()['preferred_language'] == language
        assert len(calls) == 1


def test_profile_checkpoints_include_intervening_sources_and_respect_manual_stop(sql, tmp_path, monkeypatch):
    sql('update public.lifetime_two_lane_rollout set enabled=true;')
    monkeypatch.setenv('MEMOIR_TWO_LANES', '1')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    profile_calls = []

    def provider(request):
        body = json.loads(request.content)
        bounded = body.get('bounded_lane')
        if bounded:
            payload = json.loads(bounded['packet'])['payload']
            phase = bounded['phase']
            if phase == 'profile':
                profile_calls.append(payload)
                source = payload['source']
                changes = []
                for cue, field, value in [('born in 1960', 'birth_year', 1960),
                        ('grew up in Chengde', 'childhood_place', 'Chengde')]:
                    if cue in source['text'] and field in payload['profile_context']['targets']:
                        changes.append({'field': field, 'value': value, 'source_refs': [{
                            'source_id': source['id'], 'version': source['version'], 'quote': cue,
                            'char_start': None, 'char_end': None}]})
                output = {'profile_patch': changes}
            elif phase == 'summarize':
                output = payload.get('prior', {'items': []})
            else:
                assert phase == 'extract'
                output = {'events': [], 'place_journeys': [], 'prepared_questions': []}
        else:
            output = proposal(mode='extract', name=None, question='What else do you remember?')
            output['plan']['conversation_phase'] = 'explore'
        return worker_response(request, output)

    transport = httpx.MockTransport(provider)
    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path,
        worker_url='http://controlled.invalid', worker_secret='synthetic', worker_transport=transport))
    worker = MemoryEventWorker(Broker(sql), worker_url='http://controlled.invalid',
        worker_secret='synthetic', worker_transport=transport)
    worker.lane_publisher = FixturePublication(sql.publication_dsn, authenticated_owner=OWNER)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: PostgresRest(sql, OWNER).storage())) as client:
        project = None
        for number in range(1, 21):
            text = {2: 'I was born in 1960.', 7: 'I grew up in Chengde.'}.get(number,
                'I remember the workshop and its blue door, memory ' + str(number) + '.')
            payload = {'text': text, 'client_turn_id': str(uuid4())}
            if project:
                payload['project_id'] = project
            response = client.post('/v1/agent/turn', json=payload)
            assert response.status_code == 200, response.text
            project = response.json()['project_id']
            lane_id = sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
            before = len(profile_calls)
            for _ in range(20):
                outcome = asyncio.run(worker.execute_lane(lane_id))
                if outcome.get('retrieval_complete') or outcome['status'] in {'finished', 'deferred'}:
                    break
            else:
                pytest.fail('bounded profile/timeline work did not settle')
            if number not in {1, 5, 10}:
                assert len(profile_calls) == before
            profile = client.get('/v1/agent/profile')
            assert profile.status_code == 200, profile.text
            if number == 1:
                manual = client.patch('/v1/agent/profile', json={'birth_place': 'Hobart'})
                assert manual.status_code == 200, manual.text
            if number == 5:
                assert profile.json()['birth_year'] == 1960
            if number == 10:
                assert profile.json()['childhood_place'] == 'Chengde'
                protected = client.patch('/v1/agent/profile', json={'profile_confirm_all': True})
                assert protected.status_code == 200, protected.text
                assert protected.json()['profile_automation']['stopped'] is True
        assert {call['profile_context']['target_round'] for call in profile_calls} == {1, 5, 10}
        for call in profile_calls:
            if call['profile_context']['target_round'] >= 5:
                assert 'birth_place' not in call['profile_context']['targets']
                assert call['profile_context']['reference']['birth_place']['value'] == 'Hobart'
        reread = client.get('/v1/agent/profile')
        assert reread.json()['birth_year'] == 1960
        assert reread.json()['profile_automation']['stopped'] is True
        coverage = reread.json()['profile_automation']['progress']
        assert coverage['covered_round'] == 10 and coverage['skipped_round'] == 20
        assert coverage['status'] == 'skipped'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip() == '20'


@pytest.mark.parametrize('failed', [False, True])
def test_real_profile_worker_does_not_block_a_later_conversation_reply(sql, tmp_path, monkeypatch, failed):
    sql('update public.lifetime_two_lane_rollout set enabled=true;')
    monkeypatch.setenv('MEMOIR_TWO_LANES', '1')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        bounded = body.get('bounded_lane')
        if bounded:
            if bounded['phase'] == 'profile':
                entered.set()
                await release.wait()
                if failed:
                    return httpx.Response(503)
                output = {'profile_patch': []}
            elif bounded['phase'] == 'summarize':
                output = {'items': []}
            else:
                assert bounded['phase'] == 'extract'
                output = {'events': [], 'place_journeys': [], 'prepared_questions': []}
        else:
            output = proposal(mode='extract', name=None, question='What else do you remember?')
            output['plan']['conversation_phase'] = 'explore'
        return worker_response(request, output)
    transport = httpx.MockTransport(provider)
    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path,
        worker_url='http://controlled.invalid', worker_secret='synthetic', worker_transport=transport))
    worker = MemoryEventWorker(Broker(sql), worker_url='http://controlled.invalid',
        worker_secret='synthetic', worker_transport=transport)
    worker.lane_publisher = FixturePublication(sql.publication_dsn, authenticated_owner=OWNER)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: PostgresRest(sql, OWNER).storage())) as client:
        first = client.post('/v1/agent/turn', json={'text': 'I remember the workshop.', 'client_turn_id': str(uuid4())})
        assert first.status_code == 200, first.text
        project = first.json()['project_id']
        lane_id = sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
        async def scenario():
            background = asyncio.create_task(worker.execute_lane(lane_id))
            try:
                async with asyncio.timeout(10):
                    await entered.wait()
                async with asyncio.timeout(15):
                    second = await asyncio.to_thread(client.post, '/v1/agent/turn', json={
                        'text': 'I remember its blue door.', 'project_id': project, 'client_turn_id': str(uuid4())})
                assert second.status_code == 200, second.text
                assert second.json()['conversation_saved']
                assert second.json()['reply'].endswith('What else do you remember?')
                assert not background.done()
                assert sql('select count(*) from public.user_completed_round;').stdout.strip() == '2'
            finally:
                release.set()
                await background
        asyncio.run(scenario())
        assert sum(body.get('bounded_lane', {}).get('phase') == 'profile' for body in calls) == 1
