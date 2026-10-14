"""Session creation recovers an owned project after its local adapter is lost."""
import pytest
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.store import MemoryStore
from test_agent_commit_postgres import OWNER
from test_lifetime_home_recovery import headers, identity
from test_lifetime_home_recovery import home_auth, sql, attachment_database, private_database, event_database  # noqa: F401
from test_lifetime_composer_capacity import database  # noqa: F401
from test_shared_memory_events_postgres import rpc, literal


@pytest.mark.parametrize('anonymous', [False, True])
def test_session_post_recovers_owned_lifetime_project_without_changing_history(sql, home_auth, anonymous):  # noqa: F811
    sql(f"update auth.users set is_anonymous={'true' if anonymous else 'false'} where id='{OWNER}';")
    canonical = identity(sql)
    project = canonical['project_id']
    rpc(sql, 'accept_user_narrator_source',
        f"{literal(project)},'00000000-0000-4000-8000-000000000001','Original testimony.'")
    before = sql('select jsonb_agg(to_jsonb(s)) from public.user_narrator_source s;').stdout
    store = MemoryStore()
    path = f'/api/v1/memoir/projects/{project}/memory-sessions'
    auth = {**headers(), 'Idempotency-Key': f'browser-first-memory-{project}'}
    with TestClient(main.create_app(store)) as client:
        response = client.post(path, headers=auth, json={'topic_id': 'childhood_home'})
        assert response.status_code == 201, response.text
        assert response.json()['project_id'] == project
        repeated = client.post(path, headers=auth, json={'topic_id': 'childhood_home'})
        assert repeated.status_code == 201 and repeated.json()['id'] == response.json()['id']
    assert list(store.projects) == [project]
    assert len(store.projects[project]['sessions']) == 1
    assert sql('select jsonb_agg(to_jsonb(s)) from public.user_narrator_source s;').stdout == before
    assert identity(sql) == canonical
    assert sql('select count(*) from public.user_completed_round;').stdout.strip() == '0'


@pytest.mark.parametrize('auth', [headers('other'), headers('expired'), {}, {'X-Account-Id': OWNER}])
def test_session_recovery_requires_verified_durable_ownership(sql, home_auth, auth):  # noqa: F811
    project = identity(sql)['project_id']
    store = MemoryStore()
    with TestClient(main.create_app(store)) as client:
        response = client.post(f'/api/v1/memoir/projects/{project}/memory-sessions',
            headers=auth, json={'topic_id': 'childhood_home'})
        assert response.status_code in {401, 403, 404}, response.text
    assert not store.projects
