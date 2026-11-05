"""Consecutive narration through the actual API, SQL ledger and worker transport."""
import asyncio
import json
from uuid import uuid4

import httpx

from apps.api import agent_routes, supabase_routes
from apps.api.codex_runtime import CodexRuntime
from apps.api.main import create_app
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER, OTHER
from test_background_profile_workflow import database
from test_conversation_reply import proposal
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_shared_memory_events_postgres import literal, rpc
from controlled_collector import worker_reply


def test_cancelled_replies_keep_all_originals_and_latest_reply_survives_cold_history(sql, tmp_path, monkeypatch):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMOIR_TWO_LANES', '1')
    monkeypatch.setenv('MEMORY_SPARK_PARALLEL_POLICY_REVIEW', '0')
    sql('update public.lifetime_two_lane_rollout set enabled=true;')
    identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
    project = identity['project_id']
    originals = ['We moved in 1985.', 'Actually, it was 1986.', 'My sister came with us.']
    turns = [str(uuid4()) for _ in originals]
    packets, started, cancelled = [], [], []

    class WaitingReply(httpx.AsyncByteStream):
        def __init__(self, index):
            self.index = index

        async def __aiter__(self):
            yield (json.dumps({'type':'text_delta', 'text':'{"acknowledgement":"An unfinished reply",'}) + '\n').encode()
            started[self.index].set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(self.index)

    async def provider(request):
        packet = json.loads(json.loads(request.content)['governed']['packet'])
        index = len(packets)
        packets.append(packet)
        if index < 2:
            return httpx.Response(200, headers={'Content-Type':'application/x-ndjson'}, stream=WaitingReply(index))
        output = dict(proposal(), acknowledgement='Your sister came with you when you moved in 1986.',
            question='What do you remember about arriving together?')
        return worker_reply(request, {'reply':json.dumps(output), 'thread_id':'latest-mira', 'artifacts':[]})

    def runtime():
        return CodexRuntime(home_root=tmp_path / 'homes', worker_url='http://controlled.invalid',
            worker_secret='synthetic', worker_transport=httpx.MockTransport(provider))

    monkeypatch.setattr(agent_routes, 'runtime', runtime())
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _:PostgresRest(sql, OWNER).storage())
    monkeypatch.setattr(supabase_routes, 'storage', lambda _:PostgresRest(sql, OWNER).storage())
    app = create_app(MemoryStore())

    async def run():
        started.extend([asyncio.Event(), asyncio.Event()])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://api.test') as client:
            for index in range(2):
                request = asyncio.create_task(client.post('/v1/agent/turn', headers={'Accept':'application/x-ndjson'},
                    json={'project_id':project, 'client_turn_id':turns[index], 'text':originals[index]}))
                await asyncio.wait_for(started[index].wait(), 15)
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
                assert cancelled == list(range(index + 1)), 'Worker generation outlived the cancelled API turn'
            # A new runtime must reconstruct both unanswered messages from SQL.
            monkeypatch.setattr(agent_routes, 'runtime', runtime())
            result = await client.post('/v1/agent/turn', headers={'Accept':'application/x-ndjson'},
                json={'project_id':project, 'client_turn_id':turns[2], 'text':originals[2]})
            events = [json.loads(line) for line in result.text.splitlines()]
            assert not [event for event in events if event['type'] == 'error'], events
            saved = next(event['data'] for event in events if event['type'] == 'result')
            assert saved['conversation_saved'] and saved['client_turn_id'] == turns[2]
            assert '1986' in saved['reply']
            history = await client.get(f'/api/v1/memoir/user/projects/{project}/history')
            assert history.status_code == 200, history.text
            assert [item['narrator_text'] for item in history.json()['items']] == originals
            assert [item['reply'] for item in history.json()['items']] == [None, None, saved['reply']]
            return history.json()

    history = asyncio.run(run())
    assert [row['narrator']['original'] for row in packets[-1]['tail']] == originals[:2]
    assert packets[-1]['current']['narrator']['original'] == originals[-1]
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '3'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip() == '1'
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip() == '1'
    assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip() == '0'
    # The new page reader is owner scoped, including unanswered originals.
    assert rpc(sql, 'read_user_conversation_page', literal(project), owner=OTHER) == []
    assert [row['client_turn_id'] for row in history['items']] == turns
