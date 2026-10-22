"""Controlled HTTP/SQL replay of the versioned durable background handoff."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from test_interview_strategy_runtime import (sql, database, event_database, private_database,
    attachment_database, enable_only_disposable_database_rollout, client_fixture)
from test_two_lane_memory import lane, service
from test_shared_memory_events_postgres import rpc, literal
from test_agent_commit_postgres import OWNER, as_user
from test_conversation_reply import proposal


def saved_turn(sql, tmp_path, monkeypatch, *, text='My brother Ming moved to Perth.', name=None, mode='reply_only'):
    calls = []
    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['interview_context']['reply_contract'] == 'reply-v2'
        packet = json.loads(body['governed']['packet'])
        from apps.api.lifetime_memory_engine import GOVERNED_TURN_PROMPT
        assert len(packet['instructions'] + '\n' + GOVERNED_TURN_PROMPT) < 2000
        output = proposal()
        if name is not None:
            output['work'] = {'mode': mode, 'name': name}
        return httpx.Response(200, json={'reply': json.dumps(output), 'thread_id': 'small-reply', 'artifacts': []})
    client = client_fixture(sql, tmp_path, monkeypatch, provider)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    with client:
        payload = {'text': text, 'language': 'en-AU', 'client_turn_id': str(uuid4())}
        response = client.post('/v1/agent/turn', json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['conversation_saved']
        replay = client.post('/v1/agent/turn', json={**payload, 'project_id': response.json()['project_id']})
        assert replay.status_code == 200 and replay.json()['cached'], replay.text
    assert len(calls) == 1
    identity = rpc(sql, 'resolve_lifetime_conversation', literal(response.json()['project_id']))
    lane_id = lane(sql, identity)
    page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
    assert page['two_lane']['reply_contract'] == 'reply-v2'
    assert sql('select count(*) from public.user_lifetime_continuity where kind=\'person\';').stdout.strip() == '0'
    return identity, lane_id, page


def extract(sql, page):
    from apps.api.lifetime_memory_composer import _extract
    from apps.api.lifetime_memory_lane_engine import LanePublication
    calls = []
    class Broker:
        async def rpc(self, name, **args):
            query = ','.join(key + '=>' + literal(value) for key, value in args.items())
            return json.loads(sql('set role service_role;select to_jsonb(public.' + name + '(' + query + '));').stdout.splitlines()[-1])
    def provider(request):
        calls.append(request)
        source = page['source']
        output = dict(events=[], place_journeys=[], prepared_questions=[], event_places=[], passage_dispositions=[],
            strategy_proposal=dict(strategy='explore', objective='follow_story', focus_event_ids=[]),
            continuity_updates=[dict(kind='person', text='Ming', quote='Ming', assertion='asserted',
                uncertainty=None, source_id=source['id'], source_version=source['version'],
                char_start=None, char_end=None)])
        return httpx.Response(200, json={'reply': json.dumps(output), 'thread_id': 'memory', 'artifacts': []})
    worker = SimpleNamespace(broker=Broker(), worker_url='http://controlled.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(provider),
        lane_publisher=LanePublication(sql.publication_dsn, authenticated_owner=OWNER))
    return asyncio.run(_extract(page, worker)), calls


def commit(sql, lane_id, page, result):
    return service(sql, 'commit_lifetime_memoir_lane_page',
        f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")


def test_saved_reply_hands_descriptive_work_to_one_b_pass_with_exact_replay(sql, tmp_path, monkeypatch):
    identity, lane_id, page = saved_turn(sql, tmp_path, monkeypatch)
    result, calls = extract(sql, page)
    assert len(calls) == 1
    assert result['continuity_updates'][0]['data']['text'] == 'Ming'
    committed = commit(sql, lane_id, page, result)
    assert committed['status'] == 'page_saved'
    assert sql("select count(*) from public.user_lifetime_continuity where kind='person';").stdout.strip() == '1'
    assert commit(sql, lane_id, page, result) == {'status': 'page_saved', 'replayed': True}
    changed = deepcopy(result)
    changed['continuity_updates'] = []
    with pytest.raises(AssertionError):
        commit(sql, lane_id, page, changed)
    assert sql('select count(*) from public.user_lifetime_source_extraction;').stdout.strip() == '1'


@pytest.mark.parametrize('fault', ['foreign_source', 'bad_span', 'privacy', 'missing', 'oversized', 'oversized_text', 'stale_source'])
def test_bad_b_continuity_cannot_commit_or_advance_coverage(sql, tmp_path, monkeypatch, fault):
    identity, lane_id, page = saved_turn(sql, tmp_path, monkeypatch,
        text='My brother Ming' + ' '*501 + 'moved to Perth.' if fault == 'oversized_text' else 'My brother Ming moved to Perth.')
    result, _ = extract(sql, page)
    ref = result['continuity_updates'][0]['data']['source_refs'][0]
    if fault == 'foreign_source': ref['source_id'] = str(uuid4())
    elif fault == 'bad_span': ref['char_start'] += 1
    elif fault == 'privacy': result['continuity_updates'][0]['kind'] = 'excluded_topic'
    elif fault == 'missing': result.pop('continuity_updates')
    elif fault == 'oversized': result['continuity_updates'] *= 9
    elif fault == 'oversized_text':
        ref.update(quote='Ming' + ' '*501 + 'moved', char_start=11, char_end=521)
        result['continuity_updates'][0]['data']['text'] = ref['quote']
    else:
        rpc(sql, 'change_user_narrator_source', f"{literal(identity['project_id'])},'{page['source']['id']}',1,'withdraw',null")
    with pytest.raises(AssertionError):
        commit(sql, lane_id, page, result)
    assert sql("select count(*) from public.user_lifetime_continuity where kind='person';").stdout.strip() == '0'
    assert sql('select count(*) from public.user_lifetime_source_extraction;').stdout.strip() == '0'


def test_name_only_reply_preserves_chosen_name_and_b_skips_model_work(sql, tmp_path, monkeypatch):
    identity, lane_id, page = saved_turn(sql, tmp_path, monkeypatch, text='My name is Avery.', name='Avery')
    assert page['two_lane']['work_mode'] == 'reply_only'
    result, calls = extract(sql, page)
    assert not calls and result['continuity_updates'] == []
    assert commit(sql, lane_id, page, result)['status'] == 'page_saved'
    pins = rpc(sql, 'read_lifetime_pinned', literal(identity['conversation_id']))
    assert pins['chosen_name'] == 'Avery'


def test_name_update_with_new_story_is_committed_before_b_runs(sql, tmp_path, monkeypatch):
    identity, lane_id, page = saved_turn(sql, tmp_path, monkeypatch,
        text='Please call me Avery. My brother Ming moved to Perth.', name='Avery', mode='extract')
    assert page['two_lane']['work_mode'] == 'extract'
    pins = rpc(sql, 'read_lifetime_pinned', literal(identity['conversation_id']))
    assert pins['chosen_name'] == 'Avery'
    assert sql('select count(*) from public.user_lifetime_source_extraction;').stdout.strip() == '0'


def test_current_name_proposal_preserves_existing_manual_authority(sql, tmp_path, monkeypatch):
    sql(as_user("update public.user_profile set profile=jsonb_set(profile,'{name}','\"Manual name\"');"))
    identity, _, _ = saved_turn(sql, tmp_path, monkeypatch,
        text='Please call me Avery. My brother Ming moved to Perth.', name='Avery', mode='extract')
    pins = rpc(sql, 'read_lifetime_pinned', literal(identity['conversation_id']))
    assert pins['chosen_name'] == 'Manual name'


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('withdrawn', [False, True])
def test_photo_identification_preserves_publication_fences_and_canonical_projection(sql, tmp_path, monkeypatch, locale, withdrawn):
    from functools import wraps
    from apps.api.canonical_composer import composer_request
    identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
    project = identity['project_id']
    photo = dict(key='https://example.org/gate.jpg', image_url='https://example.org/gate.jpg', title='Gate')
    profile = dict(preferred_language=locale,
        photo_memories={project: dict(favorites=[photo], selected=photo['key'], selection_revision='cue-1')})
    sql(as_user(f"insert into public.user_profile(user_id,profile) values('{OWNER}',{literal(profile)}::jsonb) "
        "on conflict(user_id) do update set profile=excluded.profile;"))
    text = ('I recognise this gate in the photo from visiting with my mother.' if locale == 'en-AU'
        else '我认得这张照片里的门，以前跟母亲一起去过。')
    def provider(request):
        context = json.loads(request.content)['interview_context']
        source, accepted_photo = context['source'], context['photo_context'][0]
        output = proposal()
        output.update(acknowledgement=('You recognise the gate from visits with your mother.' if locale == 'en-AU'
            else '您认得和母亲一起去过的那座门。'),
            question=('What else do you remember about those visits?' if locale == 'en-AU'
                else '关于那些游览，您还记得什么？'), quote=source['text'],
            associations=[dict(photo_id=accepted_photo['photo_id'], event_id=None, source_id=source['id'],
                source_version=source['version'], quote=source['text'], description=text, provenance='narrator_metadata')],
            response_photo_ids=[accepted_photo['photo_id']])
        if withdrawn:
            rpc(sql, 'change_user_narrator_source', f"{literal(project)},{literal(source['id'])},1,'withdraw',null")
        return httpx.Response(200, json={'reply': json.dumps(output), 'thread_id': 'small-photo-reply', 'artifacts': []})
    sql_errors = []
    @wraps(sql)
    def observed_sql(*args, **kwargs):
        result = sql(*args, **kwargs)
        if result.returncode:
            sql_errors.append(result.stderr)
        return result
    client = client_fixture(observed_sql, tmp_path, monkeypatch, provider)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    with client:
        response = client.post('/v1/agent/turn', json=dict(project_id=project, text=text, language=locale,
            client_turn_id=str(uuid4()), photo_selection=dict(key=photo['key'], revision='cue-1')))
        if withdrawn:
            assert response.status_code in {409, 503}, response.text
            assert sql('select count(*) from public.user_interview_photo_link;').stdout.strip() == '0'
            assert sql('select count(*) from public.user_memory;').stdout.strip() == '0'
            return
        assert response.status_code == 200, response.text + '\n' + '\n'.join(sql_errors)
        saved = response.json()
        assert saved['conversation_saved'] and saved['photo_cue']['consumed']
    source_id = saved['accepted_source_id']
    source = json.loads(sql(as_user(f"select to_jsonb(s) from public.user_narrator_source s where id={literal(source_id)};"))
        .stdout.splitlines()[-1])
    assert source['text'] == text
    events = [dict(kind='event', title='Gate visits', source_refs=[dict(source_id=source_id, version=source['version'], quote=text)])]
    view = rpc(sql, 'apply_user_memory_events',
        f"{literal(project)},{literal([dict(id=source_id, version=source['version'])])}::jsonb,{literal(events)}::jsonb")
    event = next(item for item in view['events'] if item['title'] == 'Gate visits')
    assert event['photo_associations'][0]['quote'] == text
    packet = dict(project_id=project, sources=view['sources'], events=view['events'], locale=locale,
        policy_epoch=1, base_revision=0, coverage_round=5, previous=None,
        source_manifest=[dict(id=item['id'], version=item['version']) for item in view['sources']],
        event_manifest=[dict(id=item['id'], revision=item['revision']) for item in view['events']])
    assert composer_request(packet)['context']['photo_associations'][0]['quote'] == text


@pytest.mark.parametrize('misconfiguration', ['invalid_prompt', 'missing_two_lanes'])
def test_saved_reply_replays_without_resolving_new_generation_configuration(sql, tmp_path, monkeypatch, misconfiguration):
    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(200, json={'reply': json.dumps(proposal()), 'thread_id': 'saved-reply', 'artifacts': []})
    client = client_fixture(sql, tmp_path, monkeypatch, provider)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    with client:
        payload = dict(text='My brother Ming moved to Perth.', language='en-AU', client_turn_id=str(uuid4()))
        saved = client.post('/v1/agent/turn', json=payload)
        assert saved.status_code == 200, saved.text
        if misconfiguration == 'invalid_prompt':
            monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'invalid')
        else:
            monkeypatch.setenv('MEMOIR_TWO_LANES', '0')
        replay = client.post('/v1/agent/turn', json={**payload, 'project_id': saved.json()['project_id']})
        assert replay.status_code == 200, replay.text
        assert replay.json()['cached'] and replay.json()['reply'] == saved.json()['reply']
    assert len(calls) == 1


@pytest.mark.parametrize('streaming', [False, True])
def test_reply_v2_without_two_lanes_rejects_before_source_acceptance(sql, tmp_path, monkeypatch, streaming):
    def provider(request):
        pytest.fail('Invalid generation settings must reject before provider admission')
    client = client_fixture(sql, tmp_path, monkeypatch, provider)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    monkeypatch.setenv('MEMOIR_TWO_LANES', '0')
    with client:
        response = client.post('/v1/agent/turn', json=dict(text='My brother Ming moved to Perth.',
            language='en-AU', client_turn_id=str(uuid4())),
            headers={'accept': 'application/x-ndjson' if streaming else 'application/json'})
        if streaming:
            events = [json.loads(line) for line in response.text.splitlines()]
            assert [event['type'] for event in events] == ['started', 'error']
        else:
            assert response.status_code == 503, response.text
            assert response.headers['X-Error-Code'] == 'COLLECTOR_CONFIGURATION_INVALID'
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip() == '0'
