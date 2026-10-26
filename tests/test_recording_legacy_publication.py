"""Owned unmapped projects retain reads without bypassing recording consent."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from fastapi.encoders import jsonable_encoder

from test_recording_consent import (
    consent_workflow, grant, ENDPOINT, POLICY, database, workflow, approved,
    attachment_database, private_database, event_database, sql, media, upload, OWNER,
)


@pytest.mark.parametrize('endpoint', ['source','receipt','history'])
@pytest.mark.parametrize('withdraw', [False,True], ids=['permitted','withdrawn'])
def test_unmapped_owned_read_rechecks_recordings_at_publication(consent_workflow, media, monkeypatch, endpoint, withdraw):
    from apps.api import agent_routes, supabase_routes, lifetime_memory_reads
    from memoir_postgres_workflow import PostgresRest
    from test_shared_memory_events_postgres import as_user
    client, storage, sql, objects, calls, mode = consent_workflow
    assert grant(client).status_code == 200
    record = upload(client, media).json()['recording']
    turn = str(uuid4())
    accepted = storage.accept_interview_turn('project',turn,'An original legacy memory',
        kind='narrator_transcript',recording_ids=[record['id']])
    sql(as_user("insert into public.user_memory(user_id,project_id,kind,content,client_turn_id,source_sequence) values("
        f"'{OWNER}','project','agent','Storyteller: An original legacy memory','{turn}',{accepted['source']['sequence']});"))
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(supabase_routes,'storage',lambda _:PostgresRest(sql,OWNER).storage())
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    original = lifetime_memory_reads.snapshot_lifetime_read
    frozen = []
    def after_read(service, project, reader, **kwargs):
        def read(fence):
            assert fence is None
            value = reader(fence)
            content = jsonable_encoder(value)
            data = content['items'][0] if endpoint=='history' else content
            assert [r['id'] for r in data['recordings']] == [record['id']]
            frozen.append(content)
            if withdraw:
                revoked = client.put(ENDPOINT,json={**POLICY,'action':'revoke','expected_revision':1})
                assert revoked.status_code == 200
            return value
        return original(service, project, read, **kwargs)
    monkeypatch.setattr(lifetime_memory_reads,'snapshot_lifetime_read',after_read)
    monkeypatch.setattr(supabase_routes,'snapshot_lifetime_read',after_read)
    paths = {'source':f"/api/v1/memoir/user/projects/project/sources/{accepted['source']['id']}",
        'receipt':f'/api/v1/memoir/agent/turns/{turn}?project_id=project',
        'history':'/api/v1/memoir/user/projects/project/history'}
    response = client.get(paths[endpoint])
    assert response.status_code == 200, response.text
    assert len(frozen) == 1
    expected = deepcopy(frozen[0])
    if withdraw:
        (expected['items'][0] if endpoint=='history' else expected)['recordings'] = []
    assert response.json() == expected, 'An unmapped owned read published withdrawn descriptors'
    assert int(response.headers['content-length']) == len(response.content)
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_agent_turn_lease;').stdout.strip() == '0'
