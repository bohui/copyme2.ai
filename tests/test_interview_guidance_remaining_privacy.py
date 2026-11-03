"""Supported continuity IDs and fully withheld suffixes stay outside guidance."""
import asyncio
import json
import re

import pytest

from apps.api.interview_guidance import validate_guidance_result
from test_agent_commit_postgres import OLD
from test_background_profile_workflow import database
from test_conversation_attribution import Conversation, empty, episode, reference
from test_interview_guidance_privacy import (PRIVATE, ALLOWED, MIXED, SAFE_QUESTION,
    UNSAFE_QUESTION, extract, proposal)
from legacy_guidance_fixtures import (activate_guidance_pool, drain_timeline,
    claimed_guidance, commit_guidance, identity, pool)
from test_lifetime_memory_postgres import event_database, private_database, attachment_database
from test_shared_memory_events_postgres import sql, rpc, literal


@pytest.mark.parametrize('identifier', [PRIVATE, 'A cycling crash in Chengde left me injured.'])
def test_supported_continuity_ids_have_stable_opaque_guidance_identity(sql, tmp_path, monkeypatch, identifier):
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        accepted = conversation.say(MIXED)
        drain_timeline(conversation)
        who = identity(conversation)
        ref = dict(source_id=accepted['accepted_source_id'], version=1, quote=ALLOWED,
            char_start=MIXED.index(ALLOWED), char_end=MIXED.index(ALLOWED)+len(ALLOWED))
        data = dict(text=ALLOWED, assertion='asserted', uncertainty=None, source_refs=[ref])
        epoch = sql('select policy_epoch from public.user_memoir_project;').stdout.strip()
        def save(revision):
            rpc(sql, 'acquire_user_agent_turn_lease', f"'{OLD}'")
            rpc(sql, 'save_lifetime_continuity', f"'{who['conversation_id']}',{literal(identifier)},'person',"
                f"{revision},{epoch},'{OLD}',{literal(data)}")
            rpc(sql, 'release_user_agent_turn_lease', f"'{OLD}'")
        save(0)
        before = claimed_guidance(conversation)
        async def read():
            return await conversation.worker.broker.rpc('read_lifetime_interview_guidance_page',
                p_lane_id=before['lane_id'], p_token=before['token'])
        same = asyncio.run(read())
        assert same['preferences'] == before['preferences']
        data['uncertainty'] = 'Still unclear.'
        save(1)
        page = asyncio.run(read())
        old = before['preferences']['known_continuity'][0]
        current = page['preferences']['known_continuity'][0]
        assert current['record_id'] == old['record_id'] and current['revision'] == 2
        assert commit_guidance(sql, before, proposal(before), check=False).returncode != 0
        result = proposal(page)
        assert 'finished' in commit_guidance(sql, page, result).stdout
        assert 'replayed' in commit_guidance(sql, page, result).stdout
        original = rpc(sql, 'read_lifetime_pinned', f"'{who['conversation_id']}'")
        assert original['known_continuity'][0]['record_id'] == identifier
        response = conversation.say('I would like to continue.')
        assert 'bicycle accident' not in response['reply']
        from test_conversation_reply import proposal as current_reply
        assert response['reply'].endswith(current_reply()['question'])
        assert identifier not in json.dumps(page, ensure_ascii=False)
        assert re.fullmatch(r'ct-[0-9a-f]{64}', current['record_id'])
        assert current['data']['text'] == ALLOWED and current['data']['source_refs'][0]['quote'] == ALLOWED
        assert pool(conversation)[0]['question']==SAFE_QUESTION


