"""Milestones follow real fenced HTTP sends and cannot substitute for saving."""
import asyncio
import json
import threading
from uuid import uuid4

import httpx
import pytest
from starlette.requests import ClientDisconnect

from apps.api.codex_runtime import CodexRuntime
from apps.api.lifetime_memory_runtime import lifetime_http_turn
from controlled_collector import worker_reply
from memoir_postgres_workflow import PostgresRest
from scripts.canonical_turn import canonical_turn
from scripts.issue53_sequence_application import StreamObservation
from test_agent_commit_postgres import OWNER
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_name_only_opening import proposal


SCOPE={'type':'http','asgi':{'spec_version':'2.4'}}
TEXT='I remember tending beans.'
QUESTION='What do you remember about those beans?'
MILESTONES={'question_validated','reply_complete','conversation_saved'}


def controlled_runtime(tmp_path,calls):
    def provider(request):
        calls.append(request)
        output=proposal(mode='extract',name=None,question=QUESTION)
        output['acknowledgement']='You remember tending beans.'
        return worker_reply(request,{'reply':json.dumps(output),'thread_id':'milestone-fixture','artifacts':[]})
    return CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',
        worker_secret='synthetic',worker_transport=httpx.MockTransport(provider))


async def no_disconnect():
    await asyncio.Event().wait()


@pytest.mark.parametrize('failure',[False,True])
def test_commit_barrier_prevents_premature_question_completion_or_save(sql,tmp_path,monkeypatch,failure):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','0')
    storage=PostgresRest(sql,OWNER).storage();real_rpc=storage.lifetime_rpc
    entered,release=threading.Event(),threading.Event()
    def rpc(name,**arguments):
        if name in {'commit_lifetime_turn','commit_lifetime_strategy_turn'}:
            entered.set()
            if not release.wait(10):raise TimeoutError('Controlled commit barrier')
            if failure:raise RuntimeError('Controlled save failure')
        return real_rpc(name,**arguments)
    monkeypatch.setattr(storage,'lifetime_rpc',rpc)
    calls=[];runtime=controlled_runtime(tmp_path,calls);turn=str(uuid4())
    observation=StreamObservation('tending beans',client_turn_id=turn)
    async def scenario():
        response=await lifetime_http_turn(runtime,storage,TEXT,accept='application/x-ndjson',options={'client_turn_id':turn})
        async def send(message):
            for line in message.get('body',b'').splitlines():observation.observe(json.loads(line))
        task=asyncio.create_task(response(SCOPE,no_disconnect,send))
        try:
            assert await asyncio.to_thread(entered.wait,10)
            assert observation.public and not any(e['type'] in MILESTONES for e in observation.events)
            assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
            release.set()
            async with asyncio.timeout(10):await task
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        kinds=[e['type'] for e in observation.events]
        if failure:
            assert 'error' in kinds and not any(k in MILESTONES for k in kinds)
            assert all(observation.timings[k] is None for k in ('validated_question_s','reply_complete_s','durable_save_s'))
            assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
            project=next(e['data']['project_id'] for e in observation.events if e['type']=='source_accepted')
            retry_observation=StreamObservation('tending beans',client_turn_id=turn,project_id=project)
            retry_storage=PostgresRest(sql,OWNER).storage()
            try:
                recovered=await canonical_turn(runtime,retry_storage,TEXT,
                    options={'project_id':project,'client_turn_id':turn},on_event=retry_observation.observe)
            finally:retry_storage.client.close()
            assert recovered['conversation_saved'] and len(calls)==2
            assert retry_observation.timings['validated_question_s'] is not None and retry_observation.timings['reply_complete_s'] is not None
        else:
            assert kinds.index('question_validated')<kinds.index('reply_complete')<kinds.index('conversation_saved')<kinds.index('result')
            assert max(i for i,k in enumerate(kinds) if k=='text_delta')<kinds.index('reply_complete')
            assert len(calls)==1
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
        assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='1'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
        assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip()=='0'
    asyncio.run(scenario())


@pytest.mark.parametrize('drop_at',['question_text','reply_complete'])
def test_disconnect_does_not_observe_queued_completion_and_saved_retry_is_idempotent(sql,tmp_path,monkeypatch,drop_at):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','0')
    calls=[];runtime=controlled_runtime(tmp_path,calls);turn=str(uuid4())
    observation=StreamObservation('tending beans',client_turn_id=turn)
    async def scenario():
        response=await lifetime_http_turn(runtime,PostgresRest(sql,OWNER).storage(),TEXT,
            accept='application/x-ndjson',options={'client_turn_id':turn})
        async def send(message):
            for line in message.get('body',b'').splitlines():
                event=json.loads(line)
                if (drop_at=='question_text' and event['type']=='text_delta' and QUESTION in event.get('text','')
                    or drop_at=='reply_complete' and event['type']=='reply_complete'):
                    raise OSError('Controlled disconnected receiver')
                observation.observe(event)
        with pytest.raises(ClientDisconnect):
            async with asyncio.timeout(10):await response(SCOPE,no_disconnect,send)
        assert not response.delivered
        assert observation.timings['reply_complete_s'] is None and observation.timings['durable_save_s'] is None
        assert not any(e['type'] in {'reply_complete','conversation_saved'} for e in observation.events)
        project=next(e['data']['project_id'] for e in observation.events if e['type']=='source_accepted')
        saved=json.loads(sql('select collector from public.user_interview_turn;').stdout)
        source=next(e['data']['accepted_source_id'] for e in observation.events if e['type']=='source_accepted')
        retry_observation=StreamObservation('tending beans',client_turn_id=turn,project_id=project,
            replay=True,accepted_source_id=source,expected_reply=saved['reply'])
        retry_storage=PostgresRest(sql,OWNER).storage()
        try:
            result=await canonical_turn(runtime,retry_storage,TEXT,
                options={'project_id':project,'client_turn_id':turn},on_event=retry_observation.observe)
        finally:retry_storage.client.close()
        assert result['cached'] and result['conversation_saved'] and len(calls)==1
        assert retry_observation.timings['reply_complete_s'] is not None
        assert not any(e['type'] in MILESTONES for e in retry_observation.events)
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
        assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='1'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
        assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip()=='0'
    asyncio.run(scenario())
