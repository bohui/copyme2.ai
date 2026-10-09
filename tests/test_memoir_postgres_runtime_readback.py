"""Complete-round readback with a deterministic, provider-free worker boundary.

The offline tests exercise actual runtime, lease orchestration and SQLite jobs
against an explicitly in-memory storage double. Only the opt-in PostgreSQL
tests establish persisted RPC/RLS/artifact/canonical state through fresh facades.
Neither variant replaces runtime methods, strict readback or persistence with
success mocks. No campaign inputs, provider, browser or Temporal are involved.
"""
import asyncio
import base64
from copy import deepcopy
import json
import os
import socket
import sqlite3
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from apps.api.agent_lock import AgentTurnLease
from apps.api.agent_storage import UserStorage
from apps.api.codex_runtime import CodexRuntime
from apps.api.evaluation_cases import SyntheticStorage
from apps.api.memory_event_worker import MemoirLaneBroker, MemoryEventWorker
from scripts.issue14_subscription_runner import (
    SubscriptionRunnerError, _canonical_state, _runtime_readback,
)
from memoir_postgres_workflow import PostgresRest, _sql_json_record, quoted
from test_memoir_postgres_artifacts import artifact_database as _artifact_database


PROJECT = 'synthetic-complete-round'
TEXT = 'My mother Mei and I, Avery, lived in Sydney. She taught me to sew.'
PROFILE = {'preferred_language': 'en-AU'}
ENTITLEMENT = {'status': 'paid', 'plan_key': 'family_memoir_v1',
    'family_tree': True, 'timeline': True, 'stripe_price_id': 'synthetic-family-price'}
ARTIFACT = b'{"synthetic":1}\n{"synthetic":2,"separators":"\xc2\x85\xe2\x80\xa8\xe2\x80\xa9"}\n'
FAMILY = {'people': [{'id': 'mum', 'name': 'Mei'}, {'id': 'me', 'name': 'Avery'}],
    'relationships': [{'from_person_id': 'mum', 'to_person_id': 'me',
        'relationship_type': 'parent'}]}
PLACE = {'place': 'Sydney', 'hierarchy': ['Earth', 'Australia', 'Sydney'],
    'granularity': 'city'}


def collector_proposal():
    return {'acknowledgement': 'You remember learning to sew with your mother.',
        'plan': {'candidates': [{'id': 'sewing', 'question': 'What did you first sew together?',
            'context': {'event_id': None, 'photo_id': None, 'life_stage': None, 'year': None},
            'order': 0, 'bridge': ''}], 'chosen_id': 'sewing', 'active_event_id': None},
        'associations': [], 'response_photo_ids': [], 'stopped': False}


class DeterministicWorker:
    """The sole generated-content boundary, delivered through real HTTP clients."""
    def __init__(self, *, family=True, unfinished_activity=False):
        self.family, self.unfinished_activity = family, unfinished_activity
        self.calls = []

    def handle(self, request):
        assert request.url.host == 'synthetic-worker.invalid'
        assert request.url.path == '/internal/codex/turn' and request.method == 'POST'
        body = json.loads(request.content)
        self.calls.append(deepcopy(body))
        role = body.get('agent_role', 'collector')
        artifacts = []
        if role == 'collector':
            assert body['text'] == TEXT
            assert body['interview_context']['source']['text'] == TEXT
            reply = json.dumps(collector_proposal())
            artifacts = [{'path': 'sessions/synthetic-round.jsonl',
                'content': base64.b64encode(ARTIFACT).decode('ascii')}]
        elif role == 'workspace':
            assert body['text'] == TEXT and body['canonical_events'] is True
            reply = '[[MEMORY_SPARK_PLACE_JOURNEY]]' + json.dumps(PLACE) + '[[/MEMORY_SPARK_PLACE_JOURNEY]]'
            if self.family:
                reply += '[[MEMORY_SPARK_FAMILY_TREE]]' + json.dumps(FAMILY) + '[[/MEMORY_SPARK_FAMILY_TREE]]'
        elif role == 'author_timeline':
            context = json.loads(body['text'])
            assert len(context['sources']) == 1 and context['sources'][0]['text'] == TEXT
            source = context['sources'][0]
            reply = json.dumps({'events': [{'id': 'sewing', 'kind': 'event',
                'title': 'Learning to sew with mother', 'source_refs': [{
                    'source_id': source['id'], 'version': source['version'], 'quote': TEXT,
                    'char_start': 0, 'char_end': len(TEXT)}]}]})
        else:
            raise AssertionError('Unexpected deterministic worker role')
        data = {'thread_id': 'synthetic-' + role, 'reply': reply, 'artifacts': artifacts}
        if request.headers.get('accept') != 'application/x-ndjson':
            return httpx.Response(200, json=data)
        activity = {'id': 'synthetic-' + role, 'label': 'Synthetic worker', 'status': 'running'}
        events = [{'type': 'codex_activity', 'data': activity}]
        if not self.unfinished_activity:
            events.append({'type': 'codex_activity', 'data': {**activity, 'status': 'completed'}})
        events.extend([{'type': 'provider_complete', 'data': {**data, 'artifacts': []}},
            {'type': 'result', 'data': data}])
        return httpx.Response(200, content=''.join(json.dumps(event) + '\n' for event in events),
            headers={'content-type': 'application/x-ndjson'})


