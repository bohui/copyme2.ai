"""Recall-limit pool selection and deferral survive the real API/SQL save path."""
import json
from uuid import uuid4

import httpx
import pytest

from apps.api.conversation_reply import reply_candidates
from test_conversation_reply import proposal
from test_interview_strategy_runtime import client_fixture
from test_two_lane_memory import (database, sql, event_database, private_database, attachment_database,
    enable_only_disposable_database_rollout, lane, service)
from test_shared_memory_events_postgres import literal, rpc
from test_agent_commit_postgres import OWNER


@pytest.mark.parametrize('use_pool', [False, True])
@pytest.mark.parametrize('language,story,limited,broader', [
    ('en-AU', 'I painted the new home with my father.',
     'I cannot remember that detail. I mostly waited beside him.',
     'What comes to mind about life in that home?'),
    ('zh-CN', '我和爸爸一起给新家刷墙。', '那有点记不得了，只记得在旁边等了半天。',
     '说起那个家，您还会想起哪些日常生活？'),
])
def test_mira_saves_her_connected_question_after_recall_limit_and_ignores_legacy_pool(sql, tmp_path, monkeypatch,
        language, story, limited, broader, use_pool):
    calls = []

    def provider(request):
        context = json.loads(request.content)['interview_context']
        calls.append(context)
        output = proposal()
        if len(calls) == 1:
            output.update(question='How did you help?', quote=story)
        else:
            hints = reply_candidates(context)
            assert hints==[]
            output.update(question=broader, reason='recall_limit',recall_limit_quote=limited,
                          work={'mode': 'reply_only', 'name': None})
        return httpx.Response(200, json={'reply': json.dumps(output), 'thread_id': 'recall-test', 'artifacts': []})

    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
        first = client.post('/v1/agent/turn', json={'text': story, 'language': language})
        assert first.status_code == 200, first.text
        project = first.json()['project_id']
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(project))
        lane_id = lane(sql, identity)
        page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
        result = dict(events=[], place_journeys=[], continuity_updates=[], prepared_questions=[
            dict(question='What exactly did you do while waiting?', topic='home', quote=story,
                 requires_confirmation=True, scope='detail'),
            dict(question=broader, topic='home life', quote=story, requires_confirmation=False, scope='broader')],
            strategy_proposal=dict(strategy='explore', objective='follow_story', focus_event_ids=[]))
        if not use_pool:
            result['prepared_questions'] = []
        assert service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane_id}','{page['token']}',0,{literal(result)}")['status'] == 'page_saved'
        turn = str(uuid4())
        payload = dict(project_id=project, client_turn_id=turn, text=limited, language=language)
        saved = client.post('/v1/agent/turn', json=payload, headers={'accept': 'application/x-ndjson'})
        assert saved.status_code == 200, saved.text
        events = [json.loads(line) for line in saved.text.splitlines()]
        assert events[-1]['type'] == 'result', saved.text
        value = events[-1]['data']
        expected = broader
        assert value['reply'].endswith(expected)
        visible = ''.join(event.get('text', '') for event in events if event['type'] == 'text_delta')
        assert 'What exactly did you do while waiting?' not in visible
        assert visible.endswith(expected)
        retry = client.post('/v1/agent/turn', json=payload)
        assert retry.status_code == 200 and retry.json()['cached'], retry.text
        assert retry.json()['reply'] == value['reply']

    assert len(calls) == 2
    outcome = json.loads(sql(f"select to_jsonb(o) from public.user_lifetime_strategy_outcome o where client_turn_id='{turn}';").stdout)
    assert outcome['selection_reason'] == 'recall_limit' and outcome['delivered']
    assert outcome['selected_candidate_id'] is None
    assert sql(f"select count(*) from public.lifetime_deferred_questions('{OWNER}',{literal(project)});").stdout.strip()=='0'
    assert sql(f"select count(*) from public.lifetime_resolved_questions('{OWNER}',{literal(project)});").stdout.strip() == '0'
    assert bool(rpc(sql,'read_lifetime_prepared_questions',literal(identity['conversation_id'])))==use_pool
    assert sql('select count(*) from public.user_memory_event;').stdout.strip() == '0'


def test_deferred_question_reader_is_private(sql):
    result = sql("set role authenticated;select * from public.lifetime_deferred_questions(" +
                 f"'{OWNER}','foreign-project');", check=False)
    assert result.returncode != 0
