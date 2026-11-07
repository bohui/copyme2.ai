"""Opt-in A/B run of Memoir's public Mira endpoint against disposable SQL."""
import asyncio
from functools import partial
import json
import os
from pathlib import Path
import shutil
import time
from uuid import uuid4

import httpx
import pytest

from memoir_postgres_workflow import PostgresRest, seed_fresh_canonical_project
from scripts.benchmark_agent_harness import TimedCodex, matches
from scripts.deepseek_benchmark_transport import Bridge, DeepSeekConnection
from scripts.run_memoir_live_skills import save
from test_agent_commit_postgres import database as postgres_database
from test_conversation_reply import proposal


pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_TEST_DSH_BIN') or not shutil.which('codex'),
                                reason='Requires both installed harnesses')
MODEL = 'gpt-6.1-sol'
EFFORT = 'low'
SECRET = 'synthetic-worker-secret'
STORIES = {
    'en-AU': ('I kept a red kite in the attic.', 'kite', 'red',
              'Could you look up what I told you about the kite?',
              'I am back. Please check the earlier memory for the colour of the kite.',
              'The kite in the attic stands out.', 'The kite you described was red.', 'Who flew it with you?'),
    'zh-CN': ('我把一只红风筝放在阁楼里。', '风筝', '红',
              '请帮我查一下之前说过的风筝。', '我回来了。请查一下之前那只风筝是什么颜色。',
              '您提到阁楼里放着一只风筝。', '您说那只风筝是红色的。', '以前谁和您一起放那只风筝？'),
}


@pytest.fixture(scope='module')
def database():
    yield from postgres_database.__wrapped__(publication_tcp=True, deadline=time.monotonic() + 600)


