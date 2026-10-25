"""Issue 6 public persistence seam on real, disposable PostgreSQL.

The existing harness creates and stops a random /tmp cluster. No configured
Supabase URL, shared service, or customer data is used.
"""
import json
import asyncio
from pathlib import Path

import pytest

from controlled_collector import extraction_proposal
from apps.api.store import MemoryStore

from test_agent_commit_postgres import database, as_user, OWNER, OTHER
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database


TURN = '00000000-0000-4000-8000-000000000001'
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def event_database(private_database):
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
    if check and name in {'accept_user_narrator_source', 'accept_user_interview_turn', 'accept_two_lane_interview_turn', 'change_user_narrator_source'}:
        # SQL seed callers supply a fixed empty review. Pending-policy tests use
        # raw SQL; runtime tests exercise the separately mocked provider phase.
        from controlled_policy import complete_seed_policy
        complete_seed_policy(sql, owner)
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
    assert sql('select count(*) from public.user_private_draft_outbox where not delivered;').stdout.strip()=='1'


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
    assert conflict.value.response.status_code==409 and conflict.value.response.json()['code']=='PT409'
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
        controlled_reply = (extraction_proposal(payload.language) if payload.agent_role == 'collector'
            else marker if payload.extraction_focus == 'family_tree' else 'Tell me more.')
        control.write_text(json.dumps({'reply': controlled_reply}))
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


@pytest.mark.parametrize('text', [
    'That late-teenage winter belongs to adolescence, even though the exact month is unknown.',
    '那年冬天属于青少年时期，具体月份已经记不清了。',
])
def test_new_stage_evidence_is_an_ordinary_update_without_explicit_correction_wording(sql,text):
    from apps.api.memory_events import validate_extraction
    first=rpc(sql,'accept_user_narrator_source',f"'project','{TURN}','I spent a winter repairing a radio.'")
    event=extract(sql,[first],[dict(kind='event',title='Winter',source_refs=[dict(source_id=first['id'],version=1,quote=first['text'])])])['events'][0]
    latest=rpc(sql,'accept_user_narrator_source',f"'project','00000000-0000-4000-8000-000000000002',{literal(text)}")
    ref=dict(source_id=latest['id'],version=1,quote=text)
    proposal=dict(existing_id=event['id'],expected_revision=event['revision'],kind='event',title='Winter',
        life_stage='adolescence',stage_evidence=[ref],source_refs=[ref],correction=ref)
    with pytest.raises(ValueError,match='explicit correction wording'):
        validate_extraction({'events':[proposal]},[latest],[event])
    # The same SQL guard remains authoritative for callers bypassing Python.
    args=f"'project',{literal([dict(id=latest['id'],version=1)])},{literal([proposal])}"
    assert rpc(sql,'apply_user_memory_events',args,check=False).returncode!=0
    proposal.pop('correction')
    accepted=validate_extraction({'events':[proposal]},[latest],[event])
    saved=extract(sql,[latest],accepted)['events'][0]
    assert saved['id']==event['id'] and saved['life_stage']=='adolescence'
    assert sql(f"select coalesce(data->'user_overrides','{{}}'::jsonb) ? 'life_stage' from public.user_memory_event where id={literal(saved['id'])};").stdout.strip()=='f'
    assert rpc(sql,'read_user_memory_events',"'project'")['sources'][-1]['text']==text


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
    app.state.store = MemoryStore()
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
