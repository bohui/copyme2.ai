"""Place cues must survive the canonical collector contract to reach the map."""
from copy import deepcopy
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.lifetime_memory_continuity import (
    governed_collector_schema, validate_governed_collector_result,
)
from test_name_only_opening import proposal
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_agent_commit_postgres import database as base_database


TEXT = '我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院'
PLACES = [
    {'place': '悉尼', 'hierarchy': ['Earth', '澳大利亚', '悉尼'], 'granularity': 'city',
        'latitude': -33.8688, 'longitude': 151.2093},
    {'place': '承德市', 'hierarchy': ['Earth', '中国', '河北省', '承德市'], 'granularity': 'city',
        'latitude': 40.9517, 'longitude': 117.9632},
]
CONTEXT = {'source': {'id': '00000000-0000-4000-8000-000000000004',
    'version': 1, 'status': 'active', 'kind': 'narrator_chat', 'text': TEXT}}


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True)


def test_canonical_contract_requests_named_places():
    schema = governed_collector_schema(CONTEXT)
    assert 'place_journeys' in schema['required']
    assert schema['properties']['place_journeys']['maxItems'] == 8
    assert schema['$defs']['_PlaceJourney']['additionalProperties'] is False


def test_canonical_result_preserves_both_places_from_the_reported_message():
    output = proposal(mode='extract', name=None, question='提到承德，您最先想起的是哪段往事？')
    output['place_journeys'] = deepcopy(PLACES)
    result = validate_governed_collector_result(output, CONTEXT)
    assert [place['place'] for place in result['place_journeys']] == ['悉尼', '承德市']
    assert all(place['schema_version'] == 1 for place in result['place_journeys'])
    from apps.api.place_geocoding import resolve_place_map
    assert all(resolve_place_map(place, [])['status'] == 'READY' for place in result['place_journeys'])


@pytest.mark.parametrize('place', [
    {'place': '开封', 'hierarchy': ['Earth', '中国', '开封'], 'granularity': 'city'},
    {'place': '附属医院', 'hierarchy': ['Earth', '中国', '附属医院'], 'granularity': 'city'},
    {'place': '承德市', 'hierarchy': ['Earth', '中国', '开封'], 'granularity': 'city'},
])
def test_unmentioned_places_and_buildings_do_not_reach_the_map(place):
    output = proposal(mode='extract', name=None)
    output['place_journeys'] = [place]
    assert validate_governed_collector_result(output, CONTEXT)['place_journeys'] == []


