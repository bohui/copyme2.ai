"""Real canonical lanes and next-turn replies; only model/public-source output is controlled."""
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


@pytest.mark.parametrize('contract',['reply-v2','strategy'])
@pytest.mark.parametrize('kind',['conflict','clarification','historical_news','topic_transition','life_essence','follow_up'])
def test_new_skill_generates_next_turn_context_without_writing_facts(sql,tmp_path,monkeypatch,kind,contract):
    active = {'kind':kind}
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    if kind=='life_essence':monkeypatch.setenv('MEMORY_SPARK_EARLY_POLICY_ACK','1')
    def prepare(packet):
        if active['kind'] == 'topic_transition' and len(packet['guidance_context']['recent_dialogue'])<3:
            return dict(signals=[],prepared_questions=[],acknowledgement_guidance=None,strategy_proposal=None)
        if active['kind'] == 'historical_news' and not packet['guidance_context']['news_clues']:
            return dict(signals=[],prepared_questions=[],acknowledgement_guidance=None,strategy_proposal=None)
        return guidance(packet,active['kind'])
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,guidance=prepare,
        strategy='explore' if contract=='strategy' else None)
    if contract=='reply-v2':monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS','1')
    with conversation.client:
        first=conversation.say('I was born in Boston, USA, in 1960. '+STORY if kind=='historical_news' else 'My father painted our kitchen. Helping my family mattered to me.' if kind=='life_essence' else STORY)
        assert 'interview_guidance' not in conversation.foreground[0] or conversation.foreground[0]['interview_guidance'] is None
        conversation.drain()
        if kind=='historical_news':
            install_news(conversation)
            conversation.drain()
        if kind=='topic_transition':
            for detail in ('My father painted our kitchen.','I waited beside him.'):
                conversation.say(detail)
                conversation.drain()
        pending=pool(conversation)
        assert pending and pending[0]['trigger']==kind,conversation.last_db_error
        events_before=sql('select count(*) from public.user_memory_event;').stdout
        original_reply=first['reply']
        response=conversation.say('I would like to keep talking about those memories.')
        from apps.api.historical_news import HISTORICAL_INVITATIONS
        expected_question = HISTORICAL_INVITATIONS['en-AU'][0] if kind=='historical_news' else pending[0]['question']
        assert response['reply'].endswith(expected_question)
        if kind=='topic_transition':
            saved=json.loads(sql('select collector from public.user_interview_turn order by created_at desc limit 1;').stdout)
            assert saved['plan']['chosen_id']==pending[0]['id']
            selection=next(step for step in response['trace'] if step['id']=='question-selection')
            assert selection['detail']=='Selected Lane B guidance · connected topic transition'
        assert first['reply']==original_reply
        assert sql('select count(*) from public.user_memory_event;').stdout==events_before
        assert not any(q['id']==pending[0]['id'] for q in pool(conversation))
        if kind=='life_essence':
            assert response['reply'].startswith('Helping your family seems')
            assert conversation.foreground[-1]['interview_guidance']['acknowledgement_guidance']['source_refs']
            assert rpc(sql,'read_lifetime_interview_guidance',f"'{identity(conversation)['conversation_id']}'") is None
        if kind=='historical_news':
            assert response['historical_context']['source_url']=='https://archive.example/fair'
            saved=json.loads(sql('select collector from public.user_interview_turn order by created_at desc limit 1;').stdout)
            assert 'evidence' not in saved['plan']['candidates'][0]['context'] or saved['plan']['candidates'][0]['context']['evidence'] is None
        assert any(phase=='guidance' for phase,_ in conversation.admissions)
        assert not any('prepared_questions' in packet or 'strategy_proposal' in packet for phase,packet in conversation.admissions if phase=='extract')


def test_recall_limit_can_trigger_a_connected_direction_before_three_detail_rounds(sql,tmp_path,monkeypatch):
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,
        guidance=lambda packet:guidance(packet,'topic_transition',recall=True))
    with conversation.client:
        conversation.say('怎么捣乱记不太清了，但我记得跟爸爸一起去买油漆，还一直想帮忙。')
        conversation.drain()
        assert pool(conversation)[0]['scope']=='broader',conversation.last_db_error


def test_conflict_is_ranked_before_other_triggers_but_is_not_a_reply_rewrite_guardrail():
    from apps.api.two_lane_memory import prioritize_question
    from apps.api.interview_strategy import prioritized_candidates
    raw={'acknowledgement':'We can follow that memory.','stopped':False,
        'plan':{'chosen_id':'current','candidates':[{'id':'current','question':'What happened next?'}]}}
    candidates=[dict(id='later',question='A broader question?',trigger='topic_transition',requires_confirmation=False),
        dict(id='urgent',question='Which account was it?',trigger='conflict',requires_confirmation=True)]
    context={'two_lane_memory':True,'reply_contract':'reply-v2','prepared_questions':candidates}
    assert prioritized_candidates(context,candidates)[0]['id']=='urgent'
    assert prioritize_question(deepcopy(raw),context,selection_reason='latest_story')==raw


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


