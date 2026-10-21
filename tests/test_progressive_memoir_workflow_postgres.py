"""Fixed proposals through the maintained canonical API and progressive workers."""
import asyncio
import pytest
from test_conversation_attribution import Conversation, empty, episode
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import event_database,private_database,attachment_database
from test_shared_memory_events_postgres import sql, rpc, literal
from test_agent_commit_postgres import OWNER


@pytest.mark.parametrize('locale',['en-AU','zh-CN'])
def test_authenticated_story_saves_scoped_canonical_drafts_at_rounds_five_ten_and_fifteen(sql,tmp_path,monkeypatch,locale):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'receipts.sqlite3'))
    words = (['I started school around 1964.','I carried a blue school bag.','My teacher was Ms Chen.']
             if locale=='en-AU' else ['我大约在1964年开始上学。','我背着一个蓝色书包。','我的老师是陈老师。'])
    def extract(packet):
        text=packet['sources'][0]['text']
        if text not in words:
            return empty(packet)
        previous=next(iter(packet.get('events',[])),None)
        return {**empty(packet),'events':[episode(packet,text,title='School',existing=previous)]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract,family=False)
    sql(f"update public.user_profile set profile={literal({'preferred_language':locale})}::jsonb where user_id='{OWNER}';")
    with conversation.client:
        project=None
        for number in range(1,16):
            text=words[(number-1)//5] if number in (1,6,11) else ('Thanks.' if locale=='en-AU' else '谢谢。')
            result=conversation.say(text,language=locale)
            conversation.drain()
            project=conversation.project
            state=rpc(sql,'read_user_memory_events',literal(project))
            assert state['completed_rounds']==number
            assert len(state['sources'])==number
            assert state['sources'][-1]['text']==text
            if number%5:
                continue
            conversation.deliver_receipts()
            composer=sql("select id from public.user_memoir_lane where skill='composer';").stdout.strip()
            outcome=asyncio.run(conversation.worker.execute_lane(composer))
            assert outcome.get('retrieval_complete'),(outcome,conversation.last_db_error)
            response=conversation.client.get('/v1/story/private-draft',params={'project_id':project})
            assert response.status_code==200,response.text
            saved=response.json()
            assert saved['status']=='ready',saved
            assert saved['coverage_round']==number
            assert saved['preview']['text']
            assert len(state['events'])==1
            assert {ref['source_id'] for ref in state['events'][0]['source_refs']} <= {source['id'] for source in state['sources']}
        denied=conversation.client.get('/v1/story/private-draft',params={'project_id':project},headers={'Authorization':'Bearer another-owner'})
        assert denied.status_code in {403,404}
