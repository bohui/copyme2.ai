"""Mapped story reads stay bounded and retain their pre-read publication fence."""
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.lifetime_memory_reads import ReadFence
from test_lifetime_memory_reads import FENCE


@pytest.fixture
def mapped(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.db'))
    calls = []
    fence = deepcopy(FENCE)
    result = {'status': 'ready', 'preview': {'title': 'One section', 'text': 'Saved words'},
              'snapshot_id': 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'next_cursor': 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
              'page_complete': False, 'retrieval_complete': True, 'publication_approved': False}
    def rpc(name, **kwargs):
        calls.append((name, kwargs))
        if name == 'read_lifetime_project_identity': return fence['identity']
        if name == 'capture_lifetime_read_fence': return deepcopy(fence)
        if name == 'read_lifetime_collection_selection': return {'revision':0,'periods':{},'ready':False,'tasks':[]}
        assert any(call[0] == 'capture_lifetime_read_fence' for call in calls)
        return deepcopy(result)
    @asynccontextmanager
    async def guard(original):
        assert ReadFence.model_validate(original) == ReadFence.model_validate(fence)
        calls.append(('actual_send_guard', {}))
        yield
    from apps.api import lifetime_memory_reads, collection_routes
    monkeypatch.setattr(lifetime_memory_reads, 'ReadPublication', lambda *a, **kw: SimpleNamespace(guard=guard))
    def forbidden(*a, **kw): pytest.fail('mapped route loaded legacy full history')
    storage = SimpleNamespace(user_id=FENCE['identity']['owner_id'], client=SimpleNamespace(close=lambda: None),
        lifetime_rpc=rpc, memories=forbidden, all_memories=forbidden, memory_events=forbidden,
        is_anonymous=False, retry_memoir_lane=lambda project, skill: calls.append(('retry', {'skill': skill})),
        story_entitlement=lambda: {'status': 'paid', 'plan_key': 'family_memoir_v1', 'timeline': True, 'family_tree': True})
    monkeypatch.setattr(collection_routes, 'authenticated_storage', lambda _: storage)
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: storage))
    return client, storage, calls, result


@pytest.mark.parametrize('path,operation', [
    ('/v1/story/private-draft?project_id=read-project', 'read_lifetime_private_draft_head'),
    ('/v1/story/private-draft/page?project_id=read-project&snapshot_id=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'read_lifetime_private_draft_page'),
    ('/v1/story/private-draft/section?project_id=read-project&snapshot_id=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa&partition_id=selected', 'read_workspace_draft_section'),
    ('/v1/story/events?project_id=read-project', 'read_lifetime_collection_page'),
    ('/v1/story/sources?project_id=read-project', 'read_lifetime_collection_page'),
    ('/v1/story/readiness?project_id=read-project', 'read_lifetime_stage_readiness'),
])
def test_mapped_story_gets_capture_before_rpc_and_guard_actual_send(mapped, path, operation):
    client, _, calls, _ = mapped
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.headers['cache-control'] == 'no-store'
    names = [name for name, _ in calls]
    assert names[:2] == ['read_lifetime_project_identity', 'capture_lifetime_read_fence']
    assert names[-2:] == [operation, 'actual_send_guard']


@pytest.mark.parametrize('path', [
    '/v1/story/private-draft?project_id=read-project',
    '/v1/story/events?project_id=read-project',
    '/v1/story/sources?project_id=read-project',
    '/v1/story/readiness?project_id=read-project',
    '/v1/agent/collection/read-project',
])
def test_mapped_reads_remain_canonical_when_rollout_is_disabled(mapped, monkeypatch, path):
    client, storage, calls, result = mapped
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'false')
    if '/collection/' in path:
        result.update(sources=[])
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert calls[0][0] == 'read_lifetime_project_identity'
    assert calls[-1][0] == 'actual_send_guard'
    from apps.api.lifetime_memory_read_api import mapped_identity
    assert mapped_identity(storage, 'read-project') is not None


def test_retry_uses_existing_lanes_without_creating_composition_eligibility(mapped):
    client, _, calls, result = mapped
    response = client.post('/v1/story/private-draft/retry', json={'project_id': 'read-project'})
    assert response.status_code == 200
    assert [kwargs['skill'] for name, kwargs in calls if name == 'retry'] == ['composer', 'timeline']
    assert max(index for index,(name,_) in enumerate(calls) if name=='retry') < next(index for index,(name,_) in enumerate(calls) if name=='capture_lifetime_read_fence')
    assert response.json()['page_complete'] is False
    assert response.json()['publication_approved'] is False
    assert calls[-1][0] == 'actual_send_guard'


