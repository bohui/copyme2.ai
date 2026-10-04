"""Issue 6 public persistence seam on real, disposable PostgreSQL.

The existing harness creates and stops a random /tmp cluster. No configured
Supabase URL, shared service, or customer data is used.
"""
import json
import asyncio
from pathlib import Path

import pytest

from test_agent_commit_postgres import database, as_user, OWNER, OTHER
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database


TURN = '00000000-0000-4000-8000-000000000001'
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def event_database(private_database):
    for path in sorted((ROOT / 'supabase/migrations').glob('20261004*.sql')):
        private_database(path.read_text())
    return private_database


@pytest.fixture
def sql(event_database):
    event_database('truncate public.user_memoir_project cascade;')
    event_database('truncate public.user_memory, public.user_recall_usage, '
                   'public.user_agent_session, public.user_agent_turn_lease cascade;')
    event_database('truncate public.user_profile, public.user_family_context, public.guest_conversation_transfer, '
                   'public.user_conversation_attachment cascade;')
    event_database('update auth.users set is_anonymous=false;')
    return event_database


def rpc(sql, name, arguments, *, owner=OWNER, check=True):
    result = sql(as_user(f'select public.{name}({arguments});', owner), check=check)
    return json.loads(result.stdout.splitlines()[-1]) if check else result


def literal(value):
    return "'" + (json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value).replace("'", "''") + "'"


def extract(sql, sources, events):
    manifest = [{'id': s['id'], 'version': s['version']} for s in sources]
    return rpc(sql, 'apply_user_memory_events', f"'project', {literal(manifest)}::jsonb, {literal(events)}::jsonb")


def test_one_reply_has_distinct_events_and_later_reply_enriches_the_same_identity(sql):
    first = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'I started school around 1964 and moved to Sydney in 1986.'")
    school_ref = {'source_id': first['id'], 'version': 1, 'quote': 'I started school around 1964'}
    move_ref = {'source_id': first['id'], 'version': 1, 'quote': 'moved to Sydney in 1986'}
    view = extract(sql, [first], [
        {'id': 'school', 'kind': 'event', 'title': 'Started school', 'life_stage': 'childhood',
         'temporal': {'expression': 'around 1964', 'precision': 'approximate', 'year_start': 1964, 'year_end': 1964, 'basis': [school_ref]},
         'stage_evidence': [school_ref], 'source_refs': [school_ref]},
        {'id': 'move', 'kind': 'event', 'title': 'Moved to Sydney', 'life_stage': 'young_adulthood',
         'temporal': {'expression': '1986', 'precision': 'year', 'year_start': 1986, 'year_end': 1986, 'basis': [move_ref]},
         'stage_evidence': [move_ref], 'source_refs': [move_ref]},
    ])
    events = {e['title']: e for e in view['events']}
    school, move = events['Started school'], events['Moved to Sydney']
    assert school['id'] != move['id'] and school['id'] != 'school'
    assert school['life_stage'] == 'childhood' and school['temporal']['precision'] == 'approximate'
    assert move['life_stage'] == 'young_adulthood' and move['temporal']['year_start'] == 1986
    later = rpc(sql, 'accept_user_narrator_source', "'project', '00000000-0000-4000-8000-000000000002', 'At that school I carried a blue bag.'")
    enriched = extract(sql, [later], [{'existing_id': school['id'], 'expected_revision': school['revision'],
        'kind': 'event', 'title': 'Started school', 'source_refs': [
            {'source_id': later['id'], 'version': 1, 'quote': 'At that school I carried a blue bag.'}]}])
    same = next(e for e in enriched['events'] if e['id'] == school['id'])
    assert same['revision'] == 2
    assert {r['source_id'] for r in same['source_refs']} == {first['id'], later['id']}
    assert same['temporal'] == school['temporal']
    assert next(e for e in enriched['events'] if e['id'] == move['id']) == move


def test_durable_narrator_acceptance_survives_missing_reply_and_replay(sql):
    arguments = f"'project', '{TURN}', 'I started school around 1964.', 'narrator_chat', 'en-AU'"
    accepted = rpc(sql, 'accept_user_narrator_source', arguments)
    assert rpc(sql, 'accept_user_narrator_source', arguments) == accepted
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert view['sources'] == [accepted]
    assert accepted['text'] == 'I started school around 1964.'
    assert accepted['version'] == 1 and accepted['sequence'] == 1
    assert view['processing']['extracted_through'] == 0
    assert view['processing']['pending_inputs'] == 1
    assert view['completed_rounds'] == 0
    assert view['events'] == []


def test_empty_extraction_advances_only_its_committed_input(sql):
    first = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'Thanks.'")
    manifest = json.dumps([{'id': first['id'], 'version': 1}])
    rpc(sql, 'apply_user_memory_events', f"'project', '{manifest}'::jsonb, '[]'::jsonb")
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert view['events'] == []
    assert view['processing'] == {'extracted_through': 1, 'pending_inputs': 0}
    assert view['completed_rounds'] == 0


def test_explicit_tag_correction_preserves_identity_and_fences_later_model_estimate(sql):
    first = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'I started school around 1964.'")
    ref = {'source_id': first['id'], 'version': 1, 'quote': first['text']}
    initial = extract(sql, [first], [{'id': 'school', 'kind': 'event', 'title': 'Started school',
        'life_stage': 'childhood', 'stage_evidence': [ref],
        'temporal': {'expression': 'around 1964', 'precision': 'approximate', 'year_start': 1964, 'year_end': 1964, 'basis': [ref]},
        'source_refs': [ref]}])['events'][0]
    patch = {'life_stage': 'adolescence', 'temporal': {'expression': '1966', 'precision': 'year', 'year_start': 1966, 'year_end': 1966}}
    corrected = rpc(sql, 'correct_user_memory_event', f"'project', {literal(initial['id'])}, 1, {literal(patch)}::jsonb, 'I was an adolescent, and the year was 1966.'")
    assert corrected['id'] == initial['id'] and corrected['revision'] == 2
    assert corrected['life_stage'] == 'adolescence' and corrected['temporal']['year_start'] == 1966
    assert corrected['user_overrides']['life_stage']['actor'] == OWNER
    assert all(ref in corrected['source_refs'] for ref in initial['source_refs'])
    stale = rpc(sql, 'correct_user_memory_event', f"'project', {literal(initial['id'])}, 1, {literal(patch)}::jsonb, 'stale edit'", check=False)
    assert stale.returncode != 0 and 'revision conflict' in stale.stderr
    later = rpc(sql, 'accept_user_narrator_source', "'project', '00000000-0000-4000-8000-000000000002', 'At that school I carried a blue bag.'")
    update = {'existing_id': initial['id'], 'expected_revision': 2, 'kind': 'event', 'title': 'Started school',
        'life_stage': 'childhood', 'temporal': initial['temporal'], 'stage_evidence': [ref],
        'source_refs': [{'source_id': later['id'], 'version': 1, 'quote': later['text']}]}
    saved = extract(sql, [later], [update])['events'][0]
    assert saved['id'] == initial['id'] and saved['life_stage'] == 'adolescence'
    assert saved['temporal']['year_start'] == 1966 and saved['revision'] == 3


