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


def test_withdrawal_waits_for_actual_recording_descriptor_send(consent_workflow,media):
    from apps.api.lifetime_memory_publication import TransactionalPublication,send_governed
    client,storage,sql,record,accepted,snapshot,fence=publication_recording(consent_workflow,media)
    async def scenario():
        withdrawing=None
        async def send(message):
            nonlocal withdrawing
            assert json.loads(message['body'])['data']['recordings']
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
        publisher=TransactionalPublication(sql.publication_dsn,authenticated_owner=OWNER)
        message={'type':'http.response.body','more_body':True,'body':json.dumps({
            'type':'source_accepted','data':{'recordings':snapshot}}).encode()+b'\n'}
        await send_governed(send,message,publisher=publisher,fence=fence)
        assert (await withdrawing).status_code == 200
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
