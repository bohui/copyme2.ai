"""Explicit historical-guidance setup for retained storage and privacy validators.

Current projects never install these legacy scheduling triggers. These fixtures
exercise old records independently of the current background-agent catalog.
"""
import asyncio
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from apps.api.interview_guidance import validate_guidance_result
from test_agent_commit_postgres import OWNER, OTHER
from test_background_profile_workflow import database
from test_conversation_attribution import Conversation, empty, episode
from test_lifetime_memory_postgres import event_database, private_database, attachment_database
from test_shared_memory_events_postgres import sql, rpc, literal
from test_lifetime_composer_capacity import service

@pytest.fixture(autouse=True)
def activate_guidance_pool(sql):
    sql('update public.lifetime_two_lane_rollout set enabled=true,strategy_enabled=false,strategy_shadow=false;')
    sql('create trigger memoir_legacy_test_original after update of processing_status on public.user_narrator_source for each row execute function public.enqueue_lifetime_interview_guidance();')
    sql('create trigger memoir_legacy_test_news after insert or update on public.user_historical_news_clue for each row execute function public.enqueue_lifetime_interview_guidance();')
    try:
        yield
    finally:
        sql('drop trigger memoir_legacy_test_original on public.user_narrator_source; drop trigger memoir_legacy_test_news on public.user_historical_news_clue;')


STORY = 'My father wore a red coat. I also remember it as blue. Helping my family mattered to me.'


def extraction(packet):
    return {**empty(packet), 'events':[episode(packet,packet['sources'][0]['text'],title='Family memories')]}


def guidance(packet, kind, *, recall=False):
    source = packet['guidance_context']['source_windows'][0]
    def ref(quote):
        return dict(source_id=source['id'],version=source['version'],quote=quote,
            char_start=None,char_end=None,attribution=None)
    question = {'conflict':'Do you recall whether that coat was red or blue?',
        'clarification':'Are both coat memories about your father?',
        'historical_news':'Does this public fair remind you of life in Boston then?',
        'topic_transition':'How did helping your father shape what you did together later?',
        'life_essence':'What has helping your family meant to you?',
        'follow_up':'What else do you remember about your father?'}[kind]
    signal = dict(kind=kind,source_refs=[ref(source['text'])],detail_question_ids=[],recall_limit_quote=None)
    if kind == 'conflict':signal['source_refs']=[ref('red coat'),ref('blue')]
    if kind == 'topic_transition':
        signal['detail_question_ids']=[p['question']['id'] for p in packet['guidance_context']['recent_dialogue']][:3]
        if recall:signal['recall_limit_quote']='记不太清了'
    ack = dict(text='Helping your family seems to be a meaningful thread in these memories.',
        source_refs=[ref('Helping my family mattered to me.')]) if kind == 'life_essence' else None
    raw = dict(signals=[signal],prepared_questions=[dict(question=question,topic='Family memories',
        quote=source['text'],char_start=None,char_end=None,requires_confirmation=kind in {'conflict','clarification'},
        scope='broader' if kind in {'historical_news','topic_transition','life_essence'} else 'detail',
        source_id=source['id'],source_version=source['version'],trigger=kind,
        historical_clue_id=packet['guidance_context']['news_clues'][0]['id'] if kind == 'historical_news' else None,
        bridge='A public event from the period you described.' if kind == 'historical_news' else '')],
        acknowledgement_guidance=ack,strategy_proposal=None)
    return validate_guidance_result(raw,packet)


def identity(conversation):
    return rpc(conversation.sql,'resolve_lifetime_conversation',literal(conversation.project))


def pool(conversation):
    return rpc(conversation.sql,'read_lifetime_prepared_questions',f"'{identity(conversation)['conversation_id']}'")


def install_news(conversation):
    from apps.api.historical_news import accepted_hypothesis, validate_evidence
    from test_historical_news import evidence,receipt
    basis=rpc(conversation.sql,'read_user_historical_news_basis',literal(conversation.project))
    hypothesis=accepted_hypothesis(basis)
    assert hypothesis
    record=validate_evidence(evidence(),receipt(),dict(url=evidence()['source_url'],text=evidence()['excerpt'],
        retrieved_at='2026-10-26T00:00:00Z',source_title='Town archive',publisher='Town library',publication_date='2020-01-01'),hypothesis)
    conversation.sql(f"insert into public.user_historical_news_clue values('{OWNER}',{literal(conversation.project)},"
        f"{literal(record['id'])},public.historical_news_revision('{OWNER}',{literal(conversation.project)}),'ready',"
        f"{literal(record)},{literal(hypothesis)});")
    return record




def drain_timeline(conversation):
    lane=conversation.sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
    for _ in range(64):
        outcome=asyncio.run(conversation.worker.execute_lane(lane))
        if outcome.get('retrieval_complete') or outcome['status'] in {'finished','deferred'}:
            return outcome
    pytest.fail('Timeline did not settle')


def claimed_guidance(conversation):
    lane=conversation.sql("select id from public.user_memoir_lane where skill='guidance';").stdout.strip()
    page=service(conversation.sql,'claim_memoir_lane',f"'{lane}',300")
    assert page
    return page


def commit_guidance(sql,page,result,*,check=True):
    return sql(f"set role service_role; select public.commit_lifetime_interview_guidance("
        f"'{page['lane_id']}','{page['token']}',{literal(page['page_digest'])},{literal(result)});",check=check)
