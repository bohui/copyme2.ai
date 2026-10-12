"""An actual pre-position-log schema upgrade never invents historical coverage."""
from pathlib import Path
import pytest
from test_agent_commit_postgres import OWNER,database
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import rpc


@pytest.fixture(scope='module')
def upgraded_database(private_database):
    sql=private_database
    migrations=sorted((Path(__file__).resolve().parents[1]/'supabase/migrations').glob('*.sql'))
    for path in migrations:
        if '202610040001'<=path.name<'202610120006':sql(path.read_text())
    sources=[rpc(sql,'accept_user_narrator_source',f"'approved-fixture-project','00000000-0000-4000-8000-{n:012d}','Original historical memory {n}'") for n in (1,2)]
    before=sql("select jsonb_agg(to_jsonb(s) order by sequence) from public.user_narrator_source s;").stdout
    for path in migrations:
        if path.name>='202610120006':sql(path.read_text())
    return sql,sources,before


def test_upgrade_requires_explicit_inventory_before_fixture_mapping_can_read(upgraded_database):
    sql,sources,before=upgraded_database
    assert rpc(sql,'resolve_lifetime_conversation','null')['outcome']=='mapping_required'
    assert sql("select jsonb_agg(to_jsonb(s) order by sequence) from public.user_narrator_source s;").stdout==before
    # Historical inventory does not itself attest that old direct calls ended.
    blocked = sql(f"insert into public.user_lifetime_conversation(user_id,project_id) values('{OWNER}','approved-fixture-project');", check=False)
    assert blocked.returncode != 0 and 'LIFETIME_REALTIME_CLEARANCE_REQUIRED' in blocked.stderr
    assert sql("select count(*) from public.user_lifetime_conversation;").stdout.strip() == '0'
    # Only this isolated fixture has no real calls. Do not infer production clearance.
    sql("select public.begin_lifetime_realtime_drain(0);")
    sql("select public.attest_lifetime_realtime_clearance(1,'synthetic-upgrade-fixture-no-live-calls');")
    # This explicit synthetic mapping represents a separately approved operator
    # action; no application startup or migration chooses the historical project.
    sql(f"insert into public.user_lifetime_conversation(user_id,project_id) values('{OWNER}','approved-fixture-project');")
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    failed=rpc(sql,'read_lifetime_source_page',f"'{identity['conversation_id']}',1",check=False)
    assert failed.returncode and 'LIFETIME_INVENTORY_REQUIRED' in failed.stderr
    assert sql('select count(*) from public.user_lifetime_source_position;').stdout.strip()=='0'
    # Approved fixture-only inventory preserves every source/turn ID and exact
    # sequence. Production needs its own approved inventory/rollback evidence.
    sql("insert into public.user_lifetime_source_position(user_id,project_id,sequence,source_id,version) select user_id,project_id,sequence,id,version from public.user_narrator_source;")
    page=rpc(sql,'read_lifetime_source_page',f"'{identity['conversation_id']}',1")
    assert page['complete'] and [row['source_id'] for row in page['records']]==[s['id'] for s in sources]
    sql(f"delete from public.user_lifetime_source_position where source_id='{sources[0]['id']}';")
    failed=rpc(sql,'read_lifetime_source_page',f"'{identity['conversation_id']}',1",check=False)
    assert failed.returncode and 'LIFETIME_INVENTORY_REQUIRED' in failed.stderr
