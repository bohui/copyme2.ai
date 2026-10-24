"""Project game access through disposable PostgreSQL and the real HTTP reader."""
import asyncio
import json
from uuid import uuid4

import pytest

from test_agent_commit_postgres import OWNER, OTHER
from test_lifetime_memory_postgres import attachment_database, private_database, event_database
from test_story_game_runtime_postgres import database, ready, prepare, stage, service
from test_shared_memory_events_postgres import sql, rpc, literal
from test_story_game_runtime import proposal, webpage, receipt

PROJECT = 'lifetime-game-sharing'


@pytest.fixture
def example(sql):
    sql('alter table auth.users add column if not exists email text; '
        'alter table auth.users add column if not exists email_confirmed_at timestamptz;')
    sql(f"update auth.users set email=case when id='{OWNER}' then 'owner@example.test' else 'friend@example.test' end,"
        "email_confirmed_at=clock_timestamp();")
    sql(f"insert into public.user_memoir_project(user_id,project_id) values('{OWNER}','{PROJECT}');")
    value = dict(synthetic=True, locale='en-AU', scenes=proposal()['scenes'], **webpage(),
        steps={'scenes': receipt(), 'webpage': {**receipt('webpage'), 'requested_model': 'gpt-6-astra'}},
        input_sha256='a' * 64)
    service(sql, 'save_story_game_example', f"'{OWNER}',{literal(PROJECT)},{literal(value)}")
    return value


def page(sql, owner=OWNER, check=True):
    return rpc(sql, 'read_story_game_page', literal(PROJECT), owner=owner, check=check)


def anonymous(sql, check=False):
    result = sql(f"set role anon;select public.read_story_game_page({literal(PROJECT)});", check=check)
    return json.loads(result.stdout.splitlines()[-1]) if check else result


def visibility(sql, mode):
    return rpc(sql, 'set_story_game_visibility', f"{literal(PROJECT)},{literal(mode)},{page(sql)['revision']}")


def invite(sql):
    return rpc(sql, 'invite_story_game_viewer', f"{literal(PROJECT)},'friend@example.test',{page(sql)['revision']}")


def accept(sql, invitation, owner=OTHER, check=True):
    return rpc(sql, 'accept_story_game_invitation', f"{literal(PROJECT)},{literal(invitation['token'])}", owner=owner, check=check)


def test_game_is_owner_only_by_default_without_changing_canonical_memories(sql, example):
    value = page(sql)
    assert value['visibility'] == 'private' and value['can_manage'] and value['example']
    assert value['game']['webpage'] == example['html']
    assert anonymous(sql).returncode
    assert page(sql, OTHER, False).returncode
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '0'
    assert 'receipt' not in value and 'authority' not in value and 'input_sha256' not in value


def test_public_mode_needs_no_account_and_can_be_withdrawn(sql, example):
    visibility(sql, 'public')
    value = anonymous(sql, check=True)
    assert value['game']['scenes'] and value['can_manage'] is False and value['invitations'] == []
    visibility(sql, 'private')
    assert anonymous(sql).returncode
    assert page(sql, OTHER, False).returncode


def test_invited_friend_requires_the_matching_verified_account(sql, example):
    visibility(sql, 'friends')
    invitation = invite(sql)
    assert len(invitation['token']) == 64
    assert page(sql, OTHER, False).returncode
    assert accept(sql, invitation, owner=OWNER, check=False).returncode
    sql(f"update auth.users set email_confirmed_at=null where id='{OTHER}';")
    assert accept(sql, invitation, check=False).returncode
    sql(f"update auth.users set email_confirmed_at=clock_timestamp() where id='{OTHER}';")
    assert accept(sql, invitation)['accepted']
    assert accept(sql, invitation)['accepted']
    played = page(sql, OTHER)
    assert played['game']['scenes'] and not played['can_manage'] and played['invitations'] == []
    assert anonymous(sql).returncode
    assert sql('select token_digest from public.user_story_game_invitation;').stdout.strip() != invitation['token']


