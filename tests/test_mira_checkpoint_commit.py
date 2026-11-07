"""A verified runtime archive becomes usable only with its exact reply commit."""
import asyncio
import hashlib
import json
from uuid import uuid4
from types import SimpleNamespace

import pytest

from test_agent_commit_postgres import OWNER, OTHER, OLD, as_user
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_lifetime_memory_commit import prepare, commit
from test_shared_memory_events_postgres import rpc, literal


def checkpoint(sql, identity, source, *, digest='a' * 64, upload=True):
    value = dict(scope='b' * 64, archive_sha256=digest, byte_size=123,
        sequence=source['sequence'], source_id=source['id'], source_version=source['version'],
        thread_id='fresh-engine', reply_sha256=hashlib.sha256(b'Hello Joan.').hexdigest())
    value['path'] = (OWNER + '/sandbox/' + identity['conversation_id'] + '/' + value['scope']
        + '/' + str(source['sequence']) + '-' + digest + '/checkpoint.zip')
    if upload:
        sql("insert into storage.objects(bucket_id,name,metadata) values ('memory-spark',"
            + literal(value['path']) + ",'{\"size\":123}');")
    return value


def stage(sql, fence, value, *, owner=OWNER, check=True, allow_committed=False):
    return sql("set role service_role; set request.jwt.claim.sub='" + owner + "'; "
        'select public.stage_lifetime_runtime_checkpoint(' + literal(fence) + '::jsonb,'
        + literal(value) + '::jsonb,false' + (',true' if allow_committed else '') + ');', check=check)


def pointer(sql, column='runtime_checkpoint'):
    return json.loads(sql("select coalesce(" + column + ",'null'::jsonb) from public.user_lifetime_conversation;").stdout)


def test_reply_setup_preserves_authorized_context_and_history_under_one_fence(sql):
    identity, turn, _, fence = prepare(sql)
    value = commit(sql, turn, fence)
    next_turn = str(uuid4())
    accepted = rpc(sql, 'accept_user_interview_turn', literal(identity['project_id'])
        + ", '" + next_turn + "','I remember the shed','narrator_chat','en-AU'")
    conversation = literal(identity['conversation_id'])
    fence = rpc(sql, 'capture_lifetime_fence', f"{conversation},'{OLD}'")
    sequence = accepted['source']['sequence']
    epoch = fence['policy_epoch']
    args = f"{literal(fence)}::jsonb,{sequence},'fixture-model','lifetime-v1',"
    terms = ['shed', 'name']
    setup_args = args + literal(terms) + '::jsonb'
    setup = rpc(sql, 'read_lifetime_mira_reply_setup', setup_args)
    assert setup['context'] == rpc(sql, 'read_lifetime_interview_context', conversation)
    assert setup['checkpoint'] == rpc(sql, 'read_lifetime_checkpoint_before',
        f"{conversation},{epoch},'fixture-model','lifetime-v1',{sequence},true")
    after = setup['checkpoint']['coverage_end'] if setup['checkpoint'] else 0
    assert setup['tail'] == rpc(sql, 'read_lifetime_two_lane_tail', f'{conversation},{epoch},{after},{sequence - 1}')
    assert value['interview']['reply'] in [row['assistant_reply'] for row in setup['tail']['records']]
    assert setup['evidence']['pins'] == rpc(sql, 'read_lifetime_pinned', conversation)
    assert setup['evidence']['pages'] == [
        rpc(sql, 'read_lifetime_source_page', f'{conversation},{epoch},null,8,{literal(term)}') for term in terms]
    assert setup['evidence']['fallback'] is None
    fallback = rpc(sql, 'read_lifetime_source_page', f"{conversation},{epoch},null,8,''")
    absent = rpc(sql, 'read_lifetime_mira_reply_setup', args + "'[\"unmatched\"]'::jsonb")
    assert absent['evidence']['pages'][0]['records'] == []
    assert absent['evidence']['fallback'] == fallback
    unfiltered = rpc(sql, 'read_lifetime_mira_reply_setup', args + "'[]'::jsonb")
    assert unfiltered['evidence']['pages'] == [fallback]
    assert unfiltered['evidence']['fallback'] is None
    assert rpc(sql, 'read_lifetime_mira_reply_setup',
        args + literal(['shed'] * 9) + '::jsonb', check=False).returncode != 0
    assert rpc(sql, 'read_lifetime_mira_reply_setup', setup_args, owner=OTHER, check=False).returncode != 0

    sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    stale = rpc(sql, 'read_lifetime_mira_reply_setup', setup_args, check=False)
    assert stale.returncode != 0 and 'stale lifetime fence' in stale.stderr


def test_uploaded_archive_is_not_a_usable_checkpoint(sql):
    identity, turn, accepted, fence = prepare(sql)
    checkpoint(sql, identity, accepted['source'])
    saved = commit(sql, turn, fence)
    assert saved['home_checkpoint'] is None
    assert pointer(sql) is None
    execution = rpc(sql, 'read_lifetime_interview_context', literal(identity['conversation_id']))['execution']
    assert execution['home_checkpoint'] is None