class OfflineStorage(SyntheticStorage, UserStorage):
    """Mutable unit-test storage; never evidence of PostgreSQL/RLS correctness."""
    def __init__(self, *, family=True):
        SyntheticStorage.__init__(self, {'profile': PROFILE,
            'entitlement': ENTITLEMENT if family else None}, {})
        self.user_id = str(uuid4())
        self.turn, self.source, self.objects, self.rounds = None, None, {}, 0

    def agent_turn_by_id(self, project_id, client_turn_id):
        return next((deepcopy(row) for row in self._memories
            if row.get('client_turn_id') == client_turn_id), None)

    def accept_interview_turn(self, project_id, client_turn_id, text, **options):
        assert self.turn is None and project_id == PROJECT and text == TEXT
        self.source = {'id': str(uuid4()), 'version': 1, 'sequence': 1, 'status': 'active',
            'project_id': project_id, 'text': text, 'kind': options['kind'], 'language': options['language']}
        self.turn = {'source': deepcopy(self.source), 'photo_context': [],
            'client_turn_id': client_turn_id, 'sequence': 1}
        return deepcopy(self.turn)

    def interview_context(self, project_id):
        return {'plan': None, 'photos': [], 'associations': []}

    def memory_events(self, project_id):
        return {'project_id': project_id, 'completed_rounds': self.rounds,
            'sources': [deepcopy(self.source)] if self.source else [], 'events': [],
            'processing': {'extracted_through': 0, 'pending_inputs': int(self.source is not None)}}

    def first_narrator_reply(self):
        return None

    def recall_rounds_completed(self):
        return self.rounds

    def save_interview_plan(self, project_id, client_turn_id, plan, associations, token, **options):
        assert token == self._lease_token and client_turn_id == self.turn['client_turn_id']
        self.turn.update(plan=deepcopy(plan), associations=deepcopy(associations), **options)
        return deepcopy(self.turn)

    def commit_agent_turn(self, token, thread_id, text, paths, *, source_sequence=None, **options):
        rows = SyntheticStorage.commit_agent_turn(self, token, thread_id, text, paths,
            source_sequence=source_sequence)
        rows[0].update(id=str(uuid4()), project_id=options['project_id'],
            client_turn_id=options['client_turn_id'])
        self.rounds += int(options['user_response'])
        return deepcopy(rows)

    def assign_memory_stage(self, memory_id, life_stage):
        row = next(row for row in self._memories if row['id'] == memory_id)
        row['life_stage'] = life_stage
        return [deepcopy(row)]

    def all_memories(self, **options):
        return self.memories()

    def _put(self, path, content, content_type, *, overwrite):
        assert content_type == 'application/octet-stream' and overwrite is False
        assert path.startswith(self.user_id + '/agent/') and path not in self.objects
        assert '/turns/' + str(UUID(self._lease_token)) + '/' in path
        self.objects[path] = bytes(content)

    def get_agent_file(self, relative):
        return self.objects[self.user_id + '/agent/' + self.agent_path(relative)]

    def update_agent_memory_source_paths(self, memory_id, source_paths):
        row = next(row for row in self._memories if row['id'] == memory_id)
        assert all(self.user_id + '/agent/' + path in self.objects for path in source_paths)
        row['source_paths'] = list(source_paths)
        return [deepcopy(row)]