@pytest.mark.parametrize('change', ['expired', 'wrong-project', 'revoked', 'replaced-content'])
def test_old_or_mismatched_invitations_cannot_grant_access(sql, example, change):
    visibility(sql, 'friends')
    invitation = invite(sql)
    if change == 'expired':
        sql("update public.user_story_game_invitation set expires_at=clock_timestamp()-interval '1 second';")
    elif change == 'wrong-project':
        assert rpc(sql, 'accept_story_game_invitation', f"'other-project',{literal(invitation['token'])}", owner=OTHER, check=False).returncode
        return
    elif change == 'revoked':
        rpc(sql, 'revoke_story_game_invitation', f"{literal(PROJECT)},'{invitation['invitation_id']}',{page(sql)['revision']}")
    else:
        service(sql, 'save_story_game_example', f"'{OWNER}',{literal(PROJECT)},{literal(example)}")
        assert page(sql)['visibility'] == 'private'
    assert accept(sql, invitation, check=False).returncode
    assert page(sql, OTHER, False).returncode


def test_owner_can_remove_an_accepted_friend_and_rejects_stale_sharing_changes(sql, example):
    visibility(sql, 'friends')
    invitation = invite(sql)
    accept(sql, invitation)
    before = page(sql)['revision']
    rpc(sql, 'revoke_story_game_invitation', f"{literal(PROJECT)},'{invitation['invitation_id']}',{before}")
    assert page(sql, OTHER, False).returncode
    assert rpc(sql, 'set_story_game_visibility', f"{literal(PROJECT)},'public',{before}", check=False).returncode
    assert rpc(sql, 'set_story_game_visibility', f"{literal(PROJECT)},'public',{before+1}", owner=OTHER, check=False).returncode


@pytest.mark.parametrize('role', ['anon', 'authenticated'])
def test_browser_cannot_read_private_storage_or_import_unvalidated_examples(sql, example, role):
    for table in ('user_story_game_page', 'user_story_game_invitation'):
        assert sql(f'set role {role};select * from public.{table};', check=False).returncode
    assert sql(f"set role {role};select public.save_story_game_example('{OWNER}',{literal(PROJECT)},{literal(example)});", check=False).returncode


def test_public_delivery_holds_the_visibility_lock_until_body_send_finishes(sql, example, monkeypatch):
    from apps.api.story_game_routes import StoryGameResponse
    visibility(sql, 'public')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)

    async def scenario():
        messages, withdrawal = [], None
        async def receive(): return {'type': 'http.disconnect'}
        async def send(message):
            nonlocal withdrawal
            messages.append(message)
            if message['type'] == 'http.response.start':
                withdrawal = asyncio.create_task(asyncio.to_thread(visibility, sql, 'private'))
                await asyncio.sleep(.1)
                assert not withdrawal.done()
        await StoryGameResponse(None, PROJECT)({'type': 'http'}, receive, send)
        await withdrawal
        assert messages[0]['status'] == 200
        denied = []
        async def collect(message): denied.append(message)
        await StoryGameResponse(None, PROJECT)({'type': 'http'}, receive, collect)
        assert denied[0]['status'] == 404
        assert b'My father' not in b''.join(message.get('body', b'') for message in denied)
    asyncio.run(scenario())


def test_shared_canonical_game_still_checks_source_authority(sql, ready):
    project, _, _ = ready
    game, claim, _, plan = prepare(sql, project)
    stage(sql, game, claim, plan)
    rpc(sql, 'set_story_game_visibility', f"{literal(project)},'public',1")
    assert sql(f"set role anon;select public.read_story_game_page({literal(project)});").returncode == 0
    source = sql('select id from public.user_narrator_source order by sequence limit 1;').stdout.strip()
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{source}',1,'withdraw',null")
    assert sql(f"set role anon;select public.read_story_game_page({literal(project)});", check=False).returncode
