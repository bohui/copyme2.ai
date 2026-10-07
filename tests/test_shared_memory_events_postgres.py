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
    for path in sorted((ROOT / 'supabase/migrations').glob('*.sql')):
        if path.name < '202610040001_shared_memory_events.sql':
            continue
        private_database(path.read_text())
    return private_database


@pytest.fixture
def sql(event_database):
    event_database('truncate public.user_memoir_project cascade;')
    event_database('truncate public.user_memory, public.user_recall_usage, '
                   'public.user_agent_session, public.user_agent_turn_lease, public.user_private_draft_outbox cascade;')
    event_database('truncate public.user_profile, public.user_family_context, public.guest_conversation_transfer, '
                   'public.user_conversation_attachment cascade;')
    event_database('update auth.users set is_anonymous=false;')
    return event_database


def rpc(sql, name, arguments, *, owner=OWNER, check=True):
    result = sql(as_user(f"select coalesce(to_jsonb(public.{name}({arguments})),'null'::jsonb);", owner), check=check)
    return json.loads(result.stdout.splitlines()[-1]) if check else result


def literal(value):
    return "'" + (json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value).replace("'", "''") + "'"


def extract(sql, sources, events):
    manifest = [{'id': s['id'], 'version': s['version']} for s in sources]
    return rpc(sql, 'apply_user_memory_events', f"'project', {literal(manifest)}::jsonb, {literal(events)}::jsonb")


@pytest.mark.parametrize('dependency', ['birth_basis', 'stage_evidence', 'relation'])
@pytest.mark.parametrize('action', ['edit', 'withdraw'])
def test_changing_placement_or_relation_evidence_reconciles_the_dependent_event(sql, dependency, action):
    from apps.api.memory_events import validate_extraction
    evidence = {'birth_basis':'I was born in 1950.', 'stage_evidence':'I was an adolescent then.',
                'relation':'School preceded my move.'}[dependency]
    basis = rpc(sql, 'accept_user_narrator_source', f"'project','{TURN}',{literal(evidence)}")
    original = rpc(sql, 'accept_user_narrator_source', "'project','00000000-0000-4000-8000-000000000002','At age 6 I started school.'")
    ref = {'source_id':original['id'],'version':1,'quote':original['text']}
    basis_ref = {'source_id':basis['id'],'version':1,'quote':evidence}
    proposal = {'kind':'event','title':'Started school','source_refs':[ref]}
    saved_events = []
    if dependency == 'birth_basis':
        proposal['temporal'] = {'expression':'age 6','precision':'age','year_start':1956,'year_end':1956,'basis':[basis_ref, ref]}
    elif dependency == 'stage_evidence':
        proposal.update(life_stage='adolescence',stage_evidence=[basis_ref])
    else:
        target = rpc(sql, 'accept_user_narrator_source', "'project','00000000-0000-4000-8000-000000000003','I moved to Sydney.'")
        saved_events = extract(sql, [target], [{'kind':'event','title':'Moved','source_refs':[
            {'source_id':target['id'],'version':1,'quote':target['text']}]}])['events']
        proposal['relations'] = [{'kind':'before','event_id':saved_events[0]['id'],'source_refs':[basis_ref]}]
    approved = validate_extraction({'events':[proposal]}, [basis, original], saved_events)
    before = next(event for event in extract(sql, [basis, original], approved)['events'] if event['title']=='Started school')
    replacement = literal('My corrected statement no longer establishes that fact.') if action == 'edit' else 'null'
    rpc(sql, 'change_user_narrator_source', f"'project','{basis['id']}',1,'{action}',{replacement}")
    view = rpc(sql, 'read_user_memory_events', "'project'")
    after = next(event for event in view['events'] if event['id']==before['id'])
    assert after['status'] == 'unresolved' and after['revision'] == before['revision']+1
    assert after['temporal'] == {'expression':'unknown','precision':'unknown'}
    assert after['life_stage'] == 'unplaced' and not after.get('relations')
    assert evidence not in json.dumps(after)
    assert {r['source_id'] for r in after['source_refs']} == {original['id']}
    assert view['completed_rounds'] == 0


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('ambiguous', [False, True])
def test_empty_candidates_are_unambiguous_for_new_and_existing_canonical_events(sql, existing, ambiguous):
    first = rpc(sql, 'accept_user_narrator_source', f"'project','{TURN}','I started school.'")
    ref = {'source_id':first['id'],'version':1,'quote':first['text']}
    original = extract(sql, [first], [{'kind':'event','title':'Started school','source_refs':[ref]}])['events'][0]
    second = rpc(sql, 'accept_user_narrator_source', "'project','00000000-0000-4000-8000-000000000002','That school had a blue gate.'")
    proposal = {'kind':'event','title':'School','source_refs':[{'source_id':second['id'],'version':1,'quote':second['text']}],
                'candidate_ids':[original['id']] if ambiguous else []}
    if existing:
        proposal.update(existing_id=original['id'],expected_revision=1)
    manifest = [{'id':second['id'],'version':1}]
    result = rpc(sql, 'apply_user_memory_events', f"'project',{literal(manifest)}::jsonb,{literal([proposal])}::jsonb", check=False)
    if existing and ambiguous:
        assert result.returncode != 0 and 'ambiguous candidates' in result.stderr
        assert rpc(sql, 'read_user_memory_events', "'project'")['events'] == [original]
    else:
        assert result.returncode == 0, result.stderr
        saved = next(event for event in json.loads(result.stdout.splitlines()[-1])['events'] if event['title']=='School')
        assert saved['status'] == ('unresolved' if ambiguous else 'active')
        assert saved['candidate_ids'] == proposal['candidate_ids']
        assert (saved['id']==original['id']) is existing


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


def test_an_acceptance_outbox_failure_rolls_back_original_evidence_and_replay_remains_unique(sql):
    sql("alter table public.user_private_draft_outbox add constraint controlled_reject_input check(change_kind<>'accepted');")
    try:
        result=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','An original requiring durable dispatch.'",check=False)
        assert result.returncode!=0 and 'controlled_reject_input' in result.stderr
        view=rpc(sql,'read_user_memory_events',"'project'")
        assert view['sources']==[] and view['completed_rounds']==0
    finally:
        sql('alter table public.user_private_draft_outbox drop constraint controlled_reject_input;')
    arguments=f"'project','{TURN}','An original requiring durable dispatch.'"
    original=rpc(sql,'accept_user_narrator_source',arguments)
    assert rpc(sql,'accept_user_narrator_source',arguments)==original
    view=rpc(sql,'read_user_memory_events',"'project'")
    assert view['sources']==[original] and view['processing']['pending_inputs']==1
    assert len(service_rpc(sql,'pending_memoir_receipts','100'))==1


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
            'fingerprint': 'synthetic-validated-input', 'content': 'I started school around 1964.',
            'source_refs':[{'source_id':sources[0]['id'],'version':'1','char_start':0,'char_end':len(sources[0]['text'])}]}],
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


@pytest.mark.parametrize('quote,veto,title', [
    ('I bought a house in 1980.', 'Please do not add this event to my timeline.', 'My home'),
    ('我在1980年买了一栋房子。', '请不要把这个事件加入我的时间线。', '我的家'),
])
@pytest.mark.parametrize('oversized_end', [False, True])
def test_saved_draft_keeps_canonical_span_after_a_repeated_vetoed_quote(sql, tmp_path, monkeypatch, quote, veto, title, oversized_end):
    from apps.api.memory_events import validate_extraction
    from test_agent_commit_postgres import OLD

    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    prefix = quote + ' ' + veto + ' '
    original = add_rounds(sql, 1, 1, prefix + quote)[0]
    sources = [original, *add_rounds(sql, 2, 5)]
    ref = {'source_id': original['id'], 'version': 1, 'quote': quote,
           'char_start': len(prefix), 'char_end': 999 if oversized_end else len(original['text'])}
    proposals = validate_extraction({'events': [
        {'kind': 'event', 'title': title, 'source_refs': [ref]}
    ]}, sources, [])
    assert len(proposals) == 1
    event = extract(sql, sources, proposals)['events'][0]
    assert event['source_refs'] == [ref]
    lane = deliver_latest(sql)['composer_lane_id']
    result = run_controlled_composer(sql, tmp_path, monkeypatch, lane, prose=quote,
        control_options={'title': title, 'summary': quote})
    assert result['status'] == 'saved'
    response = story_client(sql).get('/v1/story/private-draft?project_id=project',
        headers={'Authorization': 'Bearer synthetic-author'})
    assert response.status_code == 200
    saved = response.json()
    assert saved['status'] == 'ready' and saved['covered_round'] == 5
    assert saved['preview']['text'] == quote
    durable = rpc(sql, 'read_user_memoir_draft', "'project', 'en-AU'")
    passage = next(section for section in durable['sections'] if 'block' in section)
    assert passage['event_ids'] == [event['id']]
    assert passage['source_refs'] == [{'source_id': original['id'], 'version': '1',
        'char_start': len(prefix), 'char_end': len(original['text'])}]


@pytest.mark.parametrize('failure',['blocking_review','word_ceiling'])
def test_an_unreviewed_or_oversized_canonical_candidate_never_becomes_a_ready_saved_draft(sql,tmp_path,monkeypatch,failure):
    sources,lanes=five_rounds(sql)
    options={'blocking_review':True} if failure=='blocking_review' else {}
    prose='I started school around 1964.' if failure=='blocking_review' else ' '.join(['memory']*7001)
    result=run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],prose=prose,control_options=options)
    assert result['status']=='retry'
    saved=story_client(sql).get('/v1/story/private-draft?project_id=project',headers={'Authorization':'Bearer synthetic-author'}).json()
    assert saved['preview'] is None and saved['revision']==0
    assert rpc(sql,'read_user_memory_events',"'project'")['completed_rounds']==5