def test_story_workflow_retains_original_testimony_when_provider_delivery_fails(sql, tmp_path, monkeypatch):
    import httpx
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    storage = PostgresRest(sql, OWNER).storage()
    storage.save_profile({'preferred_language': 'en-AU', 'conversation_language':
        {'locale': 'en-AU', 'source': 'explicit', 'revision': 1}})
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    provider = httpx.MockTransport(lambda request: httpx.Response(503, json={'detail': 'controlled provider unavailable'}))
    runtime = CodexRuntime(home_root=tmp_path / 'homes', worker_url='http://controlled-model.invalid',
                           worker_secret='synthetic-worker-secret', worker_transport=provider)
    with pytest.raises(RuntimeError, match='HTTP 503'):
        asyncio.run(runtime.turn(storage, 'Prompt wrapper: My original memory.', project_id='project',
            conversation_text='I started school around 1964.', client_turn_id=TURN))
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert [s['text'] for s in view['sources']] == ['I started school around 1964.']
    assert view['completed_rounds'] == 0 and storage.recall_rounds_completed() == 0
    with pytest.raises(RuntimeError, match='HTTP 503'):
        asyncio.run(runtime.turn(storage, 'Prompt wrapper: My original memory.', project_id='project',
            conversation_text='I started school around 1964.', client_turn_id=TURN))
    assert rpc(sql, 'read_user_memory_events', "'project'")['sources'] == view['sources']


def service_rpc(sql, name, arguments):
    result = sql(f"set role service_role; select coalesce(to_jsonb(public.{name}({arguments})),'null'::jsonb);")
    return json.loads(result.stdout.splitlines()[-1])


def deliver_latest(sql):
    receipt = sql(as_user("select id from public.user_private_draft_outbox order by created_at desc,id desc limit 1;")).stdout.splitlines()[-1]
    return service_rpc(sql, 'queue_memoir_receipt', f"'{receipt}', 5")


def test_timeline_lane_accumulates_inputs_while_one_run_is_active_and_claims_latest(sql):
    first = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'First memory.'")
    receipt = deliver_latest(sql)
    lane = receipt['timeline_lane_id']
    active = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 120")
    assert [s['id'] for s in active['sources']] == [first['id']]
    for i in range(2, 21):
        rpc(sql, 'accept_user_narrator_source', f"'project', '00000000-0000-4000-8000-{i:012d}', 'Memory {i}.'")
        assert deliver_latest(sql)['timeline_lane_id'] == lane
        assert service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 120") is None
    before = rpc(sql, 'read_user_memory_events', "'project'")
    assert before['processing']['extracted_through'] == 0
    saved = service_rpc(sql, 'finish_memoir_timeline', f"'{lane}', {literal(active['token'])}, '[]'::jsonb")
    assert saved['status'] == 'saved'
    catchup = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 120")
    assert catchup['from_sequence'] == 2 and catchup['through_sequence'] == 20
    assert len(catchup['sources']) == 19
    assert rpc(sql, 'read_user_memory_events', "'project'")['processing']['extracted_through'] == 1


def test_failed_and_timed_out_timeline_ranges_remain_pending_and_late_worker_is_fenced(sql):
    first = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'Original memory.'")
    lane = deliver_latest(sql)['timeline_lane_id']
    active = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 120")
    failure = service_rpc(sql, 'fail_memoir_lane', f"'{lane}', {literal(active['token'])}, 'MEMOIR_PROVIDER_UNAVAILABLE', false")
    assert failure['status'] == 'retry_required'
    assert rpc(sql, 'read_user_memory_events', "'project'")['processing']['extracted_through'] == 0
    rpc(sql, 'retry_user_memoir_lane', "'project', 'timeline'")
    replacement = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 120")
    assert replacement['sources'] == [first]
    assert service_rpc(sql, 'finish_memoir_timeline', f"'{lane}', {literal(active['token'])}, '[]'::jsonb")['status'] == 'stale'
    # Administrative fixture advances the database deadline; this controls time
    # only in the disposable cluster, never through a production test endpoint.
    sql(f"update public.user_memoir_lane set run_deadline=clock_timestamp()-interval '1 second' where id='{lane}';")
    assert service_rpc(sql, 'heartbeat_memoir_lane', f"'{lane}', {literal(replacement['token'])}") is False
    catchup = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 120")
    assert catchup['sources'] == [first] and catchup['token'] != replacement['token']
    assert service_rpc(sql, 'finish_memoir_timeline', f"'{lane}', {literal(replacement['token'])}, '[]'::jsonb")['status'] == 'stale'
    assert service_rpc(sql, 'finish_memoir_timeline', f"'{lane}', {literal(catchup['token'])}, '[]'::jsonb")['status'] == 'saved'
    assert rpc(sql, 'read_user_memory_events', "'project'")['processing']['extracted_through'] == 1