@pytest.fixture(autouse=True)
def deny_python_tcp(monkeypatch):
    """Catch unintended external clients, including errors swallowed by runtime.

    The opt-in database fixture uses its existing subprocess/Unix-socket SQL
    transport. In-process HTTP must always use the deterministic MockTransports.
    """
    attempts = []
    for name in ('connect', 'connect_ex'):
        original = getattr(socket.socket, name)
        def guarded(sock, address, _original=original):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                attempts.append(True)
                raise AssertionError('Provider-free round attempted a TCP connection')
            return _original(sock, address)
        monkeypatch.setattr(socket.socket, name, guarded)
    yield
    assert attempts == [], 'Provider-free round attempted a TCP connection'


@pytest.fixture(scope='module')
def round_database():
    if os.environ.get('MEMOIR_TEST_ARTIFACT_POSTGRES') != '1':
        pytest.skip('Complete-round PostgreSQL gate requires explicit opt-in')
    setup = _artifact_database.__wrapped__()
    try:
        try:
            sql = next(setup)
        except pytest.skip.Exception:
            pytest.fail('Explicit complete-round PostgreSQL gate could not start its database', pytrace=False)
        yield sql
    finally:
        setup.close()


@pytest.fixture
def round_environment(monkeypatch, tmp_path):
    path = tmp_path / 'owned-round-tasks.sqlite'
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(path))
    monkeypatch.setenv('STRIPE_PRICE_FAMILY', ENTITLEMENT['stripe_price_id'])
    monkeypatch.setenv('MEMORY_SPARK_PRIVATE_DRAFT_CADENCE', '5')
    return path


