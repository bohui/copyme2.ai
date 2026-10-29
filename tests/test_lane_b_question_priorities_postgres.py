"""Real SQL and API delivery; only model/public-source transports are controlled."""
import json
from pathlib import Path
import subprocess
from uuid import uuid4

import httpx
import pytest

from apps.api.conversation_reply import reply_candidates
from apps.api.historical_news import HistoricalResearch
from test_conversation_reply import proposal
from test_historical_news import evidence, receipt
from test_interview_strategy_runtime import client_fixture
from test_two_lane_memory import (database, sql, event_database, private_database, attachment_database,
    enable_only_disposable_database_rollout, lane, service)
from test_shared_memory_events_postgres import literal, rpc
from split_lane_fixtures import publish_ready_news


def response(request, output):
    return httpx.Response(200, json={'reply': json.dumps(output), 'thread_id': 'background-priorities', 'artifacts': []})


@pytest.mark.parametrize('language', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('use_news', [False, True])
def test_mira_decides_whether_ready_news_changes_the_reply_and_replays_her_choice(sql, tmp_path, monkeypatch, language, use_news):
    from apps.api import agent_routes
    calls = []
    def provider(request):
        context = json.loads(request.content)['interview_context']
        calls.append(context)
        output = proposal()
        assert reply_candidates(context)==[]
        news = context.get('historical_news',{}).get('clues',[])
        if news:
            output.update(acknowledgement='您还记得波士顿的生活。' if language=='zh-CN' else 'You remember your life in Boston.',
                question=('那份档案记载的集市，会让您想起街坊间的什么吗？' if language=='zh-CN'
                    else 'Does the public fair described in that archive bring any neighbourhood memories to mind?') if use_news
                    else ('当时街坊间的日常生活是怎样的？' if language=='zh-CN' else 'What was everyday life in your neighbourhood like?'),
                historical_clue_id=news[0]['id'] if use_news else None)
        return response(request, output)

    class PublicSources:
        async def discover(self, query, *, timeout):
            assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip() != '0'
            assert sql('select count(*) from public.user_agent_turn_lease where expires_at>clock_timestamp();').stdout.strip() == '0'
            return {'receipt': receipt(), 'events': [evidence()]}
        async def inspect(self, url, *, timeout):
            return dict(url=url, text=evidence()['excerpt'], source_title='Town archive', publisher='Town library',
                        publication_date='2020-01-01', retrieved_at='2026-10-15T00:00:00Z')

    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '1')
    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
        agent_routes.runtime._news_engine = HistoricalResearch(PublicSources())
        first = client.post('/v1/agent/turn', json=dict(text='I was born in Boston, USA, in 1960.', language=language))
        assert first.status_code == 200, first.text
        project = first.json()['project_id']
        identity=rpc(sql,'resolve_lifetime_conversation',literal(project))
        from controlled_skill_harness import run_optional_background
        run_optional_background(sql,project,tmp_path,monkeypatch,agent_routes.runtime._news_engine)
        publish_ready_news(sql,identity,language)
        assert len(rpc(sql, 'read_user_historical_news', literal(project))['clues']) == 1
        assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")==[]
        turn = str(uuid4())
        payload = dict(project_id=project, text='What else could we explore?', language=language, client_turn_id=turn)
        later = client.post('/v1/agent/turn', json=payload, headers={'accept': 'application/x-ndjson'})
        assert later.status_code == 200, later.text
        events = [json.loads(line) for line in later.text.splitlines()]
        assert not [event for event in events if event['type'] == 'error'], later.text
        saved = next(event['data'] for event in events if event['type'] == 'result')
        assert saved['conversation_saved']
        if use_news:
            assert saved['historical_context']['source_url'] == evidence()['source_url']
            assert rpc(sql, 'read_user_historical_news', literal(project))['clues'] == []
        else:
            assert saved.get('historical_context') is None
            assert len(rpc(sql,'read_user_historical_news',literal(project))['clues'])==1
        replay = client.post('/v1/agent/turn', json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()['cached'] and replay.json().get('historical_context') == saved.get('historical_context')
        assert replay.json()['reply']==saved['reply']
        rendered = subprocess.run(['node', 'tests/historical-news/replay-api.mjs'],
            input=json.dumps(dict(saved=saved, replay=replay.json(), language=language)),
            text=True, capture_output=True, timeout=20, cwd=Path(__file__).resolve().parents[1])
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        assert len(calls) == 2, 'Exactly one reply call per new turn, none on replay'
        outcome = json.loads(sql('select to_jsonb(o) from public.user_lifetime_strategy_outcome o order by source_sequence desc limit 1;').stdout)
        assert outcome['delivered'] and outcome['selected_candidate_id'] is None
        assert sql("select count(*) from public.user_memoir_lane where skill='guidance';").stdout.strip()=='0'
        assert sql('select count(*) from public.user_memory_event;').stdout.strip() == '0'


@pytest.mark.parametrize('language,text,acknowledgement', [
    ('en-AU', 'Please stop for today. No more questions.', 'Understood. We’ll stop here for today.'),
    ('zh-CN', '今天先不聊了，请不要继续提问。', '好的，今天就到这里。'),
])
def test_ready_news_can_save_and_replay_an_explicit_stop_without_touching_the_prior_reply(
        sql, tmp_path, monkeypatch, language, text, acknowledgement):
    from apps.api import agent_routes
    calls = []

    def provider(request):
        context = json.loads(request.content)['interview_context']
        calls.append(context)
        output = proposal()
        if len(calls) == 2:
            assert context['historical_news']['clues'], 'Exercise a ready clue at actual reply admission'
            assert reply_candidates(context)==[]
            output.update(acknowledgement=acknowledgement, question=None, reason='pause',
                historical_clue_id=None,work={'mode': 'reply_only', 'name': None})
        return response(request, output)

    class PublicSources:
        async def discover(self, query, *, timeout):
            return {'receipt': receipt(), 'events': [evidence()]}

        async def inspect(self, url, *, timeout):
            return dict(url=url, text=evidence()['excerpt'], source_title='Town archive', publisher='Town library',
                publication_date='2020-01-01', retrieved_at='2026-10-15T00:00:00Z')

    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '1')
    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
        agent_routes.runtime._news_engine = HistoricalResearch(PublicSources())
        first = client.post('/v1/agent/turn', json=dict(
            text='I was born in Boston, USA, in 1960.', language=language))
        assert first.status_code == 200, first.text
        prior = first.json()
        identity=rpc(sql,'resolve_lifetime_conversation',literal(prior['project_id']))
        from controlled_skill_harness import run_optional_background
        run_optional_background(sql,prior['project_id'],tmp_path,monkeypatch,agent_routes.runtime._news_engine)
        publish_ready_news(sql,identity,language)
        assert len(rpc(sql, 'read_user_historical_news', literal(prior['project_id']))['clues']) == 1
        payload = dict(project_id=prior['project_id'], text=text, language=language, client_turn_id=str(uuid4()))
        later = client.post('/v1/agent/turn', json=payload, headers={'accept': 'application/x-ndjson'})
        assert later.status_code == 200, later.text
        events = [json.loads(line) for line in later.text.splitlines()]
        assert not any(event['type'] == 'error' for event in events), later.text
        saved = next(event['data'] for event in events if event['type'] == 'result')
        assert saved['conversation_saved'] and saved['reply'] == acknowledgement
        assert ''.join(event.get('text', '') for event in events if event['type'] == 'text_delta') == acknowledgement
        assert saved.get('historical_context') is None
        assert not any(event['type'] == 'question_validated' for event in events)
        original = json.loads(sql('select collector from public.user_interview_turn order by sequence limit 1;').stdout)
        assert original['reply'] == prior['reply']
        outcome = json.loads(sql('select to_jsonb(o) from public.user_lifetime_strategy_outcome o order by source_sequence desc limit 1;').stdout)
        assert outcome['selection_reason'] == 'pause' and outcome['selected_candidate_id'] is None
        assert outcome['question_delivered'] is None
        replay = client.post('/v1/agent/turn', json=payload)
        assert replay.status_code == 200 and replay.json()['cached']
        assert replay.json()['reply'] == acknowledgement and len(calls) == 2
        rendered = subprocess.run(['node', 'tests/historical-news/replay-api.mjs'],
            input=json.dumps(dict(saved=saved, replay=replay.json(), language=language, prior=prior, text=text)),
            text=True, capture_output=True, timeout=20, cwd=Path(__file__).resolve().parents[1])
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr
        assert sql('select count(*) from public.user_memory_event;').stdout.strip() == '0'


