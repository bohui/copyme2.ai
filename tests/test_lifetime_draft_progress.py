"""Five-round drafts and the final sample expose upstream extraction state."""
import pytest

from test_lifetime_composer_capacity import (
    sql, event_database, private_database, attachment_database, database,  # noqa: F401
    resolve, rpc, literal, create_lane,
)
from test_agent_commit_postgres import OTHER


@pytest.mark.parametrize('rounds',[5,20])
def test_failed_timeline_stops_draft_spinner_at_each_milestone(sql,rounds):
    identity=resolve(sql);project=identity['project_id']
    rpc(sql,'accept_user_narrator_source',f"{literal(project)},gen_random_uuid(),'An original memory.'")
    timeline=create_lane(sql,identity)
    create_lane(sql,identity,skill='composer',rounds=rounds)
    sql(f"update public.user_memoir_lane set attempts=3,error='MEMOIR_UNAVAILABLE' where id='{timeline}';")
    head=rpc(sql,'read_lifetime_private_draft_head',f"{literal(project)},'en-AU'")
    assert head['progress']['extraction']['state']=='retry_required'
    assert head['progress']['extraction']['pending_inputs']==1
    assert head['updating'] is False and head['error']=='MEMOIR_UNAVAILABLE'
    assert head['background_progress']['state']=='retry_required'
    assert head['background_progress']['phase']=='extracting'
    rpc(sql,'retry_user_memoir_lane',f"{literal(project)},'timeline'")
    resumed=rpc(sql,'read_lifetime_private_draft_head',f"{literal(project)},'en-AU'")
    assert resumed['updating'] is True
    assert resumed['progress']['extraction']['state']=='pending'
    assert resumed['background_progress']['phase']=='extracting'


def test_extraction_progress_does_not_leak_across_canonical_owners(sql):
    identity=resolve(sql);project=identity['project_id']
    rpc(sql,'accept_user_narrator_source',f"{literal(project)},gen_random_uuid(),'Owner-only testimony.'")
    timeline=create_lane(sql,identity);create_lane(sql,identity,skill='composer',rounds=5)
    sql(f"update public.user_memoir_lane set attempts=3,error='MEMOIR_UNAVAILABLE' where id='{timeline}';")
    other=resolve(sql,owner=OTHER)
    head=rpc(sql,'read_lifetime_private_draft_head',f"{literal(project)},'en-AU'",owner=OTHER)
    assert head['project_id']==other['project_id']
    assert 'extraction' not in head.get('progress',{})


def test_extraction_before_first_milestone_does_not_advertise_draft_generation(sql):
    identity=resolve(sql);project=identity['project_id']
    rpc(sql,'accept_user_narrator_source',f"{literal(project)},gen_random_uuid(),'A first recollection.'")
    create_lane(sql,identity)
    head=rpc(sql,'read_lifetime_private_draft_head',f"{literal(project)},'en-AU'")
    assert not head['updating']
    assert not head.get('background_progress')