async def run_round(storage, worker, *, streaming, tmp_path):
    runtime = CodexRuntime(home_root=tmp_path / 'unused-provider-homes',
        worker_url='http://synthetic-worker.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(worker.handle), model='synthetic-no-provider')
    correlation = {'run_id': str(uuid4()), 'case_id': 'synthetic-complete-round', 'round_id': '1'}
    events, deltas = [], []
    async def on_event(value):
        events.append(deepcopy(value))
    async def on_delta(value):
        deltas.append(value)
    result = await runtime.turn(storage, TEXT, project_id=PROJECT, language='en-AU',
        conversation_text=TEXT, source_kind='narrator_chat', client_turn_id=str(uuid4()),
        evaluation=correlation, include_trajectory=True,
        **({'on_event': on_event, 'on_delta': on_delta} if streaming else {}))
    assert runtime.observed_worker_requests == 2
    assert sorted(call.get('agent_role', 'collector') for call in worker.calls) == ['collector', 'workspace']
    if streaming:
        assert ''.join(deltas) == result['reply']
        assert any(event['type'] == 'conversation_saved' for event in events)
        assert any(event['type'] == 'workspace_update' for event in events)
    return result, correlation


def assert_workspace_persisted(result, reader, task_db, *, family):
    assert result['conversation_saved'] is True and result['task_errors'] == []
    assert result['family_features_enabled'] is family
    assert result['place_journey']['place'] == 'Sydney'
    assert reader.place_journey()['place'] == 'Sydney'
    if family:
        assert result['family_context_update']['persisted'] is True
        saved = reader.family_context(PROJECT)
        assert saved == result['family_context']
        assert {person['name'] for person in saved['people']} == {'Mei', 'Avery'}
        assert len(saved['relationships']) == 1
        assert saved['relationships'][0]['relationship_type'] == 'parent'
    assert len(result['source_paths']) == 1
    path = result['source_paths'][0]
    assert reader.get_agent_file(path) == ARTIFACT
    memories = reader.memories()
    assert len(memories) == 1 and memories[0]['source_paths'] == [path]
    assert memories[0]['content'] == 'Storyteller: ' + TEXT + '\nMemory Spark: ' + result['reply']
    with sqlite3.connect(task_db) as db:
        jobs = db.execute('select status,attempts,error,lease_token from workspace_jobs').fetchall()
    assert jobs == [('SUCCEEDED', 1, None, None)]


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('family', [False, True])
def test_offline_complete_runtime_round_passes_strict_readback(round_environment, tmp_path, streaming, family):
    storage, worker = OfflineStorage(family=family), DeterministicWorker(family=family)
    result, correlation = asyncio.run(run_round(storage, worker, streaming=streaming, tmp_path=tmp_path))
    assert_workspace_persisted(result, storage, round_environment, family=family)
    view = storage.memory_events(PROJECT)
    assert view['completed_rounds'] == 1 and view['sources'][0]['text'] == TEXT
    # This unit version has no extraction lane; do not claim canonical settlement.
    assert view['processing'] == {'extracted_through': 0, 'pending_inputs': 1}
    assert _runtime_readback(result, correlation)['accepted_source_id'] == view['sources'][0]['id']


def test_offline_successful_workspace_does_not_hide_unfinished_worker_activity(round_environment, tmp_path):
    storage, worker = OfflineStorage(family=False), DeterministicWorker(family=False, unfinished_activity=True)
    result, correlation = asyncio.run(run_round(storage, worker, streaming=True, tmp_path=tmp_path))
    assert_workspace_persisted(result, storage, round_environment, family=False)
    with pytest.raises(SubscriptionRunnerError, match='background_incomplete'):
        _runtime_readback(result, correlation)


def test_explicit_postgres_gate_cannot_pass_as_an_availability_skip(monkeypatch):
    def unavailable():
        pytest.skip('Synthetic unavailable backend')
        yield  # Keep the same lazy fixture contract without starting a service.
    monkeypatch.setenv('MEMOIR_TEST_ARTIFACT_POSTGRES', '1')
    monkeypatch.setitem(round_database.__wrapped__.__globals__, '_artifact_database',
        SimpleNamespace(__wrapped__=unavailable))
    setup = round_database.__wrapped__()
    try:
        with pytest.raises(pytest.fail.Exception, match='Explicit complete-round PostgreSQL gate'):
            next(setup)
    finally:
        setup.close()


@pytest.mark.parametrize('streaming', [False, True])
def test_postgres_complete_runtime_round_strict_and_canonical_readback(
        round_database, round_environment, tmp_path, streaming):
    """Explicit native opt-in only; actual PG, no provider/browser/Temporal."""
    sql, owner = round_database, str(uuid4())
    sql(f'insert into auth.users(id,is_anonymous) values({quoted(owner)},false);')
    storages = []
    async def scenario():
        storage = await AgentTurnLease.io(lambda: PostgresRest(sql, owner, entitlement=ENTITLEMENT).storage())
        storages.append(storage)
        await AgentTurnLease.io(storage.save_profile, PROFILE)
        worker = DeterministicWorker()
        result, correlation = await run_round(storage, worker, streaming=streaming, tmp_path=tmp_path)
        reader = await AgentTurnLease.io(lambda: PostgresRest(sql, owner, entitlement=ENTITLEMENT).storage())
        storages.append(reader)
        await AgentTurnLease.io(assert_workspace_persisted, result, reader, round_environment, family=True)
        # Strict admission occurs before canonical lane work, as in the runner.
        admitted = _runtime_readback(result, correlation)
        async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql, owner, service=True).handle)) as db:
            broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic', client=db)
            lanes = await broker.drain_once()
            assert len(lanes) == 1
            extractor = MemoryEventWorker(broker, worker_url='http://synthetic-worker.invalid',
                worker_secret='synthetic', worker_transport=httpx.MockTransport(worker.handle))
            outcome = await extractor.execute_lane(lanes[0])
            assert outcome['status'] == 'saved'
            await broker.drain_once()
            assert await broker.rpc('pending_memoir_lanes', p_limit=100) == []
        view = await AgentTurnLease.io(reader.memory_events, PROJECT)
        _canonical_state(view, {'project_id': PROJECT, 'language': 'en-AU', 'rounds': [TEXT]},
            [admitted['accepted_source_id']])
        assert len(view['events']) == 1 and view['events'][0]['status'] == 'active'
        assert view['events'][0]['source_refs'][0]['quote'] == TEXT
        assert [call.get('agent_role', 'collector') for call in worker.calls].count('author_timeline') == 1
    try:
        asyncio.run(scenario())
    finally:
        for storage in storages:
            storage.client.close()
        sql(f"begin; delete from storage.objects where split_part(name,'/',1)={quoted(owner)}; "
            f'delete from auth.users where id={quoted(owner)}; commit;')
        remaining = sql(f"select jsonb_build_object('owners',(select count(*) from auth.users where id={quoted(owner)}),"
            f"'objects',(select count(*) from storage.objects where split_part(name,'/',1)={quoted(owner)}));")
        assert _sql_json_record(remaining.stdout) == {'owners': 0, 'objects': 0}