@pytest.mark.parametrize('language,story,stop,correction,acknowledgement', [
    ('en-AU', 'I rented a room in Sydney.', 'Please stop for today. No more questions.',
     'One correction: the room was in Newcastle, not Sydney. Please use Newcastle for the room.',
     'Understood—the room was in Newcastle, not Sydney. We’ll leave it there for today.'),
    ('zh-CN', '我在悉尼租了一个房间。', '今天先不聊了，请不要继续提问。',
     '更正一下：那个房间在纽卡斯尔，不在悉尼。关于那个房间，请用纽卡斯尔。',
     '已更正：那个房间在纽卡斯尔。今天先聊到这里。'),
])
def test_correction_after_stop_saves_and_replays_without_reopening_questions_or_news(
        sql, tmp_path, monkeypatch, language, story, stop, correction, acknowledgement):
    from apps.api.lifetime_memory_runtime import LifetimePublicationContext
    calls, research = [], []

    def provider(request):
        context = json.loads(request.content)['interview_context']
        calls.append(context)
        output = proposal()
        if len(calls) == 2:
            output.update(acknowledgement='好的，今天就到这里。' if language == 'zh-CN' else 'We’ll stop here for today.',
                          question=None, reason='pause', work={'mode': 'reply_only', 'name': None})
        elif len(calls) == 3:
            assert stop in json.dumps(context['recent_dialogue'], ensure_ascii=False)
            output.update(acknowledgement=acknowledgement, question=None, reason='current_correction', quote=correction)
        return response(request, output)

    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '1')
    monkeypatch.setattr(LifetimePublicationContext, 'queue_historical_research',
                        lambda self, runtime, storage, project: research.append(project))
    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
        first = client.post('/v1/agent/turn', json=dict(text=story, language=language))
        assert first.status_code == 200, first.text
        project = first.json()['project_id']
        identity=rpc(sql,'resolve_lifetime_conversation',literal(project))
        publish_ready_news(sql,identity,language)
        prior = client.post('/v1/agent/turn', json=dict(project_id=project, text=stop, language=language))
        assert prior.status_code == 200 and prior.json()['conversation_saved'], prior.text
        assert research == [project]
        old = sql('select json_agg(collector order by sequence) from public.user_interview_turn;').stdout
        payload = dict(project_id=project, text=correction, language=language, client_turn_id=str(uuid4()))
        later = client.post('/v1/agent/turn', json=payload, headers={'accept': 'application/x-ndjson'})
        events = [json.loads(line) for line in later.text.splitlines()]
        assert later.status_code == 200 and not any(event['type'] == 'error' for event in events), later.text
        saved = next(event['data'] for event in events if event['type'] == 'result')
        assert saved['conversation_saved'] and saved['reply'] == acknowledgement
        assert not any(event['type'] == 'question_validated' for event in events)
        assert saved.get('historical_context') is None and research == [project]
        collectors = json.loads(sql('select json_agg(collector order by sequence) from public.user_interview_turn;').stdout)
        assert collectors[:-1] == json.loads(old)
        assert collectors[-1]['plan']['candidates'] == []
        assert collectors[-1]['plan']['work'] == {'mode': 'extract', 'name': None}
        source = json.loads(sql('select to_jsonb(s) from public.user_narrator_source s order by sequence desc limit 1;').stdout)
        assert source['text'] == correction and source['version'] == 1
        outcome = json.loads(sql('select to_jsonb(o) from public.user_lifetime_strategy_outcome o order by source_sequence desc limit 1;').stdout)
        assert outcome['selection_reason'] == 'current_correction' and outcome['question_delivered'] is None
        replay = client.post('/v1/agent/turn', json=payload)
        assert replay.status_code == 200 and replay.json()['cached'] and replay.json()['reply'] == acknowledgement
        assert len(calls) == 3 and research == [project]
        rendered = subprocess.run(['node', 'tests/historical-news/replay-api.mjs'],
            input=json.dumps(dict(saved=saved, replay=replay.json(), language=language, prior=prior.json(), text=correction)),
            text=True, capture_output=True, timeout=20, cwd=Path(__file__).resolve().parents[1])
        assert rendered.returncode == 0, rendered.stdout + rendered.stderr