def test_bilingual_endpoint_save_replay_and_recall(database, tmp_path, monkeypatch):
    from apps.api import agent_routes, codex_worker_service
    from apps.api.codex_runtime import CodexRuntime

    for key, value in dict(MEMOIR_TWO_LANES='1', MEMORY_SPARK_COLLECTOR_MODEL=MODEL,
            MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=EFFORT, MEMORY_SPARK_LLM_MODEL=MODEL,
            MEMORY_SPARK_LLM_REASONING_EFFORT=EFFORT, MEMORY_SPARK_DISABLE_PRIVDROP='1',
            MEMOIR_PUBLICATION_DATABASE_URL=database.publication_dsn, MEMOIR_CODEX_HOME_BACKUPS='0',
            MEMORY_SPARK_CODEX_WORKER_SECRET=SECRET, MEMORY_SPARK_LLM_API_KEY='fixture',
            MEMORY_SPARK_PARALLEL_POLICY_REVIEW='0',
            MEMORY_SPARK_EARLY_POLICY_ACK='0', MEMORY_SPARK_HISTORICAL_NEWS='0',
            MEMORY_SPARK_TASK_DB=str(tmp_path / 'tasks.sqlite')).items():
        monkeypatch.setenv(key, value)
    database('update public.lifetime_two_lane_rollout set enabled=true,strategy_enabled=true,strategy_shadow=false;')
    samples = []
    seen_sources = set()

    async def run():
        bridge = Bridge(model=MODEL, effort=EFFORT)
        bridge.app.include_router(agent_routes.router)
        bridge.app.mount('/worker', codex_worker_service.app)
        async with bridge.serve():
            async with httpx.AsyncClient(base_url=bridge.origin, trust_env=False, timeout=60) as client:
                for index, (locale, case) in enumerate(STORIES.items()):
                    arms = ('codex', 'deepseek') if index == 0 else ('deepseek', 'codex')
                    for arm in arms:
                        original, query, fact, follow, resumed, opening_ack, recall_ack, question = case
                        owner, project = str(uuid4()), 'harness-bench-' + uuid4().hex
                        database(f"insert into auth.users(id,is_anonymous) values('{owner}',false);")
                        seed_fresh_canonical_project(database, owner, project)
                        monkeypatch.setattr(agent_routes, 'authenticated_storage',
                            lambda _, owner=owner: PostgresRest(database, owner).storage())
                        home = tmp_path / owner
                        thread, source_id = None, None

                        def scripted(body, _step):
                            text = lambda row: ''.join(part.get('text', '') for part in row['content'])
                            actual = [text(item) for item in body['input'] if item.get('role') == 'user']
                            assert current in actual
                            if phase == 'opening':
                                return dict(proposal(), acknowledgement=opening_ack, question=question)
                            assert original in actual
                            if phase == 'resumed':
                                assert follow in actual
                            result = next((item for item in body['input'] if item['type'] == 'function_call_output'
                                           and item['call_id'] == 'recall_' + phase), None)
                            if result is None:
                                return dict(type='function_call', name='memoir_read_context', call_id='recall_' + phase,
                                    arguments=json.dumps(dict(collection='sources', after=None, query=query, event_id=None),
                                                         ensure_ascii=False))
                            evidence = result['output']
                            assert original in evidence and source_id in evidence
                            assert all(foreign not in evidence for foreign in seen_sources - {source_id})
                            return dict(proposal(), acknowledgement=recall_ack, question=question)

                        async with bridge.exchange(scripted) as exchange:
                            gateway = exchange.origin + '/v1'
                            monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(
                                worker_url=bridge.origin + '/worker', worker_secret=SECRET,
                                base_url=gateway, model=MODEL, task_publisher_enabled=False))
                            factory = (partial(TimedCodex, exchange=exchange) if arm == 'codex' else
                                partial(DeepSeekConnection, exchange=exchange, binary=Path(os.environ['MEMOIR_TEST_DSH_BIN'])))
                            monkeypatch.setattr(codex_worker_service, 'CodexConnection', factory)
                            for phase, current in [('opening', original), ('follow_up', follow), ('resumed', resumed)]:
                                if phase in ('opening', 'resumed'):
                                    monkeypatch.setattr(codex_worker_service, 'worker',
                                        codex_worker_service.CodexWorker(home_root=home, model=MODEL, base_url=gateway,
                                                                         api_key=exchange.token, timeout=45))
                                exchange.requests.clear()
                                exchange.started = time.perf_counter()
                                request = dict(project_id=project, language=locale, text=current, client_turn_id=str(uuid4()))
                                events = {}
                                result = None
                                async with client.stream('POST', '/v1/agent/turn', json=request,
                                        headers={'Accept': 'application/x-ndjson'}) as response:
                                    response.raise_for_status()
                                    async for line in response.aiter_lines():
                                        event = json.loads(line)
                                        kind = event['type']
                                        assert kind != 'error', event
                                        events.setdefault(kind, exchange.ms())
                                        if kind == 'result':
                                            result = event['data']
                                assert result is not None and result['conversation_saved']
                                assert {'source_accepted', 'text_delta', 'question_validated', 'conversation_saved'} <= events.keys()
                                replay = (await client.post('/v1/agent/turn', json=request)).json()
                                assert replay['cached'] and replay['reply'] == result['reply']
                                current_thread = database(
                                    f"select thread_id from public.user_lifetime_conversation where user_id='{owner}';"
                                ).stdout.strip()
                                if phase == 'opening':
                                    source_id = result['accepted_source_id']
                                    seen_sources.add(source_id)
                                    thread = current_thread
                                else:
                                    assert current_thread == thread and fact in result['reply']
                                assert len(exchange.requests) == (1 if phase == 'opening' else 2)
                                samples.append(dict(locale=locale, phase=phase, arm=arm, milestones_ms=events,
                                    resumed=phase != 'opening', requests=list(exchange.requests)))

    asyncio.run(run())
    for locale in STORIES:
        for phase in ('opening', 'follow_up', 'resumed'):
            a, b = [row for row in samples if row['locale'] == locale and row['phase'] == phase]
            for first, second in zip(a['requests'], b['requests'], strict=True):
                same = matches(first, second)
                # The two disposable projects receive independently allocated SQL IDs.
                assert all(value for name, value in same.items() if name != 'input_sha256'), same
    if path := os.getenv('MEMOIR_TEST_DSH_RECEIPT'):
        save(Path(path), dict(mode='controlled_endpoint', model=MODEL, samples=samples))