def run_controlled_composer(sql, tmp_path, monkeypatch, lane, *, prose='I started school around 1964.', control_options=None, chat_during_preparation=False):
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
    if chat_during_preparation:
        monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'tasks.sqlite'))
    async def scenario():
        async def readiness_connection(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(readiness_connection, '127.0.0.1', 0)
        app = FastAPI()
        provider = CodexWorker(home_root=tmp_path / 'worker-homes',
            base_url=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1',
            command=[sys.executable, str(ROOT / 'tests/fixtures/issue6_controlled_app_server.py'), str(control)])
        if chat_during_preparation:
            chat_control=tmp_path/'chat-provider.json'
            chat_control.write_text(json.dumps({'reply':'Tell me more.'}))
            chat_provider=CodexWorker(home_root=tmp_path/'chat-worker-homes',base_url=provider.base_url,
                command=[sys.executable,str(ROOT/'tests/fixtures/issue6_controlled_app_server.py'),str(chat_control)])
        @app.post('/internal/codex/turn')
        async def turn(payload: WorkerTurnInput):
            if chat_during_preparation and payload.agent_role!='composer':
                return await chat_provider.turn(payload)
            return await provider.turn(payload)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)) as db:
                worker = MemoryEventWorker(MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic-service', client=db),
                    worker_url='http://controlled-worker.invalid', worker_secret='synthetic-worker-secret',
                    worker_transport=httpx.ASGITransport(app=app))
                if not chat_during_preparation:
                    return await worker.execute_lane(lane)
                composition=asyncio.create_task(worker.execute_lane(lane))
                gate=Path(control_options['gate'])
                try:
                    async def held():
                        while not calls.exists() or sum(json.loads(line)['phase']=='prepare_held' for line in calls.read_text().splitlines())<2:
                            await asyncio.sleep(.05)
                    await asyncio.wait_for(held(),15)
                    from apps.api.codex_runtime import CodexRuntime
                    from test_agent_commit_postgres import OLD
                    storage=PostgresRest(sql,OWNER).storage()
                    storage.release_agent_turn_lease(OLD)
                    storage.save_profile({'preferred_language':'en-AU','conversation_language':{'locale':'en-AU','source':'explicit','revision':1}})
                    runtime=CodexRuntime(home_root=tmp_path/'chat-api-homes',worker_url=worker.worker_url,
                        worker_secret=worker.worker_secret,worker_transport=worker.worker_transport)
                    reply=await runtime.turn(storage,'The yellow boat crossed the bay.',project_id='project',client_turn_id='00000000-0000-4000-8000-000000000007')
                    assert reply['reply']=='Tell me more.' and not composition.done()
                    view=rpc(sql,'read_user_memory_events',"'project'")
                    assert view['completed_rounds']==7 and view['processing']['pending_inputs']==1
                finally:
                    gate.unlink(missing_ok=True)
                return await composition
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


def storyline_rounds(sql):
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    originals, proposals = [], []
    for number, text, stage, title in [(1,'I started school in 1960.','childhood','Started school'),
        (2,'I started work in 1975.','young_adulthood','Started work'),
        (3,'I moved to Sydney in 1990.','midlife','Moved')]:
        source = add_rounds(sql, number, number, text)[0]
        originals.append(source)
        ref = {'source_id':source['id'],'version':1,'quote':text}
        proposals.append({'kind':'event','title':title,'life_stage':stage,'stage_evidence':[ref],'source_refs':[ref]})
    originals.extend(add_rounds(sql, 4, 5))
    view = extract(sql, originals, proposals)
    return originals, view['events'], deliver_latest(sql)


def test_genuine_storyline_enrichment_preserves_unrelated_passages_exactly(sql, tmp_path, monkeypatch):
    originals, events, lanes = storyline_rounds(sql)
    prose = {'Started school':'I started school in 1960.', 'Started work':'I started work in 1975.',
             'Moved':'I moved to Sydney in 1990.'}
    options = {'storyline_events':True,'event_prose':{e['id']:prose[e['title']] for e in events}}
    lane = lanes['composer_lane_id']
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane, control_options=options)['status']=='saved'
    before = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert before['preview']['kind']=='sample_storyline' and 'I started work in 1975.' in before['preview']['text']
    school = next(e for e in events if e['title']=='Started school')
    work = next(e for e in events if e['title']=='Started work')
    rpc(sql, 'correct_user_memory_event', f"'project','{school['id']}',1,'{{\"life_stage\":\"adolescence\"}}'::jsonb,'I was an adolescent then.'")
    deliver_latest(sql)
    rewritten = {**prose,'Started school':'As an adolescent, I started school in 1960.','Started work':'In 1975, I began working.'}
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane,
        control_options={'storyline_events':True,'event_prose':{e['id']:rewritten[e['title']] for e in events}})['status']=='saved'
    after = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert after['preview']['kind']=='sample_storyline'
    assert 'I started work in 1975.' in after['preview']['text'] and 'In 1975, I began working.' not in after['preview']['text']
    unchanged = next(section for section in before['sections'] if section['event_ids']==[work['id']])
    assert next(section for section in after['sections'] if section['id']==unchanged['id'])==unchanged


@pytest.mark.parametrize('change', ['repeat_edit', 'withdraw'])
def test_recomposed_storylines_hide_changed_evidence_and_reuse_only_surviving_passages(sql, tmp_path, monkeypatch, change):
    originals, events, lanes = storyline_rounds(sql)
    lane = lanes['composer_lane_id']
    prose = {event['id']:{'Started school':'I started school in 1960.','Started work':'I started work in 1975.',
        'Moved':'I moved to Sydney in 1990.'}[event['title']] for event in events}
    options = {'storyline_events':True,'event_prose':prose}
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane, control_options=options)['status']=='saved'
    before = rpc(sql, 'read_user_memoir_draft', "'project'")
    move = next(e for e in events if e['title']=='Moved')
    work = next(e for e in events if e['title']=='Started work')
    edited = rpc(sql, 'change_user_narrator_source', f"'project','{originals[2]['id']}',1,'edit','I moved to Brisbane in 1990.'")
    assert rpc(sql, 'read_user_memoir_draft', "'project'")['preview'] is None
    changed = next(e for e in rpc(sql, 'read_user_memory_events', "'project'")['events'] if e['id']==move['id'])
    ref = {'source_id':edited['id'],'version':2,'quote':edited['text']}
    extract(sql, [edited], [{'existing_id':move['id'],'expected_revision':changed['revision'],'kind':'event','title':'Moved',
        'life_stage':'midlife','stage_evidence':[ref],'source_refs':[ref]}])
    # Drain both the edit and extraction receipts, as the actual broker does.
    for receipt in service_rpc(sql, 'pending_memoir_receipts', '100'):
        service_rpc(sql, 'queue_memoir_receipt', f"'{receipt}',5")
    options = {'storyline_events':True,'event_prose':{**prose,move['id']:'I moved to Brisbane in 1990.'}}
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane, control_options=options)['status']=='saved'
    recomposed = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert recomposed['preview']['kind']=='sample_storyline' and 'Brisbane' in recomposed['preview']['text']
    rpc(sql, 'retry_user_memoir_lane', "'project','composer'")
    frozen = service_rpc(sql, 'claim_memoir_lane', f"'{lane}',300")
    if change=='repeat_edit':
        rpc(sql, 'change_user_narrator_source', f"'project','{edited['id']}',2,'edit','I moved to Perth in 1990.'")
    else:
        rpc(sql, 'change_user_narrator_source', f"'project','{edited['id']}',2,'withdraw'")
    current = story_client(sql).get('/v1/story/private-draft?project_id=project', headers={'Authorization':'Bearer synthetic-author'})
    assert current.status_code==200 and current.json()['status']=='stale' and current.json()['preview'] is None
    assert 'Brisbane' not in current.text
    assert service_rpc(sql, 'finish_memoir_composer', f"'{lane}',{literal(frozen['token'])},2,{literal(frozen['previous'])}::jsonb")['status']=='stale'
    if change=='withdraw':
        # The obsolete lease is discarded only in this disposable test database.
        sql(f"update public.user_memoir_lane set lease_until=clock_timestamp()-interval '1 second' where id='{lane}';")
        rpc(sql, 'retry_user_memoir_lane', "'project','composer'")
        deliver_latest(sql)
        assert run_controlled_composer(sql, tmp_path, monkeypatch, lane, control_options=options)['status']=='saved'
        surviving = rpc(sql, 'read_user_memoir_draft', "'project'")
        assert surviving['preview']['kind']=='sample_storyline' and 'Brisbane' not in surviving['preview']['text']
        assert all(move['id'] not in section['event_ids'] for section in surviving['sections'])
        immutable = next(section for section in before['sections'] if section['event_ids']==[work['id']])
        assert next(section for section in surviving['sections'] if section['id']==immutable['id'])==immutable


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


def test_repeated_extraction_of_unchanged_event_advances_coverage_without_rewriting(sql, tmp_path, monkeypatch):
    import httpx
    from apps.api.memory_event_worker import MemoirLaneBroker, MemoryEventWorker
    from memoir_postgres_workflow import PostgresRest

    sources, lanes = five_rounds(sql)
    composer = lanes['composer_lane_id']
    assert run_controlled_composer(sql, tmp_path, monkeypatch, composer)['status'] == 'saved'
    client = story_client(sql)
    headers = {'Authorization': 'Bearer synthetic-author'}
    before = client.get('/v1/story/private-draft?project_id=project', headers=headers).json()
    event = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
    add_rounds(sql, 6, 10)
    proposal = {'existing_id': event['id'], 'expected_revision': event['revision'],
                'kind': event['kind'], 'title': event['title'], 'source_refs': event['source_refs']}

    async def process():
        async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)) as db:
            broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic', client=db)
            await broker.drain_once()
            provider = httpx.MockTransport(lambda request: httpx.Response(200, json={
                'reply': json.dumps({'events': [proposal]})}))
            worker = MemoryEventWorker(broker, worker_url='http://controlled-provider.invalid',
                                       worker_secret='synthetic', worker_transport=provider)
            assert (await worker.execute_lane(lanes['timeline_lane_id']))['status'] == 'saved'
    asyncio.run(process())
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert view['events'] == [event]
    assert view['processing'] == {'extracted_through': 10, 'pending_inputs': 0}
    deliver_latest(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, composer,
                                  prose='Unchanged prose must survive.')['status'] == 'saved'
    after = client.get('/v1/story/private-draft?project_id=project', headers=headers).json()
    assert after['covered_round'] == 10 and after['revision'] == before['revision']
    assert after['preview'] == before['preview'] and after['sections'] == before['sections']
    calls = [json.loads(line)['phase'] for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert calls == ['prepare_start', 'prepare_end', 'draft', 'review']


def test_checkpoint_without_personal_events_finishes_collecting_without_retrying(sql, tmp_path, monkeypatch):
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    extract(sql, add_rounds(sql, 1, 5), [])
    lane = deliver_latest(sql)['composer_lane_id']
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane)['status'] == 'saved'
    saved = story_client(sql).get('/v1/story/private-draft?project_id=project',
                                 headers={'Authorization': 'Bearer synthetic-author'}).json()
    assert saved['status'] == 'collecting' and saved['preview'] is None
    assert saved['covered_round'] == 5 and saved['milestone'] == 5
    assert saved['revision'] == 0 and saved['sections'] == []
    assert not saved['updating'] and saved['error'] is None
    assert saved['progress']['composition']['state'] == 'finished'
    assert not (tmp_path / 'calls.jsonl').exists()
    later = add_rounds(sql, 6, 6, 'I started school around 1964.') + add_rounds(sql, 7, 10)
    extract(sql, later, [{'kind': 'event', 'title': 'Started school', 'source_refs': [
        {'source_id': later[0]['id'], 'version': 1, 'quote': later[0]['text']}]}])
    assert deliver_latest(sql)['composer_lane_id'] == lane
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane)['status'] == 'saved'
    ready = story_client(sql).get('/v1/story/private-draft?project_id=project',
                                 headers={'Authorization': 'Bearer synthetic-author'}).json()
    assert ready['status'] == 'ready' and ready['covered_round'] == 10 and ready['revision'] == 1
    assert ready['preview']['text'] == 'I started school around 1964.'


