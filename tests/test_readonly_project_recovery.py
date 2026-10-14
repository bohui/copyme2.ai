"""A lost local adapter must not prevent owned, read-only checkpoint verification."""
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.store import MemoryStore
from test_lifetime_home_recovery import headers, identity
from test_lifetime_home_recovery import home_auth, sql, attachment_database, private_database, event_database  # noqa: F401
from test_lifetime_composer_capacity import database  # noqa: F401
from test_shared_memory_events_postgres import rpc, literal


def test_owned_project_get_after_restart_preserves_durable_history(sql, home_auth):  # noqa: F811
    canonical=identity(sql);project=canonical['project_id']
    rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000001','Original testimony.'")
    before=sql('select jsonb_agg(to_jsonb(s)) from public.user_narrator_source s;').stdout
    store=MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response=client.get('/v1/projects/'+project,headers=headers())
        assert response.status_code==200,response.text
        assert response.json()['id']==project and response.json()['requires_supabase_auth']
        assert client.get('/v1/projects/'+project,headers=headers('other')).status_code in {401,403}
        assert client.get('/v1/projects/'+project).status_code==401
    assert list(store.projects)==[project]
    assert sql('select jsonb_agg(to_jsonb(s)) from public.user_narrator_source s;').stdout==before
    assert identity(sql)==canonical
    assert sql('select count(*) from public.user_lifetime_conversation;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_project_get_cannot_restore_another_owners_history(sql, home_auth):  # noqa: F811
    canonical=identity(sql);store=MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response=client.get('/v1/projects/'+canonical['project_id'],headers=headers('other'))
        assert response.status_code in {403,404},response.text
    assert not store.projects
