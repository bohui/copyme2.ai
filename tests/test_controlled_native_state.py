"""Canonical controlled resume persists originals rather than replaying a mock."""
import asyncio
import json
from uuid import uuid4

import httpx

from apps.api.codex_runtime import CodexRuntime
from controlled_collector import extraction_proposal, worker_reply
from scripts.canonical_turn import canonical_turn
from scripts.controlled_native_state import controlled_database, open_case, snapshot_case


def test_controlled_snapshot_roundtrip_preserves_identity_sources_rounds_and_places(tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','synthetic-byte-bpe')
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND','native')
    case={'id':'canonical-resume','project_id':'controlled-resume'}
    contacts=[]
    def provider(request):
        from apps.api.codex_worker_service import WorkerTurnInput
        payload=WorkerTurnInput.model_validate_json(request.content)
        current=payload.interview_context['source']['text']
        contacts.append(current)
        place='Hobart' if 'Hobart' in current else 'Launceston'
        value=extraction_proposal()
        value['place_journeys']=[dict(place=place,hierarchy=['Earth','Australia',place],granularity='city',latitude=None,longitude=None)]
        return worker_reply(request,dict(thread_id='synthetic',reply=json.dumps(value),artifacts=[]))
    runtime=CodexRuntime(home_root=tmp_path/'api',model='synthetic-byte-bpe',
        worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider))
    def deliver(storage,text):
        return asyncio.run(canonical_turn(runtime,storage,text,options=dict(
            project_id=case['project_id'],language='en-AU',client_turn_id=str(uuid4()))))
    with controlled_database() as sql:
        storage,_,legacy=open_case(sql,case)
        try:
            first=deliver(storage,'I was born in Hobart.')
            assert first['conversation_saved']
            state=snapshot_case(sql,storage,legacy)
            identity=storage.lifetime_rpc('read_lifetime_project_identity',p_project_id=case['project_id'])
        finally:storage.client.close()
    with controlled_database() as sql:
        storage,_,legacy=open_case(sql,case,state)
        try:
            assert storage.lifetime_rpc('read_lifetime_project_identity',p_project_id=case['project_id'])==identity
            assert storage.memory_events(case['project_id'])['completed_rounds']==1
            second=deliver(storage,'Later I lived in Launceston.')
            assert second['conversation_saved'] and second['accepted_source_id']!=first['accepted_source_id']
            saved=snapshot_case(sql,storage,legacy)
            assert saved['rounds_completed']==2
            assert {p['place'] for p in saved['place_history']}=={'Hobart','Launceston'}
            assert [s['text'] for s in storage.memory_events(case['project_id'])['sources']]==contacts
            assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip()=='0'
        finally:storage.client.close()
    assert contacts==['I was born in Hobart.','Later I lived in Launceston.']