def test_withdrawing_all_event_evidence_settles_without_restoring_prose(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    client = story_client(sql)
    headers = {'Authorization': 'Bearer synthetic-author'}
    before = client.get('/v1/story/private-draft?project_id=project', headers=headers).json()
    rpc(sql, 'change_user_narrator_source', f"'project','{sources[0]['id']}',1,'withdraw',null")
    assert client.get('/v1/story/private-draft?project_id=project', headers=headers).json()['preview'] is None
    deliver_latest(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    after = client.get('/v1/story/private-draft?project_id=project', headers=headers).json()
    assert after['status'] == 'collecting' and after['preview'] is None and after['sections'] == []
    assert after['revision'] == before['revision'] and after['covered_round'] == 5
    assert not after['updating'] and after['error'] is None
    calls = [json.loads(line)['phase'] for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert calls == ['prepare_start', 'prepare_end', 'draft', 'review']


def test_empty_completion_cannot_discard_supported_canonical_prose(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    lane = lanes['composer_lane_id']
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane)['status'] == 'saved'
    before = rpc(sql, 'read_user_memoir_draft', "'project'")
    extract(sql, add_rounds(sql, 6, 10), [])
    deliver_latest(sql)
    job = service_rpc(sql, 'claim_memoir_lane', f"'{lane}',300")
    result = service_rpc(sql, 'finish_memoir_composer',
                         f"'{lane}','{job['token']}',1,'{{\"status\":\"insufficient_context\",\"preview\":null}}'::jsonb")
    assert result['status'] == 'rejected'
    after = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert after['preview'] == before['preview'] and after['sections'] == before['sections']
    assert after['revision'] == before['revision'] and after['covered_round'] == 5


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


@pytest.mark.parametrize('policy_changed', [False, True])
def test_bounded_partition_preparation_reuses_successes_after_provider_failure(sql, tmp_path, monkeypatch, policy_changed):
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
    if policy_changed:
        sql(f"update public.user_memoir_project set policy_epoch=policy_epoch+1 where user_id='{OWNER}' and project_id='project';")
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
    assert starts[events['Started school']] == (2 if policy_changed else 1)
    assert starts[events['Moved to Sydney']] == 2
    saved = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert saved['covered_round'] == 6 and saved['milestone'] == 5
    assert {id for section in saved['sections'] for id in section['event_ids']} == set(events.values())


def test_authenticated_chat_completes_while_independent_partition_preparations_are_held(sql,tmp_path,monkeypatch):
    sources,lanes=five_rounds(sql)
    added=add_rounds(sql,6,6,'I moved to Sydney in 1986.')
    extract(sql,added,[{'kind':'event','title':'Moved to Sydney','source_refs':[{'source_id':added[0]['id'],'version':1,'quote':added[0]['text']}]}])
    deliver_latest(sql)
    monkeypatch.setenv('MEMORY_SPARK_MEMOIR_PREPARATION_CONCURRENCY','2')
    gate=tmp_path/'held-preparations'
    gate.touch()
    result=run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],
        control_options={'hold_phase':'prepare','gate':str(gate)},chat_during_preparation=True)
    assert result['status']=='saved'
    saved=rpc(sql,'read_user_memoir_draft',"'project'")
    assert saved['covered_round']==6 and saved['updating']


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


def test_stale_event_edits_recognize_native_postgrest_conflicts_without_misclassifying_internal_failures(sql, monkeypatch):
    import httpx
    from memoir_postgres_workflow import PostgresRest
    source = rpc(sql, 'accept_user_narrator_source', f"'project','{TURN}','I started school.'")
    event = extract(sql, [source], [{'kind':'event','title':'Started school','source_refs':[
        {'source_id':source['id'],'version':1,'quote':source['text']}]}])['events'][0]
    rpc(sql, 'correct_user_memory_event', f"'project','{event['id']}',1,'{{\"life_stage\":\"childhood\"}}'::jsonb,'I was a child then.'")
    storage = PostgresRest(sql, OWNER).storage()
    with pytest.raises(httpx.HTTPStatusError) as conflict:
        storage.correct_memory_event('project', event['id'], 1, {'life_stage':'adolescence'}, 'I was an adolescent then.')
    assert conflict.value.response.status_code==500 and conflict.value.response.json()['code']=='40001'
    monkeypatch.setenv('STRIPE_PRICE_FAMILY','synthetic-price')
    entitlement = {'status':'paid','plan_key':'family_memoir_v1','family_tree':True,'timeline':True,'stripe_price_id':'synthetic-price'}
    client = story_client(sql, entitlement=entitlement)
    endpoint = f'/v1/story/events/project/{event["id"]}'
    payload = {'expected_revision':1,'patch':{'life_stage':'adolescence'},'statement':'I was an adolescent then.'}
    response = client.patch(endpoint, headers={'Authorization':'Bearer synthetic-author'}, json=payload)
    assert response.status_code==409 and response.headers['X-Error-Code']=='EVENT_REVISION_CONFLICT'
    assert rpc(sql, 'read_user_memory_events', "'project'")['events'][0]['life_stage']=='childhood'
    sql("""create function public.controlled_correction_failure() returns trigger language plpgsql as $$
      begin raise exception 'synthetic internal database failure' using errcode='XX000'; end $$;
      create trigger controlled_correction_failure before update on public.user_memory_event
        for each row execute function public.controlled_correction_failure();""")
    try:
        response = client.patch(endpoint, headers={'Authorization':'Bearer synthetic-author'}, json={**payload,'expected_revision':2})
        assert response.status_code==422 and response.headers['X-Error-Code']=='EVENT_CORRECTION_INVALID'
        assert 'synthetic internal' not in response.text
    finally:
        sql('drop trigger controlled_correction_failure on public.user_memory_event; drop function public.controlled_correction_failure();')


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
                     'fingerprint': 'frozen-synthetic-input', 'content': 'I started school around 1964.',
                     'source_refs':[{'source_id':sources[0]['id'],'version':'1','char_start':0,'char_end':len(sources[0]['text'])}]}]}
    assert service_rpc(sql, 'finish_memoir_composer', f"'{lane}', {literal(active['token'])}, 0, {literal(bundle)}::jsonb")['status'] == 'saved'
    saved = rpc(sql, 'read_user_memoir_draft', "'project', 'en-AU'")
    assert saved['covered_round'] == saved['milestone'] == 5 and saved['preview']['text'] == bundle['preview']['text']
    assert rpc(sql, 'read_user_memoir_draft', "'project', 'zh-CN'")['preview'] is None
    catchup = service_rpc(sql, 'claim_memoir_lane', f"'{lane}', 300")
    assert catchup['coverage_round'] == catchup['milestone'] == 20 and catchup['locale'] == 'zh-CN'


@pytest.mark.parametrize('trace_enabled', [False, True])
def test_story_workspace_only_dispatches_relationship_tree_and_never_duplicate_timeline(sql, tmp_path, monkeypatch, trace_enabled):
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
        calls.append({'role': payload.agent_role, 'focus': payload.extraction_focus, 'family': payload.family_enabled,
                      'canonical':getattr(payload,'canonical_events',False)})
        person={'id':'father','name':'June','family_title':'father'}
        if '1950' in payload.text:
            person.update(existing_id=storage.family_context('project')['people'][0]['id'],birth_date_expression='1950')
        marker = '[[MEMORY_SPARK_FAMILY_TREE]]'+json.dumps({'people':[person],'relationships':[]})+'[[/MEMORY_SPARK_FAMILY_TREE]]'
        control.write_text(json.dumps({'reply': marker if payload.extraction_focus == 'family_tree' else 'Tell me more.'}))
        return await provider.turn(payload)
    runtime = CodexRuntime(home_root=tmp_path / 'api-homes', worker_url='http://controlled-worker.invalid',
        worker_secret='synthetic-worker-secret', worker_transport=httpx.ASGITransport(app=app))
    options = {'include_trajectory':trace_enabled, 'source_kind':'narrator_transcript' if trace_enabled else 'narrator_chat'}
    async def scenario():
        first = await runtime.turn(storage, 'I started school around 1964.', project_id='project', client_turn_id=TURN, **options)
        if trace_enabled:
            assert first['trajectory']['final']['status'] == 'completed'
        assert not any(c['family'] or c['focus'] == 'author_timeline' for c in calls if c['role'] == 'workspace')
        assert all(c['canonical'] for c in calls if c['role']=='workspace')
        assert storage.family_context('project') is None
        calls.clear()
        await runtime.turn(storage, 'My father June taught me gardening.', project_id='project', client_turn_id='00000000-0000-4000-8000-000000000002', **options)
        assert sum(c['focus'] == 'family_tree' for c in calls) == 1
        document = storage.family_context('project')
        assert document and document['people'][0]['name'] == 'June'
        assert document['timeline'] == []
        person_id=document['people'][0]['id']
        calls.clear()
        await runtime.turn(storage,'Actually, June was born in 1950.',project_id='project',client_turn_id='00000000-0000-4000-8000-000000000003', **options)
        assert sum(c['focus']=='family_tree' for c in calls)==1
        corrected=storage.family_context('project')
        assert corrected['people'][0]['id']==person_id and corrected['people'][0]['birth_date_expression']=='1950'
        calls.clear()
        await runtime.turn(storage,'The yellow boat crossed the bay.',project_id='project',client_turn_id='00000000-0000-4000-8000-000000000004', **options)
        assert not any(c['focus']=='family_tree' for c in calls)
        assert storage.family_context('project')==corrected
    asyncio.run(scenario())
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert view['processing']['pending_inputs'] == view['completed_rounds'] == 4
    assert {source['kind'] for source in view['sources']} == {options['source_kind']}


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