def test_latest_authorized_tail_precedes_a_fully_withheld_original_suffix(sql, tmp_path, monkeypatch):
    recall = 'I cannot recall the details, but I would like to discuss the garden.'
    secrets = [f'Private segment {i}. ' for i in range(8)]
    text = ''.join(f'Allowed fragment {i}. {secret}' for i, secret in enumerate(secrets)) + '序'*1000 + ' ' + recall + '密'*2400
    anchor = 'Allowed fragment 0.'
    assert len(text) == 3781 and (text.index(recall), text.index(recall)+len(recall)) == (1313, 1381)
    def extraction(packet):
        source = packet['sources'][0]
        words = source['text']
        dispositions = [dict(disposition='withheld', reason='privacy_withheld', source_ref=reference(packet, secret))
            for secret in secrets if secret in words]
        start = words.find('密')
        if start >= 0:
            for lo in range(start, len(words), 1000):
                hi = min(len(words), lo+1000)
                ref = dict(source_id=source['id'], version=source['version'], quote=words[lo:hi],
                    char_start=lo, char_end=hi)
                dispositions.append(dict(disposition='withheld', reason='privacy_withheld', source_ref=ref))
        return {**empty(packet), 'events': [episode(packet, anchor, title='Allowed fragments')] if anchor in words else [],
            'passage_dispositions': dispositions}
    def prepare(packet):
        source = next(w for w in packet['guidance_context']['source_windows'] if anchor in w['text'])
        transition = recall in packet['source']['text']
        kind = 'topic_transition' if transition else 'follow_up'
        return validate_guidance_result(dict(signals=[dict(kind=kind,
            source_refs=[dict(source_id=source['id'], version=source['version'], quote=anchor)],
            recall_limit_quote=recall if transition else None)], prepared_questions=[dict(
                question='What would you like to tell me about the garden?', topic='Garden', quote=anchor,
                source_id=source['id'], source_version=source['version'], trigger=kind,
                requires_confirmation=False, scope='broader' if transition else 'detail')]), packet)
    conversation = Conversation(sql, tmp_path, monkeypatch, extraction)
    with conversation.client:
        accepted = conversation.say(text)
        drain_timeline(conversation)
        page = claimed_guidance(conversation)
        packet = page
        windows = packet['guidance_context']['source_windows']
        assert recall in packet['source']['text']
        assert packet['source']['char_end'] == 1381 and len(windows) <= 8
        assert any(anchor in w['text'] for w in windows)
        assert all(secret not in json.dumps(page) for secret in secrets)
        assert '密' not in json.dumps(page, ensure_ascii=False)
        for window in windows:
            assert window['text'] == text[window['char_start']:window['char_end']]
        assert 'finished' in commit_guidance(sql, page, prepare(page)).stdout
        assert pool(conversation)[0]['trigger'] == 'topic_transition'
        assert conversation.attribution(accepted['accepted_source_id'])['complete']


def test_opaque_continuity_identity_growth_keeps_the_bounded_working_set_usable(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        text = ALLOWED + ' ' + 'note. '*160
        accepted = conversation.say(text)
        drain_timeline(conversation)
        who = identity(conversation)
        quote = text[len(ALLOWED)+1:len(ALLOWED)+1+860]
        ref = dict(source_id=accepted['accepted_source_id'], version=1, quote=quote,
            char_start=len(ALLOWED)+1, char_end=len(ALLOWED)+1+len(quote))
        data = dict(text=quote, assertion='asserted', uncertainty=None, source_refs=[ref])
        epoch = sql('select policy_epoch from public.user_memoir_project;').stdout.strip()
        rpc(sql, 'acquire_user_agent_turn_lease', f"'{OLD}'")
        for number in range(4):
            rpc(sql, 'save_lifetime_continuity', f"'{who['conversation_id']}','c{number}','person',0,{epoch},'{OLD}',{literal(data)}")
        rpc(sql, 'release_user_agent_turn_lease', f"'{OLD}'")
        original = rpc(sql, 'read_lifetime_pinned', f"'{who['conversation_id']}'")
        assert len(original['known_continuity']) == 4
        drain_timeline(conversation)
        page = claimed_guidance(conversation)
        pins = page['preferences']
        assert len(pins['known_continuity']) == 3 and pins['known_continuity_complete'] is False
        assert len(json.dumps(pins['known_continuity'], separators=(',', ':')).encode()) <= 8192
        assert 'finished' in commit_guidance(sql, page, proposal(page)).stdout
        assert pool(conversation)[0]['question'] == SAFE_QUESTION
