"""Privacy boundaries at native guidance reads and the guarded dispatch seam.

All passages and model responses are synthetic. The existing harness owns a
disposable PostgreSQL cluster and replaces every provider with an HTTP fixture.
"""
import asyncio
from copy import deepcopy
import json
import re
from uuid import uuid4

import pytest

from apps.api.interview_guidance import execute_guidance_lane, validate_guidance_result
from test_agent_commit_postgres import OWNER, OTHER, OLD
from test_background_profile_workflow import database, worker_response
from test_conversation_attribution import Conversation, empty, episode, reference
from legacy_guidance_fixtures import (activate_guidance_pool, drain_timeline,
    claimed_guidance, commit_guidance, identity, pool)
from test_lifetime_memory_postgres import event_database, private_database, attachment_database, resolve
from test_shared_memory_events_postgres import sql, rpc, literal


PRIVATE = 'I had a bicycle accident in Chengde.'
CONTROL = ' Do not record this event. '
ALLOWED = 'I worked as a carpenter in Hobart.'
SAFE_QUESTION = 'What do you remember about your carpentry work?'
UNSAFE_QUESTION = 'How did the bicycle accident affect your carpentry work?'
MIXED = '小时候，我喜欢木工。🪚 ' + PRIVATE + CONTROL + ALLOWED


def extract(packet):
    text = packet['sources'][0]['text']
    if PRIVATE not in text:
        return {**empty(packet), 'events': [] if len(text) > 2000 else [episode(packet, text, title='Other memories')]}
    return {**empty(packet), 'events': [episode(packet, ALLOWED, title='Carpentry')],
        'passage_dispositions': [dict(disposition='withheld', reason='privacy_withheld',
            source_ref=reference(packet, PRIVATE + CONTROL))]}


def proposal(packet, question=SAFE_QUESTION):
    source = next(s for s in packet['guidance_context']['source_windows'] if ALLOWED in s['text'])
    ref = dict(source_id=source['id'], version=source['version'], quote=ALLOWED)
    return validate_guidance_result(dict(signals=[dict(kind='follow_up', source_refs=[ref])],
        prepared_questions=[dict(question=question, topic='Carpentry', quote=ALLOWED,
            source_id=source['id'], source_version=source['version'], trigger='follow_up',
            requires_confirmation=False, scope='detail')]), packet)


@pytest.mark.parametrize('path', ['latest', 'tail', 'older', 'fallback', 'indexed', 'dialogue'])
def test_guarded_guidance_excludes_withheld_neighbors_of_an_allowed_citation(sql, tmp_path, monkeypatch, path):
    dispatched = []

    async def boundary(request, provider):
        body = json.loads(request.content)
        if (body.get('bounded_lane') or {}).get('phase') == 'guidance':
            dispatched.append(body)
        return await provider(request)

    def prepare(packet):
        # Reproduce the finding: a model can use private input while citing only
        # the independent allowed anchor. Citation validation alone accepts it.
        question = UNSAFE_QUESTION if PRIVATE in json.dumps(packet) else SAFE_QUESTION
        return proposal(packet, question)

    def extraction(packet):
        result = extract(packet)
        if path == 'fallback' and PRIVATE in packet['sources'][0]['text']:
            result['events'] = []  # Exercise fallback without an event reference.
        return result

    conversation = Conversation(sql, tmp_path, monkeypatch, extraction,
        guidance=prepare, external_boundary=boundary)
    with conversation.client:
        if path == 'dialogue':
            conversation.say('I enjoyed learning a trade.')
        text = ('序' * 2500 + ' ' + MIXED) if path == 'tail' else MIXED
        accepted = conversation.say(text)
        if path == 'indexed':
            for topic in ('singing', 'painting', 'swimming', 'cooking', 'reading',
                          'sailing', 'gardening', 'dancing', 'walking', 'running'):
                conversation.say(f'I enjoyed {topic} with friends.')
        if path in {'older', 'fallback', 'indexed', 'dialogue'}:
            conversation.say('I still remember that carpenter job in Hobart.')
        conversation.drain()
        assert dispatched, conversation.last_db_error
        candidate = pool(conversation)[0]
        response = conversation.say('I would like to continue.')
        assert 'bicycle accident' not in response['reply']
        from test_conversation_reply import proposal as current_reply
        assert response['reply'].endswith(current_reply()['question'])
        assert SAFE_QUESTION not in response['reply'], 'Saved legacy guidance is not a current interviewing instruction'
        assert candidate['question'] == SAFE_QUESTION
        assert PRIVATE not in json.dumps(dispatched, ensure_ascii=False)
        packet = json.loads(dispatched[-1]['bounded_lane']['packet'])['payload']
        windows = [s for s in packet['guidance_context']['source_windows'] if s['id'] == accepted['accepted_source_id']]
        assert any(ALLOWED in s['text'] for s in windows)
        for window in windows:
            assert window['text'] == text[window['char_start']:window['char_end']]
        if path == 'indexed':
            event = sql(f"select event_id from public.user_memory_event_source where source_id='{accepted['accepted_source_id']}';").stdout.strip()
            assert event in packet['guidance_context']['retrieved_event_ids']
        assert candidate['char_start'] == text.index(ALLOWED)