@pytest.mark.parametrize('accept',['application/json','application/x-ndjson'])
def test_authenticated_voice_turn_retains_original_chinese_and_failed_reply_does_not_count(sql, tmp_path, monkeypatch, accept):
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
        response = client.post('/v1/agent/turn', headers={'Authorization':'Bearer synthetic-author','Accept':accept},
            json={'text':'我十二岁那年开始上学。','project_id':'project','client_turn_id':TURN,
                  'source_kind':'narrator_transcript','language':'en-AU'})
    if accept=='application/json':
        assert response.status_code == 502
    else:
        assert response.status_code == 200 and any(json.loads(line)['type']=='error' for line in response.text.splitlines())
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert view['sources'][0]['kind'] == 'narrator_transcript'
    assert view['sources'][0]['language'] == 'zh-CN' and view['sources'][0]['text'] == '我十二岁那年开始上学。'
    assert view['completed_rounds'] == 0


def test_streamed_server_greeting_is_delivered_without_narrator_evidence_or_round_usage(sql,tmp_path,monkeypatch):
    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    storage=PostgresRest(sql,OWNER).storage()
    storage.save_profile({'preferred_language':'en-AU','conversation_language':{'locale':'en-AU','source':'explicit','revision':1}})
    provider=httpx.MockTransport(lambda request: httpx.Response(200,
        headers={'Content-Type':'application/x-ndjson'},content=json.dumps({'type':'result','data':{
            'reply':'Share whatever comes to mind.','thread_id':'synthetic-thread','source_paths':[]}})+'\n'))
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda authorization: PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'greeting-homes',
        worker_url='http://controlled-model.invalid',worker_secret='synthetic-worker-secret',worker_transport=provider))
    app=FastAPI()
    app.include_router(agent_routes.router)
    with TestClient(app) as client:
        response=client.post('/v1/agent/greeting',headers={'Authorization':'Bearer synthetic-author','Accept':'application/x-ndjson'},
            json={'action':'begin','project_id':'project'})
    assert response.status_code==200
    messages=[json.loads(line) for line in response.text.splitlines()]
    assert not any(message['type']=='error' for message in messages)
    assert any(message['type']=='result' and message['data']['reply']=='Share whatever comes to mind.' for message in messages)
    view=rpc(sql,'read_user_memory_events',"'project'")
    assert view['sources']==[] and view['completed_rounds']==0


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


@pytest.mark.parametrize('namespace', ['timeline', 'composer'])
def test_legacy_period_import_preserves_both_supported_range_endpoints_and_original_evidence(sql, namespace):
    original = rpc(sql, 'accept_user_narrator_source', f"'project','{TURN}','I worked as a carpenter from 1986 to 2005.'")
    item = {'id':'legacy-carpentry','kind':'period','title':'Worked as a carpenter','start_expression':'1986','end_expression':'2005',
            'precision':'range','date':{'original_expression':'from 1986 to 2005','precision':'range'},
            'visibility':'private','include_in_print':False,
            'source_refs':[{'source_id':original['id'],'quote':original['text']} ]}
    if namespace == 'timeline':
        sql(f"insert into public.user_family_context(user_id,project_id,document) values ('{OWNER}','project',{literal({'people':[],'timeline':[item]})}::jsonb);")
        migrate = lambda:rpc(sql, 'migrate_user_memory_events', "'project'")
    else:
        migrate = lambda:rpc(sql, 'migrate_user_memoir_index', f"'project',{literal([item])}::jsonb")
    migrate()
    before = rpc(sql, 'read_user_memory_events', "'project'")
    event = before['events'][0]
    assert event['id']=='legacy-carpentry' and event['kind']=='period' and event['status']=='active'
    assert event['temporal']['year_start']==1986 and event['temporal']['year_end']==2005
    assert event['temporal']['expression']=='from 1986 to 2005' and event['temporal']['precision']=='range'
    assert event['temporal']['legacy_start_expression']=='1986' and event['temporal']['legacy_end_expression']=='2005'
    assert event['temporal']['basis']==event['source_refs']
    assert event['source_refs'][0]['quote']==original['text']
    assert event['visibility']=='private' and event['include_in_print'] is False
    migrate()
    assert rpc(sql, 'read_user_memory_events', "'project'")==before


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
    assert after['updating'] is False
    proposal = rpc(sql, 'read_user_memoir_proposal', "'project', 'en-AU'")
    assert proposal['base_revision'] == 1 and 'blue bag' in proposal['preview']['text']
    stale = rpc(sql, 'protect_user_memoir_draft', "'project', 'en-AU', 0, false", check=False)
    assert stale.returncode != 0


@pytest.mark.parametrize('change', ['edit', 'withdraw', 'tag', 'unlink'])
def test_proposal_only_evidence_changes_remove_the_proposal_and_fence_older_workers(sql, tmp_path, monkeypatch, change):
    sources, lanes = five_rounds(sql)
    lane = lanes['composer_lane_id']
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane)['status']=='saved'
    before = rpc(sql, 'read_user_memoir_draft', "'project'")
    rpc(sql, 'protect_user_memoir_draft', "'project','en-AU',1,true")
    blue = add_rounds(sql, 6, 6, 'I carried a blue chest to work in 1975.')[0]
    added = extract(sql, [blue], [{'kind':'event','title':'Started work','source_refs':[
        {'source_id':blue['id'],'version':1,'quote':blue['text']}]}])
    event = next(e for e in added['events'] if e['title']=='Started work')
    extract(sql, add_rounds(sql, 7, 10), [])
    deliver_latest(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lane, control_options={'event_prose':{
        'Started school':'I started school around 1964.', 'Started work':'I carried a blue chest to work in 1975.'}})['status']=='proposed'
    assert 'blue chest' in rpc(sql, 'read_user_memoir_proposal', "'project','en-AU'")['preview']['text']
    rpc(sql, 'retry_user_memoir_lane', "'project','composer'")
    older = service_rpc(sql, 'claim_memoir_lane', f"'{lane}',300")
    if change in ('edit','withdraw'):
        replacement = "'I started work in 1975 without that chest.'" if change=='edit' else 'null'
        rpc(sql, 'change_user_narrator_source', f"'project','{blue['id']}',1,'{change}',{replacement}")
    elif change == 'tag':
        rpc(sql, 'correct_user_memory_event', f"'project','{event['id']}',1,'{{\"life_stage\":\"adolescence\"}}'::jsonb,'I was an adolescent then.'")
    else:
        rpc(sql, 'unlink_user_memory_event_source', f"'project','{event['id']}',1,'{blue['id']}','That chest was not part of this event.'")
    assert rpc(sql, 'read_user_memoir_proposal', "'project','en-AU'") is None
    after = rpc(sql, 'read_user_memoir_draft', "'project'")
    assert after['status']=='ready' and after['preview']==before['preview'] and after['sections']==before['sections']
    assert not after['proposal_pending'] and after['covered_round']==5 and after['revision']==1
    assert service_rpc(sql, 'finish_memoir_composer', f"'{lane}',{literal(older['token'])},1,{literal(older['previous'])}::jsonb")['status']=='stale'


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


@pytest.mark.parametrize('cache_store',['private_jobs','memory_preview'])
@pytest.mark.parametrize('form', ['chapter', 'storyline'])
def test_saved_legacy_composer_cache_is_imported_with_stable_event_and_section_references(sql,tmp_path,monkeypatch,cache_store,form):
    import sqlite3
    from apps.api.private_draft_jobs import PrivateDraftJobs
    from memoir_postgres_workflow import PostgresRest
    if form=='storyline':
        sources,initial_events,lanes=storyline_rounds(sql)
        options={'storyline_events':True,'event_prose':{e['id']:{'Started school':'I started school in 1960.',
            'Started work':'I started work in 1975.','Moved':'I moved to Sydney in 1990.'}[e['title']] for e in initial_events}}
        expected_text='I started school in 1960.\n\nI started work in 1975.\n\nI moved to Sydney in 1990.'
    else:
        sources,lanes=five_rounds(sql)
        options=None
        expected_text='I started school around 1964.'
    coverage=20 if cache_store=='memory_preview' else 5
    if coverage==20:
        extract(sql,add_rounds(sql,6,20),[])
        deliver_latest(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],control_options=options)['status']=='saved'
    rpc(sql,'retry_user_memoir_lane',"'project','composer'")
    job=service_rpc(sql,'claim_memoir_lane',f"'{lanes['composer_lane_id']}',300")
    old_id=job['events'][0]['id']
    legacy=json.loads(json.dumps(job['previous']).replace(old_id,'legacy-composer-school'))
    rounds=PostgresRest(sql,OWNER).storage().private_draft_rounds('project')
    for source in job['sources']:
        memory_id=next(r['memory_id'] for r in rounds if r['turn_id']==source['client_turn_id'])
        legacy=json.loads(json.dumps(legacy).replace(source['id'],memory_id))
    path=tmp_path/'old-private-drafts.sqlite'
    if cache_store=='private_jobs':
        PrivateDraftJobs(path)  # Existing store schema; fixture holds a prior validated bundle.
        with sqlite3.connect(path) as db:
            db.execute('insert into private_draft_projects(user_id,project_id,locale,source_key,payload,revision,completed_milestone,draft) values(?,?,?,?,?,?,?,?)',
                       (OWNER,'project','en-AU','legacy','{}',1,coverage,json.dumps(legacy)))
    else:
        legacy.update(type='memoir_preview',snapshot_key='legacy-snapshot')
        sql(f"insert into public.user_memory(user_id,kind,content,source_paths) values('{OWNER}','memoir',{literal(legacy)},array['memoir-preview:project']);")
    sql('truncate public.user_memory_event cascade; truncate public.user_memoir_manuscript,public.user_memoir_section_revision,public.user_memoir_milestone;')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path))
    client=story_client(sql)
    saved=client.get('/v1/story/private-draft?project_id=project',headers={'Authorization':'Bearer synthetic-author'})
    assert saved.status_code==200 and saved.json()['preview']['text']==expected_text
    assert saved.json()['preview']['kind']==('sample_storyline' if form=='storyline' else 'sample_chapter')
    assert saved.json()['covered_round']==coverage and saved.json()['revision']==1
    assert saved.json()['milestones']==[{'milestone':coverage,'state':'completed','covered_round':coverage,'manuscript_revision':1}]
    events=rpc(sql,'read_user_memory_events',"'project'")['events']
    assert events[0]['id']=='legacy-composer-school'
    assert saved.json()['sections'][0]['event_ids']==['legacy-composer-school']
    assert saved.json()['sections'][0]['source_refs'][0]['source_id']==sources[0]['id']
    assert client.get('/v1/story/private-draft?project_id=project',headers={'Authorization':'Bearer synthetic-author'}).json()==saved.json()


