"""Controlled evaluation delivery uses the actual SQL and ASGI publication seam."""
import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from apps.api.codex_runtime import CodexRuntime
from controlled_collector import worker_reply
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_name_only_opening import proposal
from test_shared_memory_events_postgres import rpc
from scripts.canonical_turn import canonical_turn, CanonicalTurnFailed


def test_controlled_delivery_and_replay_keep_sql_authority_until_asgi_send(sql, tmp_path, monkeypatch):
    identity = rpc(sql,'resolve_lifetime_conversation','null')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    calls, events = [], []
    def provider(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload['governed']['fence']['identity']['owner_id'] == OWNER
        assert payload['evaluation']['case_id'] == 'canonical-publication'
        return worker_reply(request,dict(thread_id='synthetic',reply=json.dumps(proposal(name='Joan')),artifacts=[]))
    runtime = CodexRuntime(home_root=tmp_path/'runtime',worker_url='http://synthetic.invalid',
        worker_secret='synthetic',worker_transport=httpx.MockTransport(provider))
    storage = PostgresRest(sql,OWNER).storage()
    async def scenario():
        options=dict(project_id=identity['project_id'],language='en-AU',client_turn_id=str(uuid4()),
            conversation_text='My name is Joan',source_kind='narrator_chat')
        result = await canonical_turn(runtime,storage,'My name is Joan',options=options,
            evaluation={'case_id':'canonical-publication'},on_event=events.append)
        assert result['conversation_saved'] and result['accepted_source_id']
        assert result['trajectory']['final']['status'] == 'completed'
        assert not storage.client.is_closed
        assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip() == '0'
        assert any(event['type']=='conversation_saved' for event in events)
        monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED','true')
        replay = await canonical_turn(runtime,storage,'My name is Joan',options=options,
            evaluation={'case_id':'canonical-publication'})
        assert replay['cached'] and replay['reply'] == result['reply']
        assert len(calls) == 1
    try:
        asyncio.run(scenario())
        assert sql('select count(*) from public.user_completed_round;').stdout.strip() == '1'
    finally:
        storage.client.close()


def test_unconfigured_publication_never_dispatches_or_accepts_input(sql,tmp_path,monkeypatch):
    monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL',raising=False)
    def provider(request):
        pytest.fail('Missing SQL authority must reject before provider admission')
    runtime=CodexRuntime(home_root=tmp_path/'runtime',worker_url='http://synthetic.invalid',
        worker_secret='synthetic',worker_transport=httpx.MockTransport(provider))
    storage=PostgresRest(sql,OWNER).storage()
    try:
        with pytest.raises(CanonicalTurnFailed):
            asyncio.run(canonical_turn(runtime,storage,'Synthetic input',options={}))
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '0'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip() == '0'
        assert not storage.client.is_closed
    finally:
        storage.client.close()


def test_actual_worker_correlation_and_trace_survive_canonical_delivery(sql,tmp_path,monkeypatch):
    from apps.api import codex_worker_service as workers
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_CODEX_WORKER_SECRET','synthetic')
    contacts=[]
    class AppServer:
        def __init__(self,command,home,**options):
            self.options=options
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def request(self,method,params):
            assert method=='thread/start' and params['ephemeral'] is True
            async with self.options['request_admission']():pass
            return {'thread':{'id':'controlled'}}
        async def turn(self,thread,text,**options):
            async with self.options['request_admission']():pass
            contacts.append(options['responsesapi_client_metadata'])
            self.options['trajectory'].record('codex','request.turn/start')
            result=json.dumps(proposal(name='Joan'))
            if options.get('on_delta'):await options['on_delta'](result)
            return result
    monkeypatch.setattr(workers,'CodexConnection',AppServer)
    monkeypatch.setattr(workers,'worker',workers.CodexWorker(home_root=tmp_path/'worker',api_key='synthetic'))
    runtime=CodexRuntime(home_root=tmp_path/'runtime',worker_url='http://worker.invalid',
        worker_secret='synthetic',worker_transport=httpx.ASGITransport(app=workers.app))
    storage=PostgresRest(sql,OWNER).storage()
    try:
        result=asyncio.run(canonical_turn(runtime,storage,'My name is Joan',options={
            'project_id':identity['project_id'],'language':'en-AU','client_turn_id':str(uuid4())},
            evaluation={'run_id':'controlled-native','case_id':'canonical-worker','round_id':'1'}))
        assert result['conversation_saved'] and result['trajectory']['final']['status']=='completed'
        assert contacts[0]['case_id']=='canonical-worker' and contacts[0]['round_id']=='1'
        assert sum(step['action']=='request.turn/start' for step in result['trajectory']['steps'])==1
        assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip()=='0'
    finally:storage.client.close()
