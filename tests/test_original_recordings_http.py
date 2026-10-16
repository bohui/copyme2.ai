"""Authenticated HTTP → real SQL, controlling only external object/STT boundaries."""
import base64
import hashlib
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.original_recordings import RecordingStore
from apps.api.story_routes import StoryTranscriptionInput
from apps.api.speech import SpeechProviderError
from test_interview_photo_acceptance import SqlStorage
from test_original_recordings import media
from test_original_recordings_postgres import database as photos_database, attachment_database, private_database, event_database, sql, approved, server
from test_shared_memory_events_postgres import OWNER, rpc, literal
from test_agent_commit_postgres import OTHER
from test_guest_conversation_transfer import THIRD


@pytest.fixture(scope='module')
def database():
    from test_agent_commit_postgres import database as base_database
    yield from base_database.__wrapped__(publication_tcp=True, postgres_image='postgres:17.6')


@pytest.fixture
def workflow(approved, monkeypatch):
    sql=approved
    sql("grant usage on schema storage to authenticated; grant select,insert,update,delete on storage.objects to authenticated; alter table storage.objects enable row level security;")
    sql("create or replace function storage.allow_any_operation(allowed text[]) returns boolean language sql stable as $$select false$$;")
    objects={}; calls=[]; mode={'upload_fail':False,'read_mismatch':False,'stt_fail':False,'empty':False,'delete_fail':False}
    class Storage(SqlStorage):
        is_anonymous=False
        def request(self,method,path,**options):
            if not path.startswith('/storage/'): return super().request(method,path,**options)
            calls.append((method,path))
            key=path.rsplit('/',1)[-1]
            if method=='POST':
                if mode['upload_fail']:return httpx.Response(503,request=httpx.Request(method,'https://synthetic.test')).raise_for_status()
                if key in objects:return httpx.Response(409,request=httpx.Request(method,'https://synthetic.test')).raise_for_status()
                objects[key]=options['content'];body=b''
            elif method=='GET':body=b'wrong' if mode['read_mismatch'] else objects[key]
            else:
                if mode['delete_fail']:return httpx.Response(503,request=httpx.Request(method,'https://synthetic.test')).raise_for_status()
                for path in options['json']['prefixes']:objects.pop(path.rsplit('/',1)[-1],None)
                body=b''
            return httpx.Response(200,content=body)
    class Speech:
        def transcribe(self,audio,**options):
            calls.append(('stt',audio))
            if mode['stt_fail']:raise SpeechProviderError('synthetic timeout')
            return {'text':'' if mode['empty'] else 'Raw ASR words 中文','provider':'controlled','model':'synthetic','language':'zh','segments':[]}
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMOIR_ORIGINAL_RECORDINGS','1')
    storage=Storage(sql)
    def authenticated(header):
        if header not in {'Bearer synthetic','Bearer other','Bearer anonymous'}: raise HTTPException(401,'Sign in required')
        result=Storage(sql)
        result.user_id=OWNER if header=='Bearer synthetic' else OTHER if header=='Bearer other' else THIRD
        result.is_anonymous=header=='Bearer anonymous'
        return result
    app=create_app(MemoryStore(),speech_service=Speech(),story_storage_factory=authenticated)
    return TestClient(app,headers={'Authorization':'Bearer synthetic'}),storage,sql,objects,calls,mode


def upload(client, media, key=None):
    content,mime=media
    return client.post('/api/v1/memoir/story/transcriptions',headers={'Authorization':'Bearer synthetic'},json={
        'audio_base64':base64.b64encode(content).decode(),'mime_type':mime,'upload_idempotency_key':key or str(uuid4())})


def test_exact_original_survives_new_application_and_client_edited_acceptance(workflow,media):
    client,storage,sql,objects,calls,mode=workflow
    key=str(uuid4());response=upload(client,media,key)
    assert response.status_code==200,response.text
    recording=response.json()['recording']; assert recording['backend_saved'] is True
    assert 'object_path' not in str(response.json())
    assert upload(client,media,key).json()['recording']['id']==recording['id']
    assert len([c for c in calls if c[0]=='stt'])==1
    turn=str(uuid4())
    accepted=storage.accept_interview_turn('project',turn,'Corrected name and typed words',kind='narrator_transcript',recording_ids=[recording['id']])
    assert accepted['source']['text']=='Corrected name and typed words'
    # Destroy request/app-local state; fresh authenticated API and storage client.
    fresh=TestClient(create_app(MemoryStore(),story_storage_factory=lambda _:type(storage)(sql)),headers={'Authorization':'Bearer synthetic'})
    metadata=fresh.get('/api/v1/memoir/story/recordings/'+recording['id']).json()
    assert metadata['asr_result']['text']=='Raw ASR words 中文'
    assert metadata['recording']['lifecycle']=='attached'
    read=fresh.get(recording['content_url'])
    assert read.status_code==200,read.text
    assert read.content==media[0]
    assert hashlib.sha256(read.content).hexdigest()==recording['content_sha256']
    assert read.headers['content-type']==recording['content_type']
    assert read.headers['cache-control']=='private, no-store'
    assert storage.interview_turn_by_id('project',turn)['recordings'][0]['id']==recording['id']


