"""Bounded first-reply profiling; output timings, never credentials or testimony.

first-turn creates a fresh anonymous test account/project and saves one synthetic
reply through the web proxy. collector uses disposable app-server homes and the
production prompt/schema, with per-call effort overrides (no service changes).
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from uuid import uuid4

if __file__ != '<stdin>':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_TEXT = '我叫韩凤江'
STORY_TEXT = ('我叫韩凤江，小时候住在开封。父亲在铁路工作，母亲在家照顾我们。'
              '我和姐姐每天放学后到河边玩，夏天捉小鱼，冬天捡漂亮的石头。'
              '有一次我掉进浅水里，姐姐把我拉了上来，回家后我们都不敢告诉父母。')


def report(**values):
    print(json.dumps(values, ensure_ascii=False), flush=True)


async def first_turn(origin, timeout):
    import httpx

    stage = 'config'
    async with httpx.AsyncClient(timeout=timeout) as client:
        async def request(method, url, **kwargs):
            response = await client.request(method, url, **kwargs)
            if not response.is_success:
                report(stage=stage, http_status=response.status_code)
                raise RuntimeError('Profiling request failed')
            return response.json()

        api = origin.rstrip('/') + '/api/v1/memoir'
        config = await request('GET', api + '/agent/config')
        stage = 'anonymous_signup'
        auth = await request('POST', config['supabase_url'] + '/auth/v1/signup',
            headers={'apikey': config['supabase_publishable_key']}, json={'data': {}})
        headers = {'Authorization': 'Bearer ' + auth['access_token']}
        stage = 'create_project'
        project = await request('POST', api + '/projects', headers=headers,
            json={'mode': 'self', 'language': 'zh-CN'})
        report(kind='synthetic_test_identity', user_id=auth['user']['id'], project_id=project['id'])
        stage = 'first_turn'
        started = time.perf_counter()
        seen = {}
        async with client.stream('POST', api + '/agent/turn',
            headers={**headers, 'Accept': 'application/x-ndjson'},
            json={'project_id': project['id'], 'client_turn_id': str(uuid4()),
                  'text': TEST_TEXT, 'first_reply_localization': True}) as response:
            if not response.is_success:
                report(stage=stage, http_status=response.status_code)
                raise RuntimeError('First turn failed')
            seen['headers_s'] = round(time.perf_counter() - started, 3)
            async for line in response.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                kind = event.get('type')
                seconds = round(time.perf_counter() - started, 3)
                label = kind
                if kind == 'progress':
                    data = event.get('data') or {}
                    label = 'progress:' + str(data.get('id')) + ':' + str(data.get('status'))
                if label not in seen:
                    seen[label] = seconds
                    report(kind='http_event', event=label, elapsed_s=seconds)
                if kind == 'error':
                    raise RuntimeError('First turn stream failed')
                if kind == 'conversation_saved':
                    report(kind='first_turn_summary', timings=seen,
                        measurement='HTTP events received; browser paint is not measured')
                    return
        raise RuntimeError('Stream ended before conversation_saved')


async def collector(efforts, timeout, case='introduction', model_override=None):
    from apps.api.codex_agent import CodexConnection, provider_config
    from apps.api.codex_runtime import build_conversation_system_prompt
    from apps.api.codex_worker_files import write_config
    from apps.api.interview_plan import CollectorVisibleStream, collector_schema, run_collector_turn, validate_collector_result

    model = model_override or os.environ.get('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled')
    base_url = os.environ['MEMORY_SPARK_LLM_BASE_URL']
    key = os.environ['MEMORY_SPARK_LLM_API_KEY']
    # One stable, synthetic first source for every fresh-thread trial.
    text = TEST_TEXT if case == 'introduction' else STORY_TEXT
    context = {'source': {'id': str(uuid4()), 'version': 1, 'status': 'active', 'text': text},
        'photo_context': [], 'sources': [], 'events': [], 'opening_turn': True}
    instructions = build_conversation_system_prompt('(none)', {'preferred_language': 'zh-CN'},
        project_id='project_profiling', language='zh-CN', conversation_rounds_completed=0,
        interview_context=context)
    for index, effort in enumerate(efforts, 1):
        timings = {}
        visible = CollectorVisibleStream()
        started = time.perf_counter()
        calls = 0

        async def delta(chunk):
            if chunk:
                timings.setdefault('first_raw_delta_s', round(time.perf_counter() - started, 3))
            if visible.feed(chunk):
                timings['first_visible_ack_s'] = round(time.perf_counter() - started, 3)
                report(kind='collector_ack', trial=index, effort=effort, elapsed_s=timings['first_visible_ack_s'])

        report(kind='collector_start', case=case, trial=index, effort=effort, model=model,
            instructions_chars=len(instructions))
        with tempfile.TemporaryDirectory(prefix='memoir-first-reply-', dir='/tmp') as directory:
            home = Path(directory)
            # Never run the model as the privileged worker supervisor. Nobody
            # is outside the worker's tenant UID range (20000–59999), so it
            # cannot read another storyteller's 0700 runtime home.
            privileged = os.geteuid() == 0
            uid = 65534 if privileged else os.getuid()
            write_config(home, home, uid, provider_config(base_url, model), apply_owner=privileged)
            command = [os.getenv('MEMORY_SPARK_CODEX_BIN', 'codex'), 'app-server']
            if privileged:
                command = [os.getenv('MEMORY_SPARK_CODEX_PRIVDROP_BIN', '/usr/bin/setpriv'),
                    f'--reuid={uid}', f'--regid={uid}', '--clear-groups', '--no-new-privs', *command]
            async with CodexConnection(command, home,
                provider_env={'MEMORY_SPARK_LLM_API_KEY': key}, timeout=timeout) as connection:
                timings['appserver_initialized_s'] = round(time.perf_counter() - started, 3)
                thread = await connection.request('thread/start', {'cwd': str(home), 'ephemeral': False,
                    'modelProvider': 'llm_provider', 'model': model, 'approvalPolicy': 'never',
                    'sandbox': 'read-only', 'baseInstructions': instructions})
                timings['thread_ready_s'] = round(time.perf_counter() - started, 3)
                original_turn = connection.turn

                async def counted_turn(*args, **kwargs):
                    nonlocal calls
                    calls += 1
                    return await original_turn(*args, **kwargs)

                connection.turn = counted_turn
                reply = await run_collector_turn(connection, thread['thread']['id'],
                    'Storyteller message:\n' + text, interview_context=context,
                    output_schema=collector_schema(), on_delta=delta, effort=effort)
                timings['validated_reply_s'] = round(time.perf_counter() - started, 3)
                result = validate_collector_result(reply, context)
        report(kind='collector_summary', case=case, trial=index, effort=effort, model=model, timings=timings,
            appserver_turns=calls, work_mode=result['plan']['work']['mode'],
            candidate_count=len(result['plan']['candidates']),
            expected_work_mode=result['plan']['work']['mode'] == ('reply_only' if case == 'introduction' else 'extract'),
            exact_name=result['plan']['work']['name'] == '韩凤江' if case == 'introduction' else None,
            validated=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['first-turn', 'collector', 'conversation'])
    parser.add_argument('--origin', default='http://localhost:3010')
    parser.add_argument('--efforts', nargs='+', choices=['low', 'medium', 'high', 'max'], default=['max', 'low', 'low', 'max'])
    parser.add_argument('--case', choices=['introduction', 'story'], default='introduction',
        help='Synthetic collector input; first-turn always uses the introduction')
    parser.add_argument('--model', help='Collector route override; does not change the shared service')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--deadline', type=float, default=1200, help='Bounded conversation campaign deadline')
    parser.add_argument('--review', action='store_true', help='Include public synthetic replies in conversation comparison')
    parser.add_argument('--candidate-model', help='Isolated conversation candidate route; normal service is unchanged')
    parser.add_argument('--candidate-effort', choices=['max', 'low'], default='max')
    parser.add_argument('--candidate-prompt-version', choices=['legacy', 'compact-v1'], default='compact-v1')
    args = parser.parse_args()
    try:
        if args.mode == 'conversation':
            if not 0 < args.timeout <= 120 or not 0 < args.deadline <= 1200:
                parser.error('Conversation timeout/deadline exceed the bounded campaign')
            if args.model:
                parser.error('--model is only supported in isolated collector mode')
            from scripts.profile_conversation_latency import campaign
            _, results = asyncio.run(campaign(args.timeout, args.deadline, args.review,
                candidate_model=args.candidate_model, candidate_effort=args.candidate_effort,
                candidate_prompt_version=args.candidate_prompt_version))
            if len(results) != 24 or any(r['status'] != 'saved' for r in results):
                raise RuntimeError('Conversation comparison did not complete')
        else:
            asyncio.run(first_turn(args.origin, args.timeout) if args.mode == 'first-turn'
                else collector(args.efforts, args.timeout, args.case, args.model))
    except Exception as error:
        # Provider/auth exception text can include private headers or output.
        report(kind='profile_failed', failure_class=type(error).__name__)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