def test_editing_the_only_original_preserves_event_identity_for_reconciliation(sql):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I started school around 1964.'")
    event=extract(sql,[source],[{'kind':'event','title':'Started school',
        'source_refs':[{'source_id':source['id'],'version':1,'quote':source['text']}]}])['events'][0]
    edited=rpc(sql,'change_user_narrator_source',f"'project','{source['id']}',1,'edit','I started school around 1966.'")
    pending=rpc(sql,'read_user_memory_events',"'project'")['events']
    assert len(pending)==1 and pending[0]['id']==event['id'] and pending[0]['status']=='unresolved'
    assert pending[0]['reconciliation_source_ids']==[source['id']]
    reconciled=extract(sql,[edited],[{'existing_id':event['id'],'expected_revision':2,'kind':'event','title':'Started school',
        'source_refs':[{'source_id':source['id'],'version':2,'quote':edited['text']}]}])['events'][0]
    assert reconciled['id']==event['id'] and reconciled['status']=='active'
    assert rpc(sql,'read_user_memory_events',"'project'")['completed_rounds']==0


def test_withdrawal_removes_original_from_conversation_and_source_history_without_recounting(sql):
    from memoir_postgres_workflow import PostgresRest
    sources,_=five_rounds(sql)
    private='I started school around 1964.'
    assert any(private in r['content'] for r in PostgresRest(sql,OWNER).storage().memories())
    rpc(sql,'change_user_narrator_source',f"'project','{sources[0]['id']}',1,'withdraw'")
    assert all(private not in r['content'] for r in PostgresRest(sql,OWNER).storage().memories())
    assert rpc(sql,'read_user_memory_events',"'project'")['completed_rounds']==5
    assert private not in sql(as_user('select to_jsonb(v) from public.user_narrator_source_version v;')).stdout


def test_withdrawal_removes_restricted_legacy_draft_and_timeline_bytes_within_its_project(sql):
    from memoir_postgres_workflow import PostgresRest
    sources,_=five_rounds(sql)
    private=sources[0]['text']
    alias='legacy-original-school'
    sql(f"insert into public.user_narrator_source_alias values('{OWNER}','project','{alias}','{sources[0]['id']}');")
    timeline={'people':[], 'timeline':[
        {'id':'old-school','title':private,'source_refs':[{'source_id':alias,'quote':private}]},
        {'id':'unrelated','title':'Other permitted memory','source_refs':[]}]}
    sql(f"insert into public.user_family_context(user_id,project_id,document) values('{OWNER}','project',{literal(timeline)}::jsonb);")
    sql(f"insert into public.user_memory(user_id,kind,content,source_paths) values "
        f"('{OWNER}','memoir',{literal(private)},array['memoir-preview:project']),"
        f"('{OWNER}','memoir','Other project remains private.',array['memoir-preview:other-project']),"
        f"('{OTHER}','memoir','Other owner remains private.',array['memoir-preview:project']);")
    storage=PostgresRest(sql,OWNER).storage()
    rpc(sql,'change_user_narrator_source',f"'project','{sources[0]['id']}',1,'withdraw'")
    assert private not in str(storage.memories())+str(storage.family_context('project'))
    assert storage.family_context('project')['timeline'][0]['id']=='unrelated'
    assert any('Other project remains private.' in r['content'] for r in storage.memories())
    assert any('Other owner remains private.' in r['content'] for r in PostgresRest(sql,OTHER).storage().memories())


@pytest.mark.parametrize('action',['edit','delete'])
def test_existing_conversation_memory_edit_and_delete_update_canonical_evidence(sql,action):
    from memoir_postgres_workflow import PostgresRest
    sources,_=five_rounds(sql)
    memory=next(r for r in PostgresRest(sql,OWNER).storage().memories() if r['client_turn_id']==sources[0]['client_turn_id'])
    query=(f"update public.user_memory set content=E'Storyteller: I started school around 1966.\\nMemory Spark: A reply' where id='{memory['id']}';"
           if action=='edit' else f"delete from public.user_memory where id='{memory['id']}';")
    sql(as_user(query))
    view=rpc(sql,'read_user_memory_events',"'project'")
    source=next(s for s in view['sources'] if s['id']==sources[0]['id'])
    assert source['version']==2
    assert source['text']==('I started school around 1966.' if action=='edit' else '[withdrawn]')
    assert source['status']==('active' if action=='edit' else 'withdrawn')
    assert view['completed_rounds']==5
    assert len(view['events'])==(1 if action=='edit' else 0)


def test_source_edit_preserves_a_surviving_explicit_user_correction(sql):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I started school around 1964.'")
    event=extract(sql,[source],[{'kind':'event','title':'Started school',
        'source_refs':[{'source_id':source['id'],'version':1,'quote':source['text']}]}])['events'][0]
    patch={'life_stage':'adolescence','temporal':{'expression':'1966','precision':'year','year_start':1966,'year_end':1966}}
    correction=rpc(sql,'correct_user_memory_event',f"'project','{event['id']}',1,{literal(patch)}::jsonb,'Actually, I was an adolescent in 1966.'")
    edited=rpc(sql,'change_user_narrator_source',f"'project','{source['id']}',1,'edit','I started school with a blue bag.'")
    pending=rpc(sql,'read_user_memory_events',"'project'")['events'][0]
    assert pending['user_overrides']==correction['user_overrides'] and pending['life_stage']=='adolescence'
    assert pending['temporal']==correction['temporal']
    reextract=extract(sql,[edited],[{'existing_id':event['id'],'expected_revision':3,'kind':'event','title':'Started school',
        'source_refs':[{'source_id':edited['id'],'version':2,'quote':edited['text']}]}])['events'][0]
    assert reextract['temporal']==correction['temporal'] and reextract['life_stage']=='adolescence'


def test_removed_event_source_link_cannot_be_silently_restored_by_extraction(sql):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I started school around 1964.'")
    original={'source_id':source['id'],'version':1,'quote':source['text']}
    event=extract(sql,[source],[{'kind':'event','title':'Started school','source_refs':[original]}])['events'][0]
    later=rpc(sql,'accept_user_narrator_source',"'project','00000000-0000-4000-8000-000000000002','At that school I carried a blue bag.'")
    remaining={'source_id':later['id'],'version':1,'quote':later['text']}
    extract(sql,[later],[{'existing_id':event['id'],'expected_revision':1,'kind':'event','title':'Started school','source_refs':[remaining]}])
    removed=rpc(sql,'unlink_user_memory_event_source',f"'project','{event['id']}',2,'{source['id']}','That source belongs to another school visit.'")
    assert removed['id']==event['id'] and removed['revision']==3 and removed['status']=='unresolved'
    assert removed['source_refs']==[remaining]
    bad={'existing_id':event['id'],'expected_revision':3,'kind':'event','title':'Started school','source_refs':[original,remaining]}
    attempt=rpc(sql,'apply_user_memory_events',f"'project',{literal([{'id':later['id'],'version':1}])}::jsonb,{literal([bad])}::jsonb",check=False)
    assert attempt.returncode!=0 and 'removed source link' in attempt.stderr
    saved=extract(sql,[later],[{**bad,'source_refs':[remaining]}])['events'][0]
    assert saved['status']=='active' and saved['source_refs']==[remaining]
    assert rpc(sql,'read_user_memory_events',"'project'")['completed_rounds']==0


def test_removing_an_original_link_preserves_an_explicit_correction_from_surviving_evidence(sql):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I started school around 1964.'")
    event=extract(sql,[source],[{'kind':'event','title':'Started school',
        'source_refs':[{'source_id':source['id'],'version':1,'quote':source['text']}]}])['events'][0]
    patch={'life_stage':'adolescence','temporal':{'expression':'1966','precision':'year','year_start':1966,'year_end':1966}}
    corrected=rpc(sql,'correct_user_memory_event',f"'project','{event['id']}',1,{literal(patch)}::jsonb,'Actually, I was an adolescent in 1966.'")
    removed=rpc(sql,'unlink_user_memory_event_source',f"'project','{event['id']}',2,'{source['id']}','Those original words referred to another school visit.'")
    assert removed['id']==event['id'] and removed['revision']==3
    assert removed['user_overrides']==corrected['user_overrides']
    assert removed['life_stage']=='adolescence' and removed['temporal']==corrected['temporal']
    assert all(ref['source_id']!=source['id'] for ref in removed['source_refs'])


def test_completed_checkpoint_is_updating_before_its_receipt_is_delivered(sql):
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sources = add_rounds(sql, 1, 1, 'I started school around 1964.')
    sources += add_rounds(sql, 2, 5)
    extract(sql, sources, [{'kind':'event','title':'Started school','source_refs':[
        {'source_id':sources[0]['id'],'version':1,'quote':sources[0]['text']}]}])
    with story_client(sql) as client:
        response = client.get('/v1/story/private-draft?project_id=project',
                              headers={'Authorization':'Bearer synthetic-author'})
    assert response.status_code == 200
    draft = response.json()
    assert draft['status'] == 'collecting' and draft['covered_round'] == 0
    assert draft['updating'] is True
    assert draft['progress']['composition']['state'] == 'pending'