@pytest.mark.parametrize('stage',['upload_fail','read_mismatch','stt_fail','empty'])
def test_failure_acknowledges_only_completed_stage_and_same_key_recovers(workflow,media,stage):
    client,storage,sql,objects,calls,mode=workflow
    mode[stage]=True;key=str(uuid4());response=upload(client,media,key)
    assert response.status_code==503,response.text
    detail=response.json()['detail']
    assert detail['backend_saved']==(stage in {'stt_fail','empty'})
    assert not [c for c in calls if c[0]=='stt'] or stage in {'stt_fail','empty'}
    recording_id=detail['recording_id']
    if stage=='read_mismatch':objects.clear()
    mode[stage]=False
    retry=client.post('/api/v1/memoir/story/transcriptions',json={'recording_id':recording_id}) if detail['backend_saved'] else upload(client,media,key)
    assert retry.status_code==200,retry.text
    assert retry.json()['recording']['id']==recording_id
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'


def test_failed_cleanup_is_inaccessible_and_retryable_without_deleting_text(workflow,media):
    client,storage,sql,objects,calls,mode=workflow
    recording=upload(client,media).json()['recording']
    storage.accept_interview_turn('project',str(uuid4()),'Words stay',kind='narrator_transcript',recording_ids=[recording['id']])
    mode['delete_fail']=True
    response=client.delete('/api/v1/memoir/story/recordings/'+recording['id'])
    assert response.json()['cleanup_status']=='pending'
    assert client.get(recording['content_url']).status_code==404
    assert sql('select text from public.user_narrator_source;').stdout.strip()=='Words stay'
    mode['delete_fail']=False
    assert client.delete('/api/v1/memoir/story/recordings/'+recording['id']).json()['cleanup_status']=='complete'
    assert not objects