def test_family_display_gate_still_precedes_canonical_event_read(mapped):
    client, storage, calls, _ = mapped
    storage.story_entitlement = lambda: {'status': 'paid', 'plan_key': 'electronic_memoir_v1'}
    assert client.get('/v1/story/events?project_id=read-project').status_code == 403
    assert calls == []


def test_page_parameter_bounds_reject_before_database(mapped):
    client, _, calls, _ = mapped
    assert client.get('/v1/story/private-draft/page?project_id=read-project&snapshot_id=not-uuid').status_code == 422
    assert client.get('/v1/story/events?project_id=read-project&limit=9').status_code == 422
    assert calls == []


def test_canonical_collection_does_not_keyerror_on_valid_draft_head(mapped):
    client, _, calls, result = mapped
    result.clear()
    result.update(sources=[{'id': 'source', 'text': 'Exact original'}], complete=False,
                  next_cursor='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb')
    response = client.get('/v1/agent/collection/read-project')
    assert response.status_code == 200, response.text
    assert response.json()['sources'] == [{'id': 'source', 'text': 'Exact original', 'content': 'Exact original'}]
    assert response.json()['complete'] is False
    assert response.json()['tasks'] == []
    assert calls[-1][0] == 'actual_send_guard'

# Isolated real PostgreSQL migration/authority checks. No configured services.
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, resolve
from test_lifetime_memory_reads import database
from test_shared_memory_events_postgres import rpc, literal
from test_agent_commit_postgres import OWNER, OTHER
from apps.api.stage_readiness import word_equivalents


def test_pg_source_pages_cover_more_than_one_page_and_reject_stale_or_cross_owner_cursor(sql):
    project = resolve(sql)['project_id']
    for number in range(19):
        rpc(sql, 'accept_user_narrator_source', f"{literal(project)}, '00000000-0000-4000-8000-{number:012d}', 'Original {number}'")
    first = rpc(sql, 'read_lifetime_collection_page', f"{literal(project)}, 'sources'")
    assert len(first['sources']) == 8 and first['complete'] is False
    seen = first['sources'][:]
    cursor = first['next_cursor']
    while cursor:
        page = rpc(sql, 'read_lifetime_collection_page', f"{literal(project)}, 'sources', '{cursor}'")
        seen.extend(page['sources'])
        cursor = page['next_cursor']
    assert len(seen) == 19 and len({r['id'] for r in seen}) == 19
    assert {r['text'] for r in seen} == {f'Original {n}' for n in range(19)}
    assert rpc(sql, 'read_lifetime_collection_page', f"{literal(project)}, 'sources', '{first['next_cursor']}'", owner=OTHER, check=False).returncode
    assert rpc(sql, 'read_lifetime_collection_page', f"{literal(project)}, 'events', '{first['next_cursor']}'", check=False).returncode
    rpc(sql, 'change_user_narrator_source', f"{literal(project)}, '{seen[0]['id']}', 1, 'withdraw', null")
    assert rpc(sql, 'read_lifetime_collection_page', f"{literal(project)}, 'sources', '{first['next_cursor']}'", check=False).returncode


@pytest.mark.parametrize('text', ["我住在苏州。I remember mother's well-loved garden. 1960 🙂", 'école αβγ १२३ ᚠᛇᚻ foo_bar',
    'one', '', 'hello\nworld', '𠀀𯨟汉字', "The storyteller said: 我记得花园\nAcknowledge the storyteller naturally, then ask one gentle open-ended follow-up question."])
def test_pg_readiness_word_count_matches_existing_heuristic(sql, text):
    from apps.api.stage_readiness import narrator_response
    content = f'Storyteller: {text}\nMemory Spark: A reply'
    expected = word_equivalents(narrator_response({'kind': 'agent', 'content': content}))
    result = sql(f"select public.lifetime_narrator_word_equivalents('agent',{literal(content)});")
    assert int(result.stdout.strip()) == expected


def test_pg_readiness_metadata_tracks_edits_reassignment_and_deletion(sql):
    project = resolve(sql)['project_id']
    memory = 'ffffffff-ffff-4fff-8fff-ffffffffffff'
    content = 'Storyteller: ' + 'word ' * 300 + '\nMemory Spark: reply'
    sql(f"insert into public.user_memory(id,user_id,project_id,kind,content,life_stage) values('{memory}','{OWNER}',{literal(project)},'agent',{literal(content)},'childhood');")
    view = rpc(sql, 'read_lifetime_stage_readiness', literal(project))
    assert view['stages']['childhood'] == {'word_equivalents': 300, 'percent': 30.0, 'color': 'amber'}
    assert view['maximum_percent'] == 50 and view['heuristic'] == 'narrator_context_volume_v1'
    sql(f"update public.user_memory set life_stage='midlife' where id='{memory}';")
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project))['stages']['childhood']['word_equivalents'] == 0
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project))['stages']['midlife']['word_equivalents'] == 300
    sql(f"delete from public.user_memory where id='{memory}';")
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project))['stages']['midlife']['word_equivalents'] == 0