def test_place_storage_requires_owner_current_source_and_grounded_label(sql):
    from test_agent_commit_postgres import OWNER, OTHER, OLD, as_user
    from test_shared_memory_events_postgres import rpc, literal
    identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
    project = identity['project_id']
    source = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}',{literal(TEXT)}")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence = rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")
    places = validate_governed_collector_result({**proposal(mode='extract', name=None),
        'place_journeys': PLACES}, {'source': source})['place_journeys']
    arguments = f"{literal(fence)}::jsonb,'{source['id']}',1,{literal(places)}::jsonb"
    try:
        rpc(sql, 'persist_lifetime_place_journeys', arguments)
        assert len(rpc(sql, 'read_lifetime_place_journeys', literal(project))) == 2
        assert rpc(sql, 'read_lifetime_place_journeys', literal(project), owner=OTHER, check=False).returncode != 0
        assert rpc(sql, 'persist_lifetime_place_journeys', arguments, owner=OTHER, check=False).returncode != 0
        assert sql(as_user('select * from public.user_lifetime_place_journey;', OWNER), check=False).returncode != 0
        forged = [{**places[0], 'place': 'Perth', 'hierarchy': ['Earth', 'Australia', 'Perth']}]
        assert rpc(sql, 'persist_lifetime_place_journeys',
            f"{literal(fence)}::jsonb,'{source['id']}',1,{literal(forged)}::jsonb", check=False).returncode != 0
        assert rpc(sql, 'persist_lifetime_place_journeys',
            f"{literal(fence)}::jsonb,'{source['id']}',2,{literal(places)}::jsonb", check=False).returncode != 0
        assert len(rpc(sql, 'read_lifetime_place_journeys', literal(project))) == 2
    finally:
        sql(as_user(f"select public.release_user_agent_turn_lease('{OLD}');"))


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('change', ['withdraw', 'edit'])
def test_canonical_http_turn_delivers_places_to_the_workspace(sql, tmp_path, monkeypatch, streaming, change):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from memoir_postgres_workflow import PostgresRest
    from test_agent_commit_postgres import OWNER

    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'gpt-5.6-luna-pooled')
    calls = []

    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        assert json.loads(body['governed']['packet'])['current']['narrator']['original'] == TEXT
        output = proposal(mode='extract', name=None, question='提到承德，您最先想起的是哪段往事？')
        output['acknowledgement'] = '慧博，谢谢您告诉我这些。'
        output['place_journeys'] = deepcopy(PLACES)
        result = {'reply': json.dumps(output, ensure_ascii=False),
            'thread_id': 'synthetic-place-turn', 'artifacts': []}
        if request.headers.get('accept') == 'application/x-ndjson':
            return httpx.Response(200, headers={'Content-Type': 'application/x-ndjson'},
                content=json.dumps({'type': 'result', 'data': result}) + '\n')
        return httpx.Response(200, json=result)

    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path,
        worker_url='http://controlled.invalid', worker_secret='synthetic', worker_transport=httpx.MockTransport(provider)))
    payload = {'text': TEXT, 'language': 'zh-CN', 'client_turn_id': str(uuid4())}
    headers = {'Accept': 'application/x-ndjson' if streaming else 'application/json'}
    with TestClient(create_app(MemoryStore())) as client:
        response = client.post('/api/v1/memoir/agent/turn',
            headers=headers, json=payload)
        retry = client.post('/api/v1/memoir/agent/turn', headers=headers, json=payload)
    assert response.status_code == 200, response.text
    if streaming:
        events = [json.loads(line) for line in response.text.splitlines()]
        assert not [event for event in events if event['type'] == 'error'], events
        result = next(event['data'] for event in events if event['type'] == 'result')
        workspace = next(event['data'] for event in events if event['type'] == 'workspace_update')
        assert workspace['place_journeys'] == result['place_journeys']
        assert workspace['project_id'] == result['project_id'] and workspace['source_sequence'] == 1
        assert workspace['place_journey_change']['mentioned']
    else:
        result = response.json()
    assert result['conversation_saved']
    assert [place['place'] for place in result['place_journeys']] == ['悉尼', '承德市']
    assert result['place_journey']['place'] == '承德市'
    replay = next(json.loads(line)['data'] for line in retry.text.splitlines()
        if json.loads(line)['type'] == 'result') if streaming else retry.json()
    assert replay['cached'] and replay['place_journeys'] == result['place_journeys']
    assert len(calls) == 1
    from apps.api import main
    from test_lifetime_home_recovery import HomeRest
    monkeypatch.setattr(main, 'authenticated_storage', lambda _: HomeRest(sql, OWNER).storage())
    storage = PostgresRest(sql, OWNER).storage()
    try:
        saved = storage.lifetime_rpc('read_lifetime_place_journeys', p_project_id=result['project_id'])
        assert saved == result['place_journeys']
        with TestClient(create_app(MemoryStore())) as client:
            auth = {'Authorization': 'Bearer synthetic'}
            home = client.post('/v1/projects', headers=auth, json={})
            assert home.status_code == 201, home.text
            assert home.json()['profile']['memory_places'] == saved
            decorated = deepcopy(saved)
            decorated[-1]['pictures'] = [{'asset_id': 'synthetic', 'title': 'Public reference'}]
            patched = client.patch('/v1/projects/' + result['project_id'], headers=auth,
                json={'profile': {'memory_places': decorated}})
            assert patched.status_code == 200, patched.text
            assert patched.json()['profile']['memory_places'] == decorated
            restored = client.get('/v1/agent/place-journey', headers=auth)
            assert restored.json()['place_journey']['place'] == '承德市'
            storage.change_narrator_source(result['project_id'], result['accepted_source_id'], 1,
                action=change, text='小时候在爸爸工作的学校的家属院里玩。' if change == 'edit' else None)
            assert storage.lifetime_rpc('read_lifetime_place_journeys', p_project_id=result['project_id']) == []
            assert client.get('/v1/agent/place-journey', headers=auth).json()['place_journey'] is None
            cleared = client.get('/v1/projects/' + result['project_id'], headers=auth)
            assert cleared.json()['profile']['memory_places'] == []
    finally:
        storage.client.close()
