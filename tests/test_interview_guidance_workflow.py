"""Current interviewing runs in Mira; saved Lane B results are later context."""
import json

import pytest

from apps.api.conversation_reply import reply_candidates
from scripts.evaluate_mira_prompt import realtime_cases
from test_background_profile_workflow import database
from test_conversation_attribution import Conversation, empty, episode
from test_conversation_reply import proposal
from test_lifetime_memory_postgres import event_database, private_database, attachment_database
from test_shared_memory_events_postgres import sql


def extraction(packet):
    return {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'],title='Family memory')]}


@pytest.mark.parametrize('locale',['en-AU','zh-CN'])
@pytest.mark.parametrize('kind',['conflict','ambiguity','topic','values'])
def test_mira_saves_current_interviewing_decisions_before_background_work(sql,tmp_path,monkeypatch,locale,kind):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    probe=next(case for case in realtime_cases() if case['id']==f'realtime/{kind}/{locale}')
    current=probe['context']['source']['text']
    questions={
        'en-AU':dict(conflict='Was that move in 1988 or 1992?',
            ambiguity='Is this Robin your cousin, or a different person?',
            topic='What comes to mind about your sister singing in the kitchen?',
            values='How did staying close to family shape your everyday life?'),
        'zh-CN':dict(conflict='这次搬家是在1988年，还是1992年？',
            ambiguity='这位小宁和您提到的表姐是同一个人吗？',
            topic='说起姐姐在厨房唱歌，您会想起怎样的画面？',
            values='留在家人身边，对您每天的生活有什么影响？'),
    }
    acknowledgement=('听起来，陪伴家人可能是您很看重的一条线索。' if locale=='zh-CN'
        else 'It sounds as though staying near family may be a meaningful thread for you.') if kind=='values' else (
        '我们可以慢慢把这段回忆说清楚。' if locale=='zh-CN' else 'We can take our time with that memory.')
    def reply(context):
        output=proposal()
        assert reply_candidates(context)==[]
        if context['source']['text']==current:
            output.update(acknowledgement=acknowledgement,question=questions[locale][kind])
            if kind=='topic':
                output.update(recall_limit_quote=current.split('.')[0] if locale=='en-AU' else '等爸爸买涂料时做了什么，我记不得了')
        return output
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,reply=reply)
    with conversation.client:
        if kind in {'conflict','ambiguity'}:
            conversation.say(probe['context']['recent_dialogue'][0]['response']['text'],language=locale)
        result=conversation.say(current,language=locale)
        assert result['conversation_saved'] and result['reply'].startswith(acknowledgement)
        assert result['reply'].endswith(questions[locale][kind])
        assert conversation.admissions==[], 'Current clarification and reflection must not wait for Lane B'
        assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='0'
        assert sql("select count(*) from public.user_memoir_lane where skill='guidance';").stdout.strip()=='0'
        before=result['reply']
        conversation.drain()
        assert not any(phase=='guidance' for phase,_ in conversation.admissions)
        assert sql('select count(*) from public.user_memory_event;').stdout.strip()!='0',conversation.last_db_error
        conversation.say('I also remember helping in the garden.',language=locale)
        context=conversation.foreground[-1]
        assert context['events'], 'Saved timeline work reaches the next reply even without an active-event plan'
        assert not {'prepared_questions','interview_guidance','strategy_context'} & context.keys()
        assert result['reply']==before


def test_saved_legacy_guidance_does_not_enter_miras_context_or_override_her_reply(sql,tmp_path,monkeypatch):
    from split_lane_fixtures import publish
    from test_lifetime_composer_capacity import service
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    own_question='What do you remember about your sister singing?'
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,
        reply=lambda _:dict(proposal(),question=own_question))
    with conversation.client:
        original=conversation.say('My father painted the kitchen.')
        lane=sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
        page=service(sql,'claim_memoir_lane',f"'{lane}',300")
        legacy='Which colour did your father use for that wall?'
        publish(sql,page,[dict(question=legacy,topic='Kitchen',
            quote=page['source']['text'],requires_confirmation=True)])
        result=conversation.say('My sister used to sing in the kitchen.')
        assert result['reply'].endswith(own_question)
        assert legacy not in json.dumps(conversation.foreground[-1])
        assert not {'prepared_questions','interview_guidance','strategy_context'} & conversation.foreground[-1].keys()
        assert result['conversation_saved'] and original['conversation_saved']


def test_saved_timeline_delivery_uses_original_evidence_instead_of_derived_private_prose(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    original='I worked as a carpenter in Hobart.'
    poison='Unrelated private material must not be copied from a generated title.'
    def extract(packet):
        return {**empty(packet),'events':[episode(packet,original,title=poison)]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        conversation.say(original)
        conversation.drain()
        assert poison in sql('select data from public.user_memory_event;').stdout
        conversation.say('I also remember making furniture.')
        context=conversation.foreground[-1]
        assert poison not in json.dumps(context)
        event=context['events'][0]
        assert event['title'] is None
        assert event['original_passages'][0]['text']==original


def test_late_news_waits_for_the_next_reply_without_replacing_current_text(sql,tmp_path,monkeypatch):
    from legacy_guidance_fixtures import install_news
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS','1')
    calls=[]
    def reply(context):
        calls.append(context)
        if len(calls)==2:
            assert not context.get('historical_news',{}).get('clues')
            install_news(conversation)
        return dict(proposal(),question='What do you remember about the kitchen?')
    conversation=Conversation(sql,tmp_path,monkeypatch,extraction,reply=reply)
    with conversation.client:
        first=conversation.say('I was born in Boston, USA, in 1960.')
        conversation.drain()
        second=conversation.say('I remember our kitchen.')
        frozen=second['reply']
        assert second.get('historical_context') is None
        third=conversation.say('I remember the neighbours too.')
        assert calls[-1]['historical_news']['clues']
        assert reply_candidates(calls[-1])==[]
        assert third.get('historical_context') is None, 'An available clue remains optional'
        saved=json.loads(sql('select json_agg(collector order by sequence) from public.user_interview_turn;').stdout)
        assert saved[0]['reply']==first['reply'] and saved[1]['reply']==frozen
        assert sql("select count(*) from public.user_memoir_lane where skill='guidance';").stdout.strip()=='0'
