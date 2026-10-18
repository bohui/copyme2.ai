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


def test_baseline_supplies_the_private_round_storage_contract():
    sql = (ROOT / 'supabase/migrations/202610180001_initial_schema.sql').read_text().lower()
    for fragment in ('project_id text', 'client_turn_id uuid',
                     'create table public.user_completed_round',
                     'create table public.user_private_draft_outbox',
                     'create function public.private_draft_event_snapshot'):
        assert fragment in sql


def test_baseline_supplies_generated_stage_order_and_ordered_sources():
    sql = (ROOT / 'supabase/migrations/202610180001_initial_schema.sql').read_text().lower()
    assert 'life_stage_order smallint generated always as' in sql
    assert '(user_id, project_id, life_stage_order, created_at, id)' in sql
