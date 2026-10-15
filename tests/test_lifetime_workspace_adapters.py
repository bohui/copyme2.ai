"""Legacy workspace surfaces never bypass canonical history/profile authority."""
from fastapi.testclient import TestClient
from apps.api import supabase_routes
from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.agent_storage import UserStorage
from memoir_postgres_workflow import PostgresRest
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER
from test_shared_memory_events_postgres import rpc


def test_mapped_workspace_reads_are_governed_and_legacy_cache_writes_are_explicit(sql,monkeypatch):
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    monkeypatch.setattr(supabase_routes,'storage',lambda _:PostgresRest(sql,OWNER).storage())
    def no_legacy(*args,**kwargs):raise AssertionError('Mapped recovery must not read unbounded legacy cache')
    monkeypatch.setattr(UserStorage,'all_memories',no_legacy)
    monkeypatch.setattr(UserStorage,'first_narrator_reply',no_legacy)
    with TestClient(create_app(MemoryStore())) as client:
        response=client.get('/v1/user/conversations')
        assert response.status_code==200,response.text
        assert response.json()['resume_project_id']==identity['project_id']
        assert response.json()['items'][0]['messages']==[]
        assert response.headers['cache-control']=='no-store'
        profile=client.get('/v1/user/profile')
        assert profile.status_code==200 and profile.json()['name'] is None
        assert profile.headers['cache-control']=='no-store'
        assert client.get('/v1/user/memories').status_code==409
        assert client.post('/v1/user/memories',json={'content':'unprovenanced old mirror'}).status_code==409
        assert client.put('/v1/user/profile',json={'name':'Old generated name'}).status_code==409
    assert sql('select count(*) from public.user_memory;').stdout.strip()=='0'
