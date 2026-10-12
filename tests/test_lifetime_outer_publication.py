"""Publication barriers at the real application's outermost ASGI send."""
import asyncio
import json

import pytest
from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.lifetime_memory_publication import TransactionalPublication
from apps.api.lifetime_memory_reads import ReadPublication,ReadSnapshot,ReadJSONResponse
from apps.api.lifetime_memory_transport import GovernedJSONResponse,GovernedStreamingResponse,GovernedResult,governed_turn_events
from test_lifetime_memory_publication import setup
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER
from test_shared_memory_events_postgres import rpc


@pytest.mark.parametrize('kind',['stream','json','read'])
@pytest.mark.parametrize('cancel',[False,True])
def test_outer_server_send_holds_policy_fence_and_cancellation_releases(sql,kind,cancel):
    import psycopg
    identity,source,fence,dsn=setup(sql)
    app=create_app(MemoryStore())
    publisher=TransactionalPublication(dsn,authenticated_owner=OWNER)
    read_fence=rpc(sql,'capture_lifetime_read_fence',f"'{identity['project_id']}'")
    @app.get('/publication-boundary')
    async def route():
        if kind=='read':
            return ReadJSONResponse(ReadSnapshot({'reply':'private payload'},read_fence),
                publisher=ReadPublication(dsn,authenticated_owner=OWNER))
        if kind=='json':
            return GovernedJSONResponse({'reply':'private payload'},publisher=publisher,fence=fence)
        async def run(emit):
            emit.set_fence(fence)
            await emit('private payload')
            return GovernedResult({'reply':'private payload'},fence)
        return GovernedStreamingResponse(governed_turn_events(run),publisher=publisher)
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();messages=[]
        async def receive():
            await asyncio.Event().wait()
        async def send(message):
            if message['type']=='http.response.body' and b'private payload' in message.get('body',b''):
                entered.set()
                await release.wait()
            messages.append(message)
        scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1',
            'method':'GET','scheme':'http','path':'/publication-boundary','raw_path':b'/publication-boundary',
            'query_string':b'','headers':[(b'x-request-id',b'outer-fence-test'),(b'origin',b'http://localhost:3000')],
            'client':('127.0.0.1',1234),'server':('test',80)}
        sending=asyncio.create_task(app(scope,receive,send))
        async with asyncio.timeout(3):await entered.wait()
        connection=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        try:
            await connection.execute('set role authenticated')
            await connection.execute("select set_config('request.jwt.claim.sub',%s,false)",(OWNER,))
            correcting=asyncio.create_task(connection.execute("select public.change_user_narrator_source(%s,%s,1,'withdraw',null)",(identity['project_id'],source['id'])))
            async with asyncio.timeout(1):
                while True:
                    blocked=await (await observer.execute('select cardinality(pg_blocking_pids(%s))',(connection.info.backend_pid,))).fetchone()
                    if blocked[0]:break
                    assert not correcting.done(),'Correction committed while outer server send was still blocked'
            if cancel:
                sending.cancel()
                with pytest.raises(asyncio.CancelledError):await sending
            else:
                release.set()
                await sending
            await correcting
            headers=dict(next(message for message in messages if message['type']=='http.response.start')['headers'])
            assert headers[b'x-request-id']==b'outer-fence-test'
            assert headers[b'access-control-allow-origin']==b'http://localhost:3000'
            if cancel:assert not any(b'private payload' in message.get('body',b'') for message in messages)
        finally:
            sending.cancel()
            await asyncio.gather(sending,return_exceptions=True)
            await connection.close();await observer.close()
    asyncio.run(scenario())