def test_atlas_activity_selects_and_commits_in_both_runtimes(database, tmp_path, monkeypatch):
    from apps.api import agent_routes, codex_worker_service
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.memory_event_worker import MemoryEventWorker
    from apps.api.private_draft_broker import PrivateDraftBroker
    from controlled_skill_harness import empty_document, install_document_provider
    from scripts.deepseek_benchmark_transport import request_evidence
    from test_background_profile_workflow import Broker

    for key, value in dict(MEMOIR_TWO_LANES='1', MEMORY_SPARK_LLM_MODEL=MODEL,
            MEMORY_SPARK_LLM_REASONING_EFFORT=EFFORT, MEMORY_SPARK_COLLECTOR_MODEL=MODEL,
            MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=EFFORT, MEMORY_SPARK_MEMOIR_COMPOSER_MODEL=MODEL,
            MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT=EFFORT, MEMORY_SPARK_DISABLE_PRIVDROP='1',
            MEMOIR_PUBLICATION_DATABASE_URL=database.publication_dsn, MEMOIR_CODEX_HOME_BACKUPS='0',
            MEMORY_SPARK_CODEX_WORKER_SECRET=SECRET, MEMORY_SPARK_LLM_API_KEY='fixture',
            MEMORY_SPARK_PARALLEL_POLICY_REVIEW='0', MEMORY_SPARK_EARLY_POLICY_ACK='0',
            MEMORY_SPARK_HISTORICAL_NEWS='0', MEMORY_SPARK_TASK_DB=str(tmp_path / 'tasks.sqlite')).items():
        monkeypatch.setenv(key, value)
    database('update public.lifetime_two_lane_rollout set enabled=true,strategy_enabled=true,strategy_shadow=false;')
    samples = []
    broker = Broker(database)
    selected = 'memoir-author-timeline'

    async def run():
        bridge = Bridge(model=MODEL, effort=EFFORT)
        bridge.app.include_router(agent_routes.router)
        bridge.app.mount('/worker', codex_worker_service.app)
        async with bridge.serve(), httpx.AsyncClient(timeout=60, trust_env=False) as client:
            activity = MemoryEventWorker(broker, worker_url=bridge.origin + '/worker', worker_secret=SECRET)
            for index, (locale, story) in enumerate(STORIES.items()):
                arms = ('codex', 'deepseek') if index == 0 else ('deepseek', 'codex')
                for arm in arms:
                    owner, project = str(uuid4()), 'atlas-harness-bench-' + uuid4().hex
                    database(f"insert into auth.users(id,is_anonymous) values('{owner}',false);")
                    seed_fresh_canonical_project(database, owner, project)
                    monkeypatch.setattr(agent_routes, 'authenticated_storage',
                        lambda _, owner=owner: PostgresRest(database, owner).storage())
                    stage = 'opening'
                    bounded = []

                    def script(body, step):
                        if stage == 'opening':
                            return dict(proposal(), acknowledgement=story[-3], question=story[-1])
                        decisions = [
                            ('memoir_read_skill', {'skill': selected}),
                            ('memoir_process_source', {'skills': [selected]}),
                        ]
                        if step == 3:
                            result = next(item for item in body['input'] if item.get('call_id') == 'atlas_2'
                                and item['type'] == 'function_call_output')
                            assert json.loads(result['output'])['status'] in ('saved', 'finished')
                            return {'status': 'finished'}
                        name, args = decisions[step - 1]
                        return dict(type='function_call', name=name, arguments=json.dumps(args), call_id=f'atlas_{step}')

                    def direct(body):
                        schema = body['text']['format']['schema']
                        scoped = []
                        for name in ('EvidenceRef', 'CurrentSourceRef', '_ContinuityUpdate'):
                            if name in schema.get('$defs', {}):
                                field = schema['$defs'][name]['properties']['source_id']
                                if 'enum' in field:
                                    assert field['enum'] == [source_id]
                                    field['enum'] = ['synthetic-source']
                                    scoped.append(name)
                                if 'const' in field:
                                    assert field['const'] == source_id
                                    field['const'] = 'synthetic-source'
                                    scoped.append(name)
                        bounded.append({**request_evidence(body), 'scope_normalized': scoped})
                        return empty_document(body)

                    async with bridge.exchange(script) as exchange:
                        gateway = exchange.origin + '/v1'
                        monkeypatch.setattr(codex_worker_service, 'worker', codex_worker_service.CodexWorker(
                            home_root=tmp_path / owner, model=MODEL, base_url=gateway,
                            api_key=exchange.token, timeout=55))
                        monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(
                            worker_url=bridge.origin + '/worker', worker_secret=SECRET,
                            base_url=gateway, model=MODEL, task_publisher_enabled=False))
                        monkeypatch.setattr(codex_worker_service, 'CodexConnection', partial(TimedCodex, exchange=exchange))
                        response = await client.post(bridge.origin + '/v1/agent/turn', json=dict(
                            project_id=project, language=locale, text=story[0], client_turn_id=str(uuid4())))
                        assert response.status_code == 200, response.text
                        source_id = response.json()['accepted_source_id']
                        pending = database(f"select id from public.user_private_draft_outbox where user_id='{owner}' "
                                           "and not delivered;").stdout.splitlines()
                        for receipt in pending:
                            page = await broker.rpc('private_draft_event_page', p_event_id=receipt)
                            checkpoint = await asyncio.to_thread(PrivateDraftBroker.reconcile, page)
                            assert checkpoint['retrieval_complete']
                            await broker.rpc('queue_memoir_receipt', p_receipt_id=receipt, p_cadence=5)
                        await broker.rpc('pending_memoir_background_agents')
                        run_id = database(f"select id from public.user_memoir_background_agent "
                                          f"where user_id='{owner}';").stdout.strip()
                        assert run_id
                        stage = 'atlas'
                        exchange.requests.clear()
                        if arm == 'deepseek':
                            monkeypatch.setattr(codex_worker_service, 'CodexConnection',
                                partial(DeepSeekConnection, exchange=exchange,
                                        binary=Path(os.environ['MEMOIR_TEST_DSH_BIN'])))
                        # The bounded extraction path stays on the existing
                        # Responses transport for both native orchestration arms.
                        with monkeypatch.context() as patch:
                            install_document_provider(patch, direct)
                            exchange.started = time.perf_counter()
                            result = await activity.execute_background_agent(run_id)
                            elapsed = exchange.ms()
                        assert result['status'] == 'finished' and result['pending'] is False
                        assert database(f"select processing_status from public.user_narrator_source "
                                        f"where id='{source_id}';").stdout.strip() == 'succeeded'
                        assert database("select token is null from public.user_memoir_background_agent "
                                        f"where id='{run_id}';").stdout.strip() == 't'
                        assert len(exchange.requests) == 3 and bounded
                        samples.append(dict(locale=locale, arm=arm, durable_finish_ms=elapsed,
                            native_calls=list(exchange.requests), bounded_calls=bounded))

    asyncio.run(run())
    for locale in STORIES:
        a, b = [row for row in samples if row['locale'] == locale]
        for kind in ('native_calls', 'bounded_calls'):
            for first, second in zip(a[kind], b[kind], strict=True):
                assert all(value for name, value in matches(first, second).items() if name != 'input_sha256')
    if path := os.getenv('MEMOIR_TEST_DSH_ATLAS_RECEIPT'):
        save(Path(path), dict(mode='controlled_durable_atlas', model=MODEL, samples=samples))


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_source_to_private_draft_workflow(locale, tmp_path, monkeypatch):
    from contextlib import contextmanager
    from test_conversation_attribution import Conversation, empty, episode
    from test_shared_memory_events_postgres import literal, rpc
    from test_story_game_runtime_postgres import compose_game_chapters
    from scripts.memoir_skill_eval_suite import plan

    planned = plan()
    workflow = next(row for row in planned['workflow_items'] if row['locale'] == locale)
    game = next(row for row in planned['items'] if row['case'] == 'proposal' and row['locale'] == locale
                and row['skill'] == 'memoir-story-game')
    texts = [block['text'] for chapter in game['task']['chapters'] for block in chapter['blocks']]
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    started = time.perf_counter()
    with contextmanager(postgres_database.__wrapped__)(publication_tcp=True) as sql:
        conversation = Conversation(sql, tmp_path, monkeypatch, lambda packet: {
            **empty(packet), 'events': [episode(packet, packet['sources'][0]['text'],
                                               title=packet['sources'][0]['text'])]},
            strategy='shape')
        with conversation.client:
            for text in texts:
                conversation.say(text, language=locale)
                conversation.drain()
            project = literal(conversation.project)
            head = rpc(sql, 'read_lifetime_private_draft_head', f'{project},{literal(locale)}')
            if head['status'] != 'ready':
                asyncio.run(compose_game_chapters(conversation))
                head = rpc(sql, 'read_lifetime_private_draft_head', f'{project},{literal(locale)}')
            assert head['status'] == 'ready'
            page = rpc(sql, 'read_lifetime_private_draft_page', f"{project},'{head['snapshot_id']}',null,8")
            assert page['records']
            section = next(row for row in page['records'] if row['source_refs'])
            ref = section['source_refs'][0]
            source_id, version = literal(ref['source_id']), int(ref['version'])
            assert sql('select count(*) from public.user_narrator_source '
                       f'where project_id={project} and id={source_id} and version={version} '
                       "and status='active';").stdout.strip() == '1'
            assert sql('select count(*) from public.user_memory_event '
                       f"where project_id={project} and id={literal(section['event_id'])} "
                       f"and revision={int(section['event_revision'])} and status='active';").stdout.strip() == '1'
            rpc(sql, 'change_user_narrator_source',
                f"{project},'{ref['source_id']}',{ref['version']},'withdraw',null")
            old = rpc(sql, 'read_lifetime_private_draft_page',
                      f"{project},'{head['snapshot_id']}',null,8", check=False)
            assert old.returncode != 0 or ref['source_id'] not in old.stdout
    if output := os.getenv('MEMOIR_TEST_DSH_WORKFLOW_RECEIPTS'):
        save(Path(output) / f'workflow-{locale}.json', dict(case_id=workflow['id'], locale=locale,
            status='pass', source_versions=True, event_revisions=True, draft_readback=True,
            withdrawal_readback=True, elapsed_ms=round((time.perf_counter() - started) * 1000, 2)))