def test_existing_worker_boundary_commits_canonical_events_and_successful_empty_processing(sql, tmp_path, monkeypatch):
    import sys
    import httpx
    from fastapi import FastAPI, Header, HTTPException
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
    from memoir_postgres_workflow import PostgresRest
    source = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'I started school around 1964.'")
    control = tmp_path / 'provider.json'
    control.write_text(json.dumps({'reply': {'events': [{'id': 'school', 'kind': 'event', 'title': 'Started school',
        'source_refs': [{'source_id': source['id'], 'version': 1, 'quote': source['text']}]}]}}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')  # Supported isolated macOS worker mode.
    provider_worker = CodexWorker(home_root=tmp_path / 'worker-homes',
        command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
    app = FastAPI()
    @app.post('/internal/codex/turn')
    async def worker_turn(payload: WorkerTurnInput, x_codex_worker_secret: str | None = Header(default=None)):
        if x_codex_worker_secret != 'synthetic-worker-secret':
            raise HTTPException(401)
        return await provider_worker.turn(payload)
    async def scenario():
        service_transport = httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)
        async with httpx.AsyncClient(transport=service_transport) as db_client:
            broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=db_client)
            lane_ids = await broker.drain_once()
            worker = MemoryEventWorker(broker, worker_url='http://controlled-worker.invalid',
                worker_secret='synthetic-worker-secret', worker_transport=httpx.ASGITransport(app=app))
            assert (await worker.execute_lane(lane_ids[0]))['status'] == 'saved'
            saved = rpc(sql, 'read_user_memory_events', "'project'")
            assert saved['events'][0]['title'] == 'Started school'
            assert saved['events'][0]['source_refs'][0]['source_id'] == source['id']
            rpc(sql, 'accept_user_narrator_source', "'project', '00000000-0000-4000-8000-000000000002', 'Thanks.'")
            control.write_text(json.dumps({'reply': {'events': []}}))
            await broker.drain_once()
            assert (await worker.execute_lane(lane_ids[0]))['status'] == 'saved'
            after = rpc(sql, 'read_user_memory_events', "'project'")
            assert after['events'] == saved['events']
            assert after['processing']['extracted_through'] == 2
    asyncio.run(scenario())


def test_composer_checkpoint_waits_for_extraction_and_coalesces_at_claim_time(sql):
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sources = []
    for i in range(1, 6):
        turn = f'00000000-0000-4000-8000-{i:012d}'
        sources.append(rpc(sql, 'accept_user_narrator_source', f"'project', '{turn}', 'Memory {i}.'"))
        rpc(sql, 'commit_user_agent_turn', f"'{OLD}', 'thread', E'Storyteller: Memory {i}.\\nMemory Spark: Tell me more.', '{{}}'::text[], null, 'project', '{turn}', true, 'unplaced'")
    queued = deliver_latest(sql)
    composer = queued['composer_lane_id']
    assert service_rpc(sql, 'claim_memoir_lane', f"'{composer}', 300") is None
    timeline = service_rpc(sql, 'claim_memoir_lane', f"'{queued['timeline_lane_id']}', 120")
    service_rpc(sql, 'finish_memoir_timeline', f"'{queued['timeline_lane_id']}', {literal(timeline['token'])}, '[]'::jsonb")
    active = service_rpc(sql, 'claim_memoir_lane', f"'{composer}', 300")
    assert active['coverage_round'] == 5 and active['through_sequence'] == 5
    for i in range(6, 21):
        turn = f'00000000-0000-4000-8000-{i:012d}'
        rpc(sql, 'accept_user_narrator_source', f"'project', '{turn}', 'Memory {i}.'")
        rpc(sql, 'commit_user_agent_turn', f"'{OLD}', 'thread', E'Storyteller: Memory {i}.\\nMemory Spark: Tell me more.', '{{}}'::text[], null, 'project', '{turn}', true, 'unplaced'")
        assert deliver_latest(sql)['composer_lane_id'] == composer
        assert service_rpc(sql, 'claim_memoir_lane', f"'{composer}', 300") is None
    service_rpc(sql, 'fail_memoir_lane', f"'{composer}', {literal(active['token'])}, 'MEMOIR_UNAVAILABLE', false")
    rpc(sql, 'retry_user_memoir_lane', "'project', 'composer'")
    assert service_rpc(sql, 'claim_memoir_lane', f"'{composer}', 300") is None
    next_timeline = service_rpc(sql, 'claim_memoir_lane', f"'{queued['timeline_lane_id']}', 120")
    service_rpc(sql, 'finish_memoir_timeline', f"'{queued['timeline_lane_id']}', {literal(next_timeline['token'])}, '[]'::jsonb")
    catchup = service_rpc(sql, 'claim_memoir_lane', f"'{composer}', 300")
    assert catchup['coverage_round'] == 20 and catchup['through_sequence'] == 20
    assert catchup['from_sequence'] == 1 and len(catchup['sources']) == 20


def five_rounds(sql, text='I started school around 1964.'):
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sources = []
    for i in range(1, 6):
        turn = f'00000000-0000-4000-8000-{i:012d}'
        words = text if i == 1 else 'Thanks.'
        sources.append(rpc(sql, 'accept_user_narrator_source', f"'project', '{turn}', {literal(words)}"))
        rpc(sql, 'commit_user_agent_turn', f"'{OLD}', 'thread', {literal('Storyteller: ' + words + chr(10) + 'Memory Spark: Tell me more.')}, '{{}}'::text[], null, 'project', '{turn}', true, 'unplaced'")
    ref = {'source_id': sources[0]['id'], 'version': 1, 'quote': text}
    extract(sql, sources, [{'id': 'school', 'kind': 'event', 'title': 'Started school', 'source_refs': [ref]}])
    return sources, deliver_latest(sql)


def test_latest_validated_draft_is_available_with_coverage_while_update_is_running(sql):
    sources, lanes = five_rounds(sql)
    composer = lanes['composer_lane_id']
    first = service_rpc(sql, 'claim_memoir_lane', f"'{composer}', 300")
    event = first['events'][0]
    bundle = {'status': 'ready', 'preview': {'title': 'Starting school', 'text': 'I started school around 1964.'},
        'validation': {'ok': True}, 'review': {'ready_for_user_review': True, 'publication_approved': False, 'findings': []},
        'sections': [{'id': 'school-section', 'chapter_id': 'school-chapter', 'event_ids': [event['id']],
            'fingerprint': 'synthetic-validated-input', 'content': 'I started school around 1964.'}],
        'manuscript': {'kind': 'sample_chapter', 'chapters': []}}
    saved = service_rpc(sql, 'finish_memoir_composer', f"'{composer}', {literal(first['token'])}, 0, {literal(bundle)}::jsonb")
    assert saved['status'] == 'saved'
    view = rpc(sql, 'read_user_memoir_draft', "'project', 'en-AU'")
    assert view['status'] == 'ready' and view['covered_round'] == 5
    assert view['preview']['text'] == 'I started school around 1964.'
    assert view['revision'] == 1 and view['sections'][0]['revision'] == 1
    rpc(sql, 'retry_user_memoir_lane', "'project', 'composer'")
    newer = service_rpc(sql, 'claim_memoir_lane', f"'{composer}', 300")
    updating = rpc(sql, 'read_user_memoir_draft', "'project', 'en-AU'")
    assert updating['preview'] == view['preview'] and updating['covered_round'] == 5 and updating['updating']
    invalid = {**bundle, 'review': {'ready_for_user_review': False, 'publication_approved': False, 'findings': []}}
    assert service_rpc(sql, 'finish_memoir_composer', f"'{composer}', {literal(newer['token'])}, 1, {literal(invalid)}::jsonb")['status'] == 'rejected'
    assert rpc(sql, 'read_user_memoir_draft', "'project', 'en-AU'")['preview'] == view['preview']


def test_existing_composer_worker_uses_shared_event_ids_and_originals_without_reextracting(sql, tmp_path, monkeypatch):
    import sys
    import httpx
    from fastapi import FastAPI
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
    from memoir_postgres_workflow import PostgresRest
    sources, lanes = five_rounds(sql)
    timeline = rpc(sql, 'read_user_memory_events', "'project'")
    calls = tmp_path / 'calls.jsonl'
    control = tmp_path / 'provider.json'
    control.write_text(json.dumps({'mode': 'composer', 'calls': str(calls)}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    app = FastAPI()
    async def scenario():
        async def readiness_connection(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(readiness_connection, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        provider_worker = CodexWorker(home_root=tmp_path / 'worker-homes', base_url=f'http://127.0.0.1:{port}/v1',
            command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
        @app.post('/internal/codex/turn')
        async def worker_turn(payload: WorkerTurnInput):
            return await provider_worker.turn(payload)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)) as db:
                broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=db)
                worker = MemoryEventWorker(broker, worker_url='http://controlled-worker.invalid',
                    worker_secret='synthetic-worker-secret', worker_transport=httpx.ASGITransport(app=app))
                assert (await worker.execute_lane(lanes['composer_lane_id']))['status'] == 'saved'
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())
    saved = rpc(sql, 'read_user_memoir_draft', "'project', 'en-AU'")
    assert saved['status'] == 'ready' and saved['covered_round'] == 5
    assert saved['preview']['text'] == 'I started school around 1964.'
    assert saved['sections'][0]['event_ids'] == [timeline['events'][0]['id']]
    assert saved['sections'][0]['source_refs'][0]['source_id'] == sources[0]['id']
    assert [json.loads(line)['phase'] for line in calls.read_text().splitlines()] == ['prepare_start', 'prepare_end', 'draft', 'review']


def run_controlled_composer(sql, tmp_path, monkeypatch, lane, *, prose='I started school around 1964.', control_options=None):
    """The external provider is controlled; storage, worker, JS and render are real."""
    import sys
    import httpx
    from fastapi import FastAPI
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
    from memoir_postgres_workflow import PostgresRest
    calls = tmp_path / 'calls.jsonl'
    control = tmp_path / 'provider.json'
    control.write_text(json.dumps({'mode': 'composer', 'calls': str(calls), 'prose': prose, **(control_options or {})}))
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    async def scenario():
        async def readiness_connection(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(readiness_connection, '127.0.0.1', 0)
        app = FastAPI()
        provider = CodexWorker(home_root=tmp_path / 'worker-homes',
            base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
            command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
        @app.post('/internal/codex/turn')
        async def turn(payload: WorkerTurnInput):
            return await provider.turn(payload)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)) as db:
                worker = MemoryEventWorker(MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=db),
                    worker_url='http://controlled-worker.invalid', worker_secret='synthetic-worker-secret',
                    worker_transport=httpx.ASGITransport(app=app))
                return await worker.execute_lane(lane)
        finally:
            server.close()
            await server.wait_closed()
    return asyncio.run(scenario())


def add_rounds(sql, start, end, text='Thanks.'):
    from test_agent_commit_postgres import OLD
    result = []
    for i in range(start, end + 1):
        turn = f'00000000-0000-4000-8000-{i:012d}'
        result.append(rpc(sql, 'accept_user_narrator_source', f"'project', '{turn}', {literal(text)}"))
        rpc(sql, 'commit_user_agent_turn', f"'{OLD}', 'thread', {literal('Storyteller: '+text+chr(10)+'Memory Spark: Tell me more.')}, '{{}}'::text[], null, 'project', '{turn}', true, 'unplaced'")
    return result


def test_unchanged_checkpoint_advances_coverage_without_new_prose_or_revision(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    lane = lanes['composer_lane_id']
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane)['status'] == 'saved'
    before = rpc(sql, 'read_user_memoir_draft', "'project'")
    extract(sql, add_rounds(sql, 6, 10), [])
    assert deliver_latest(sql)['composer_lane_id'] == lane
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane, prose='Provider would rewrite unchanged prose.')['status'] == 'saved'
    after = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert after['covered_round'] == 10 and after['milestone'] == 10
    assert after['preview'] == before['preview'] and after['sections'] == before['sections']
    assert after['revision'] == before['revision']
    calls = [json.loads(line)['phase'] for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert calls == ['prepare_start', 'prepare_end', 'draft', 'review']


@pytest.mark.parametrize('action', ['edit', 'withdraw'])
def test_source_changes_immediately_hide_dependent_drafts_and_reject_late_output(sql, tmp_path, monkeypatch, action):
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    before = rpc(sql, 'read_user_memoir_draft', "'project'")
    rpc(sql, 'retry_user_memoir_lane', "'project', 'composer'")
    active = service_rpc(sql, 'claim_memoir_lane', f"'{lanes['composer_lane_id']}', 300")
    text = 'I started school around 1966.' if action == 'edit' else None
    changed = rpc(sql, 'change_user_narrator_source', f"'project', '{sources[0]['id']}', 1, '{action}', {literal(text) if text else 'null'}")
    assert changed['id'] == sources[0]['id'] and changed['version'] == 2
    after = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert after['status'] == 'stale' and after['preview'] is None and after['sections'] == []
    assert after['revision'] == before['revision']
    assert service_rpc(sql, 'finish_memoir_composer', f"'{lanes['composer_lane_id']}', {literal(active['token'])}, 1, {literal(active['previous'])}::jsonb")['status'] == 'stale'
    timeline = rpc(sql, 'read_user_memory_events', "'project'")
    assert timeline['completed_rounds'] == 5
    assert all(ref['source_id'] != sources[0]['id'] for event in timeline['events'] for ref in event['source_refs'])
    assert changed['text'] == (text or '[withdrawn]')
    assert deliver_latest(sql)['composer_lane_id'] == lanes['composer_lane_id']


def test_tag_correction_invalidates_old_and_new_groups_without_changing_rounds(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    event = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
    patch = {'life_stage': 'adolescence', 'temporal': {'expression': '1966', 'precision': 'year', 'year_start': 1966, 'year_end': 1966}}
    changed = rpc(sql, 'correct_user_memory_event', f"'project', {literal(event['id'])}, 1, {literal(patch)}::jsonb, 'I was an adolescent in 1966.'")
    assert rpc(sql, 'read_user_memoir_draft', "'project'")['status'] == 'stale'
    changes = rpc(sql, 'read_user_memory_event_changes', "'project', 1")
    assert changes[-1]['event_id'] == event['id']
    assert changes[-1]['old_group']['life_stage'] == 'unplaced'
    assert changes[-1]['new_group']['life_stage'] == 'adolescence' and changes[-1]['new_group']['year_start'] == 1966
    assert changed['id'] == event['id'] and rpc(sql, 'read_user_memory_events', "'project'")['completed_rounds'] == 5


def test_bounded_partition_preparation_reuses_successes_after_provider_failure(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    added = add_rounds(sql, 6, 6, 'I moved to Sydney in 1986.')
    extract(sql, added, [{'kind': 'event', 'title': 'Moved to Sydney',
        'source_refs': [{'source_id': added[0]['id'], 'version': 1, 'quote': added[0]['text']}]}])
    deliver_latest(sql)
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_PREPARATION_CONCURRENCY', '2')
    result = run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'],
        control_options={'prepare_delay': .25, 'fail_prepare': ['Moved to Sydney']})
    assert result['status'] == 'retry'
    assert rpc(sql, 'read_user_memoir_draft', "'project'")['preview'] is None
    rpc(sql, 'retry_user_memoir_lane', "'project', 'composer'")
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    active = peak = 0
    starts = {}
    for call in calls:
        if call['phase'] == 'prepare_start':
            active += 1
            peak = max(peak, active)
            starts[call['event_id']] = starts.get(call['event_id'], 0) + 1
        elif call['phase'] == 'prepare_end':
            active -= 1
    events = {e['title']: e['id'] for e in rpc(sql, 'read_user_memory_events', "'project'")['events']}
    assert peak == 2 and active == 0
    assert starts[events['Started school']] == 1 and starts[events['Moved to Sydney']] == 2
    saved = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert saved['covered_round'] == 6 and saved['milestone'] == 5
    assert {id for section in saved['sections'] for id in section['event_ids']} == set(events.values())


def test_new_evidence_for_an_old_event_changes_its_passage_and_preserves_unrelated_bytes(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    second = add_rounds(sql, 6, 6, 'I moved to Sydney in 1986.')
    extract(sql, second, [{'kind': 'event', 'title': 'Moved to Sydney',
        'source_refs': [{'source_id': second[0]['id'], 'version': 1, 'quote': second[0]['text']}]}])
    deliver_latest(sql)
    original = {'Started school': 'I started school around 1964.', 'Moved to Sydney': 'I moved to Sydney in 1986.'}
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'], control_options={'event_prose': original})['status'] == 'saved'
    before = rpc(sql, 'read_user_memoir_draft', "'project'")
    events = {e['title']: e for e in rpc(sql, 'read_user_memory_events', "'project'")['events']}
    school, move = events['Started school'], events['Moved to Sydney']
    detail = add_rounds(sql, 7, 7, 'At that school I carried a blue bag.')
    extract(sql, detail, [{'existing_id': school['id'], 'expected_revision': 1, 'kind': 'event', 'title': 'Started school',
        'source_refs': [{'source_id': detail[0]['id'], 'version': 1, 'quote': detail[0]['text']}]}])
    extract(sql, add_rounds(sql, 8, 10), [])
    deliver_latest(sql)
    changed = {'Started school': 'I started school around 1964. I carried a blue bag.',
               'Moved to Sydney': 'A provider rewrite of an unchanged passage.'}
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'], control_options={'event_prose': changed})['status'] == 'saved'
    after = rpc(sql, 'read_user_memoir_draft', "'project'")
    old_move = next(s for s in before['sections'] if s['event_ids'] == [move['id']])
    assert next(s for s in after['sections'] if s['id'] == old_move['id']) == old_move
    assert 'I carried a blue bag.' in after['preview']['text'] and 'provider rewrite' not in after['preview']['text']
    old_school = next(s for s in before['sections'] if s['event_ids'] == [school['id']])
    new_school = next(s for s in after['sections'] if s['id'] == old_school['id'])
    assert new_school['revision'] == old_school['revision'] + 1 and new_school['content'] != old_school['content']


def story_client(sql, *, entitlement=None):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from apps.api.story_routes import build_router
    from memoir_postgres_workflow import PostgresRest
    def storage(authorization):
        if authorization != 'Bearer synthetic-author':
            raise HTTPException(401)
        return PostgresRest(sql, OWNER, entitlement=entitlement).storage()
    app = FastAPI()
    app.include_router(build_router(storage))
    return TestClient(app)


def test_authenticated_saved_draft_returns_shared_coverage_and_keeps_premium_display_gated(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    client = story_client(sql)
    headers = {'Authorization': 'Bearer synthetic-author'}
    saved = client.get('/v1/story/private-draft?project_id=project', headers=headers)
    assert saved.status_code == 200 and saved.json()['preview']['text'] == 'I started school around 1964.'
    assert saved.json()['covered_round'] == 5
    assert client.get('/v1/story/events?project_id=project', headers=headers).status_code == 403
    assert client.get('/v1/story/private-draft?project_id=project').status_code == 401
    response = client.post('/v1/story/private-draft/retry', headers=headers, json={'project_id': 'project'})
    assert response.status_code == 200 and response.json()['updating']
    assert rpc(sql, 'read_user_memory_events', "'project'")['completed_rounds'] == 5


def test_active_composer_keeps_frozen_milestone_and_locale_while_later_targets_arrive(sql):
    sources, lanes = five_rounds(sql)
    lane = lanes['composer_lane_id']
    active = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 300")
    later = add_rounds(sql, 6, 20)
    extract(sql, later, [])
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"preferred_language\":\"zh-CN\"}}') on conflict(user_id) do update set profile=excluded.profile;")
    deliver_latest(sql)
    assert service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 300") is None
    event = active['events'][0]
    bundle = {'preview': {'title': 'School', 'text': 'I started school around 1964.'},
        'validation': {'ok': True}, 'review': {'ready_for_user_review': True, 'publication_approved': False, 'findings': []},
        'event_manifest': active['event_manifest'], 'source_manifest': active['source_manifest'],
        'sections': [{'id': 'school-passage', 'chapter_id': 'school-chapter', 'event_ids': [event['id']],
                     'fingerprint': 'frozen-synthetic-input', 'content': 'I started school around 1964.'}]}
    assert service_rpc(sql, 'finish_memoir_composer', f"'{lane}', {literal(active['token'])}, 0, {literal(bundle)}::jsonb")['status'] == 'saved'
    saved = rpc(sql, 'read_user_memoir_draft', "'project', 'en-AU'")
    assert saved['covered_round'] == saved['milestone'] == 5 and saved['preview']['text'] == bundle['preview']['text']
    assert rpc(sql, 'read_user_memoir_draft', "'project', 'zh-CN'")['preview'] is None
    catchup = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 300")
    assert catchup['coverage_round'] == catchup['milestone'] == 20 and catchup['locale'] == 'zh-CN'


def test_story_workspace_only_dispatches_relationship_tree_and_never_duplicate_timeline(sql, tmp_path, monkeypatch):
    import sys
    import httpx
    from fastapi import FastAPI
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'jobs.sqlite'))
    monkeypatch.setenv('STRIPE_PRICE_FAMILY', 'synthetic-price')
    entitlement = {'status': 'paid', 'plan_key': 'family_memoir_v1', 'family_tree': True, 'timeline': True,
                   'stripe_price_id': 'synthetic-price'}
    storage = PostgresRest(sql, OWNER, entitlement=entitlement).storage()
    storage.save_profile({'preferred_language': 'en-AU', 'conversation_language': {'locale': 'en-AU', 'source': 'explicit', 'revision': 1}})
    control = tmp_path / 'provider.json'
    provider = CodexWorker(home_root=tmp_path / 'worker-homes',
        command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
    app, calls = FastAPI(), []
    @app.post('/internal/codex/turn')
    async def turn(payload: WorkerTurnInput):
        calls.append({'role': payload.agent_role, 'focus': payload.extraction_focus, 'family': payload.family_enabled})
        marker = ('[[MEMORY_SPARK_FAMILY_TREE]]{"people":[{"id":"father","name":"June","relationship_to_narrator":"father"}],"relationships":[]}[[/MEMORY_SPARK_FAMILY_TREE]]')
        control.write_text(json.dumps({'reply': marker if payload.extraction_focus == 'family_tree' else 'Tell me more.'}))
        return await provider.turn(payload)
    runtime = CodexRuntime(home_root=tmp_path / 'api-homes', worker_url='http://controlled-worker.invalid',
        worker_secret='synthetic-worker-secret', worker_transport=httpx.ASGITransport(app=app))
    async def scenario():
        await runtime.turn(storage, 'I started school around 1964.', project_id='project', client_turn_id=TURN)
        assert not any(c['family'] or c['focus'] == 'author_timeline' for c in calls if c['role'] == 'workspace')
        assert storage.family_context('project') is None
        calls.clear()
        await runtime.turn(storage, 'My father June taught me gardening.', project_id='project', client_turn_id='00000000-0000-4000-8000-000000000002')
        assert sum(c['focus'] == 'family_tree' for c in calls) == 1
        document = storage.family_context('project')
        assert document and document['people'][0]['name'] == 'June'
        assert document['timeline'] == []
    asyncio.run(scenario())
    assert rpc(sql, 'read_user_memory_events', "'project'")['processing']['pending_inputs'] == 2


@pytest.mark.parametrize('precision,expression,years', [
    ('year', 'when I was young', (1970, 1970)), ('unknown', 'unknown', (1970, 1970)),
    ('range', '1970 to 1980', (1980, 1970)), ('age', 'at age 12', (1970, 1970)),
])
def test_unsupported_numeric_dates_are_rejected_at_the_public_persistence_boundary(sql, precision, expression, years):
    text = 'I remember this ' + expression + '.'
    source = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', {literal(text)}")
    ref = {'source_id': source['id'], 'version': 1, 'quote': text}
    proposal = {'kind': 'event', 'title': 'A memory', 'source_refs': [ref],
        'temporal': {'expression': expression, 'precision': precision, 'year_start': years[0], 'year_end': years[1], 'basis': [ref]}}
    manifest = [{'id': source['id'], 'version': 1}]
    rejected = rpc(sql, 'apply_user_memory_events', f"'project', {literal(manifest)}::jsonb, {literal([proposal])}::jsonb", check=False)
    assert rejected.returncode != 0
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert view['events'] == [] and view['processing']['extracted_through'] == 0


def test_withdrawal_reprocesses_surviving_originals_and_retains_the_event_identity(sql):
    first = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'I started school in 1964.'")
    ref = {'source_id': first['id'], 'version': 1, 'quote': first['text']}
    initial = extract(sql, [first], [{'kind': 'event', 'title': 'Started school', 'source_refs': [ref]}])['events'][0]
    second = rpc(sql, 'accept_user_narrator_source', "'project', '00000000-0000-4000-8000-000000000002', 'At that school I carried a blue bag.'")
    surviving = {'source_id': second['id'], 'version': 1, 'quote': second['text']}
    extract(sql, [second], [{'existing_id': initial['id'], 'expected_revision': 1, 'kind': 'event', 'title': 'Started school', 'source_refs': [surviving]}])
    rpc(sql, 'change_user_narrator_source', f"'project', '{first['id']}', 1, 'withdraw'")
    before = rpc(sql, 'read_user_memory_events', "'project'")
    event = before['events'][0]
    assert event['id'] == initial['id'] and event['status'] == 'unresolved'
    assert event['source_refs'] == [surviving]
    assert before['processing']['pending_inputs'] == 1
    lane = deliver_latest(sql)['timeline_lane_id']
    job = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 120")
    assert [s['id'] for s in job['sources']] == [second['id']]
    proposal = {'existing_id': initial['id'], 'expected_revision': event['revision'], 'kind': 'event',
                'title': 'Carried a blue school bag', 'source_refs': [surviving]}
    assert service_rpc(sql, 'finish_memoir_timeline', f"'{lane}', {literal(job['token'])}, {literal([proposal])}::jsonb")['status'] == 'saved'
    after = rpc(sql, 'read_user_memory_events', "'project'")
    assert after['events'][0]['id'] == initial['id'] and after['events'][0]['status'] == 'active'
    assert after['events'][0]['source_refs'] == [surviving]
    assert after['processing']['pending_inputs'] == after['completed_rounds'] == 0


def test_withdrawn_evidence_can_be_replaced_by_a_valid_surviving_draft(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    second = add_rounds(sql, 6, 6, 'At that school I carried a blue bag.')
    event = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
    ref = {'source_id': second[0]['id'], 'version': 1, 'quote': second[0]['text']}
    extract(sql, second, [{'existing_id': event['id'], 'expected_revision': 1, 'kind': 'event',
                         'title': 'Started school', 'source_refs': [ref]}])
    deliver_latest(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    rpc(sql, 'change_user_narrator_source', f"'project', '{sources[0]['id']}', 1, 'withdraw'")
    deliver_latest(sql)  # Deliver the revocation intent before its extraction result.
    changed = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
    extract(sql, second, [{'existing_id': event['id'], 'expected_revision': changed['revision'], 'kind': 'event',
                         'title': 'Blue school bag', 'source_refs': [ref]}])
    deliver_latest(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'],
                                  prose='At that school I carried a blue bag.')['status'] == 'saved'
    saved = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert saved['revision'] == 2 and saved['covered_round'] == 6
    assert saved['preview']['text'] == 'At that school I carried a blue bag.'
    assert sources[0]['id'] not in {r['source_id'] for s in saved['sections'] for r in s['source_refs']}


def test_event_person_and_chronology_references_cannot_cross_project_scope(sql):
    sql(f"insert into public.user_family_context(user_id,project_id,document) values ('{OWNER}','elsewhere','{{\"people\":[{{\"id\":\"foreign-father\",\"name\":\"June\"}}]}}');")
    source = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'My father June taught me gardening.'")
    ref = {'source_id': source['id'], 'version': 1, 'quote': source['text']}
    proposal = {'kind': 'event', 'title': 'Gardening with father', 'source_refs': [ref], 'person_ids': ['foreign-father']}
    result = rpc(sql, 'apply_user_memory_events', f"'project', {literal([{'id':source['id'],'version':1}])}::jsonb, {literal([proposal])}::jsonb", check=False)
    assert result.returncode != 0
    assert rpc(sql, 'read_user_memory_events', "'project'")['events'] == []
    sql(f"insert into public.user_family_context(user_id,project_id,document) values ('{OWNER}','project','{{\"people\":[{{\"id\":\"father\",\"name\":\"June\"}}]}}');")
    proposal['person_ids'] = ['father']
    saved = extract(sql, [source], [proposal])['events'][0]
    assert saved['person_ids'] == ['father']
    other = rpc(sql, 'accept_user_narrator_source', "'elsewhere', '00000000-0000-4000-8000-000000000002', 'I moved away.'")
    foreign_event = rpc(sql, 'apply_user_memory_events', f"'elsewhere', {literal([{'id':other['id'],'version':1}])}::jsonb, {literal([{'kind':'event','title':'Moved away','source_refs':[{'source_id':other['id'],'version':1,'quote':other['text']}]}])}::jsonb")['events'][0]
    later = rpc(sql, 'accept_user_narrator_source', "'project', '00000000-0000-4000-8000-000000000003', 'This was before I moved away.'")
    proposal = {'kind': 'event', 'title': 'Gardening later', 'source_refs': [{'source_id':later['id'],'version':1,'quote':later['text']}],
                'relations': [{'kind':'before','event_id':foreign_event['id'],'source_refs':[{'source_id':later['id'],'version':1,'quote':later['text']}]}]}
    result = rpc(sql, 'apply_user_memory_events', f"'project', {literal([{'id':later['id'],'version':1}])}::jsonb, {literal([proposal])}::jsonb", check=False)
    assert result.returncode != 0
    assert rpc(sql, 'read_user_memory_events', "'project'")['events'] == [saved]


def test_explicit_chat_correction_uses_the_accepted_original_without_duplicate_testimony(sql):
    first = rpc(sql, 'accept_user_narrator_source', f"'project', '{TURN}', 'I started school in 1964.'")
    event = extract(sql, [first], [{'kind':'event','title':'Started school','source_refs':[{'source_id':first['id'],'version':1,'quote':first['text']}]}])['events'][0]
    correction = rpc(sql, 'accept_user_narrator_source', "'project', '00000000-0000-4000-8000-000000000002', 'Actually, the school year was 1966, in adolescence.'")
    ref = {'source_id':correction['id'],'version':1,'quote':correction['text']}
    proposal = {'existing_id':event['id'],'expected_revision':1,'kind':'event','title':'Started school',
                'life_stage':'adolescence','stage_evidence':[ref], 'correction':ref,
                'temporal':{'expression':'1966','precision':'year','year_start':1966,'year_end':1966,'basis':[ref]}, 'source_refs':[ref]}
    view = extract(sql, [correction], [proposal])
    corrected = view['events'][0]
    assert corrected['id'] == event['id'] and corrected['revision'] == 2
    assert corrected['life_stage'] == 'adolescence' and corrected['temporal']['year_start'] == 1966
    assert corrected['user_overrides']['temporal']['origin'] == 'chat'
    assert corrected['user_overrides']['temporal']['actor'] == OWNER
    assert len(view['sources']) == 2 and view['completed_rounds'] == 0
    later = rpc(sql, 'accept_user_narrator_source', "'project', '00000000-0000-4000-8000-000000000003', 'At that school I carried a blue bag.'")
    ref = {'source_id':later['id'],'version':1,'quote':later['text']}
    final = extract(sql, [later], [{'existing_id':event['id'],'expected_revision':2,'kind':'event','title':'School',
                                  'life_stage':'childhood','stage_evidence':[ref],'source_refs':[ref]}])['events'][0]
    assert final['life_stage'] == 'adolescence' and final['temporal']['year_start'] == 1966


def test_authenticated_voice_turn_retains_original_chinese_and_failed_reply_does_not_count(sql, tmp_path, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    storage = PostgresRest(sql, OWNER).storage()
    storage.save_profile({'preferred_language':'en-AU','conversation_language':{'locale':'en-AU','source':'explicit','revision':1}})
    provider = httpx.MockTransport(lambda request: httpx.Response(503, json={'detail':'controlled unavailable provider'}))
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda authorization: PostgresRest(sql, OWNER).storage())
    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path/'api-homes',
        worker_url='http://controlled-model.invalid', worker_secret='synthetic-worker-secret', worker_transport=provider))
    app = FastAPI()
    app.include_router(agent_routes.router)
    with TestClient(app) as client:
        response = client.post('/v1/agent/turn', headers={'Authorization':'Bearer synthetic-author'},
            json={'text':'我十二岁那年开始上学。','project_id':'project','client_turn_id':TURN,
                  'source_kind':'narrator_transcript','language':'en-AU'})
    assert response.status_code == 502
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert view['sources'][0]['kind'] == 'narrator_transcript'
    assert view['sources'][0]['language'] == 'zh-CN' and view['sources'][0]['text'] == '我十二岁那年开始上学。'
    assert view['completed_rounds'] == 0


def test_legacy_migration_preserves_ids_original_evidence_and_private_flags_on_replay(sql):
    memory_id = 'aaaa1111-1111-4111-8111-111111111111'
    sql(f"insert into public.user_memory(id,user_id,project_id,client_turn_id,kind,content) values ('{memory_id}','{OWNER}','project','{TURN}','agent',E'Storyteller: I started school around 1964.\\nMemory Spark: A derived assistant reply.');")
    legacy = {'people':[{'id':'father','name':'June'}], 'timeline':[
        {'id':'legacy-school','kind':'event','title':'Started school','date_expression':'around 1964','precision':'approximate',
         'visibility':'private','include_in_print':False,'person_ids':['father'],
         'source_refs':[{'source_id':memory_id,'quote':'I started school around 1964.'}]},
        {'id':'legacy-uncertain','kind':'period','title':'Worked as a carpenter','start_expression':'1986','end_expression':'2005',
         'precision':'range','visibility':'private','include_in_print':False}]}
    sql(f"insert into public.user_family_context(user_id,project_id,document) values ('{OWNER}','project',{literal(legacy)}::jsonb);")
    rpc(sql, 'migrate_user_memory_events', "'project'")
    before = rpc(sql, 'read_user_memory_events', "'project'")
    school = next(e for e in before['events'] if e['id']=='legacy-school')
    uncertain = next(e for e in before['events'] if e['id']=='legacy-uncertain')
    assert before['sources'][0]['text'] == 'I started school around 1964.'
    assert school['source_refs'][0]['quote'] == before['sources'][0]['text']
    assert school['temporal']['expression'] == 'around 1964' and school['temporal']['precision'] == 'approximate'
    assert school['visibility'] == 'private' and school['include_in_print'] is False and school['person_ids'] == ['father']
    assert uncertain['kind'] == 'period' and uncertain['status'] == 'unresolved'
    assert uncertain['provenance_status'] == 'legacy_evidence_unavailable' and uncertain['source_refs'] == []
    # The existing ledger recognises this completed narrator/reply pair. The
    # migration must preserve its one round, never manufacture another.
    assert before['completed_rounds'] == 1
    for path in sorted((ROOT/'supabase/migrations').glob('20261004*.sql')):
        sql(path.read_text())
    rpc(sql, 'migrate_user_memory_events', "'project'")
    assert rpc(sql, 'read_user_memory_events', "'project'") == before


def test_capability_transfer_preserves_canonical_ids_draft_dependencies_and_retry_state(sql, tmp_path, monkeypatch):
    from test_agent_commit_postgres import OLD
    token = 'ef' * 32
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    before = rpc(sql, 'read_user_memory_events', "'project'")
    draft = rpc(sql, 'read_user_memoir_draft', "'project'")
    sql(as_user(f"select public.release_user_agent_turn_lease({literal(OLD)});"))
    sql(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    rpc(sql, 'prepare_guest_conversation_transfer', f"'{token}', 'project', '[]'::jsonb")
    result = rpc(sql, 'attach_guest_conversation', literal(token), owner=OTHER)
    after = rpc(sql, 'read_user_memory_events', "'project'", owner=OTHER)
    saved = rpc(sql, 'read_user_memoir_draft', "'project'", owner=OTHER)
    assert after['events'] == before['events'] and after['sources'] == before['sources']
    assert after['processing'] == before['processing'] and after['completed_rounds'] == 5
    assert saved['preview'] == draft['preview'] and saved['sections'] == draft['sections']
    assert saved['covered_round'] == 5 and saved['revision'] == 1
    assert rpc(sql, 'attach_guest_conversation', literal(token), owner=OTHER) == result
    assert rpc(sql, 'read_user_memory_events', "'project'", owner=OTHER) == after
    assert rpc(sql, 'read_user_memoir_draft', "'project'", owner=OTHER) == saved
    rejected = rpc(sql, 'attach_guest_conversation', literal(token), owner=OWNER, check=False)
    assert rejected.returncode != 0


def test_protected_draft_keeps_its_bytes_and_saves_enrichment_as_a_revision_bound_proposal(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    before = rpc(sql, 'read_user_memoir_draft', "'project'")
    rpc(sql, 'protect_user_memoir_draft', "'project', 'en-AU', 1, true")
    event = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
    details = add_rounds(sql, 6, 6, 'At that school I carried a blue bag.')
    extract(sql, details, [{'existing_id':event['id'],'expected_revision':1,'kind':'event','title':'School',
        'source_refs':[{'source_id':details[0]['id'],'version':1,'quote':details[0]['text']}]}])
    extract(sql, add_rounds(sql, 7, 10), [])
    deliver_latest(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'],
                                  prose='I started school around 1964. I carried a blue bag.')['status'] == 'proposed'
    after = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert after['preview'] == before['preview'] and after['sections'] == before['sections']
    assert after['covered_round'] == 5 and after['revision'] == 1 and after['proposal_pending']
    proposal = rpc(sql, 'read_user_memoir_proposal', "'project', 'en-AU'")
    assert proposal['base_revision'] == 1 and 'blue bag' in proposal['preview']['text']
    stale = rpc(sql, 'protect_user_memoir_draft', "'project', 'en-AU', 0, false", check=False)
    assert stale.returncode != 0


@pytest.mark.parametrize('language,text,expression',[
    ('en-AU','I was born in 1952. At age twelve I started school.','At age twelve'),
    ('zh-CN','我1952年出生，十二岁开始上学。','十二岁'),
])
def test_supported_age_estimates_retain_original_language_expression_and_birth_basis(sql,language,text,expression):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}',{literal(text)},'narrator_transcript','{language}'")
    ref={'source_id':source['id'],'version':1,'quote':text}
    event=extract(sql,[source],[{'kind':'event','title':'Started school','source_refs':[ref],
        'temporal':{'expression':expression,'precision':'age','year_start':1964,'year_end':1964,'basis':[ref]}}])['events'][0]
    assert event['temporal']['expression']==expression and event['temporal']['precision']=='age'
    assert event['temporal']['year_start']==1964 and event['temporal']['basis']==[ref]
    assert rpc(sql,'read_user_memory_events',"'project'")['sources'][0]['language']==language


def test_saved_legacy_composer_cache_is_imported_with_stable_event_and_section_references(sql,tmp_path,monkeypatch):
    import sqlite3
    from apps.api.private_draft_jobs import PrivateDraftJobs
    from memoir_postgres_workflow import PostgresRest
    sources,lanes=five_rounds(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    rpc(sql,'retry_user_memoir_lane',"'project','composer'")
    job=service_rpc(sql,'claim_memoir_lane',f"'{lanes['composer_lane_id']}',300")
    old_id=job['events'][0]['id']
    legacy=json.loads(json.dumps(job['previous']).replace(old_id,'legacy-composer-school'))
    rounds=PostgresRest(sql,OWNER).storage().private_draft_rounds('project')
    for source in sources:
        memory_id=next(r['memory_id'] for r in rounds if r['turn_id']==source['client_turn_id'])
        legacy=json.loads(json.dumps(legacy).replace(source['id'],memory_id))
    path=tmp_path/'old-private-drafts.sqlite'
    PrivateDraftJobs(path)  # Existing store schema; fixture holds a prior validated bundle.
    with sqlite3.connect(path) as db:
        db.execute('insert into private_draft_projects(user_id,project_id,locale,source_key,payload,revision,completed_milestone,draft) values(?,?,?,?,?,?,?,?)',
                   (OWNER,'project','en-AU','legacy','{}',1,5,json.dumps(legacy)))
    sql('truncate public.user_memory_event cascade; truncate public.user_memoir_manuscript,public.user_memoir_section_revision;')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path))
    client=story_client(sql)
    saved=client.get('/v1/story/private-draft?project_id=project',headers={'Authorization':'Bearer synthetic-author'})
    assert saved.status_code==200 and saved.json()['preview']['text']=='I started school around 1964.'
    assert saved.json()['covered_round']==5 and saved.json()['revision']==1
    events=rpc(sql,'read_user_memory_events',"'project'")['events']
    assert events[0]['id']=='legacy-composer-school'
    assert saved.json()['sections'][0]['event_ids']==['legacy-composer-school']
    assert saved.json()['sections'][0]['source_refs'][0]['source_id']==sources[0]['id']
    assert client.get('/v1/story/private-draft?project_id=project',headers={'Authorization':'Bearer synthetic-author'}).json()==saved.json()
