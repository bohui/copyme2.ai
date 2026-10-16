"""Atomic literal-policy acceptance on a disposable database only."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from test_agent_commit_postgres import database, as_user, OWNER, OTHER, OLD
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, rpc, literal
from test_lifetime_memory_postgres import sql, resolve
from apps.api.lifetime_memory_continuity import literal_continuity_updates

TURN = '00000000-0000-4000-8000-000000000701'


def accept(sql, identity, text, turn=TURN, check=True):
    # JSON may contain literal U+2028/U+2029. Python splitlines() would split
    # those inside source text, so consume the complete psql JSON result here.
    result = sql(as_user(f"select public.accept_user_interview_turn({literal(identity['project_id'])},'{turn}',{literal(text)});"), check=check)
    return json.loads(result.stdout.strip()) if check else result


def status(sql, identity):
    return rpc(sql, 'read_lifetime_policy_status', f"'{identity['conversation_id']}'")


def policies(sql, identity):
    epoch = int(sql(f"select policy_epoch from public.user_memoir_project where user_id='{OWNER}' and project_id={literal(identity['project_id'])};").stdout.strip())
    return rpc(sql, 'read_lifetime_continuity', f"'{identity['conversation_id']}',{epoch}")['records']


@pytest.mark.parametrize('text', [
    "Don't discuss my school. Let's set aside my workplace for now.",
    '不要讨论我的学校。先不聊我的工作。',
    'I visited home.\n\tDo not mention my school!\n先不聊我的工作。',
    'She said:\nDon\'t discuss my school.',
    'The teacher wrote.\nDo not discuss my school.',
    '他写道：\n不要讨论我的学校。',
])
def test_policy_is_complete_when_acceptance_returns_and_matches_python(sql, text):
    identity = resolve(sql)
    accepted = accept(sql, identity, text)
    source = accepted['source']
    expected = [row for row in literal_continuity_updates({'source': source})
                if row['kind'] in {'excluded_topic', 'paused_topic'}]
    saved = policies(sql, identity)
    assert [{'record_id': row['record_id'], 'kind': row['kind'], 'data': row['data']} for row in saved] == sorted(expected, key=lambda row: row['record_id'])
    assert status(sql, identity)['pending'] is False
    assert sql('select count(*) from public.user_lifetime_source_policy_receipt;').stdout.strip() == '1'
    # A crash preserves the controls but cannot silently abandon the accepted
    # source. Reconcile that exact turn before admitting a different source.
    blocked = accept(sql, identity, 'I walked through the garden.',
                     '00000000-0000-4000-8000-000000000702', check=False)
    assert blocked.returncode != 0 and 'pending reply' in blocked.stderr
    resumed = accept(sql, identity, text)
    assert resumed['source']['id'] == source['id']
    assert status(sql, identity)['pending'] is False
    assert len(policies(sql, identity)) == len(expected)


@pytest.mark.parametrize('template', ['Do not mention topic {n}.', '不要讨论话题{n}。'])
def test_exact_eight_are_atomic_but_nine_are_rejected_before_acceptance(sql, template):
    identity = resolve(sql)
    nine = ' '.join(template.format(n=n) for n in range(9))
    failed = accept(sql, identity, nine, check=False)
    assert failed.returncode != 0 and 'LIFETIME_POLICY_INPUT_LIMIT' in failed.stderr
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_interview_turn;').stdout.strip() == '0'
    assert status(sql, identity)['pending'] is False
    accept(sql, identity, ' '.join(template.format(n=n) for n in range(8)))
    assert len(policies(sql, identity)) == 8


def test_overlong_recognized_control_rolls_back_without_truncation(sql):
    identity = resolve(sql)
    failed = accept(sql, identity, 'Do not discuss ' + '字' * 500, check=False)
    assert failed.returncode != 0 and 'LIFETIME_POLICY_INPUT_LIMIT' in failed.stderr
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '0'


def test_retry_and_empty_model_update_never_duplicate_or_remove_atomic_controls(sql):
    identity = resolve(sql)
    first = accept(sql, identity, "Don't discuss my school.")
    before = policies(sql, identity)
    again = accept(sql, identity, "Don't discuss my school.")
    assert again['source']['id'] == first['source']['id']
    assert policies(sql, identity) == before
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence = rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")
    rpc(sql, 'persist_lifetime_continuity_updates', f"{literal(fence)}::jsonb,'[]',true")
    assert policies(sql, identity) == before


def test_source_edit_uses_final_policy_epoch_and_withdrawal_removes_controls(sql):
    identity = resolve(sql)
    source = accept(sql, identity, 'I remember school.')['source']
    edited = rpc(sql, 'change_user_narrator_source',
        f"{literal(identity['project_id'])},'{source['id']}',1,'edit',{literal('Do not discuss my school.')} ")
    saved = policies(sql, identity)
    assert len(saved) == 1 and saved[0]['policy_epoch'] == 2
    assert saved[0]['data']['source_refs'][0]['version'] == edited['version'] == 2
    assert status(sql, identity)['pending'] is False
    rpc(sql, 'change_user_narrator_source', f"{literal(identity['project_id'])},'{source['id']}',2,'withdraw',null")
    assert policies(sql, identity) == [] and status(sql, identity)['pending'] is False


def test_unproven_import_is_pending_and_blocks_body_publication_without_replaying_history(sql):
    identity = resolve(sql)
    # Database-owner fixture models a historical/import path, not new authorized narration.
    sql(f"insert into public.user_narrator_source(user_id,project_id,client_turn_id,sequence,text,kind,language) values('{OWNER}',{literal(identity['project_id'])},'{TURN}',1,'Do not discuss my school.','narrator_chat','en-AU');")
    pending = status(sql, identity)
    assert pending['pending'] is True and pending['pending_client_turn_id'] == TURN
    assert policies(sql, identity) == []
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence = rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")
    denied = rpc(sql, 'lock_lifetime_publication', f"{literal(fence)}::jsonb", check=False)
    assert denied.returncode != 0 and 'LIFETIME_POLICY_PENDING' in denied.stderr
    read = rpc(sql, 'capture_lifetime_read_fence', literal(identity['project_id']))
    denied = rpc(sql, 'lock_lifetime_read_publication', f"{literal(read)}::jsonb", check=False)
    assert denied.returncode != 0 and 'LIFETIME_POLICY_PENDING' in denied.stderr
    denied = rpc(sql, 'persist_lifetime_continuity_updates', f"{literal(fence)}::jsonb,'[]',true", check=False)
    assert denied.returncode != 0
    assert status(sql, identity) == pending
    assert rpc(sql, 'read_lifetime_policy_status', f"'{identity['conversation_id']}'", owner=OTHER, check=False).returncode != 0


def test_policy_receipt_and_completion_helpers_are_not_client_writable(sql):
    identity = resolve(sql)
    source = accept(sql, identity, 'I remember school.')['source']
    for statement in [
        'select * from public.user_lifetime_source_policy_receipt',
        'delete from public.user_lifetime_pending_policy',
        f"select public.apply_lifetime_literal_policy('{OWNER}',{literal(identity['project_id'])},'{source['id']}',1)",
    ]:
        assert sql(as_user(statement), check=False).returncode != 0


def test_mapping_inventory_cannot_be_cleared_by_fixing_only_one_historical_source(sql):
    first = rpc(sql, 'accept_user_narrator_source', f"'old','{TURN}','Do not mention my school.'")
    rpc(sql, 'accept_user_narrator_source', "'old','00000000-0000-4000-8000-000000000702','Do not mention my workplace.'")
    # Explicit owner-only mapping fixture; mapping itself never replays preferences.
    sql(f"insert into public.user_lifetime_conversation(user_id,project_id) values('{OWNER}','old');")
    identity = resolve(sql)
    assert status(sql, identity)['pending'] is True
    assert policies(sql, identity) == []
    rpc(sql, 'change_user_narrator_source', f"'old','{first['id']}',1,'withdraw',null")
    assert status(sql, identity)['pending'] is True
    assert sql('select count(*) from public.user_lifetime_policy_inventory_pending;').stdout.strip() == '1'


def test_missing_profile_concurrent_acceptance_and_profile_creation_do_not_upgrade_deadlock(sql):
    identity = resolve(sql)
    sql(f"delete from public.user_profile where user_id='{OWNER}';")
    with ThreadPoolExecutor(max_workers=2) as pool:
        accepted = pool.submit(accept, sql, identity, 'Do not mention my school.')
        profile = pool.submit(sql, as_user("set statement_timeout='3s'; insert into public.user_profile(user_id,profile) values(auth.uid(),'{}') on conflict(user_id) do update set profile=excluded.profile;"))
        assert accepted.result(timeout=5)['source']
        assert profile.result(timeout=5).returncode == 0
    assert len(policies(sql, identity)) == 1 and status(sql, identity)['pending'] is False


def test_old_private_read_fence_cannot_publish_after_atomic_acceptance(sql):
    identity = resolve(sql)
    old = rpc(sql, 'capture_lifetime_read_fence', literal(identity['project_id']))
    accept(sql, identity, 'Do not mention my school.')
    result = rpc(sql, 'lock_lifetime_read_publication', f'{literal(old)}::jsonb', check=False)
    assert result.returncode != 0 and 'stale lifetime read fence' in result.stderr


def test_legacy_unmapped_sources_do_not_gain_policy_state_or_profiles(sql):
    sql(f"delete from public.user_profile where user_id='{OWNER}';")
    rpc(sql, 'accept_user_narrator_source', f"'legacy','{TURN}','Do not mention my school.'")
    assert sql('select count(*) from public.user_lifetime_source_policy_receipt;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_lifetime_pending_policy;').stdout.strip() == '0'


def test_upgrade_inventory_blocks_completed_raw_and_edited_history_without_replay(sql):
    identity = resolve(sql)
    completed = accept(sql, identity, 'Do not mention my school.')['source']
    sql(f"update public.user_interview_turn set collector='{{}}' where source_id='{completed['id']}';")
    raw = rpc(sql, 'accept_user_narrator_source', f"{literal(identity['project_id'])},'00000000-0000-4000-8000-000000000702','I remember work.'")
    rpc(sql, 'change_user_narrator_source', f"{literal(identity['project_id'])},'{raw['id']}',1,'edit','Do not mention my workplace.'")
    # Reproduce pre-027 provenance, then execute the exact header-only upgrade
    # statement. It must not infer that completion or old generated text proves
    # every raw/current source's privacy directives were durably applied.
    sql('delete from public.user_lifetime_source_policy_receipt; delete from public.user_lifetime_continuity;')
    migration = (Path(__file__).resolve().parents[1] / 'supabase/migrations/202610120027_lifetime_atomic_policy.sql').read_text()
    inventory = migration.split('-- Existing identity upgrade boundary.', 1)[1].split('-- End upgrade inventory.', 1)[0]
    inventory = 'insert into public.user_lifetime_policy_inventory_pending' + inventory.split('insert into public.user_lifetime_policy_inventory_pending', 1)[1]
    sql(inventory)
    assert status(sql, identity)['pending'] is True
    assert policies(sql, identity) == []
    assert accept(sql, identity, 'Do not mention my school.')['source']['id'] == completed['id']
    assert status(sql, identity)['pending'] is True and policies(sql, identity) == []
    captured = rpc(sql, 'capture_lifetime_read_fence', literal(identity['project_id']))
    denied = rpc(sql, 'lock_lifetime_read_publication', f'{literal(captured)}::jsonb', check=False)
    assert 'LIFETIME_POLICY_PENDING' in denied.stderr
    assert sql(as_user('delete from public.user_lifetime_policy_inventory_pending'), check=False).returncode != 0


def test_reviewed_legacy_uuid5_control_is_idempotent_without_automatic_retry_replay(sql):
    from uuid import NAMESPACE_URL, uuid5
    identity = resolve(sql)
    source = accept(sql, identity, 'Do not mention my school.')['source']
    saved = policies(sql, identity)[0]
    ref = saved['data']['source_refs'][0]
    old_id = str(uuid5(NAMESPACE_URL, f"memoir:continuity:{source['id']}:1:excluded_topic:{ref['char_start']}:{ref['char_end']}"))
    sql(f"update public.user_lifetime_continuity set record_id='{old_id}'; delete from public.user_lifetime_source_policy_receipt;")
    sql(f"insert into public.user_lifetime_pending_policy values('{OWNER}',{literal(identity['project_id'])},'{identity['conversation_id']}','{source['id']}',1,'{TURN}','literal-v1');")
    assert accept(sql, identity, 'Do not mention my school.')['source']['id'] == source['id']
    assert status(sql, identity)['pending'] is True
    before = policies(sql, identity)
    assert len(before) == 1 and before[0]['record_id'] == old_id
    # Explicit database-owner fixture review of this one complete source. This
    # is never called automatically on retry or exposed as an authenticated RPC.
    sql(f"select public.apply_lifetime_literal_policy('{OWNER}',{literal(identity['project_id'])},'{source['id']}',1);")
    assert policies(sql, identity) == before
    assert status(sql, identity)['pending'] is False


@pytest.mark.parametrize('text', [
    '\u00a0Do not mention my school.\u00a0',
    '\u2003Do not mention my school.\u2003',
    '\u3000Do not mention my school.\u3000',
    '\u2028Do not mention my school.\u2029',
    '\r\n\tDo not mention my school!\r\n',
    'Do\u00a0not\u2003mention\u3000my school.',
    'Don’t mention my school！先不聊我的工作。',
    'ñsaidñ. Do not mention my school.',
    '中文example。Do not discuss school.',
    'Do not mention ñifñ.',
])
def test_sql_and_python_policy_parser_match_frozen_unicode_semantics(sql, text):
    identity = resolve(sql)
    source = accept(sql, identity, text)['source']
    expected = [item for item in literal_continuity_updates({'source': source}) if item['kind'] in {'excluded_topic','paused_topic'}]
    actual = [{'record_id': item['record_id'], 'kind': item['kind'], 'data': item['data']} for item in policies(sql, identity)]
    assert actual == sorted(expected, key=lambda row: row['record_id'])
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence = rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")
    rpc(sql, 'persist_lifetime_continuity_updates', f'{literal(fence)}::jsonb,{literal(expected)}::jsonb,false')
    assert len(policies(sql, identity)) == len(expected)
    for item in actual:
        ref = item['data']['source_refs'][0]
        assert text[ref['char_start']:ref['char_end']] == ref['quote']


@pytest.mark.parametrize('separator', ['\r', '\r\n', '\u2028', '\u2029'])
def test_sql_unicode_line_separators_preserve_the_complete_control_bound(sql, separator):
    identity = resolve(sql)
    text = separator.join(f'Do not mention topic {n}' for n in range(9))
    result = accept(sql, identity, text, check=False)
    assert result.returncode != 0 and 'LIFETIME_POLICY_INPUT_LIMIT' in result.stderr
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '0'


def test_upgrade_inventory_detects_raw_history_with_a_stale_zero_header(sql):
    identity = resolve(sql)
    sql(f"insert into public.user_narrator_source(user_id,project_id,client_turn_id,sequence,text,kind,language) values('{OWNER}',{literal(identity['project_id'])},'{TURN}',1,'An imported original.','narrator_chat','en-AU');")
    assert sql(f"select source_sequence from public.user_memoir_project where user_id='{OWNER}' and project_id={literal(identity['project_id'])};").stdout.strip() == '0'
    # Remove only the post-027 marker to model the pre-migration database state.
    sql('delete from public.user_lifetime_pending_policy;')
    migration = (Path(__file__).resolve().parents[1] / 'supabase/migrations/202610120027_lifetime_atomic_policy.sql').read_text()
    inventory = migration.split('-- Existing identity upgrade boundary.', 1)[1].split('-- End upgrade inventory.', 1)[0]
    inventory = 'insert into public.user_lifetime_policy_inventory_pending' + inventory.split('insert into public.user_lifetime_policy_inventory_pending', 1)[1]
    sql(inventory)
    assert status(sql, identity)['pending'] is True
    assert sql('select count(*) from public.user_lifetime_policy_inventory_pending;').stdout.strip() == '1'
    assert policies(sql, identity) == []