def test_fully_withheld_guidance_finishes_without_model_dispatch(sql, tmp_path, monkeypatch):
    def withheld(packet):
        return {**empty(packet), 'passage_dispositions': [dict(disposition='withheld',
            reason='privacy_withheld', source_ref=reference(packet, packet['sources'][0]['text']))]}
    conversation = Conversation(sql, tmp_path, monkeypatch, withheld)
    with conversation.client:
        conversation.say(PRIVATE)
        conversation.drain()
        assert not [p for phase, p in conversation.admissions if phase == 'guidance']
        assert pool(conversation) == []


def test_latest_allowed_fragments_remain_usable_without_canonical_events(sql, tmp_path, monkeypatch):
    def unresolved(packet):
        result = extract(packet)
        result['events'] = []
        return result
    conversation = Conversation(sql, tmp_path, monkeypatch, unresolved, guidance=proposal)
    with conversation.client:
        conversation.say(MIXED)
        conversation.drain()
        assert pool(conversation)[0]['question'] == SAFE_QUESTION


def restrict(sql, source, spans):
    for start, end, disposition in spans:
        sql(f"""insert into public.user_memory_attribution_window
            (user_id,project_id,source_id,source_version,char_start,char_end,policy_epoch,disposition,reason)
            values('{OWNER}',{literal(source['project_id'])},'{source['id']}',{source['version']},
            {start},{end},1,{literal(disposition)},'privacy_withheld')
            on conflict(user_id,project_id,source_id,source_version,char_start,char_end)
            do update set disposition=excluded.disposition;""")


@pytest.mark.parametrize('spans', [
    [(0, 5, 'withheld')], [(8, 16, 'withheld')], [(20, 26, 'withheld')],
    [(2, 12, 'withheld'), (8, 18, 'withheld')],
    [(2, 8, 'withheld'), (8, 18, 'non_story')],
    [(0, 13, 'withheld'), (13, 26, 'withheld')],
])
def test_authorized_windows_preserve_unicode_boundaries_and_union_restrictions(sql, spans):
    project = resolve(sql)['project_id']
    text = '甲🙂one private two 三 four end'
    source = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}',{literal(text)}")
    restrict(sql, source, spans)
    def windows(owner=OWNER, version=1):
        return json.loads(sql(f"select coalesce(jsonb_agg(w),'[]') from public.lifetime_guidance_source_windows("
            f"'{owner}',{literal(project)},'{source['id']}',{version},0,{len(text)}) w;").stdout)
    actual = windows()
    positions = {index for window in actual for index in range(window['char_start'], window['char_end'])}
    assert positions == {index for index in range(len(text))
        if not any(start <= index < end for start, end, _ in spans)}
    for window in actual:
        assert window['text'] == text[window['char_start']:window['char_end']]
    assert windows(OTHER) == [] and windows(version=2) == []
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{source['id']}',1,'withdraw',null")
    assert windows() == []


def test_private_query_terms_do_not_select_indexed_events(sql):
    project = resolve(sql)['project_id']
    old = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','A bicycle accident happened near Chengde.'")
    events = [dict(kind='event', title='An older memory',
        source_refs=[dict(source_id=old['id'], version=1, quote=old['text'])])]
    manifest = [dict(id=old['id'], version=1)]
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal(manifest)},{literal(events)}")
    current = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}',{literal(MIXED)}")
    arguments = f"'{OWNER}',{literal(project)},'{current['id']}',1"
    def matches():
        return json.loads(sql(f"select coalesce(jsonb_agg(r),'[]') from public.retrieve_lifetime_guidance_events({arguments}) r;").stdout)
    assert matches()  # The same native index finds the public terms before restriction.
    restrict(sql, current, [(MIXED.index(PRIVATE), MIXED.index(ALLOWED), 'withheld')])
    assert matches() == []


@pytest.mark.parametrize('change', ['withdraw', 'policy', 'preferences', 'classification'])
def test_stale_private_span_pages_cannot_dispatch_or_commit(sql, tmp_path, monkeypatch, change):
    conversation = Conversation(sql, tmp_path, monkeypatch, extract, guidance=proposal)
    with conversation.client:
        conversation.say(MIXED)
        drain_timeline(conversation)
        page = claimed_guidance(conversation)
        result = proposal(page)
        if change == 'withdraw':
            rpc(sql, 'change_user_narrator_source', f"{literal(conversation.project)},'{page['source']['id']}',1,'withdraw',null")
        elif change == 'policy':
            sql('update public.user_memoir_project set policy_epoch=policy_epoch+1;')
        elif change == 'preferences':
            sql('update public.user_lifetime_conversation set preference_revision=preference_revision+1;')
        else:
            source = dict(id=page['source']['id'], version=1, project_id=conversation.project)
            restrict(sql, source, [(MIXED.index(ALLOWED), len(MIXED), 'withheld')])
        with pytest.raises(AssertionError, match='Disposable provider admission'):
            asyncio.run(execute_guidance_lane(page, conversation.worker))
        assert not [p for phase, p in conversation.admissions if phase == 'guidance']
        assert commit_guidance(sql, page, result, check=False).returncode != 0
        assert pool(conversation) == []