def test_accepted_original_is_updating_before_timeline_receipt_delivery(sql):
    rpc(sql, 'accept_user_narrator_source', f"'project','{TURN}','I started school around 1964.'")
    with story_client(sql) as client:
        response = client.get('/v1/story/private-draft?project_id=project',
                              headers={'Authorization':'Bearer synthetic-author'})
    assert response.status_code == 200
    draft = response.json()
    assert draft['status'] == 'collecting' and draft['covered_round'] == 0
    assert draft['updating'] is True
    assert draft['progress']['extraction']['state'] == 'pending'
    assert draft['progress']['extraction']['pending_inputs'] == 1
    assert draft['progress']['composition']['state'] == 'finished'


def test_event_correction_is_updating_before_its_receipt_is_delivered(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    event = rpc(sql, 'read_user_memory_events', "'project'")['events'][0]
    rpc(sql, 'correct_user_memory_event', f"'project','{event['id']}',1,'{{\"life_stage\":\"childhood\"}}'::jsonb,'I was a child then.'")
    with story_client(sql) as client:
        response = client.get('/v1/story/private-draft?project_id=project',
                              headers={'Authorization':'Bearer synthetic-author'})
    assert response.status_code == 200
    draft = response.json()
    assert draft['status'] == 'stale' and draft['preview'] is None
    assert draft['updating'] is True
    assert draft['progress']['composition']['state'] == 'pending'


@pytest.mark.parametrize('cadence,updating,target', [(3, True, 3), (7, False, 0)])
def test_undelivered_checkpoint_uses_configured_cadence_without_changing_recall_allowance(sql, monkeypatch, cadence, updating, target):
    from test_agent_commit_postgres import OLD
    monkeypatch.setenv('MEMORY_SPARK_PRIVATE_DRAFT_CADENCE', str(cadence))
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sources = add_rounds(sql, 1, 5)
    extract(sql, sources, [])
    with story_client(sql) as client:
        draft = client.get('/v1/story/private-draft?project_id=project',
                           headers={'Authorization':'Bearer synthetic-author'}).json()
        access = client.get('/v1/story/state', headers={'Authorization':'Bearer synthetic-author'}).json()['recall_status']
    assert draft['updating'] is updating
    assert draft['progress']['composition']['target_milestone'] == target
    view = rpc(sql, 'read_user_memory_events', "'project'")
    assert view['completed_rounds'] == 5
    assert access['rounds_completed'] == 5 and access['free_rounds'] == 20


def test_old_receipts_do_not_keep_a_saved_checkpoint_or_other_scopes_updating(sql, tmp_path, monkeypatch):
    sources, lanes = five_rounds(sql)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes['composer_lane_id'])['status'] == 'saved'
    assert service_rpc(sql, 'pending_memoir_receipts', '100')
    with story_client(sql) as client:
        saved = client.get('/v1/story/private-draft?project_id=project',
                           headers={'Authorization':'Bearer synthetic-author'}).json()
        other_project = client.get('/v1/story/private-draft?project_id=other-project',
                                   headers={'Authorization':'Bearer synthetic-author'}).json()
    assert saved['status'] == 'ready' and saved['covered_round'] == 5 and saved['updating'] is False
    assert other_project['updating'] is False and other_project['preview'] is None
    other_owner = rpc(sql, 'read_user_memoir_draft', "'project'", owner=OTHER)
    assert other_owner['updating'] is False and other_owner['preview'] is None


def test_terminal_extraction_failure_stops_draft_polling_until_the_author_retries(sql):
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    add_rounds(sql, 1, 5, 'I started school around 1964.')
    lanes = deliver_latest(sql)
    job = service_rpc(sql, 'claim_memoir_lane', f"'{lanes['timeline_lane_id']}',300")
    assert service_rpc(sql, 'fail_memoir_lane', f"'{job['lane_id']}','{job['token']}','MEMOIR_PROVIDER_UNAVAILABLE',false")['status'] == 'retry_required'
    with story_client(sql) as client:
        saved = client.get('/v1/story/private-draft?project_id=project',
                           headers={'Authorization':'Bearer synthetic-author'}).json()
        assert saved['updating'] is False and saved['error'] == 'MEMOIR_PROVIDER_UNAVAILABLE'
        assert saved['progress']['extraction']['state'] == 'retry_required'
        assert saved['progress']['composition']['state'] == 'pending'
        retried = client.post('/v1/story/private-draft/retry', headers={'Authorization':'Bearer synthetic-author'},
                              json={'project_id':'project'}).json()
    assert retried['updating'] and retried['progress']['extraction']['state'] == 'pending'
    assert rpc(sql, 'read_user_memory_events', "'project'")['completed_rounds'] == 5


def test_terminal_composer_failure_exposes_a_retry_instead_of_perpetual_updating(sql):
    sources,lanes=five_rounds(sql)
    job=service_rpc(sql,'claim_memoir_lane',f"'{lanes['composer_lane_id']}',300")
    result=service_rpc(sql,'fail_memoir_lane',f"'{job['lane_id']}','{job['token']}','MEMOIR_PROVIDER_UNAVAILABLE',false")
    assert result['status']=='retry_required'
    saved=story_client(sql).get('/v1/story/private-draft?project_id=project',headers={'Authorization':'Bearer synthetic-author'}).json()
    assert saved['updating'] is False and saved['error']=='MEMOIR_PROVIDER_UNAVAILABLE'
    assert saved['progress']['composition']['state']=='retry_required'
    assert saved['progress']['extraction']['extracted_through']==5
    retried=story_client(sql).post('/v1/story/private-draft/retry',headers={'Authorization':'Bearer synthetic-author'},json={'project_id':'project'}).json()
    assert retried['updating'] and retried['progress']['composition']['state']=='pending'
    assert rpc(sql,'read_user_memory_events',"'project'")['completed_rounds']==5


@pytest.mark.parametrize('text,expression',[
    ('My mother was born in 1952. At age twelve I started school.','At age twelve'),
    ('我母亲1952年出生，我十二岁开始上学。','十二岁'),
])
def test_a_relatives_birth_does_not_establish_the_narrators_age_based_year(sql,text,expression):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}',{literal(text)}")
    ref={'source_id':source['id'],'version':1,'quote':text}
    proposal={'kind':'event','title':'School','source_refs':[ref],
        'temporal':{'expression':expression,'precision':'age','year_start':1964,'year_end':1964,'basis':[ref]}}
    result=rpc(sql,'apply_user_memory_events',f"'project',{literal([{'id':source['id'],'version':1}])}::jsonb,{literal([proposal])}::jsonb",check=False)
    assert result.returncode!=0 and 'supported original evidence' in result.stderr
    unknown={**proposal,'temporal':{'expression':expression,'precision':'age','basis':[ref]}}
    saved=extract(sql,[source],[unknown])['events'][0]
    assert saved['temporal'].get('year_start') is None and saved['temporal']['expression']==expression


def test_ambiguous_legacy_cross_index_matches_retain_aliases_without_active_duplicate_facts(sql):
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I started school around 1964.'")
    ref={'source_id':source['id'],'version':1,'quote':source['text']}
    document={'project_id':'project','revision':1,'people':[],'relationships':[],
        'timeline':[{'id':'legacy-school','kind':'event','title':'Started school','source_refs':[ref]}]}
    sql(f"insert into public.user_family_context(user_id,project_id,document) values('{OWNER}','project',{literal(document)}::jsonb);")
    rpc(sql,'migrate_user_memory_events',"'project'")
    composer=[{'id':'legacy-school','summary':'Started school','source_refs':[ref]}]
    migrated=rpc(sql,'migrate_user_memoir_index',f"'project',{literal(composer)}::jsonb")
    alias=migrated['event_id_map']['legacy-school']
    assert alias!='legacy-school'
    event=next(e for e in migrated['events'] if e['id']==alias)
    assert event['status']=='unresolved' and event['candidate_ids']==['legacy-school']
    assert event['provenance_status']=='legacy_identity_unresolved'
    assert rpc(sql,'migrate_user_memoir_index',f"'project',{literal(composer)}::jsonb")['event_id_map']==migrated['event_id_map']


def test_unchanged_heading_is_restored_before_review_and_rendering(sql,tmp_path,monkeypatch):
    sources,lanes=five_rounds(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    before=rpc(sql,'read_user_memoir_draft',"'project'")
    new=add_rounds(sql,6,6,'I moved to Sydney in 1986.')
    extract(sql,new,[{'kind':'event','title':'Moved to Sydney',
        'source_refs':[{'source_id':new[0]['id'],'version':1,'quote':new[0]['text']}]}])
    extract(sql,add_rounds(sql,7,10),[])
    deliver_latest(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],
        prose='An unwanted rewrite of the unchanged original.',
        control_options={'focus_first':True,'title':'An unwanted provider rewrite','block_id':'renamed-original'})['status']=='saved'
    after=rpc(sql,'read_user_memoir_draft',"'project'")
    assert after['preview']['title']==before['preview']['title']
    assert next(s for s in after['sections'] if 'heading' in s)==next(s for s in before['sections'] if 'heading' in s)
    assert after['preview']['text']==before['preview']['text']


def test_withdrawal_preserves_unrelated_immutable_passages_when_rebuilding(sql,tmp_path,monkeypatch):
    sources,lanes=five_rounds(sql)
    other=add_rounds(sql,6,6,'I moved to Sydney in 1986.')
    extract(sql,other,[{'kind':'event','title':'Moved to Sydney',
        'source_refs':[{'source_id':other[0]['id'],'version':1,'quote':other[0]['text']}]}])
    deliver_latest(sql)
    original={'Started school':'I started school around 1964.','Moved to Sydney':'I moved to Sydney in 1986.'}
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],control_options={'event_prose':original})['status']=='saved'
    before=rpc(sql,'read_user_memoir_draft',"'project'")
    move=next(s for s in before['sections'] if s['content']=='I moved to Sydney in 1986.')
    rpc(sql,'change_user_narrator_source',f"'project','{sources[0]['id']}',1,'withdraw'")
    assert rpc(sql,'read_user_memoir_draft',"'project'")['preview'] is None
    deliver_latest(sql)
    rewritten={'Moved to Sydney':'An unsolicited provider rewrite of the move.'}
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],control_options={'event_prose':rewritten,'title':'Moving to Sydney'})['status']=='saved'
    after=rpc(sql,'read_user_memoir_draft',"'project'")
    assert next(s for s in after['sections'] if s['id']==move['id'])==move
    assert 'school' not in after['preview']['text'] and after['preview']['text']=='I moved to Sydney in 1986.'


