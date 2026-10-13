"""Guest first replies use the canonical engine without adopting saved history."""
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api import main, lifetime_memory_reads
from apps.api.store import MemoryStore

from test_agent_commit_postgres import OWNER, OTHER, as_user, database
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_canonical_only_postgres import canonical_database


@pytest.fixture
def guest_sql(canonical_database):
    canonical_database('truncate public.user_memoir_project, public.user_memory, public.user_conversation_attachment cascade;')
    canonical_database('update auth.users set is_anonymous=false;')
    canonical_database(f"update auth.users set is_anonymous=true where id='{OWNER}';")
    return canonical_database


def resolve(sql, project=None, owner=OWNER, check=True):
    argument = 'null' if project is None else "'" + project.replace("'", "''") + "'"
    result = sql(as_user('select public.resolve_lifetime_conversation(' + argument + ');', owner), check=check)
    return json.loads(result.stdout.splitlines()[-1]) if check else result


def empty_project(sql, project, owner=OWNER):
    sql(f"insert into public.user_memoir_project(user_id,project_id) values('{owner}','{project}');")


def test_guest_home_resolves_canonical_identity_before_allocating_an_adapter(monkeypatch):
    calls = []
    identity = {'schema_version': 1, 'outcome': 'resolved', 'owner_id': OWNER,
        'conversation_id': str(UUID(int=9)), 'product': 'memoir', 'project_id': 'lifetime-guest'}

    def rpc(name, **options):
        calls.append(name)
        assert name == 'resolve_lifetime_conversation'
        return identity

    storage = SimpleNamespace(user_id=OWNER, user={'id': OWNER, 'is_anonymous': True}, is_anonymous=True, lifetime_rpc=rpc,
        profile=lambda: {}, ensure_memoir_project=lambda project: calls.append('legacy_project'),
        client=SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(main, 'authenticated_storage', lambda authorization: storage)
    monkeypatch.setattr(lifetime_memory_reads, 'snapshot_lifetime_read', lambda storage, project, read: read(None))
    with TestClient(main.create_app(MemoryStore())) as client:
        for _ in range(2):
            response = client.post('/api/v1/memoir/projects',
                headers={'Authorization': 'Bearer synthetic-guest'}, json={'mode': 'self'})
            assert response.status_code == 201, response.text
            assert response.json()['id'] == identity['project_id']
    assert calls == ['resolve_lifetime_conversation'] * 2


def test_new_guest_has_one_canonical_identity_across_visits_and_account_linking(guest_sql):
    first = resolve(guest_sql)
    assert first['outcome'] == 'resolved'
    assert first['owner_id'] == OWNER
    assert resolve(guest_sql) == first
    guest_sql(f"update auth.users set is_anonymous=false where id='{OWNER}';")
    assert resolve(guest_sql, first['project_id']) == first
    assert guest_sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '1'


def test_guest_first_reply_reuses_its_only_empty_owned_project(guest_sql):
    empty_project(guest_sql, 'project-first-reply')
    first = resolve(guest_sql, 'project-first-reply')
    assert first['outcome'] == 'resolved'
    assert first['project_id'] == 'project-first-reply'
    assert resolve(guest_sql, 'project-first-reply') == first


@pytest.mark.parametrize('history', ['source', 'memory', 'unscoped', 'attachment', 'multiple_projects'])
def test_guest_history_still_requires_explicit_mapping(guest_sql, history):
    empty_project(guest_sql, 'project-first-reply')
    if history == 'source':
        guest_sql(f"insert into public.user_narrator_source(user_id,project_id,client_turn_id,sequence,text,kind,language) values('{OWNER}','project-first-reply','00000000-0000-4000-8000-000000000001',1,'Saved original memory','narrator_chat','en-AU');")
    elif history in {'memory', 'unscoped'}:
        project = "'project-first-reply'" if history == 'memory' else 'null'
        guest_sql(f"insert into public.user_memory(user_id,project_id,kind,content) values('{OWNER}',{project},'agent','Saved original memory');")
    elif history == 'attachment':
        guest_sql(f"insert into public.user_conversation_attachment(user_id,project_id,messages) values('{OWNER}','project-first-reply','[]');")
    else:
        empty_project(guest_sql, 'project-second')
    result = resolve(guest_sql, 'project-first-reply')
    assert result['outcome'] == 'mapping_required'
    assert guest_sql('select count(*) from public.user_lifetime_conversation;').stdout.strip() == '0'


def test_guest_cannot_adopt_another_owners_project_or_an_invented_project(guest_sql):
    empty_project(guest_sql, 'project-other', OTHER)
    for project in ['project-other', 'project-invented']:
        assert resolve(guest_sql, project, check=False).returncode != 0
    assert resolve(guest_sql, owner=str(UUID(int=77)), check=False).returncode != 0
    assert guest_sql("set role anon; select public.resolve_lifetime_conversation(null);", check=False).returncode != 0


def test_verified_historical_project_remains_unmapped(guest_sql):
    empty_project(guest_sql, 'project-verified', OTHER)
    assert resolve(guest_sql, 'project-verified', OTHER)['outcome'] == 'mapping_required'
