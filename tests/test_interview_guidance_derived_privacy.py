"""Derived prose cannot acquire permission through a different allowed citation."""
import asyncio
import json
import re

import pytest

from test_agent_commit_postgres import OLD
from test_background_profile_workflow import database
from test_conversation_attribution import Conversation
from test_interview_guidance_privacy import (PRIVATE, ALLOWED, MIXED, SAFE_QUESTION,
    UNSAFE_QUESTION, extract, proposal)
from test_interview_guidance_workflow import (activate_guidance_pool, drain_timeline,
    claimed_guidance, commit_guidance, identity, pool)
from apps.api.interview_guidance import execute_guidance_lane
from test_lifetime_memory_postgres import event_database, private_database, attachment_database
from test_shared_memory_events_postgres import sql, rpc, literal


@pytest.mark.parametrize('field,reply_v2', [('event_title', False), ('event_uncertainty', False),
    ('continuity_text', False), ('continuity_uncertainty', False), ('continuity_uncertainty', True)])
@pytest.mark.parametrize('poison', [PRIVATE, 'A cycling crash in Chengde left me injured.'])
def test_derived_prose_with_allowed_citations_cannot_enter_guidance_or_the_next_reply(sql, tmp_path, monkeypatch, field, reply_v2, poison):
    if reply_v2:
        monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    dispatched = []
    async def boundary(request, provider):
        body = json.loads(request.content)
        if (body.get('bounded_lane') or {}).get('phase') == 'guidance':
            dispatched.append(body)
        return await provider(request)
    def extraction(packet):
        result = extract(packet)
        if field.startswith('event_'):
            result['events'][0][field.removeprefix('event_')] = poison
        if reply_v2:
            source = packet['sources'][0]
            start = source['char_start'] + source['text'].index(ALLOWED)
            result['continuity_updates'] = [dict(kind='person', text=ALLOWED, assertion='asserted',
                uncertainty=poison, source_id=source['id'], source_version=source['version'],
                quote=ALLOWED, char_start=start, char_end=start+len(ALLOWED))]
        return result
    def prepare(packet):
        question = UNSAFE_QUESTION if poison in json.dumps(dispatched[-1], ensure_ascii=False) else SAFE_QUESTION
        return proposal(packet, question)
    conversation = Conversation(sql, tmp_path, monkeypatch, extraction, guidance=prepare, external_boundary=boundary)
    with conversation.client:
        accepted = conversation.say(MIXED)
        drain_timeline(conversation)
        if field.startswith('continuity_') and not reply_v2:
            who = identity(conversation)
            ref = dict(source_id=accepted['accepted_source_id'], version=1, quote=ALLOWED,
                char_start=MIXED.index(ALLOWED), char_end=MIXED.index(ALLOWED)+len(ALLOWED))
            data = dict(text=ALLOWED, assertion='asserted', uncertainty=None, source_refs=[ref])
            data[field.removeprefix('continuity_')] = poison
            rpc(sql, 'acquire_user_agent_turn_lease', f"'{OLD}'")
            epoch = sql('select policy_epoch from public.user_memoir_project;').stdout.strip()
            rpc(sql, 'save_lifetime_continuity', f"'{who['conversation_id']}','derived','person',0,{epoch},'{OLD}',{literal(data)}")
            rpc(sql, 'release_user_agent_turn_lease', f"'{OLD}'")
        conversation.drain()
        assert dispatched, conversation.last_db_error
        # Confirm native evidence is allowed, while the derived text is private.
        if field.startswith('event_'):
            original = json.loads(sql('select data from public.user_memory_event;').stdout)
            assert original[field.removeprefix('event_')] == poison
            evidence = json.loads(sql('select evidence from public.user_memory_event_source;').stdout)
        else:
            original = json.loads(sql("select data from public.user_lifetime_continuity where kind='person';").stdout)
            assert original[field.removeprefix('continuity_')] == poison
            evidence = original['source_refs'][0]
        assert evidence['quote'] == ALLOWED
        response = conversation.say('I would like to continue.')
        assert 'bicycle accident' not in response['reply']
        assert response['reply'].endswith(SAFE_QUESTION)
        assert pool(conversation) == []
        assert poison not in json.dumps(dispatched, ensure_ascii=False)
        packet = json.loads(dispatched[-1]['bounded_lane']['packet'])['payload']
        allowed = next(w for w in packet['guidance_context']['source_windows'] if ALLOWED in w['text'])
        assert allowed['text'] == MIXED[allowed['char_start']:allowed['char_end']]