@pytest.mark.parametrize('change',['source','policy','preferences','generation','news'])
def test_stale_guidance_cannot_publish_into_the_next_turn(sql,tmp_path,monkeypatch,change):
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction)
    with conversation.client:
        conversation.say('I was born in Boston, USA, in 1960. '+STORY if change=='news' else STORY)
        drain_timeline(conversation)
        if change=='news':install_news(conversation)
        page=claimed_guidance(conversation)
        result=guidance(page,'clarification')
        if change=='source':
            rpc(sql,'change_user_narrator_source',f"{literal(conversation.project)},'{page['source']['id']}',1,'withdraw',null")
        elif change=='policy':sql('update public.user_memoir_project set policy_epoch=policy_epoch+1;')
        elif change=='preferences':sql('update public.user_lifetime_conversation set preference_revision=preference_revision+1;')
        elif change=='generation':sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
        else:
            sql("update public.user_historical_news_clue set status='rejected';")
        rejected=commit_guidance(sql,page,result,check=False)
        assert rejected.returncode!=0
        assert sql('select count(*) from public.user_lifetime_prepared_question;').stdout.strip()=='0'
        assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='1'


def test_native_writer_rejects_foreign_evidence_and_uninspected_news(sql,tmp_path,monkeypatch):
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction)
    with conversation.client:
        conversation.say(STORY)
        drain_timeline(conversation)
        page=claimed_guidance(conversation)
        raw=guidance(page,'clarification')
        raw['signals'][0]['source_refs'][0]['source_id']=str(uuid4())
        assert commit_guidance(sql,page,raw,check=False).returncode!=0
        raw=guidance(page,'clarification')
        raw['prepared_questions'][0].update(trigger='historical_news',scope='broader',requires_confirmation=False,
            historical_clue_id='news-'+'f'*24)
        raw['signals'][0]['kind']='historical_news'
        assert commit_guidance(sql,page,raw,check=False).returncode!=0
        assert rpc(sql,'read_lifetime_interview_guidance',f"'{identity(conversation)['conversation_id']}'",owner=OTHER,check=False).returncode!=0
        committed=commit_guidance(sql,page,guidance(page,'clarification'))
        assert 'finished' in committed.stdout
        assert 'replayed' in commit_guidance(sql,page,guidance(page,'clarification')).stdout


def test_guidance_failure_does_not_block_timeline_or_immediate_reply(sql,tmp_path,monkeypatch):
    def fail(_packet):raise RuntimeError('Controlled guidance outage')
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,guidance=fail)
    with conversation.client:
        conversation.say(STORY)
        conversation.drain()
        assert sql('select processing_status from public.user_narrator_source;').stdout.strip()=='succeeded'
        assert sql("select error from public.user_memoir_lane where skill='guidance';").stdout.strip()=='MEMOIR_UNAVAILABLE'
        assert conversation.say('I also helped him in the garden.')['conversation_saved']


@pytest.mark.parametrize('kind',['clarification','follow_up'])
def test_late_guidance_does_not_replace_or_regenerate_a_streamed_reply(sql,tmp_path,monkeypatch,kind):
    entered=release=None
    hold={'once':True}
    async def prepare(packet):
        if hold['once']:
            hold['once']=False
            entered.set()
            await release.wait()
        return guidance(packet,kind)
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,guidance=prepare)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    with conversation.client:
        conversation.say(STORY)
        drain_timeline(conversation)
        async def run():
            nonlocal entered,release
            entered,release=asyncio.Event(),asyncio.Event()
            lane=sql("select id from public.user_memoir_lane where skill='guidance';").stdout.strip()
            task=asyncio.create_task(conversation.worker.execute_lane(lane))
            try:
                await asyncio.wait_for(entered.wait(),10)
                response=await asyncio.to_thread(conversation.client.post,'/v1/agent/turn',
                    headers={'accept':'application/x-ndjson'},json=dict(project_id=conversation.project,
                        client_turn_id=str(uuid4()),text='I also helped him in the garden.'))
                events=[json.loads(line) for line in response.text.splitlines()]
                assert not any(e['type'] in {'error','collector_restart'} for e in events)
                assert len([e for e in events if e['type']=='result'])==1
                result=next(e['data'] for e in events if e['type']=='result')
                assert 'both coat memories' not in result['reply']
                assert not conversation.foreground[-1].get('prepared_questions')
                assert len(conversation.foreground)==2
            finally:
                release.set()
                outcome=await task
            assert outcome['status']=='finished'
            assert len([phase for phase,_ in conversation.admissions if phase=='guidance'])==1
            return result
        current=asyncio.run(run())
        question=pool(conversation)[0]['question']
        following=conversation.say('Yes, I would like to continue.')
        assert following['reply'].endswith(question)
        assert 'both coat memories' not in current['reply']
        assert len(conversation.foreground)==3