@pytest.mark.parametrize('two_lane',[False,True])
@pytest.mark.parametrize('streaming',[False,True])
def test_canonical_http_source_receipt_history_and_exact_readback(workflow,media,tmp_path,monkeypatch,two_lane,streaming):
    import json
    from apps.api import agent_routes, supabase_routes
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    from test_name_only_opening import proposal
    from controlled_collector import worker_reply
    client,storage,sql,objects,calls,mode=workflow
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMOIR_TWO_LANES','1' if two_lane else '0')
    if two_lane:sql('update public.lifetime_two_lane_rollout set enabled=true;')
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS','99')
    turn_calls=[]
    def provider(request):
        turn_calls.append(1)
        output=proposal(mode='extract',name=None,question='What do you remember about the garden?')
        output['acknowledgement']='You remember the garden.'
        output['plan']['conversation_phase']='explore'
        if request.headers.get('accept')=='application/x-ndjson':
            return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},content=json.dumps({'type':'result','data':{'reply':json.dumps(output),'thread_id':'synthetic','artifacts':[]}})+'\n')
        return worker_reply(request,{'reply':json.dumps(output),'thread_id':'synthetic','artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(supabase_routes,'storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    first=upload(client,media).json()['recording'];second=upload(client,media).json()['recording']
    command={'text':'I remember the garden, with a corrected name and typed clarification.',
        'source_kind':'narrator_transcript','recording_ids':[second['id'],first['id']],'client_turn_id':str(uuid4())}
    headers={'Accept':'application/x-ndjson' if streaming else 'application/json','Authorization':'Bearer synthetic'}
    result=client.post('/api/v1/memoir/agent/turn',json=command,headers=headers)
    assert result.status_code==200,result.text
    if streaming:
        events=[json.loads(line) for line in result.text.splitlines()]
        assert not [event for event in events if event['type']=='error'],result.text
        result=next(event['data'] for event in events if event['type']=='result')
        assert next(event['data'] for event in events if event['type']=='source_accepted')['recordings']
    else:result=result.json()
    assert result['conversation_saved'] is True
    assert [r['id'] for r in result['recordings']]==command['recording_ids']
    project=result['project_id'];source=result['accepted_source_id']
    receipt=client.get(f"/api/v1/memoir/agent/turns/{command['client_turn_id']}?project_id={project}")
    assert receipt.status_code==200,receipt.text
    assert [r['id'] for r in receipt.json()['recordings']]==command['recording_ids']
    history=client.get(f'/api/v1/memoir/user/projects/{project}/history')
    assert history.status_code==200,history.text
    assert [r['id'] for r in history.json()['items'][0]['recordings']]==command['recording_ids']
    details=client.get(f'/api/v1/memoir/user/projects/{project}/sources/{source}')
    assert details.status_code==200,details.text
    assert [r['id'] for r in details.json()['recordings']]==command['recording_ids']
    replay=client.post('/api/v1/memoir/agent/turn',json=command,headers={'Authorization':'Bearer synthetic'})
    assert replay.status_code==200,replay.text
    assert replay.json()['accepted_source_id']==source
    assert len(turn_calls)==1
    changed=client.post('/api/v1/memoir/agent/turn',json={**command,'recording_ids':[first['id'],second['id']]},headers={'Authorization':'Bearer synthetic'})
    assert changed.status_code==409,changed.text
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
    assert client.get(first['content_url']).content==media[0]


def test_withdrawal_between_object_read_and_asgi_send_never_releases_stale_audio(workflow,media,monkeypatch):
    client,storage,sql,objects,calls,mode=workflow
    recording=upload(client,media).json()['recording']
    accepted=storage.accept_interview_turn('project',str(uuid4()),'Withdraw later',kind='narrator_transcript',recording_ids=[recording['id']])
    original=RecordingStore.content
    def withdraw_after_read(self,record):
        content=original(self,record)
        rpc(sql,'change_user_narrator_source',f"'project','{accepted['source']['id']}',1,'withdraw'")
        return content
    monkeypatch.setattr(RecordingStore,'content',withdraw_after_read)
    result=client.get(recording['content_url'])
    assert result.status_code==404,result.text
    assert media[0] not in result.content


def test_finalization_failure_keeps_pending_identity_and_never_dispatches_stt(workflow,media):
    client,storage,sql,objects,calls,mode=workflow
    sql("create function public.fixture_fail_finalization() returns trigger language plpgsql as $$begin raise exception 'synthetic finalization failure';end$$; create trigger fixture_fail_finalization before update on public.user_original_recording for each row when (new.storage_status='ready') execute function public.fixture_fail_finalization();")
    key=str(uuid4())
    try:result=upload(client,media,key)
    finally:sql('drop trigger fixture_fail_finalization on public.user_original_recording; drop function public.fixture_fail_finalization();')
    assert result.status_code==503,result.text
    assert result.json()['detail']['backend_saved'] is False
    assert not [call for call in calls if call[0]=='stt']
    recovered=upload(client,media,key)
    assert recovered.status_code==200,recovered.text
    assert recovered.json()['recording']['id']==result.json()['detail']['recording_id']


def test_consent_authority_revocation_fences_original_reads_and_provider_retries(workflow,media):
    client,storage,sql,objects,calls,mode=workflow
    record=upload(client,media).json()['recording']
    before=len([call for call in calls if call[0]=='stt'])
    sql("create or replace function public.original_recording_authorized(p_owner uuid,p_project_id text) returns boolean language sql stable security definer set search_path='' as $$select false$$;")
    assert client.get(record['content_url']).status_code==404
    denied=client.post('/api/v1/memoir/story/transcriptions',json={'recording_id':record['id']})
    assert denied.status_code==403,denied.text
    assert len([call for call in calls if call[0]=='stt'])==before


def test_api_outsider_and_anonymous_are_rejected_before_objects_or_provider(workflow,media):
    client,storage,sql,objects,calls,mode=workflow
    record=upload(client,media).json()['recording'];before=len(calls)
    denied=client.get(record['content_url'],headers={'Authorization':'Bearer other'})
    assert denied.status_code==404,denied.text
    denied=client.post('/api/v1/memoir/story/transcriptions',json={'recording_id':record['id']},headers={'Authorization':'Bearer other'})
    assert denied.status_code==404,denied.text
    content,mime=media
    denied=client.post('/api/v1/memoir/story/transcriptions',json={'audio_base64':base64.b64encode(content).decode(),'mime_type':mime},headers={'Authorization':'Bearer anonymous'})
    assert denied.status_code==403,denied.text
    assert client.get(record['content_url'],headers={'Authorization':'Bearer invalid'}).status_code==401
    assert len(calls)==before


def test_failed_mira_reply_keeps_accepted_source_and_audio_without_consuming_round(workflow,media,tmp_path,monkeypatch):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from memoir_postgres_workflow import PostgresRest
    client,storage,sql,objects,calls,mode=workflow
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(lambda _:httpx.Response(503))))
    record=upload(client,media).json()['recording'];turn=str(uuid4())
    result=client.post('/api/v1/memoir/agent/turn',json={'text':'I remember the garden.','source_kind':'narrator_transcript','recording_ids':[record['id']],'client_turn_id':turn})
    assert result.status_code==503,result.text
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
    assert client.get(record['content_url']).content==media[0]
    assert client.get('/api/v1/memoir/story/recordings/'+record['id']).json()['recording']['lifecycle']=='attached'