@pytest.mark.parametrize('sister_year', [1966, 1968])
def test_conflicting_attributed_dates_remain_unresolved_until_an_explicit_author_correction(sql, sister_year):
    first=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I remember starting school around 1964.'")
    ref={'source_id':first['id'],'version':1,'quote':first['text'],'attribution':'Narrator'}
    event=extract(sql,[first],[{'kind':'event','title':'Started school','source_refs':[ref],
        'temporal':{'expression':'around 1964','precision':'approximate','year_start':1964,'year_end':1964,'basis':[ref]}}])['events'][0]
    later=rpc(sql,'accept_user_narrator_source',"'project','00000000-0000-4000-8000-000000000002','My brother remembers that same school start around 1966.'")
    other={'source_id':later['id'],'version':1,'quote':later['text'],'attribution':'Brother'}
    saved=extract(sql,[later],[{'existing_id':event['id'],'expected_revision':1,'kind':'event','title':'Started school',
        'source_refs':[other],'temporal':{'expression':'around 1966','precision':'approximate','year_start':1966,'year_end':1966,'basis':[other]}}])['events'][0]
    assert saved['temporal']['precision']=='unknown' and saved['temporal'].get('year_start') is None
    assert {a['temporal']['year_start'] for a in saved['temporal_accounts']}=={1964,1966}
    assert {r['attribution'] for r in saved['source_refs']}=={'Narrator','Brother'}
    third=rpc(sql,'accept_user_narrator_source',f"'project','00000000-0000-4000-8000-000000000003','My sister remembers that same school start around {sister_year}.'")
    third_ref={'source_id':third['id'],'version':1,'quote':third['text'],'attribution':'Sister'}
    disputed=extract(sql,[third],[{'existing_id':event['id'],'expected_revision':2,'kind':'event','title':'Started school',
        'source_refs':[third_ref],'temporal':{'expression':f'around {sister_year}','precision':'approximate','year_start':sister_year,'year_end':sister_year,'basis':[third_ref]}}])['events'][0]
    assert disputed['temporal']['precision']=='unknown' and disputed['temporal'].get('year_start') is None
    assert len(disputed['temporal_accounts'])==3
    assert {a['temporal']['year_start'] for a in disputed['temporal_accounts']}=={1964,1966,sister_year}
    assert disputed['temporal_accounts'][-1]['temporal']['basis']==[third_ref]
    assert {r['attribution'] for r in disputed['source_refs']}=={'Narrator','Brother','Sister'}
    patch={'temporal':{'expression':'1965','precision':'year','year_start':1965,'year_end':1965}}
    resolved=rpc(sql,'correct_user_memory_event',f"'project','{event['id']}',3,{literal(patch)}::jsonb,'Actually, the year was 1965.'")
    assert resolved['temporal']['year_start']==1965 and resolved['timing_conflict'] is False


@pytest.mark.parametrize('temporal_echo', ['saved_summary', 'recorded_account'])
@pytest.mark.parametrize('dispatch', ['rpc', 'worker'])
def test_acknowledgement_replaying_conflicted_dates_keeps_the_saved_event_unchanged(sql, temporal_echo, dispatch):
    first = rpc(sql, 'accept_user_narrator_source', f"'project','{TURN}','I remember starting school around 1964.'")
    ref = {'source_id': first['id'], 'version': 1, 'quote': first['text'], 'attribution': 'Narrator'}
    event = extract(sql, [first], [{'kind': 'event', 'title': 'Started school', 'source_refs': [ref],
        'temporal': {'expression': 'around 1964', 'precision': 'approximate',
                     'year_start': 1964, 'year_end': 1964, 'basis': [ref]}}])['events'][0]
    later = rpc(sql, 'accept_user_narrator_source', "'project','00000000-0000-4000-8000-000000000002','My brother remembers that same school start around 1966.'")
    other = {'source_id': later['id'], 'version': 1, 'quote': later['text'], 'attribution': 'Brother'}
    saved = extract(sql, [later], [{'existing_id': event['id'], 'expected_revision': event['revision'],
        'kind': 'event', 'title': 'Started school', 'source_refs': [other],
        'temporal': {'expression': 'around 1966', 'precision': 'approximate',
                     'year_start': 1966, 'year_end': 1966, 'basis': [other]}}])['events'][0]
    assert saved['timing_conflict'] and len(saved['temporal_accounts']) == 2
    acknowledgement = rpc(sql, 'accept_user_narrator_source', "'project','00000000-0000-4000-8000-000000000003','Thanks.'")
    temporal = saved['temporal'] if temporal_echo == 'saved_summary' else saved['temporal_accounts'][1]['temporal']
    proposal = {'existing_id': saved['id'], 'expected_revision': saved['revision'],
        'kind': saved['kind'], 'title': saved['title'], 'source_refs': saved['source_refs'], 'temporal': temporal}
    if dispatch == 'rpc':
        after = extract(sql, [acknowledgement], [proposal])
    else:
        import httpx
        from apps.api.memory_event_worker import MemoirLaneBroker, MemoryEventWorker
        from memoir_postgres_workflow import PostgresRest
        lanes = deliver_latest(sql)
        async def process():
            async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)) as db:
                broker = MemoirLaneBroker(url='http://synthetic.invalid', key='synthetic', client=db)
                provider = httpx.MockTransport(lambda request: httpx.Response(200, json={
                    'reply': json.dumps({'events': [proposal]})}))
                worker = MemoryEventWorker(broker, worker_url='http://controlled-provider.invalid',
                                          worker_secret='synthetic', worker_transport=provider)
                assert (await worker.execute_lane(lanes['timeline_lane_id']))['status'] == 'saved'
        asyncio.run(process())
        after = rpc(sql, 'read_user_memory_events', "'project'")
    assert after['events'] == [saved]
    assert after['processing'] == {'extracted_through': 3, 'pending_inputs': 0}
    assert after['completed_rounds'] == 0


def test_similar_events_ambiguous_matches_and_long_periods_share_originals_without_merging(sql):
    text='In 1970 I visited the same town twice, once with Mum and once alone. I worked there from 1986 to 2005.'
    source=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}',{literal(text)}")
    ref={'source_id':source['id'],'version':1,'quote':text}
    first=extract(sql,[source],[{'kind':'event','title':'Town visit','source_refs':[ref]},
        {'kind':'event','title':'Town visit','source_refs':[ref]},
        {'kind':'period','title':'Worked in town','source_refs':[ref],
         'temporal':{'expression':'from 1986 to 2005','precision':'range','year_start':1986,'year_end':2005,'basis':[ref]}}])['events']
    assert len(first)==3 and len({e['id'] for e in first})==3
    period=next(e for e in first if e['kind']=='period')
    assert period['temporal']['year_start']==1986 and period['temporal']['year_end']==2005
    uncertain=rpc(sql,'accept_user_narrator_source',"'project','00000000-0000-4000-8000-000000000002','I cannot remember which of those visits included lunch.'")
    candidates=[e['id'] for e in first if e['kind']=='event']
    saved=extract(sql,[uncertain],[{'kind':'event','title':'Lunch during a visit','candidate_ids':candidates,
        'uncertainty':'Visit identity unresolved','source_refs':[{'source_id':uncertain['id'],'version':1,'quote':uncertain['text']}]}])['events']
    pending=next(e for e in saved if e['title']=='Lunch during a visit')
    assert pending['status']=='unresolved' and pending['candidate_ids']==candidates
    assert next(e for e in saved if e['id']==period['id'])==period


def test_nondefault_private_cadence_does_not_change_the_independent_round_allowance(sql):
    from test_agent_commit_postgres import OLD
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    sources=add_rounds(sql,1,2)
    extract(sql,sources,[])
    receipts=service_rpc(sql,'pending_memoir_receipts','100')
    for receipt in receipts: service_rpc(sql,'queue_memoir_receipt',f"'{receipt}',3")
    assert rpc(sql,'read_user_memoir_draft',"'project'")['milestone']==0
    source=add_rounds(sql,3,3)
    extract(sql,source,[])
    last=service_rpc(sql,'pending_memoir_receipts','100')
    lanes=[service_rpc(sql,'queue_memoir_receipt',f"'{r}',3") for r in last]
    lane=next(l['composer_lane_id'] for l in lanes if l['composer_lane_id'])
    snapshot=service_rpc(sql,'claim_memoir_lane',f"'{lane}',300")
    assert snapshot['milestone']==snapshot['coverage_round']==3
    from memoir_postgres_workflow import PostgresRest
    assert PostgresRest(sql,OWNER).storage().recall_rounds_completed()==3
    from apps.api.recall import free_recall_rounds
    assert free_recall_rounds()==20


def test_a_changed_access_policy_refuses_an_older_frozen_composer_result(sql,tmp_path,monkeypatch):
    sources,lanes=five_rounds(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    rpc(sql,'retry_user_memoir_lane',"'project','composer'")
    held=service_rpc(sql,'claim_memoir_lane',f"'{lanes['composer_lane_id']}',300")
    before=rpc(sql,'read_user_memoir_draft',"'project'")
    # Controlled authorization/policy boundary, not a source text mutation.
    sql(f"update public.user_memoir_project set policy_epoch=policy_epoch+1 where user_id='{OWNER}' and project_id='project';")
    late=service_rpc(sql,'finish_memoir_composer',f"'{held['lane_id']}','{held['token']}',1,{literal(held['previous'])}::jsonb")
    assert late['status']=='stale'
    assert rpc(sql,'read_user_memoir_draft',"'project'")['revision']==before['revision']


def test_an_access_policy_change_fences_extraction_without_acknowledging_the_input(sql):
    rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I started school around 1964.'")
    lane=deliver_latest(sql)['timeline_lane_id']
    held=service_rpc(sql,'claim_memoir_lane',f"'{lane}',300")
    sql(f"update public.user_memoir_project set policy_epoch=policy_epoch+1 where user_id='{OWNER}' and project_id='project';")
    assert service_rpc(sql,'finish_memoir_timeline',f"'{lane}','{held['token']}','[]'::jsonb")['status']=='stale'
    view=rpc(sql,'read_user_memory_events',"'project'")
    assert view['processing']=={'extracted_through':0,'pending_inputs':1}


def test_editing_an_acknowledgement_keeps_the_independent_saved_passage_available(sql,tmp_path,monkeypatch):
    sources,lanes=five_rounds(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    before=rpc(sql,'read_user_memoir_draft',"'project'")
    edited=rpc(sql,'change_user_narrator_source',f"'project','{sources[1]['id']}',1,'edit','Thank you.'")
    current=rpc(sql,'read_user_memoir_draft',"'project'")
    assert current['status']=='ready' and current['preview']==before['preview']
    extract(sql,[edited],[])
    deliver_latest(sql)
    result=run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])
    assert result['status'] in {'saved','finished'}
    after=rpc(sql,'read_user_memoir_draft',"'project'")
    assert after['preview']==before['preview'] and after['sections']==before['sections']
    assert after['revision']==before['revision'] and after['covered_round']==5


