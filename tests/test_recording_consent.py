"""Consent and voice retention through authenticated HTTP and real PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import threading
import asyncio
import json
from uuid import uuid4

import pytest
import psycopg

from test_original_recordings_http import (database, workflow, approved, attachment_database,
    private_database, event_database, sql, media, upload)
from test_original_recordings_postgres import server
from test_shared_memory_events_postgres import OWNER, OTHER, as_user

POLICY = {'policy_version':'original-recordings-v1', 'locale':'en-AU',
    'expected_revision':0, 'retain_originals':True, 'ai_processing':True}
ENDPOINT = '/api/v1/memoir/story/recording-consent'


@pytest.fixture
def consent_workflow(workflow):
    client,storage,sql,objects,calls,mode = workflow
    baseline = (Path(__file__).resolve().parents[1] / 'supabase/migrations/202610180001_initial_schema.sql').read_text()
    definition = re.search(r'CREATE FUNCTION public.original_recording_authorized\(.*?\$\$;', baseline, re.S)[0]
    sql(definition.replace('CREATE FUNCTION', 'CREATE OR REPLACE FUNCTION', 1))
    sql('truncate public.user_recording_consent;')
    sql("update auth.users set email=null,email_confirmed_at=null,phone=null,phone_confirmed_at=null;")
    sql(f"update auth.users set email='voice-fixture@example.invalid',email_confirmed_at=now() where id='{OWNER}';")
    return workflow


def grant(client, **values):
    return client.put(ENDPOINT, json={**POLICY, 'action':'grant', **values})


def test_groq_consent_never_dispatches_mandarin_audio_to_qwen(consent_workflow, media, monkeypatch):
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from apps.api import speech
    client,storage,sql,objects,calls,mode = consent_workflow
    assert grant(client).status_code == 200
    monkeypatch.setenv('DASHSCOPE_API_KEY','synthetic-qwen-key')
    monkeypatch.setenv('DASHSCOPE_WORKSPACE_ID','synthetic-workspace')
    fallbacks=[]
    def unavailable(*args,**kwargs): raise speech.SpeechProviderError('controlled Groq outage')
    def qwen(*args,**kwargs):
        fallbacks.append(1)
        return {'text':'未经授权的转写','provider':'qwen','model':'fixture'}
    monkeypatch.setattr(speech.GroqSpeechService,'transcribe',unavailable)
    monkeypatch.setattr(speech.QwenASRService,'transcribe',qwen)
    service=speech.build_speech_service()
    app=create_app(MemoryStore(),speech_service=service,story_storage_factory=lambda _:storage)
    content,mime=media
    import base64
    result=TestClient(app).post('/api/v1/memoir/story/transcriptions',json={
        'audio_base64':base64.b64encode(content).decode(),'mime_type':mime,'language':'zh-CN'})
    assert not fallbacks, 'Groq-only consent dispatched original audio to Qwen'
    assert result.status_code == 503
    assert result.json()['detail']['backend_saved'] is True


def test_withdrawal_before_object_fetch_prevents_even_a_backend_storage_read(consent_workflow,media,monkeypatch):
    from apps.api.original_recordings import RecordingStore
    client,storage,sql,objects,calls,mode = consent_workflow
    assert grant(client).status_code == 200
    record=upload(client,media).json()['recording']
    original=RecordingStore.content
    after_withdrawal=[]
    def delayed(self,current):
        revoked=client.put(ENDPOINT,json={**POLICY,'action':'revoke','expected_revision':1})
        assert revoked.status_code == 200
        before=len(calls)
        try:return original(self,current)
        finally:after_withdrawal.extend(calls[before:])
    monkeypatch.setattr(RecordingStore,'content',delayed)
    result=client.get(record['content_url'])
    assert result.status_code == 404
    assert not after_withdrawal, 'Backend fetched original bytes after withdrawal committed'


def publication_recording(consent_workflow,media):
    from test_shared_memory_events_postgres import rpc,literal
    from test_agent_commit_postgres import OLD
    client,storage,sql,objects,calls,mode = consent_workflow
    assert grant(client).status_code == 200
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    record=upload(client,media).json()['recording']
    accepted=storage.accept_interview_turn(identity['project_id'],str(uuid4()),'An original memory',
        kind='narrator_transcript',recording_ids=[record['id']])
    snapshot=storage.source_recordings(identity['project_id'],accepted['source']['id'])
    assert snapshot
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    return client,storage,sql,record,accepted,snapshot,fence


def test_queued_recording_descriptor_is_filtered_at_actual_stream_send(consent_workflow,media):
    from apps.api.lifetime_memory_publication import TransactionalPublication
    from apps.api.lifetime_memory_transport import GovernedStreamingResponse,governed_turn_events
    from test_lifetime_memory_transport import SCOPE,no_disconnect,body_event
    client,storage,sql,record,accepted,snapshot,fence=publication_recording(consent_workflow,media)
    identity=fence['identity']
    async def scenario():
        queued,withdrawn=asyncio.Event(),asyncio.Event()
        delivered,observed=[],[]
        async def run(emit):
            emit.set_fence(fence)
            await emit.event({'type':'source_accepted','data':{'accepted_source_id':accepted['source']['id'],'recordings':snapshot}})
            queued.set()
            await withdrawn.wait()
            return {'recordings':await asyncio.to_thread(storage.source_recordings,identity['project_id'],accepted['source']['id'])}
        async def send(message):
            event=body_event(message)
            if not event:return
            if event['type']=='started':
                await queued.wait()
                response=await asyncio.to_thread(client.put,ENDPOINT,json={**POLICY,'action':'revoke','expected_revision':1})
                assert response.status_code == 200
                withdrawn.set()
            delivered.append(event)
        publisher=TransactionalPublication(sql.publication_dsn,authenticated_owner=OWNER)
        await GovernedStreamingResponse(governed_turn_events(run),publisher=publisher,on_delivered=observed.append)(SCOPE,no_disconnect,send)
        accepted_event=next(event['data'] for event in delivered if event['type']=='source_accepted')
        assert accepted_event['recordings'] == [], 'Stream released a cached descriptor after withdrawal'
        assert next(event['data'] for event in observed if event['type']=='source_accepted')['recordings'] == []
        assert next(event['data'] for event in delivered if event['type']=='result')['recordings'] == []
    asyncio.run(scenario())


@pytest.mark.parametrize('two_lane,publication', [
    (False,'json'), (True,'json'),
    (False,'source_accepted'), (True,'source_accepted'),
    (False,'result'), (True,'result'),
    (True,'reply_complete'),
    (False,'conversation_saved'), (True,'conversation_saved'),
])
def test_runtime_cached_recordings_withdrawn_before_actual_publication(
        consent_workflow,media,tmp_path,monkeypatch,two_lane,publication):
    """Real HTTP/runtime/SQL; revoke only after this exact body is serialized."""
    import httpx
    from apps.api import agent_routes, lifetime_memory_transport as transport
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    from test_name_only_opening import proposal
    from controlled_collector import worker_reply
    client,storage,sql,objects,calls,mode=consent_workflow
    assert grant(client).status_code == 200
    monkeypatch.setenv('MEMOIR_TWO_LANES','1' if two_lane else '0')
    sql('update public.lifetime_two_lane_rollout set enabled='+('true' if two_lane else 'false')+';')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS','99')

    def provider(request):
        output=proposal(mode='extract',name=None,question='What do you remember about the garden?')
        output['acknowledgement']='You remember the garden.'
        output['plan']['conversation_phase']='explore'
        return worker_reply(request,{'reply':json.dumps(output),'thread_id':'synthetic','artifacts':[]})

    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',
        worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    recording=upload(client,media).json()['recording']
    original_send=transport.send_governed
    withdrawn=[]

    async def withdraw_before_send(send,message,*,publisher,fence):
        event=json.loads(message['body'])
        kind='json' if publication=='json' else event.get('type')
        if kind==publication and not withdrawn:
            content=event if kind=='json' else event['data']
            assert [r['id'] for r in content['recordings']] == [recording['id']]
            result=await asyncio.to_thread(client.put,ENDPOINT,
                json={**POLICY,'action':'revoke','expected_revision':1})
            assert result.status_code == 200, result.text
            withdrawn.append(True)
        return await original_send(send,message,publisher=publisher,fence=fence)

    monkeypatch.setattr(transport,'send_governed',withdraw_before_send)
    command={'text':'I remember the garden.','source_kind':'narrator_transcript',
        'recording_ids':[recording['id']],'client_turn_id':str(uuid4())}
    response=client.post('/api/v1/memoir/agent/turn',json=command,
        headers={'Accept':'application/json' if publication=='json' else 'application/x-ndjson'})
    assert response.status_code == 200, response.text
    assert withdrawn == [True], 'The selected actual response path was not reached'
    if publication=='json':
        result=response.json()
        assert result['recordings'] == [], 'Ordinary JSON released a withdrawn descriptor'
        assert int(response.headers['content-length']) == len(response.content)
        assert not response.content.endswith(b'\n')
    else:
        events=[json.loads(line) for line in response.text.splitlines()]
        assert not [event for event in events if event['type']=='error'], response.text
        boundary=next(i for i,event in enumerate(events) if event['type']==publication)
        for event in events[boundary:]:
            if 'recordings' in event.get('data',{}):
                assert event['data']['recordings'] == [], f"{event['type']} released a withdrawn descriptor"
        completion=next(event['data'] for event in events if event['type']=='reply_complete')
        assert ('recordings' in completion) == two_lane
        result=next(event['data'] for event in events if event['type']=='result')
    assert result['conversation_saved'] is True and result['reply']
    assert storage.source_recordings(result['project_id'],result['accepted_source_id']) == []
    assert client.get(recording['content_url']).status_code == 404


@pytest.mark.parametrize('publication', ['json','source_accepted','result','reply_complete','conversation_saved'])
@pytest.mark.parametrize('outcome', ['sent','cancelled','timeout','error'])
def test_withdrawal_waits_for_actual_recording_descriptor_send(consent_workflow,media,publication,outcome):
    from starlette.requests import ClientDisconnect
    from apps.api.lifetime_memory_publication import TransactionalPublication
    from test_lifetime_memory_transport import SCOPE,no_disconnect
    from test_recording_descriptor_publication import response_for
    client,storage,sql,record,accepted,snapshot,fence=publication_recording(consent_workflow,media)
    async def scenario():
        entered,release=asyncio.Event(),asyncio.Event()
        cleaned,delivered=[],[]

        async def cleanup():
            cleaned.append(True)

        async def send(message):
            if message['type']=='http.response.body' and b'content_url' in message.get('body',b''):
                event=json.loads(message['body'])
                data=event if publication=='json' else event['data']
                assert data['recordings'] == snapshot, 'Allowed descriptors must stay unchanged'
                entered.set()
                await release.wait()
                if outcome=='error':raise OSError('controlled ASGI send failure')
            delivered.append(message)

        publisher=TransactionalPublication(sql.publication_dsn,authenticated_owner=OWNER,
            send_timeout=.5 if outcome=='timeout' else 2)
        response=response_for(publication,{'reply':'Original memory','recordings':snapshot},
            publisher,cleanup=cleanup,fence=fence)
        sending=asyncio.create_task(response(SCOPE,no_disconnect,send))
        withdrawing=None
        try:
            async with asyncio.timeout(3):await entered.wait()
            withdrawing=asyncio.create_task(asyncio.to_thread(client.put,ENDPOINT,
                json={**POLICY,'action':'revoke','expected_revision':1}))
            observer=await psycopg.AsyncConnection.connect(sql.publication_dsn,autocommit=True)
            try:
                async with asyncio.timeout(3):
                    while not (await (await observer.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like 'select public.recording_server_operation%')")).fetchone())[0]:
                        assert not withdrawing.done(), 'Withdrawal completed before descriptor send'
                        await asyncio.sleep(.01)
            finally:await observer.close()
            assert not withdrawing.done()
            if outcome=='cancelled':sending.cancel()
            elif outcome!='timeout':release.set()
            if outcome=='sent':
                await sending
                assert response.delivered
            else:
                expected_error={'cancelled':asyncio.CancelledError,'timeout':TimeoutError,'error':OSError}[outcome]
                if publication!='json' and outcome in {'timeout','error'}:expected_error=ClientDisconnect
                with pytest.raises(expected_error):await sending
                assert not response.delivered
                assert not any(b'content_url' in message.get('body',b'') for message in delivered)
            assert (await withdrawing).status_code == 200
            assert cleaned == [True]
        finally:
            sending.cancel()
            await asyncio.gather(sending,return_exceptions=True)
            if withdrawing is not None:await withdrawing
    asyncio.run(scenario())
    assert client.get(record['content_url']).status_code == 404


def test_withdrawal_before_upload_readback_prevents_storage_get(consent_workflow,media,monkeypatch):
    client,storage,sql,objects,calls,mode=consent_workflow
    assert grant(client).status_code == 200
    original=type(storage).request
    readback=[]
    def withdraw_after_upload(self,method,path,**options):
        result=original(self,method,path,**options)
        if method=='POST' and path.startswith('/storage/'):
            assert client.put(ENDPOINT,json={**POLICY,'action':'revoke','expected_revision':1}).status_code == 200
            readback.append(len(calls))
        return result
    monkeypatch.setattr(type(storage),'request',withdraw_after_upload)
    response=upload(client,media)
    assert response.status_code == 503
    assert readback and not calls[readback[0]:], 'Storage verification GET ran after withdrawal'


def test_opt_in_requires_both_purposes_and_confirmed_recoverable_identity(consent_workflow, media):
    client,storage,sql,objects,calls,mode = consent_workflow
    status = client.get(ENDPOINT)
    assert status.json()['consented'] is False and status.json()['recoverable_identity'] is True
    assert status.headers['cache-control'] == 'private, no-store'
    assert upload(client, media).status_code == 403
    for missing in ['retain_originals', 'ai_processing']:
        assert grant(client, **{missing:False}).status_code == 403
    sql(f"update auth.users set email_confirmed_at=null,raw_user_meta_data='{{\"recording_consent\":true}}' where id='{OWNER}';")
    assert client.get(ENDPOINT).json()['recoverable_identity'] is False
    assert grant(client).status_code == 403
    assert not objects and not calls


def test_consent_enables_exact_original_and_withdrawal_fences_reads_and_stt(consent_workflow, media):
    client,storage,sql,objects,calls,mode = consent_workflow
    consent = grant(client)
    assert consent.status_code == 200, consent.text
    assert consent.json()['consented'] is True and consent.json()['revision'] == 1
    response = upload(client, media)
    assert response.status_code == 200, response.text
    recording = response.json()['recording']
    assert client.get(recording['content_url']).content == media[0]
    before = len(calls)
    revoked = client.put(ENDPOINT, json={**POLICY, 'action':'revoke', 'expected_revision':1})
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()['consented'] is False and revoked.json()['revision'] == 2
    assert client.get(recording['content_url']).status_code == 404
    assert client.post('/api/v1/memoir/story/transcriptions', json={'recording_id':recording['id']}).status_code == 403
    assert grant(client).status_code == 409  # A delayed grant cannot undo withdrawal.
    assert len(calls) == before
    assert grant(client, expected_revision=2).status_code == 200


def test_anonymous_outsider_and_direct_table_writes_cannot_grant_consent(consent_workflow):
    client,storage,sql,objects,calls,mode = consent_workflow
    assert client.put(ENDPOINT, headers={'Authorization':'Bearer anonymous'}, json={**POLICY,'action':'grant'}).status_code == 403
    assert client.put(ENDPOINT, headers={'Authorization':'Bearer other'}, json={**POLICY,'action':'grant','owner_id':OWNER}).status_code == 422
    assert client.put(ENDPOINT, headers={'Authorization':'Bearer invalid'}, json={**POLICY,'action':'grant'}).status_code == 401
    assert grant(client).status_code == 200
    assert client.get(ENDPOINT, headers={'Authorization':'Bearer other'}).json()['consented'] is False
    assert sql(as_user('select * from public.user_recording_consent;'),check=False).returncode != 0
    assert sql(as_user(f"select public.recording_consent_operation('{OTHER}','consent_grant','{{}}');"),check=False).returncode != 0
    assert sql(as_user("update public.original_recording_rollout set enabled=true;"),check=False).returncode != 0


def test_revocation_waits_for_admitted_provider_guard(consent_workflow, media):
    client,storage,sql,objects,calls,mode = consent_workflow
    assert grant(client).status_code == 200
    recording = upload(client,media).json()['recording']
    entered = threading.Event()
    with psycopg.connect(sql.publication_dsn) as connection, ThreadPoolExecutor() as pool:
        connection.execute('select public.recording_server_operation(%s,%s,%s,%s)', (OWNER,'read',recording['id'],'{}'))
        def withdraw():
            entered.set()
            return client.put(ENDPOINT,json={**POLICY,'action':'revoke','expected_revision':1})
        future = pool.submit(withdraw)
        assert entered.wait(2)
        # Observe the database lock rather than relying on a scheduler delay.
        with psycopg.connect(sql.publication_dsn,autocommit=True) as observer:
            import time
            until=time.monotonic()+3
            while time.monotonic()<until:
                if observer.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like 'select public.recording_server_operation%')").fetchone()[0]:
                    break
            else: pytest.fail('Withdrawal did not wait for the provider guard')
        assert not future.done()
        connection.commit()
        assert future.result(timeout=5).json()['consented'] is False
    assert client.get(recording['content_url']).status_code == 404


def test_rollout_identity_changes_and_invalid_policy_fail_closed(consent_workflow, media):
    client,storage,sql,objects,calls,mode = consent_workflow
    assert grant(client, policy_version='outdated').status_code == 422
    assert grant(client, retain_originals='true').status_code == 422
    assert grant(client).status_code == 200
    sql(f"update auth.users set email_confirmed_at=null where id='{OWNER}';")
    assert upload(client, media).status_code == 403
    sql('update public.original_recording_rollout set enabled=false;')
    assert client.get(ENDPOINT).json()['enabled'] is False
    assert grant(client, expected_revision=1).status_code == 403
    assert client.put(ENDPOINT,json={**POLICY,'action':'revoke','expected_revision':1}).status_code == 200
    assert not calls
