"""Saved canonical interviews create and consume historical clues through real SQL."""
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.codex_runtime import CodexRuntime
from apps.api.historical_news import HistoricalResearch
from apps.api.main import create_app
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER, database as base_database
from test_historical_news import evidence, receipt, news_proposal
from test_lifetime_memory_engine import valid_reply
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_shared_memory_events_postgres import rpc, literal


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True)


@pytest.mark.parametrize('streaming', [False, True])
def test_canonical_save_research_and_later_citation(sql, tmp_path, monkeypatch, streaming):
    from apps.api import agent_routes
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '1')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'gpt-5.6-luna-pooled')
    calls = []

    def collector(request):
        body = json.loads(request.content)
        context = body['interview_context']
        calls.append(context)
        output = json.loads(valid_reply()) if len(calls) == 1 else news_proposal()
        output['plan']['conversation_phase'] = 'explore'
        data = {'thread_id': 'controlled-news-thread', 'reply': json.dumps(output), 'artifacts': []}
        if request.headers.get('accept') == 'application/x-ndjson':
            return httpx.Response(200, headers={'Content-Type': 'application/x-ndjson'},
                content=json.dumps({'type': 'result', 'data': data})+'\n')
        return httpx.Response(200, json=data)

    class Provider:
        async def discover(self, query, *, timeout):
            assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip() != '0'
            assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip() == '0'
            return {'receipt': receipt(), 'events': [evidence()]}

        async def inspect(self, url, *, timeout):
            return {'url': url, 'text': evidence()['excerpt'], 'source_title': 'Town archive',
                'publisher': 'Town library', 'publication_date': '2020-01-01',
                'retrieved_at': '2026-10-15T00:00:00Z'}

    runtime = CodexRuntime(home_root=tmp_path, worker_url='http://controlled.invalid',
        worker_secret='synthetic', worker_transport=httpx.MockTransport(collector))
    runtime._news_engine = HistoricalResearch(Provider())
    monkeypatch.setattr(agent_routes, 'runtime', runtime)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    headers = {'Accept': 'application/x-ndjson' if streaming else 'application/json'}

    def result(response):
        assert response.status_code == 200, response.text
        if streaming:
            events = [json.loads(line) for line in response.text.splitlines()]
            assert not [e for e in events if e['type'] == 'error'], events
            return next(e['data'] for e in events if e['type'] == 'result')
        return response.json()

    with TestClient(create_app(MemoryStore())) as client:
        payload = {'client_turn_id': str(uuid4()),
            'text': 'I was born in Boston, USA, in 1960. I carried a blue umbrella.', 'language': 'en-AU'}
        first = result(client.post('/v1/agent/turn', headers=headers, json=payload))
        assert first['conversation_saved'] and 'historical_context' not in first
        project = first['project_id']
        state = rpc(sql, 'read_user_historical_news', literal(project))
        assert len(state['clues']) == 1
        replay = result(client.post('/v1/agent/turn', headers=headers, json={**payload, 'project_id': project}))
        assert replay['cached'] and len(calls) == 1
        assert sql('select count(*) from public.user_historical_news_job;').stdout.strip() == '1'
        later = result(client.post('/v1/agent/turn', headers=headers, json={
            'project_id': project, 'text': 'What else could we explore?', 'language': 'en-AU'}))
        assert later['historical_context']['source_url'] == evidence()['source_url']
        assert len(calls[1]['historical_news']['clues']) == 1
        assert rpc(sql, 'read_user_historical_news', literal(project))['clues'] == []
    assert sql('select count(*) from public.user_memory_event;').stdout.strip() == '0'
