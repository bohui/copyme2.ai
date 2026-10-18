"""Cold reads of actual canonical commits, never configured user data."""
import pytest

from apps.api.stage_readiness import readiness
from stage_progress_fixture import save_stage_source, link_stage
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve
from test_shared_memory_events_postgres import rpc, literal
from test_agent_commit_postgres import OTHER


def read(sql, project):
    # Each RPC uses a fresh PostgreSQL session: no process-local readiness cache.
    return rpc(sql, 'read_lifetime_stage_readiness', literal(project))['stages']


@pytest.mark.parametrize('words', [100, 157, 299, 300, 650, 999, 1000, 1200])
def test_canonical_saved_stage_words_survive_cold_read(sql, words):
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, '忆' * words)
    link_stage(sql, project, source, 'childhood')
    stages = read(sql, project)
    assert stages['childhood'] == readiness(words)
    assert all(value == readiness(0) for stage, value in stages.items() if stage != 'childhood')
    assert read(sql, project) == stages


def test_mixed_stage_spans_do_not_count_other_stages_or_duplicate_evidence(sql):
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, '童' * 100 + '中' * 300 + '未' * 1000)
    event = link_stage(sql, project, source, 'childhood', 0, 100)
    # Another event and an overlapping reference must not inflate the ring.
    link_stage(sql, project, source, 'childhood', 0, 100)
    link_stage(sql, project, source, 'childhood', 50, 100, event)
    link_stage(sql, project, source, 'midlife', 100, 400)
    stages = read(sql, project)
    assert stages['childhood'] == readiness(100)
    assert stages['midlife'] == readiness(300)
    assert stages['later_life'] == readiness(0)


def test_fresh_unplaced_and_unsaved_sources_are_empty(sql):
    project = resolve(sql)['project_id']
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project))['pending'] is False
    assert all(value == readiness(0) for value in read(sql, project).values())
    source = save_stage_source(sql, project, '忆' * 1000)
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project))['pending'] is True
    sql("update public.user_narrator_source set processing_status='succeeded';")
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project))['pending'] is False
    assert all(value == readiness(0) for value in read(sql, project).values())
    from uuid import uuid4
    unsaved = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','童年'")
    link_stage(sql, project, unsaved, 'childhood')
    assert all(value == readiness(0) for value in read(sql, project).values())


def test_stage_reassignment_edit_withdrawal_and_owner_scope(sql):
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, '忆' * 300)
    event = link_stage(sql, project, source, 'childhood')
    assert read(sql, project)['childhood'] == readiness(300)
    sql(f"update public.user_memory_event set life_stage='midlife' where id='{event}';")
    assert read(sql, project)['childhood'] == readiness(0)
    assert read(sql, project)['midlife'] == readiness(300)
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=OTHER, check=False).returncode
    other_project = resolve(sql, owner=OTHER)['project_id']
    assert all(value == readiness(0) for value in read_for_owner(sql, other_project, OTHER).values())
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{source['id']}',1,'edit','更正童年'")
    assert all(value == readiness(0) for value in read(sql, project).values())
    changed = {**source, 'text': '更正童年', 'version': 2}
    link_stage(sql, project, changed, 'childhood')
    assert read(sql, project)['childhood'] == readiness(4)
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{source['id']}',2,'withdraw',null")
    assert all(value == readiness(0) for value in read(sql, project).values())


def read_for_owner(sql, project, owner):
    return rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=owner)['stages']




def test_legacy_totals_survive_and_canonical_replies_are_not_double_counted(sql):
    from test_agent_commit_postgres import OWNER
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, '忆' * 100)
    link_stage(sql, project, source, 'childhood')
    sql(f"update public.user_memory set life_stage='childhood' where client_turn_id='{source['client_turn_id']}';")
    text = 'Storyteller: ' + 'memory ' * 200 + '\nMemory Spark: assistant prose is excluded'
    sql(f"insert into public.user_memory(user_id,project_id,kind,content,life_stage) values "
        f"('{OWNER}',{literal(project)},'agent',{literal(text)},'midlife');")
    assert read(sql, project)['childhood'] == readiness(100)
    assert read(sql, project)['midlife'] == readiness(200)