def test_conflict_retrieves_an_event_from_ten_rounds_earlier_without_full_history(sql,tmp_path,monkeypatch):
    observed=[]
    earlier='爸爸在钢厂退休是1998年。'
    current='爸爸2001年从钢厂退休以后，就经常接我放学。'
    def prepare(packet):
        windows=packet['guidance_context']['source_windows']
        old=next(s for s in windows if earlier in s['text'])
        latest=next(s for s in windows if current in s['text'])
        observed.append(packet)
        references=[dict(source_id=s['id'],version=s['version'],quote=quote) for s,quote in ((old,earlier),(latest,current))]
        raw=dict(signals=[dict(kind='conflict',source_refs=references)],
            prepared_questions=[dict(question='您前面提到1998年，这次说是2001年，都是指爸爸从钢厂退休这件事吗？',
                topic='爸爸退休',quote=current,source_id=latest['id'],source_version=latest['version'],
                trigger='conflict',requires_confirmation=True,scope='detail')])
        return validate_guidance_result(raw,packet)
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,guidance=prepare)
    with conversation.client:
        first=conversation.say(earlier,language='zh-CN')
        for topic in ('我在学校参加了合唱团。','我喜欢在湖边画画。','我第一次学会骑自行车。','我去了海边旅行。',
                      '我和同桌一起做实验。','我养过一只小猫。','我读过一本航海的书。','我开始学习做饭。','我在公园认识了朋友。','我参加了校园运动会。'):
            conversation.say(topic,language='zh-CN')
        latest=conversation.say(current,language='zh-CN')
        conversation.drain()
        assert observed,conversation.last_db_error
        packet=observed[-1]
        assert len(packet['events'])<=8 and len(packet['guidance_context']['source_windows'])<=8
        assert len(json.dumps(packet,ensure_ascii=False).encode())<65536
        old_event=sql(f"select event_id from public.user_memory_event_source where source_id='{first['accepted_source_id']}';").stdout.strip()
        assert old_event in packet['guidance_context']['retrieved_event_ids']
        assert old_event in {e['id'] for e in packet['events']}
        assert pool(conversation)[0]['trigger']=='conflict'
        assert '1998年，这次说是2001年' not in latest['reply']
        response=conversation.say('我还想聊聊爸爸的事。',language='zh-CN')
        assert '1998年，这次说是2001年' in response['reply']


def test_pool_publication_preserves_the_existing_turn_read_set(sql,tmp_path,monkeypatch):
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,
        guidance=lambda packet:guidance(packet,'follow_up'))
    with conversation.client:
        conversation.say(STORY)
        conversation.drain()
        original=pool(conversation)[0]
        sql("update public.user_memoir_lane set pending=true,guidance_revision=guidance_revision+1 where skill='guidance';")
        page=claimed_guidance(conversation)
        lease=str(uuid4())
        assert rpc(sql,'acquire_user_agent_turn_lease',f"'{lease}',60")
        rpc(sql,'accept_two_lane_interview_turn',f"{literal(conversation.project)},'{uuid4()}','I also helped him in the garden.'")
        captured=pool(conversation)
        assert captured[0]['id']==original['id']
        saved=commit_guidance(sql,page,guidance(page,'conflict'))
        assert 'finished' in saved.stdout
        assert pool(conversation)==captured, 'B publication cannot change the current A read set'
        assert sql('select count(*) from public.user_interview_turn where interview_guidance_snapshot is not null;').stdout.strip()=='1'
        assert rpc(sql,'release_user_agent_turn_lease',f"'{lease}'")
        assert pool(conversation)[0]['trigger']=='conflict'
        assert sql('select count(*) from public.user_interview_turn where interview_guidance_snapshot is not null;').stdout.strip()=='0'