def test_schema_retry_and_native_commit_replay_keep_only_authorized_spans(sql, tmp_path, monkeypatch):
    attempts = []
    def prepare(packet):
        attempts.append(deepcopy(packet))
        return {} if len(attempts) == 1 else proposal(packet)
    conversation = Conversation(sql, tmp_path, monkeypatch, extract, guidance=prepare)
    with conversation.client:
        conversation.say(MIXED)
        drain_timeline(conversation)
        page = claimed_guidance(conversation)
        assert asyncio.run(execute_guidance_lane(page, conversation.worker))['status'] == 'finished'
        assert len(attempts) == 2
        second = deepcopy(attempts[1])
        assert second.pop('retry_reason') == 'OUTPUT_SCHEMA'
        assert attempts[0] == second
        assert PRIVATE not in json.dumps(attempts, ensure_ascii=False)
        result = proposal(page)
        assert 'replayed' in commit_guidance(sql, page, result).stdout
        assert len(pool(conversation)) == 1


def test_citations_cannot_join_across_a_private_gap_or_recover_a_hidden_quote(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        conversation.say(MIXED)
        drain_timeline(conversation)
        page = claimed_guidance(conversation)
        for quote in (PRIVATE, MIXED[:MIXED.index(PRIVATE)] + ALLOWED):
            raw = proposal(page)
            for ref in (raw['signals'][0]['source_refs'][0], raw['prepared_questions'][0]):
                ref.update(quote=quote, char_start=0, char_end=len(quote))
            with pytest.raises(ValueError, match='authorized occurrence'):
                validate_guidance_result(raw, page)
            assert commit_guidance(sql, page, raw, check=False).returncode != 0
        assert 'finished' in commit_guidance(sql, page, proposal(page)).stdout


@pytest.mark.parametrize('copy', ['continuity', 'question', 'policy'])
def test_guidance_envelope_does_not_copy_withheld_quotes_from_pins_or_questions(sql, tmp_path, monkeypatch, fixed_policy_controls, copy):
    dispatched = []
    if copy == 'policy':
        fixed_policy_controls.append(('excluded_topic', PRIVATE))
    async def boundary(request, provider):
        body = json.loads(request.content)
        if (body.get('bounded_lane') or {}).get('phase') == 'guidance':
            dispatched.append(body)
        if copy == 'question' and not body.get('bounded_lane'):
            from test_conversation_reply import proposal as collector_proposal
            output = dict(collector_proposal(),question=UNSAFE_QUESTION,quote=PRIVATE)
            return worker_response(request, output)
        return await provider(request)
    conversation = Conversation(sql, tmp_path, monkeypatch, extract, guidance=proposal, external_boundary=boundary)
    with conversation.client:
        accepted = conversation.say(MIXED)
        drain_timeline(conversation)
        if copy == 'continuity':
            who = identity(conversation)
            rpc(sql, 'acquire_user_agent_turn_lease', f"'{OLD}'")
            for key, quote in [('private', PRIVATE), ('allowed', ALLOWED)]:
                ref = dict(source_id=accepted['accepted_source_id'], version=1, quote=quote,
                    char_start=MIXED.index(quote), char_end=MIXED.index(quote)+len(quote))
                data = dict(text=quote, assertion='asserted', uncertainty=None, source_refs=[ref])
                rpc(sql, 'save_lifetime_continuity', f"'{who['conversation_id']}',{literal(key)},'person',0,"
                    f"{sql('select policy_epoch from public.user_memoir_project;').stdout.strip()},'{OLD}',{literal(data)}")
            rpc(sql, 'release_user_agent_turn_lease', f"'{OLD}'")
        conversation.drain()
        if copy == 'policy':
            assert not dispatched
            assert pool(conversation) == []
            assert sql("select count(*) from public.user_background_skill_work where phase='guidance' and model_invoked;").stdout.strip() == '0'
            # Original mandatory policy remains intact; only optional guidance skips.
            assert PRIVATE in json.dumps(rpc(sql, 'read_lifetime_pinned', f"'{identity(conversation)['conversation_id']}'"))
            return
        assert dispatched, conversation.last_db_error
        assert PRIVATE not in json.dumps(dispatched, ensure_ascii=False)
        pins = dispatched[-1]['bounded_lane']['fence']['preferences']
        if copy == 'continuity':
            assert len(pins['known_continuity']) == 1
            assert re.fullmatch(r'ct-[0-9a-f]{64}', pins['known_continuity'][0]['record_id'])
            assert pins['known_continuity'][0]['data']['text'] == ALLOWED
            assert pins['known_continuity_complete'] is False
        else:
            assert pins['active_question'] is None
            packet = json.loads(dispatched[-1]['bounded_lane']['packet'])['payload']
            for item in packet['guidance_context']['recent_dialogue']:
                assert item['question']['delivered'] is True and item['question']['id']
                assert item['question']['text'] is None and item['question']['evidence'] is None
