"""A selected test owner can exercise real strategy delivery during shadow rollout."""
import pytest

from test_interview_strategy_postgres import (
    database, sql, event_database, private_database, attachment_database,
    enable_only_disposable_database_rollout, setup, commit,
)
from test_agent_commit_postgres import OWNER, OTHER, as_user
from test_shared_memory_events_postgres import rpc, literal
from test_conversation_attribution import Conversation, empty, episode


@pytest.fixture
def scoped_sql(sql):
    sql('delete from public.lifetime_strategy_active_owner;')
    sql('update public.lifetime_two_lane_rollout set enabled=true,strategy_enabled=true,strategy_shadow=true;')
    return sql


def enroll(sql):
    sql(f"insert into public.lifetime_strategy_active_owner(user_id) values ('{OWNER}');")


def mode(sql, owner):
    return sql(f"select public.lifetime_interview_strategy_rollout('{owner}');").stdout.strip()


def test_only_enrolled_owner_receives_active_planning_and_no_mode_is_fabricated(scoped_sql):
    sql = scoped_sql
    assert mode(sql, OWNER) == mode(sql, OTHER) == 'shadow'
    enroll(sql)
    identity, _, lane_id, page = setup(sql)
    assert page['two_lane']['strategy_mode'] == 'active'
    commit(sql, lane_id, page)
    context = rpc(sql, 'read_lifetime_strategy_context', f"'{identity['conversation_id']}'")
    assert context['mode'] == 'active' and context['plan']['strategy'] == 'shape'
    assert mode(sql, OTHER) == 'shadow'
    assert rpc(sql, 'read_lifetime_current_mode', literal(identity['project_id'])) is None
    assert sql('select strategy_shadow from public.lifetime_two_lane_rollout;').stdout.strip() == 't'


def test_enrolled_owner_gets_shape_only_from_a_real_delivered_foreground_reply(scoped_sql, tmp_path, monkeypatch):
    sql = scoped_sql
    conversation = Conversation(sql, tmp_path, monkeypatch,
        lambda packet: {**empty(packet), 'events': [episode(packet, packet['sources'][0]['text'])]}, strategy='shape')
    sql('update public.lifetime_two_lane_rollout set strategy_shadow=true;')
    enroll(sql)
    with conversation.client:
        conversation.say('I repaired bicycles with my father. I want to arrange these memories.')
        conversation.drain()
        current = rpc(sql, 'read_lifetime_current_mode', literal(conversation.project))
        assert current['mode'] == 'shape' and current['reply_id'] and current['source_id']
        sql('update public.lifetime_strategy_active_owner set enabled=false;')
        assert rpc(sql, 'read_lifetime_current_mode', literal(conversation.project)) is None


@pytest.mark.parametrize('field', ['enabled', 'strategy_enabled'])
def test_global_kill_switch_still_disables_an_enrolled_owner(scoped_sql, field):
    enroll(scoped_sql)
    assert mode(scoped_sql, OWNER) == 'active'
    scoped_sql(f'update public.lifetime_two_lane_rollout set {field}=false;')
    assert mode(scoped_sql, OWNER) == 'disabled'


def test_authenticated_callers_cannot_enroll_or_inspect_another_owner(scoped_sql):
    assert scoped_sql(as_user(f"insert into public.lifetime_strategy_active_owner(user_id) values ('{OWNER}');"),
                      check=False).returncode
    assert scoped_sql(as_user(f"select public.lifetime_interview_strategy_rollout('{OTHER}');"),
                      check=False).returncode


def test_disabling_cohort_fences_a_planner_that_already_claimed_its_page(scoped_sql):
    enroll(scoped_sql)
    _, _, lane_id, page = setup(scoped_sql)
    scoped_sql('update public.lifetime_strategy_active_owner set enabled=false;')
    with pytest.raises(AssertionError):
        commit(scoped_sql, lane_id, page)
    assert scoped_sql('select count(*) from public.user_lifetime_interview_strategy;').stdout.strip() == '0'