@pytest.mark.parametrize('contract',['reply-v2','strategy'])
def test_replacing_the_pool_during_a_stream_does_not_restart_the_current_reply(sql,tmp_path,monkeypatch,contract):
    import threading
    import httpx
    active={'new':False,'hold_commit':False}
    entered=release=None
    validating=threading.Event();finish_commit=threading.Event()
    later='I also helped him in the garden.'
    def controlled_sql(query,**options):
        if active['hold_commit'] and any(name in query for name in ('public.commit_lifetime_turn(','public.commit_lifetime_strategy_turn(')):
            active['hold_commit']=False
            validating.set()
            assert finish_commit.wait(10)
        return sql(query,**options)
    controlled_sql.publication_dsn=sql.publication_dsn
    async def prepare(packet):
        if active['new']:
            entered.set()
            await release.wait()
        return guidance(packet,'conflict' if active['new'] else 'follow_up')
    async def boundary(request,provider):
        body=json.loads(request.content)
        response=await provider(request)
        if body.get('bounded_lane') or body['interview_context']['source']['text']!=later:
            return response
        data=json.loads(response.content.splitlines()[-1])['data']
        return httpx.Response(200,headers={'content-type':'application/x-ndjson'},content=(
            json.dumps(dict(type='text_delta',text=data['reply']))+'\n'+json.dumps(dict(type='result',data=data))+'\n'))
    conversation=Conversation(controlled_sql,tmp_path,monkeypatch,extraction,guidance=prepare,external_boundary=boundary,
        strategy='explore' if contract=='strategy' else None)
    if contract=='reply-v2':monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    monkeypatch.setenv('MEMORY_SPARK_PARALLEL_POLICY_REVIEW','1')
    with conversation.client:
        conversation.say(STORY)
        conversation.drain()
        original=pool(conversation)[0]
        active.update(new=True,hold_commit=True)
        sql("update public.user_memoir_lane set pending=true,guidance_revision=guidance_revision+1 where skill='guidance';")
        async def run():
            nonlocal entered,release
            entered,release=asyncio.Event(),asyncio.Event()
            lane=sql("select id from public.user_memoir_lane where skill='guidance';").stdout.strip()
            background=asyncio.create_task(conversation.worker.execute_lane(lane))
            foreground=None
            try:
                await asyncio.wait_for(entered.wait(),10)
                foreground=asyncio.create_task(asyncio.to_thread(conversation.client.post,'/v1/agent/turn',
                    headers={'accept':'application/x-ndjson'},json=dict(project_id=conversation.project,text=later,client_turn_id=str(uuid4()))))
                if not await asyncio.to_thread(validating.wait,10):
                    if foreground.done():
                        pytest.fail((await foreground).text+conversation.last_db_error)
                    pytest.fail('Foreground did not reach the saved-reply boundary')
                release.set()
                assert (await asyncio.wait_for(background,10))['status']=='finished',conversation.last_db_error
                assert pool(conversation)[0]['id']==original['id']
                live=json.loads(sql('select questions from public.user_lifetime_prepared_question;').stdout)
                assert live[0]['trigger']=='conflict'
            finally:
                release.set();finish_commit.set()
                await background
            response=await foreground
            events=[json.loads(line) for line in response.text.splitlines()]
            assert not any(e['type'] in {'error','collector_restart'} for e in events),response.text
            assert len({e['data']['revision'] for e in events if e['type']=='reply_revision'})<=1
            saved=next(e['data'] for e in events if e['type']=='result')
            assert saved['reply'].endswith(original['question'])
            assert ''.join(e.get('text','') for e in events if e['type']=='text_delta').endswith(original['question'])
            assert len(conversation.foreground)==2
        asyncio.run(run())
        following=conversation.say('I would like to continue.')
        assert 'red or blue' in following['reply']
        assert len(conversation.foreground)==3


def test_withdrawing_either_conflict_passage_invalidates_a_question_anchored_to_the_other(sql,tmp_path,monkeypatch):
    def prepare(packet):
        windows=packet['guidance_context']['source_windows']
        if len({w['id'] for w in windows})<2:
            return dict(signals=[],prepared_questions=[],acknowledgement_guidance=None,strategy_proposal=None)
        old=next(w for w in windows if '1998' in w['text'])
        current=next(w for w in windows if '2001' in w['text'])
        refs=[dict(source_id=w['id'],version=w['version'],quote=w['text']) for w in (old,current)]
        return validate_guidance_result(dict(signals=[dict(kind='conflict',source_refs=refs,detail_question_ids=[],recall_limit_quote=None)],
            prepared_questions=[dict(question='Do those years refer to the same retirement?',topic='Father’s retirement',
                quote=current['text'],source_id=current['id'],source_version=current['version'],trigger='conflict',
                requires_confirmation=True,scope='detail')],acknowledgement_guidance=None,strategy_proposal=None),packet)
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,guidance=prepare)
    with conversation.client:
        older=conversation.say('My father retired in 1998.')
        conversation.drain()
        current=conversation.say('My father retired in 2001.')
        conversation.drain()
        candidate=pool(conversation)[0]
        assert candidate['source_id']==current['accepted_source_id']
        assert {r['source_id'] for r in candidate['trigger_source_refs']}=={older['accepted_source_id'],current['accepted_source_id']}
        rpc(sql,'change_user_narrator_source',f"{literal(conversation.project)},'{older['accepted_source_id']}',1,'withdraw',null")
        assert pool(conversation)==[]
