"""Canonical ASGI, SQL, and Responses transport with explicitly controlled LLMs."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from apps.api import conversation_reply_transport, policy_review
from apps.api.codex_runtime import CodexRuntime
from apps.api.lifetime_memory_policy import PolicyUnavailable
from apps.api.model_request import complete_json
from scripts.canonical_turn import canonical_turn, CanonicalTurnFailed
from memoir_postgres_workflow import PostgresRest
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_agent_commit_postgres import OWNER
from test_conversation_reply_transport import events, sse


@pytest.mark.parametrize('language', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('outcome', ['clear', 'restrict', 'unavailable'])
@pytest.mark.parametrize('worker', [False, True])
def test_parallel_reply_replaces_only_current_turn_and_never_saves_before_policy(sql, tmp_path, monkeypatch, language, outcome, worker):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY','controlled-key')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    monkeypatch.setenv('MEMORY_SPARK_PARALLEL_POLICY_REVIEW','1')
    monkeypatch.setenv('MEMOIR_TWO_LANES','1')
    monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY','0')
    monkeypatch.delenv('MEMORY_SPARK_EARLY_POLICY_ACK',raising=False)
    chinese=language=='zh-CN'
    previous='我和父亲在承德经营一家商店。后来我搬到了悉尼。' if chinese else 'My father and I ran a shop in Chengde. Later, I moved to Sydney.'
    restriction='以后请不要再提我的父亲。' if chinese else "Please don't bring up my father again."
    redirect='我们聊聊搬到悉尼的经历吧。' if chinese else "Let's talk about moving to Sydney."
    current=(restriction+redirect if chinese else restriction+' '+redirect) if outcome!='clear' else (
        '刚到悉尼时，海港很明亮。' if chinese else 'The harbour was bright when I arrived in Sydney.')
    phase={'index':0,'calls':0}
    requests=[]
    errors=[]
    from apps.api.lifetime_memory_transport import GovernedTurnStream
    original_failure=GovernedTurnStream.log_failure
    def observe_failure(self,error,**kwargs):
        import traceback
        errors.append(''.join(traceback.format_exception(error)))
        return original_failure(self,error,**kwargs)
    monkeypatch.setattr(GovernedTurnStream,'log_failure',observe_failure)

    async def run():
        review_entered,release_review=asyncio.Event(),asyncio.Event()
        draft_visible,draft_stopped=asyncio.Event(),asyncio.Event()
        release_draft=asyncio.Event()
        async def review(name,payload,schema,**kwargs):
            if phase['index']:
                review_entered.set()
                await release_review.wait()
                if outcome=='unavailable': raise PolicyUnavailable()
            restrictions=[]
            if phase['index'] and outcome=='restrict':
                start=payload['source']['text'].index(restriction)
                restrictions=[dict(kind='excluded_topic',quote=restriction,char_start=start,char_end=start+len(restriction))]
            output=dict(complete=True,restrictions=restrictions)
            def respond(request):
                return httpx.Response(200,json=dict(id='controlled-policy',status='completed',output=[dict(
                    type='message',status='completed',content=[dict(type='output_text',text=json.dumps(output))])]))
            return await complete_json(name,payload,schema,transport=httpx.MockTransport(respond),**kwargs)

        real_stream=conversation_reply_transport.stream_reply
        async def provider(request):
            body=json.loads(request.content);requests.append(body)
            if phase['index']:
                phase['calls']+=1
                view=json.loads(body['input'][1]['content'])
                if phase['calls']==1:
                    assert view['dialogue'][0]['assistant']['text']==saved_first['reply']
                if phase['calls']>1:
                    assert outcome=='restrict'
                    assert restriction in view['preferences']['excluded_topics']
                    assert view['dialogue'][0]['assistant'] is None
            first=phase['index']==0
            stale=not first and phase['calls']==1 and outcome!='clear'
            acknowledgement=('您提到后来搬到了悉尼。' if chinese else 'You mentioned moving to Sydney.')
            question=(('父亲有没有帮助您在悉尼安顿下来？' if chinese else 'Did your father help you settle in Sydney?') if stale else
                ('您初到悉尼时，什么最让您难忘？' if chinese else 'What stands out about your first days in Sydney?'))
            raw=json.dumps(dict(acknowledgement=acknowledgement,question=question,
                reason='latest_story' if first or outcome=='clear' else 'user_redirect',hint=None,
                quote=None,work=dict(mode='extract',name=None),resolved_questions=[]),ensure_ascii=False)
            class Stream(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield sse(events(raw)[:1])
                    if not first and phase['calls']==1:
                        try: await release_draft.wait()
                        finally: draft_stopped.set()
                    yield sse(events(raw)[1:])
            return httpx.Response(200,stream=Stream(),headers={'Content-Type':'text/event-stream'})
        async def send(**kwargs): return await real_stream(**kwargs,transport=httpx.MockTransport(provider))
        monkeypatch.setattr(policy_review,'complete_json',review)
        monkeypatch.setattr(conversation_reply_transport,'stream_reply',send)
        async def worker_provider(request):
            from apps.api.codex_worker_service import WorkerTurnInput
            from apps.api.lifetime_memory_engine import run_governed_collector
            from apps.api.turn_stream import turn_events
            payload=WorkerTurnInput.model_validate(json.loads(request.content))
            async def generate(emit):
                return await run_governed_collector(command=[],home_root=tmp_path/'worker',
                    base_url='http://controlled.invalid/v1',api_key='controlled-key',model=payload.model,
                    governed=payload.governed,interview_context=payload.interview_context,
                    on_delta=emit,on_event=emit.event,effort='low')
            class WorkerStream(httpx.AsyncByteStream):
                def __init__(self): self.events=turn_events(generate)
                async def __aiter__(self):
                    async for value in self.events: yield value.encode() if isinstance(value,str) else value
                async def aclose(self): await self.events.aclose()
            return httpx.Response(200,stream=WorkerStream(),headers={'Content-Type':'application/x-ndjson'})
        def runtime():
            return CodexRuntime(home_root=tmp_path/'homes',base_url='http://controlled.invalid/v1',
                model='gpt-5.6-luna-pooled',**(dict(worker_url='http://worker.invalid',worker_secret='controlled',
                    worker_transport=httpx.MockTransport(worker_provider)) if worker else {}))
        storage=PostgresRest(sql,OWNER).storage()
        try:
            try: saved_first=await canonical_turn(runtime(),storage,previous,options=dict(client_turn_id=str(uuid4()),language=language))
            except CanonicalTurnFailed: pytest.fail('\n'.join(errors))
        finally: storage.client.close()
        old=json.loads(sql('select collector from public.user_interview_turn order by sequence limit 1;').stdout)
        phase['index']=1
        observed=[]
        async def observe(event):
            observed.append(event)
            if event['type']=='text_delta' and event.get('text'): draft_visible.set()
        storage=PostgresRest(sql,OWNER).storage()
        task=asyncio.create_task(canonical_turn(runtime(),storage,current,
            options=dict(project_id=saved_first['project_id'],client_turn_id=str(uuid4()),language=language),on_event=observe))
        try:
            await asyncio.wait_for(review_entered.wait(),10)
            await asyncio.wait_for(draft_visible.wait(),10)
            assert not task.done()
            assert phase['calls']==1
            assert not any(event['type'] in {'reply_complete','conversation_saved'} for event in observed)
            assert sql('select count(*) from public.user_interview_turn where collector is not null;').stdout.strip()=='1'
            release_review.set()
            if outcome=='clear': release_draft.set()
            if outcome=='unavailable':
                with pytest.raises(CanonicalTurnFailed): await asyncio.wait_for(task,10)
                assert sql('select count(*) from public.user_interview_turn where collector is not null;').stdout.strip()=='1'
            else:
                try: final=await asyncio.wait_for(task,10)
                except CanonicalTurnFailed: pytest.fail('\n'.join(errors))
                assert final['conversation_saved']
                revisions=[e['data']['revision'] for e in observed if e['type']=='reply_revision']
                assert revisions==([0,1] if outcome=='restrict' else [0])
                retained=''.join(e['text'] for e in observed if e['type']=='text_delta' and e.get('revision')==revisions[-1])
                assert retained==final['reply']
                assert phase['calls']==(2 if outcome=='restrict' else 1)
                if outcome=='restrict': assert ('父亲' if chinese else 'father') not in final['reply']
            assert draft_stopped.is_set()
            assert json.loads(sql('select collector from public.user_interview_turn order by sequence limit 1;').stdout)==old
        finally:
            release_review.set();release_draft.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            storage.client.close()
    asyncio.run(run())
