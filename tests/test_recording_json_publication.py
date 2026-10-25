"""Single-recording JSON replies retain consent through outer ASGI send."""
import asyncio
import base64
import json
from uuid import uuid4

import psycopg
import pytest
from starlette.responses import JSONResponse

from apps.api.original_recordings import OriginalContentResponse
from test_recording_consent import (
    consent_workflow, grant, ENDPOINT, POLICY, database, workflow, approved,
    attachment_database, private_database, event_database, sql, media, upload,
)


@pytest.fixture
def recording_json(consent_workflow, media):
    client, storage, sql, objects, calls, mode = consent_workflow
    assert grant(client).status_code == 200
    key = str(uuid4())
    record = upload(client, media, key).json()['recording']
    audio = {'audio_base64':base64.b64encode(media[0]).decode(), 'mime_type':media[1]}
    requests = {'metadata':('GET','/api/v1/memoir/story/recordings/' + record['id'],None),
        'by_upload':('GET','/api/v1/memoir/story/recordings/by-upload/' + key,None),
        'transcription':('POST','/api/v1/memoir/story/transcriptions',{'recording_id':record['id']}),
        'fresh_upload':('POST','/api/v1/memoir/story/transcriptions',
            {**audio,'upload_idempotency_key':str(uuid4())}),
        'upload_retry':('POST','/api/v1/memoir/story/transcriptions',
            {**audio,'upload_idempotency_key':key})}
    return client, sql, record, requests


def request_json(client, requests, endpoint):
    method, path, payload = requests[endpoint]
    return client.request(method, path, json=payload)


@pytest.mark.parametrize('endpoint', ['metadata', 'by_upload', 'transcription', 'fresh_upload', 'upload_retry'])
@pytest.mark.parametrize('withdraw', [False, True], ids=['permitted', 'withdrawn'])
def test_recording_json_withdrawn_after_serialization_before_send(recording_json, monkeypatch, endpoint, withdraw):
    client, sql, record, requests = recording_json
    frozen = []
    def barrier(original):
        async def before_send(self, scope, receive, send):
            try: content = json.loads(self.body)
            except (ValueError, UnicodeError): content = None
            if isinstance(content, dict) and isinstance(content.get('recording'), dict) and not frozen:
                if endpoint != 'fresh_upload': assert content['recording']['id'] == record['id']
                frozen.append(content)
                if withdraw:
                    response = await asyncio.to_thread(client.put, ENDPOINT,
                        json={**POLICY, 'action':'revoke', 'expected_revision':1})
                    assert response.status_code == 200
            return await original(self, scope, receive, send)
        return before_send
    # Both existing adapters expose frozen bytes before starting publication.
    # The barrier changes only consent; authorization still uses real SQL.
    monkeypatch.setattr(JSONResponse, '__call__', barrier(JSONResponse.__call__))
    monkeypatch.setattr(OriginalContentResponse, '__call__', barrier(OriginalContentResponse.__call__))
    response = request_json(client, requests, endpoint)
    assert len(frozen) == 1
    if withdraw:
        assert response.status_code == 404, 'A frozen recording JSON response published after withdrawal'
        published = frozen[0]['recording']
        assert published['id'] not in response.text and 'content_url' not in response.text
        assert client.get('/api/v1/memoir/story/recordings/' + published['id']).status_code == 404
        assert client.get(published['content_url']).status_code == 404
    else:
        assert response.status_code == 200, response.text
        assert response.json() == frozen[0]
        assert int(response.headers['content-length']) == len(response.content)
        assert response.headers['content-type'] == 'application/json'
        if endpoint in {'metadata', 'by_upload'}:
            assert response.headers['cache-control'] == 'private, no-store'
            assert 'Authorization' in response.headers['vary']
        assert not response.content.endswith(b'\n')


@pytest.mark.parametrize('endpoint,outcome', [
    (endpoint, outcome) for endpoint in ('metadata','by_upload','transcription','fresh_upload','upload_retry')
    for outcome in ('sent','cancelled','error')
] + [('metadata','timeout')])
def test_recording_json_send_holds_consent_and_failure_releases_locks(recording_json, endpoint, outcome):
    client, sql, record, requests = recording_json
    method, path, payload = requests[endpoint]
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []
        async def send(message):
            if message['type'] == 'http.response.body' and b'content_url' in message.get('body',b''):
                sent_record = json.loads(message['body'])['recording']
                if endpoint != 'fresh_upload': assert sent_record['id'] == record['id']
                entered.set()
                await release.wait()
                if outcome == 'error': raise OSError('controlled ASGI send failure')
            messages.append(message)
        received = False
        async def receive():
            nonlocal received
            if not received:
                received = True
                return {'type':'http.request','body':json.dumps(payload).encode(),'more_body':False}
            await asyncio.Event().wait()
        scope = {'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
            'method':method, 'scheme':'http',
            'path':path, 'raw_path':path.encode(), 'query_string':b'',
            'headers':[(b'authorization',b'Bearer synthetic'),(b'content-type',b'application/json')],
            'client':('127.0.0.1',1234),'server':('test',80)}
        sending = asyncio.create_task(client.app(scope, receive, send))
        withdrawing = None
        try:
            async with asyncio.timeout(3): await entered.wait()
            withdrawing = asyncio.create_task(asyncio.to_thread(client.put, ENDPOINT,
                json={**POLICY,'action':'revoke','expected_revision':1}))
            async with await psycopg.AsyncConnection.connect(sql.publication_dsn, autocommit=True) as observer:
                async with asyncio.timeout(3):
                    while not (await (await observer.execute("select exists(select 1 from pg_stat_activity where wait_event_type='Lock' and query like 'select public.recording_server_operation%')")).fetchone())[0]:
                        assert not withdrawing.done(), 'Withdrawal completed during actual recording JSON send'
                        await asyncio.sleep(.01)
            assert not withdrawing.done()
            if outcome == 'cancelled': sending.cancel()
            elif outcome != 'timeout': release.set()
            if outcome == 'sent':
                await sending
            else:
                with pytest.raises({'cancelled':asyncio.CancelledError,'error':OSError,'timeout':TimeoutError}[outcome]):
                    await sending
                assert not any(b'content_url' in message.get('body',b'') for message in messages)
            assert (await withdrawing).status_code == 200
        finally:
            sending.cancel()
            await asyncio.gather(sending, return_exceptions=True)
            if withdrawing is not None: await withdrawing
    asyncio.run(scenario())
    assert client.get(record['content_url']).status_code == 404
