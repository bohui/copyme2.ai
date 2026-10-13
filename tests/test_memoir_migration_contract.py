from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore


ROOT = Path(__file__).resolve().parents[1]


def test_api_app_imports_and_starts_from_the_committed_dependency_set():
    with TestClient(create_app(MemoryStore())) as client:
        assert client.get('/health').status_code == 200


def test_integrated_app_registers_workspace_and_formal_authority_routes():
    app = create_app(MemoryStore())
    schema = app.openapi()
    operations = {(path, method) for path, item in schema['paths'].items()
                  for method in item if method in {'get', 'post', 'put', 'patch', 'delete'}}
    assert {
        ('/v1/agent/turn', 'post'),
        ('/v1/story/private-draft/rework', 'post'),
        ('/v1/agent/projects/{project_id}/formal-memoir', 'post'),
        ('/v1/agent/projects/{project_id}/formal-memoir', 'get'),
        ('/v1/agent/projects/{project_id}/story-game/consent', 'put'),
        ('/v1/agent/projects/{project_id}/story-game/eligibility', 'get'),
    } <= operations
    focus = schema['components']['schemas']['TurnInput']['properties']['workspace_focus']
    assert 'WorkspaceMemoryFocus' in str(focus)
    ids = [schema['paths'][path][method]['operationId'] for path, method in operations]
    assert len(ids) == len(set(ids))


def test_private_round_migration_supplies_the_storage_contract_used_by_agent_storage():
    sql = (ROOT / 'supabase/migrations/202610020002_private_draft_rounds.sql').read_text()

    for fragment in (
        'add column if not exists project_id text',
        'add column if not exists client_turn_id uuid',
        'create table public.user_completed_round',
        'create table public.user_private_draft_outbox',
        'create function public.private_draft_event_snapshot',
        'p_project_id text default null',
        'p_client_turn_id uuid default null',
        'p_user_response boolean default true',
    ):
        assert fragment in sql


def test_response_stage_migration_supplies_ordering_and_life_stage_rpc_contract():
    sql = (ROOT / 'supabase/migrations/202610020004_response_stage_index.sql').read_text()

    assert 'add column life_stage_order smallint generated always as' in sql
    assert 'create index user_memory_stage_sources' in sql
    assert 'p_life_stage text default \'unplaced\'' in sql
    assert 'drop function public.commit_user_agent_turn(uuid,text,text,text[],bigint,text,uuid,boolean);' in sql