def test_withdrawal_prunes_only_the_owners_legacy_execution_cache_before_outbox_acknowledgement(sql,tmp_path,monkeypatch):
    import sqlite3
    import httpx
    from apps.api.memory_event_worker import MemoirLaneBroker
    from apps.api.private_draft_jobs import PrivateDraftJobs
    from apps.api.preview_jobs import PreviewJobs
    from memoir_postgres_workflow import PostgresRest
    sources,lanes=five_rounds(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    rpc(sql,'retry_user_memoir_lane',"'project','composer'")
    bundle=service_rpc(sql,'claim_memoir_lane',f"'{lanes['composer_lane_id']}',300")['previous']
    path=tmp_path/'legacy-cache.sqlite'
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(path))
    queue=PrivateDraftJobs(path)
    rounds=PostgresRest(sql,OWNER).storage().private_draft_rounds('project')
    queue.synchronize(OWNER,'project','en-AU',rounds,sources,completed=5,free_limit=20,cadence=5)
    cached_id=queue.pending_ids()[0]
    assert queue.finish(queue.claim(cached_id),result=bundle)
    previews=PreviewJobs(path)
    preview=previews.submit(OWNER,'project','legacy-preview','en-AU',{'original':'I started school around 1964.'})
    preview=previews.claim(OWNER,preview['id'])
    previews.checkpoint(preview['id'],preview['lease_token'],'reviewing',{'private_draft':bundle})
    queue.synchronize(OTHER,'project','en-AU',[],[{'id':'other-source','version':1,'text':'Other owner remains private.'}],
        completed=0,free_limit=20,cadence=5)
    rpc(sql,'change_user_narrator_source',f"'project','{sources[0]['id']}',1,'withdraw'")
    async def drain():
        async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql,OWNER,service=True).handle)) as db:
            await MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic-service',client=db).drain_once()
    asyncio.run(drain())
    assert queue.status(cached_id)=='STALE' and queue.claim(cached_id) is None
    assert previews.get(OWNER,preview['id'])['status']=='STALE'
    assert previews.finish(preview['id'],preview['lease_token']) is False
    # Restricted checkpoint retention is observed at the existing cache storage
    # boundary; reader eligibility alone cannot prove its bytes were removed.
    with sqlite3.connect(path) as db:
        owned=db.execute('select payload,draft,proposal from private_draft_projects where user_id=?',(OWNER,)).fetchall()
        jobs=db.execute('select payload,checkpoint from private_draft_jobs where user_id=?',(OWNER,)).fetchall()
        preview_bytes=db.execute('select payload,checkpoint from preview_jobs where user_id=?',(OWNER,)).fetchall()
        other=db.execute('select payload from private_draft_projects where user_id=?',(OTHER,)).fetchone()[0]
    assert 'I started school around 1964.' not in str(owned)+str(jobs)+str(preview_bytes)
    assert 'Other owner remains private.' in other
    assert service_rpc(sql,'pending_memoir_receipts','100')==[]


def test_a_composer_section_cannot_cite_originals_outside_its_frozen_project(sql,tmp_path,monkeypatch):
    sources,lanes=five_rounds(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    rpc(sql,'retry_user_memoir_lane',"'project','composer'")
    held=service_rpc(sql,'claim_memoir_lane',f"'{lanes['composer_lane_id']}',300")
    foreign=rpc(sql,'accept_user_narrator_source',f"'other-project','{TURN}','A different private project.'")
    bundle=held['previous']
    bundle['sections'][0]['source_refs']=[{'source_id':foreign['id'],'version':'1','char_start':0,'char_end':10}]
    bundle['sections'][0]['fingerprint']='untrusted-dependency-change'
    result=sql(f"set role service_role; select public.finish_memoir_composer('{held['lane_id']}','{held['token']}',1,{literal(bundle)}::jsonb);",check=False)
    assert result.returncode!=0 and 'unavailable source' in result.stderr
    assert rpc(sql,'read_user_memoir_draft',"'project'")['revision']==1


def test_coalesced_checkpoint_history_retains_milestones_separately_from_covered_rounds(sql,tmp_path,monkeypatch):
    import httpx
    from apps.api.memory_event_worker import MemoirLaneBroker
    from memoir_postgres_workflow import PostgresRest
    sources,lanes=five_rounds(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    extract(sql,add_rounds(sql,6,21),[])
    async def drain():
        async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql,OWNER,service=True).handle)) as db:
            await MemoirLaneBroker(url='http://synthetic.invalid',key='synthetic-service',client=db).drain_once()
    asyncio.run(drain())
    pending=rpc(sql,'read_user_memoir_draft',"'project'")
    assert [m['milestone'] for m in pending['milestones']]==[5,10,15,20]
    assert [m['state'] for m in pending['milestones']]==['completed','pending','pending','pending']
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    saved=rpc(sql,'read_user_memoir_draft',"'project'")
    assert saved['covered_round']==21 and saved['milestone']==20 and saved['revision']==1
    assert [m['state'] for m in saved['milestones']]==['completed']*4
    assert [m['covered_round'] for m in saved['milestones']]==[5,21,21,21]


def test_incremental_composition_retrieves_old_dirty_evidence_with_small_continuity_context(sql,tmp_path,monkeypatch):
    sources,lanes=five_rounds(sql)
    move=add_rounds(sql,6,6,'I moved to Sydney in 1986.')
    extract(sql,move,[{'kind':'event','title':'Moved to Sydney',
        'source_refs':[{'source_id':move[0]['id'],'version':1,'quote':move[0]['text']}]}])
    extract(sql,add_rounds(sql,7,10),[])
    deliver_latest(sql)
    original={'Started school':'I started school around 1964.','Moved to Sydney':'I moved to Sydney in 1986.'}
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],control_options={'event_prose':original})['status']=='saved'
    before=rpc(sql,'read_user_memoir_draft',"'project'")
    school=next(e for e in rpc(sql,'read_user_memory_events',"'project'")['events'] if e['title']=='Started school')
    extract(sql,add_rounds(sql,11,15),[])
    late=add_rounds(sql,16,16,'At that same school, I carried a blue bag.')
    extract(sql,late,[{'existing_id':school['id'],'expected_revision':1,'kind':'event','title':'Started school',
        'source_refs':[{'source_id':late[0]['id'],'version':1,'quote':late[0]['text']}]}])
    extract(sql,add_rounds(sql,17,20),[])
    deliver_latest(sql)
    (tmp_path/'calls.jsonl').unlink()
    updated={**original,'Started school':'I started school around 1964. I carried a blue bag.'}
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],control_options={'event_prose':updated})['status']=='saved'
    packets=[json.loads(line) for line in (tmp_path/'calls.jsonl').read_text().splitlines() if json.loads(line)['phase'] in {'draft','review'}]
    assert packets and all({sources[0]['id'],late[0]['id']}.issubset(p['source_ids']) and len(p['source_ids'])<=4 for p in packets)
    assert all(p['dirty_event_ids']==[school['id']] for p in packets)
    after=rpc(sql,'read_user_memoir_draft',"'project'")
    assert 'blue bag' in after['preview']['text'] and after['covered_round']==20
    unchanged=next(s for s in before['sections'] if s['content']=='I moved to Sydney in 1986.')
    assert next(s for s in after['sections'] if s['id']==unchanged['id'])==unchanged


def test_the_existing_sample_endpoint_uses_the_shared_draft_and_withholds_a_corrected_old_sample(sql,tmp_path,monkeypatch):
    sources,lanes=five_rounds(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    client=story_client(sql)
    headers={'Authorization':'Bearer synthetic-author'}
    # The existing sample gate remains twenty rounds, independently of the
    # five-round private checkpoint. The reserved provider endpoint is offline.
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'sample-jobs.sqlite'))
    monkeypatch.setenv('MEMORY_SPARK_CODEX_HOME',str(tmp_path/'offline-homes'))
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_URL','http://controlled-model.invalid')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic-worker-secret')
    assert client.post('/v1/story/preview',headers=headers,json={'project_id':'project'}).status_code==409
    extract(sql,add_rounds(sql,6,20),[])
    deliver_latest(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'])['status']=='saved'
    before=rpc(sql,'read_user_memoir_draft',"'project'")
    sample=client.post('/v1/story/preview',headers=headers,json={'project_id':'project'})
    assert sample.status_code==200 and sample.json()['preview']==before['preview']
    assert sample.json()['covered_round']==20
    event=rpc(sql,'read_user_memory_events',"'project'")['events'][0]
    patch={'life_stage':'adolescence','temporal':{'expression':'1966','precision':'year','year_start':1966,'year_end':1966}}
    rpc(sql,'correct_user_memory_event',f"'project','{event['id']}',1,{literal(patch)}::jsonb,'Actually, I was an adolescent in 1966.'")
    pending=client.post('/v1/story/preview',headers=headers,json={'project_id':'project'})
    assert pending.status_code==202 and pending.json()['status']=='pending' and pending.json()['preview'] is None
    job=pending.json()['job']['id']
    assert client.get('/v1/story/preview/'+job,headers=headers).json()['preview'] is None
    deliver_latest(sql)
    assert run_controlled_composer(sql,tmp_path,monkeypatch,lanes['composer_lane_id'],prose='I started school in 1966.')['status']=='saved'
    corrected=client.get('/v1/story/preview/'+job,headers=headers).json()
    assert corrected['status']=='ready' and corrected['preview']['text']=='I started school in 1966.'
    assert rpc(sql,'read_user_memory_events',"'project'")['completed_rounds']==20
