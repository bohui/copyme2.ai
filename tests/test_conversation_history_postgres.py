"""Refresh restores saved exchanges from PostgreSQL without a browser cache."""
import json
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api import supabase_routes
from apps.api.conversation_recovery import conversation_history
from apps.api.main import create_app
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_agent_commit_postgres import OWNER, OTHER, OLD, as_user
from test_interview_work_plan_postgres import plan
from test_lifetime_memory_commit import prepare, commit
from test_lifetime_memory_postgres import (
    sql, event_database, private_database, attachment_database,
)
from test_lifetime_memory_publication import database
from test_shared_memory_events_postgres import rpc, literal


def read_history(sql, identity):
    storage = PostgresRest(sql, OWNER).storage()
    try:
        return conversation_history(storage, identity['project_id'], 100, None)
    finally:
        storage.client.close()


def test_refresh_keeps_saved_assistant_reply_after_profile_update(sql):
    identity, turn, _, fence = prepare(sql)
    commit(sql, turn, fence)
    sql(as_user("update public.user_profile set profile=profile||"
                "'{\"birth_place\":\"Sydney\"}'::jsonb;"))
    history = read_history(sql, identity)
    assert [(item.narrator_text, item.reply) for item in history.items] == [
        ('My name is Joan', 'Hello Joan.'),
    ]
    # Generation retries still require the current profile/context revision.
    assert rpc(sql, 'read_lifetime_reply', f"'{identity['conversation_id']}','{turn}'")['reply'] is None


def test_history_keeps_reply_under_unchanged_privacy_preferences(sql):
    identity, turn, _, _ = prepare(sql)
    sql(as_user("update public.user_profile set profile=profile||"
                "'{\"memory_preferences\":{\"excluded_topics\":[\"work\"]}}'::jsonb;"))
    fence = rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")
    commit(sql, turn, fence)
    sql(as_user("update public.user_profile set profile=profile||"
                "'{\"preferred_language\":\"zh-CN\"}'::jsonb;"))
    assert read_history(sql, identity).items[0].reply == 'Hello Joan.'


@pytest.mark.parametrize('change', ['exclude', 'pause', 'withdraw', 'edit'])
def test_history_still_hides_replies_after_privacy_or_source_changes(sql, change):
    identity, turn, accepted, fence = prepare(sql)
    commit(sql, turn, fence)
    if change in ('exclude', 'pause'):
        preferences = {'excluded_topics' if change == 'exclude' else 'paused_topics': ['Joan']}
        sql(as_user(f"update public.user_profile set profile=profile||"
                    f"{literal({'memory_preferences': preferences})}::jsonb;"))
    else:
        rpc(sql, 'change_user_narrator_source',
            f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,"
            f"'{change}',{literal('My name is Jane') if change == 'edit' else 'null'}")
    assert read_history(sql, identity).items[0].reply is None


def test_history_restores_preexisting_saved_replies_after_profile_updates(sql):
    identity, turn, _, fence = prepare(sql)
    commit(sql, turn, fence)
    sql("update public.user_interview_turn set collector=collector-'history_privacy_digest';")
    sql(as_user("update public.user_profile set profile=profile||"
                "'{\"birth_place\":\"Sydney\"}'::jsonb;"))
    assert read_history(sql, identity).items[0].reply == 'Hello Joan.'


def test_history_reply_rpc_rejects_another_owner(sql):
    identity, turn, _, fence = prepare(sql)
    commit(sql, turn, fence)
    assert rpc(sql, 'read_lifetime_history_reply',
        f"'{identity['conversation_id']}','{turn}'", owner=OTHER, check=False).returncode != 0


def test_refresh_replays_all_paginated_api_exchanges_into_the_web_client(sql, monkeypatch):
    identity, turn, _, fence = prepare(sql)
    commit(sql, turn, fence)
    expected = [
        ['user', 'My name is Joan'], ['assistant', 'Hello Joan.'],
        ['user', 'We caught insects by the river.'], ['assistant', 'Which insects did you catch?'],
        ['user', 'My friend kept crickets at home.'], ['assistant', 'What do you remember about your friend?'],
    ]
    for index in (2, 4):
        turn = str(uuid4())
        rpc(sql, 'accept_user_interview_turn',
            f"{literal(identity['project_id'])},'{turn}',{literal(expected[index][1])},'narrator_chat','en-AU'")
        fence = rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")
        value = plan('extract', None)
        value['candidates'][0].update(id=f'memory-{index}', question=expected[index + 1][1])
        value['chosen_id'] = f'memory-{index}'
        rpc(sql, 'commit_lifetime_turn',
            f"{literal(fence)}::jsonb,'{turn}',{literal(value)}::jsonb,'[]',"
            f"{literal(expected[index + 1][1])},'[]','fresh-engine','lifetime-v1','fixture-model'")
    sql(as_user("update public.user_profile set profile=profile||"
                "'{\"birth_place\":\"Sydney\"}'::jsonb;"))
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setattr(supabase_routes, 'storage', lambda _: PostgresRest(sql, OWNER).storage())
    pages, cursor = [], None
    with TestClient(create_app(MemoryStore())) as client:
        while True:
            response = client.get(f"/api/v1/memoir/user/projects/{identity['project_id']}/history",
                params={'limit': 2, **({'cursor': cursor} if cursor else {})})
            assert response.status_code == 200, response.text
            assert response.headers['cache-control'] == 'no-store'
            pages.append(response.json())
            cursor = pages[-1]['next_cursor']
            if cursor is None:
                break
    assert len(pages) == 2
    result = subprocess.run(['node', 'tests/js/helpers/replay-conversation-history.mjs'],
        input=json.dumps({'pages': pages, 'expected': expected}), text=True,
        capture_output=True, timeout=10, cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stdout + result.stderr