def test_verified_metadata_is_promoted_atomically_with_the_exact_reply(sql):
    identity, turn, accepted, fence = prepare(sql)
    value = checkpoint(sql, identity, accepted['source'])
    stage(sql, fence, value)
    assert pointer(sql) is None
    assert pointer(sql, 'runtime_checkpoint_candidate')['path'] == value['path']
    assert rpc(sql, 'read_lifetime_interview_context', literal(identity['conversation_id']))['execution'] is None
    saved = commit(sql, turn, fence)
    assert all(saved['home_checkpoint'][key] == expected for key, expected in value.items())
    assert pointer(sql) == saved['home_checkpoint']
    assert pointer(sql, 'runtime_checkpoint_candidate') is None
    assert rpc(sql, 'read_lifetime_interview_context', literal(identity['conversation_id']))['execution']['home_checkpoint'] == pointer(sql)
    # A new source/policy version cannot resurrect this runtime state.
    sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    assert rpc(sql, 'read_lifetime_interview_context', literal(identity['conversation_id']))['execution']['home_checkpoint'] is None


def test_deferred_verification_attaches_after_the_reply_releases_its_lease(sql):
    identity, turn, accepted, fence = prepare(sql)
    value = checkpoint(sql, identity, accepted['source'])
    assert commit(sql, turn, fence)['home_checkpoint'] is None
    sql(as_user(f"select public.release_user_agent_turn_lease('{OLD}');"))
    assert pointer(sql) is None

    wrong_reply = {**value, 'reply_sha256':'c' * 64}
    assert stage(sql, fence, wrong_reply, allow_committed=True, check=False).returncode != 0
    assert pointer(sql) is None
    stage(sql, fence, value, allow_committed=True)
    execution = rpc(sql, 'read_lifetime_interview_context', literal(identity['conversation_id']))['execution']
    assert execution['home_checkpoint']['path'] == value['path']
    assert pointer(sql, 'runtime_checkpoint_candidate') is None

    sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    assert stage(sql, fence, value, allow_committed=True, check=False).returncode != 0
    assert rpc(sql, 'read_lifetime_interview_context', literal(identity['conversation_id']))['execution']['home_checkpoint'] is None


def test_failed_next_commit_keeps_the_previous_usable_checkpoint(sql):
    identity, first_turn, accepted, fence = prepare(sql)
    first_fence = fence
    first = checkpoint(sql, identity, accepted['source'])
    stage(sql, fence, first)
    commit(sql, first_turn, fence)
    previous = pointer(sql)
    second_turn = str(uuid4())
    accepted = rpc(sql, 'accept_user_interview_turn', literal(identity['project_id'])
        + ", '" + second_turn + "','My name is Joan','narrator_chat','en-AU'")
    fence = rpc(sql, 'capture_lifetime_fence', "'" + identity['conversation_id'] + "','" + OLD + "'")
    second = checkpoint(sql, identity, accepted['source'], digest='c' * 64)
    stage(sql, fence, second)
    sql("alter table public.user_memory add constraint checkpoint_commit_failure check (content not like '%Hello Joan.%') not valid;")
    try:
        failed = commit(sql, second_turn, fence, check=False)
        assert failed.returncode != 0 and 'checkpoint_commit_failure' in failed.stderr
        assert pointer(sql) == previous
        assert pointer(sql, 'runtime_checkpoint_candidate')['path'] == second['path']
        assert rpc(sql, 'read_lifetime_interview_context', literal(identity['conversation_id']))['execution']['home_checkpoint'] == previous
    finally:
        sql('alter table public.user_memory drop constraint checkpoint_commit_failure;')
    commit(sql, second_turn, fence)
    assert pointer(sql)['path'] == second['path']
    assert stage(sql, first_fence, first, allow_committed=True, check=False).returncode != 0
    assert pointer(sql)['path'] == second['path']
    assert pointer(sql)['path'] != previous['path']


def test_client_cannot_attest_verification_or_write_checkpoint_metadata(sql):
    identity, _, accepted, fence = prepare(sql)
    value = checkpoint(sql, identity, accepted['source'])
    args = literal(fence) + '::jsonb,' + literal(value) + '::jsonb,false'
    assert rpc(sql, 'stage_lifetime_runtime_checkpoint', args, check=False).returncode != 0
    assert sql(as_user("update public.user_lifetime_conversation set runtime_checkpoint='{}';"), check=False).returncode != 0
    assert stage(sql, fence, value, owner=OTHER, check=False).returncode != 0
    assert pointer(sql, 'runtime_checkpoint_candidate') is None


def test_worker_staging_bridge_commits_only_pending_metadata(sql):
    from apps.api.codex_home_store import stage_checkpoint
    from apps.api.lifetime_memory_contracts import ExecutionFence
    identity, turn, accepted, fence = prepare(sql)
    value = checkpoint(sql, identity, accepted['source'])
    publisher = SimpleNamespace(_dsn=sql.publication_dsn, lock_function='lock_lifetime_publication')
    asyncio.run(stage_checkpoint(publisher, ExecutionFence.model_validate(fence), value))
    assert pointer(sql) is None
    assert pointer(sql, 'runtime_checkpoint_candidate')['path'] == value['path']
    commit(sql, turn, fence)
    assert pointer(sql)['path'] == value['path']


@pytest.mark.parametrize('change', ['missing_object', 'wrong_size', 'wrong_path', 'stale_fence'])
def test_staging_requires_the_exact_stored_object_and_current_authority(sql, change):
    identity, _, accepted, fence = prepare(sql)
    value = checkpoint(sql, identity, accepted['source'], upload=change != 'missing_object')
    if change == 'wrong_size':
        value['byte_size'] += 1
    elif change == 'wrong_path':
        value['path'] = value['path'].replace(OWNER, OTHER)
    elif change == 'stale_fence':
        sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    assert stage(sql, fence, value, check=False).returncode != 0
    assert pointer(sql) is None and pointer(sql, 'runtime_checkpoint_candidate') is None