@pytest.mark.parametrize('kind,question', [
    ('conflict', 'Was the move in 1962 or 1963?'),
    ('identity', 'Which sister were you describing?'),
    ('chronology', 'Did the shop open before or after the move?'),
    ('broaden_scope', 'What changed in your life after school?'),
])
def test_mira_makes_interviewing_decisions_in_the_current_saved_reply(sql, tmp_path, monkeypatch, kind, question):
    calls = []
    def provider(request):
        context = json.loads(request.content)['interview_context']
        calls.append(context)
        output = proposal()
        assert reply_candidates(context)==[]
        output.update(question=question)
        return response(request, output)

    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
        first = client.post('/v1/agent/turn', json={'text': 'I cannot remember whether my sister and I opened the shop before the move.'})
        assert first.status_code == 200, first.text
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(first.json()['project_id']))
        assert first.json()['reply'].endswith(question)
        assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='0'
        assert sql("select count(*) from public.user_memoir_lane where skill='guidance';").stdout.strip()=='0'
        later = client.post('/v1/agent/turn', json=dict(project_id=identity['project_id'], text='Please go on.'))
        assert later.status_code == 200, later.text
        assert later.json()['reply'].endswith(question)
        assert len(calls) == 2
        outcome = json.loads(sql('select to_jsonb(o) from public.user_lifetime_strategy_outcome o order by source_sequence desc limit 1;').stdout)
        assert outcome['delivered'] and outcome['selected_candidate_id'] is None