@pytest.mark.parametrize('mode', ['budget_full', 'already_present'])
def test_fragmented_latest_source_reserves_an_authorized_tail_for_recall_limits(sql, tmp_path, monkeypatch, mode):
    recall = 'I cannot remember the date.'
    secrets = [f'Private-only detail number {n}.' for n in range(8)]
    head = ALLOWED + ' ' + ' '.join(f'Allowed detail {n}. {secret}' for n, secret in enumerate(secrets))
    text = head + ' ' + '延' * 3000 + ' ' + recall
    if mode == 'already_present':
        secrets = secrets[:1]
        text = ALLOWED + ' ' + '延' * 3000 + ' ' + secrets[0] + ' ' + recall
    dispatched = []
    async def boundary(request, provider):
        body = json.loads(request.content)
        if (body.get('bounded_lane') or {}).get('phase') == 'guidance':
            dispatched.append(body)
        return await provider(request)
    def extraction(packet):
        from test_conversation_attribution import empty, episode, reference
        source = packet['sources'][0]['text']
        return {**empty(packet), 'events': [episode(packet, ALLOWED, title='Carpentry')] if ALLOWED in source else [],
            'passage_dispositions': [dict(disposition='withheld', reason='privacy_withheld',
                source_ref=reference(packet, secret)) for secret in secrets if secret in source]}
    def prepare(packet):
        result = proposal(packet)
        if recall in packet['source']['text']:
            result['signals'][0].update(kind='topic_transition', recall_limit_quote=recall)
            result['prepared_questions'][0].update(trigger='topic_transition', scope='broader')
        return result
    conversation = Conversation(sql, tmp_path, monkeypatch, extraction, guidance=prepare, external_boundary=boundary)
    with conversation.client:
        conversation.say(text)
        conversation.drain()
        assert dispatched, conversation.last_db_error
        packet = json.loads(dispatched[-1]['bounded_lane']['packet'])['payload']
        windows = packet['guidance_context']['source_windows']
        assert recall in packet['source']['text']
        assert len(windows) <= 8 and any(ALLOWED in w['text'] for w in windows)
        assert all(secret not in json.dumps(dispatched) for secret in secrets)
        for window in windows:
            assert window['text'] == text[window['char_start']:window['char_end']]
        assert pool(conversation)[0]['trigger'] == 'topic_transition'


def test_private_collector_ids_become_stable_opaque_delivered_identities(sql, tmp_path, monkeypatch):
    dispatched, results = [], []
    collector_calls = 0
    async def boundary(request, provider):
        nonlocal collector_calls
        body = json.loads(request.content)
        if (body.get('bounded_lane') or {}).get('phase') == 'guidance':
            dispatched.append(body)
        response = await provider(request)
        if not body.get('bounded_lane'):
            collector_calls += 1
            if collector_calls <= 3:
                from test_background_profile_workflow import worker_response
                output = json.loads(response.json()['reply'])
                output['plan']['candidates'][0]['id'] = PRIVATE
                output['plan']['chosen_id'] = PRIVATE
                return worker_response(request, output)
        return response
    def prepare(packet):
        unsafe = PRIVATE in json.dumps(dispatched[-1], ensure_ascii=False)
        result = proposal(packet, UNSAFE_QUESTION if unsafe else SAFE_QUESTION)
        if not unsafe:
            ids = [item['question']['id'] for item in packet['guidance_context']['recent_dialogue']][:3]
            result['signals'][0].update(kind='topic_transition', detail_question_ids=ids)
            result['prepared_questions'][0].update(trigger='topic_transition', scope='broader')
        results.append(result)
        return result
    conversation = Conversation(sql, tmp_path, monkeypatch, extract, guidance=prepare, external_boundary=boundary)
    with conversation.client:
        for _ in range(3):
            conversation.say(MIXED)
        drain_timeline(conversation)
        page = claimed_guidance(conversation)
        async def run():
            again = await conversation.worker.broker.rpc('read_lifetime_interview_guidance_page',
                p_lane_id=page['lane_id'], p_token=page['token'])
            assert again['guidance_context']['recent_dialogue'] == page['guidance_context']['recent_dialogue']
            return await execute_guidance_lane(page, conversation.worker)
        assert asyncio.run(run())['status'] == 'finished'
        assert 'replayed' in commit_guidance(sql, page, results[-1]).stdout
        original = json.loads(sql(f"select public.lifetime_question_dialogue('{page['user_id']}',{literal(conversation.project)});").stdout)
        assert {item['question']['id'] for item in original} == {PRIVATE}
        response = conversation.say('I would like to continue.')
        assert 'bicycle accident' not in response['reply']
        assert PRIVATE not in json.dumps(dispatched, ensure_ascii=False)
        ids = [item['question']['id'] for item in page['guidance_context']['recent_dialogue']]
        assert len(set(ids)) == 3 and all(re.fullmatch(r'dq-[0-9a-f]{64}', value) for value in ids)
        assert response['reply'].endswith(SAFE_QUESTION)
        assert pool(conversation) == []