def test_pg_event_pages_preserve_uncertainty_and_page_evidence_and_conflicting_dates(sql):
    project = resolve(sql)['project_id']
    original = rpc(sql, 'accept_user_narrator_source', f"{literal(project)}, '00000000-0000-4000-8000-000000000001', 'Maybe Ming; I recall either 1963 or 1964.'")
    data = {'title': 'School with Ming', 'uncertainty': 'Name and year uncertain', 'assertion': 'inferred', 'timing_conflict': True,
        'temporal': {'expression':'unknown','precision':'unknown'},
        'temporal_accounts': [{'temporal': {'expression': str(1960+n), 'precision': 'year'}} for n in range(11)],
        'contradicts': ['earlier account'], 'supersedes': ['older proposed date']}
    sql(f"insert into public.user_memory_event(user_id,project_id,id,kind,life_stage,status,data,change_sequence) values('{OWNER}',{literal(project)},'uncertain','event','unplaced','unresolved',{literal(data)}::jsonb,1);")
    for index, quote in enumerate(['Maybe Ming', '1963', '1964']):
        ref = {'source_id': original['id'], 'version': 1, 'quote': quote}
        sql(f"insert into public.user_memory_event_source values('{OWNER}',{literal(project)},'uncertain','{original['id']}',1,'{index}',{literal(ref)}::jsonb);")
    first = rpc(sql, 'read_lifetime_collection_page', f"{literal(project)},'events'")['events'][0]
    assert first['uncertainty'] == 'Name and year uncertain' and first['assertion'] == 'inferred'
    assert first['timing_conflict'] is True and first['status'] == 'unresolved'
    assert first['evidence_complete'] is False and len(first['source_refs']) == 1
    evidence = rpc(sql, 'read_lifetime_collection_page', f"{literal(project)},'event_sources','{first['evidence_next_cursor']}',8,'uncertain'")
    assert evidence['complete'] is True and len(evidence['source_refs']) == 2
    details = rpc(sql, 'read_lifetime_collection_page', f"{literal(project)},'event_details',null,8,'uncertain'")
    assert len(details['details']) == 8 and details['complete'] is False
    rest = rpc(sql, 'read_lifetime_collection_page', f"{literal(project)},'event_details','{details['next_cursor']}',8,'uncertain'")
    assert rest['complete'] is True and len(rest['details']) == 5


@pytest.mark.parametrize('locale,requested', [('en-AU','zh-CN'), ('zh-CN','en-AU')])
def test_requested_language_never_silently_returns_or_retries_a_different_edition(mapped, locale, requested):
    client, _, calls, result = mapped
    result['locale'] = locale
    for method,path,kwargs in [
        ('get',f'/v1/story/private-draft?project_id=read-project&language={requested}',{}),
    ]:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 409 and response.headers['x-error-code'] == 'LIFETIME_EDITION_UNAVAILABLE'
    assert not any(name=='retry' for name,_ in calls)



@pytest.mark.parametrize('locale', ['en-AU','zh-CN'])
def test_explicit_saved_edition_is_passed_to_database_without_profile_mutation(mapped, locale):
    client, _, calls, result = mapped
    result['locale'] = locale
    response = client.get(f'/v1/story/private-draft?project_id=read-project&language={locale}')
    assert response.status_code == 200
    assert next(kwargs for name,kwargs in calls if name=='read_lifetime_private_draft_head')['p_locale']==locale


def test_pg_actual_http_source_body_is_guarded_at_send_and_withdrawal_never_leaks(sql, monkeypatch):
    from test_lifetime_memory_reads import setup_read
    identity,source,_,dsn=setup_read(sql)
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',dsn)
    after_read=[False]
    def call(name,**kwargs):
        arguments=','.join(key+'=>'+('null' if value is None else str(value) if isinstance(value,int) else literal(value)) for key,value in kwargs.items())
        value=rpc(sql,name,arguments)
        if name=='read_lifetime_collection_page' and after_read[0]:
            rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{source['id']}',1,'withdraw',null")
        return value
    storage=SimpleNamespace(user_id=OWNER,lifetime_rpc=call,client=SimpleNamespace(close=lambda:None))
    app=create_app(MemoryStore(),story_storage_factory=lambda _:storage)
    with TestClient(app,raise_server_exceptions=False) as client:
        path=f"/v1/story/sources?project_id={identity['project_id']}"
        good=client.get(path)
        assert good.status_code==200 and good.json()['sources'][0]['text']=='Read original memory'
        assert good.headers['cache-control']=='no-store'
        after_read[0]=True
        stale=client.get(path)
        assert stale.status_code>=400
        assert 'Read original memory' not in stale.text
