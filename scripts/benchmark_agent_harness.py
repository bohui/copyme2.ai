#!/usr/bin/env python3
"""Compare actual harnesses using Memoir's synthetic bilingual evaluation catalog."""
import argparse
import asyncio
from fnmatch import fnmatch
from functools import partial
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from dotenv import dotenv_values
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))

from apps.api.codex_agent import CodexConnection, provider_config
from apps.api.conversation_reply import reply_instructions, reply_schema
from apps.api.conversation_reply_context import context_update, conversation_context
from apps.api.conversation_reply_session import _item
from apps.api.interview_context_tools import InterviewContextTools
from scripts.deepseek_benchmark_transport import Bridge, DeepSeekConnection
from scripts.memoir_agent_eval_cases import catalog
from scripts.memoir_skill_eval_suite import digest, plan
from scripts.run_memoir_agent_evaluation import background, grade_background, grade_reply
from scripts.run_memoir_live_skills import save


class TimedCodex(CodexConnection):
    def __init__(self, *args, exchange, **kwargs):
        super().__init__(*args, **kwargs)
        self.exchange = exchange
        exchange.connection = self
        self.first_text_ms = self.sdk_first_text_ms = None

    async def __aenter__(self):
        started = time.perf_counter()
        connection = await super().__aenter__()
        self.startup_ms = round((time.perf_counter() - started) * 1000, 2)
        return connection

    async def turn(self, thread, text, on_delta=None, **kwargs):
        async def observe(delta):
            if delta and self.first_text_ms is None:
                self.first_text_ms = self.sdk_first_text_ms = self.exchange.ms()
            if on_delta:
                await on_delta(delta)
        return await super().turn(thread, text, on_delta=observe, **kwargs)


async def reply(case, factory, home, config, timeout):
    context, view = (case['task'][key] for key in ('context', 'view'))
    instructions = reply_instructions()
    schema = reply_schema(context)
    entities, history = conversation_context(view)
    current = view['current']['narrator']['original']
    items = [_item(value) for value in [*history, dict(role='user', content=context_update(entities))]]
    model, effort, base_url, key = (config['MEMORY_SPARK_LLM_' + key]
        for key in ('MODEL', 'REASONING_EFFORT', 'BASE_URL', 'API_KEY'))
    home.mkdir(mode=0o700)
    (home / 'config.toml').write_text(provider_config(base_url, model, governed=True))

    class CaseContext(InterviewContextTools):
        async def read(self, args):
            # The catalog carries a projected view. No cross-project lookup is
            # attempted here. The endpoint regression separately exercises SQL.
            return {'items': [], 'next_cursor': None}

    tools = CaseContext(None, SimpleNamespace(model_dump=lambda **_kw: {}))
    async with factory(['codex', 'app-server'], home, provider_env={'MEMORY_SPARK_LLM_API_KEY': key},
                       timeout=timeout, tool_handler=tools.call) as connection:
        opened = await connection.request('thread/start', dict(cwd=str(home), ephemeral=True,
            model=model, modelProvider='llm_provider', approvalPolicy='never', sandbox='read-only',
            baseInstructions=instructions, dynamicTools=tools.specs()))
        thread = opened['thread']['id']
        await connection.request('thread/inject_items', dict(threadId=thread, items=items))
        value = json.loads(await connection.turn(thread, current, output_schema=schema,
                                                 effort=effort, max_response_bytes=512_000))
    Draft202012Validator(schema).validate(value)
    return value, grade_reply(case, value)


def scripted(case, body, step):
    """The transport control has predetermined replies and tool choices."""
    if case['component'] == 'lane-a':
        from test_conversation_reply import proposal
        zh = case['locale'] == 'zh-CN'
        gold = case['gold'].get('facts', {})
        pause = gold.get('stopped') or gold.get('question') is False
        value = dict(proposal(), acknowledgement='我听到了。' if zh else 'I hear you.',
            question=None if pause else ('那时您记得什么？' if zh else 'What do you remember from then?'),
            reason='pause' if pause else 'latest_story')
        for key, field in body['text']['format']['schema']['properties'].items():
            if 'enum' in field and value[key] not in field['enum']:
                value[key] = field['enum'][0]
        return value
    skills = case['gold']['skills']
    if skills is None:
        decisions = [(tool, {'skill': skill})
            for skill in ('memoir-author-timeline', 'memoir-composer')
            for tool in ('memoir_read_skill', 'memoir_execute_skill')]
    else:
        decisions = [('memoir_read_skill', {'skill': skill}) for skill in skills]
        decisions.append(('memoir_process_source', {'skills': skills}))
    if step > len(decisions):
        return {'status': 'finished'}
    name, args = decisions[step - 1]
    return dict(type='function_call', name=name, arguments=json.dumps(args), call_id=f'call_fixture_{step}')


async def measure(case, arm, bridge, binary, directory, timeout, live):
    fixture = None if live else partial(scripted, case)
    async with bridge.exchange(fixture) as exchange:
        config = {f'MEMORY_SPARK_LLM_{key}': val for key, val in dict(
            MODEL=bridge.model, REASONING_EFFORT=bridge.effort,
            BASE_URL=exchange.origin + '/v1', API_KEY=exchange.token).items()}
        factory = (partial(TimedCodex, exchange=exchange) if arm == 'codex'
                   else partial(DeepSeekConnection, exchange=exchange, binary=binary))
        row = {'arm': arm, 'status': 'unavailable'}
        try:
            async with asyncio.timeout(timeout):
                if case['component'] == 'lane-a':
                    output, checks = await reply(case, factory, directory / arm, config, timeout)
                else:
                    output = await background(case, config, directory / arm, timeout,
                                              connection_factory=factory)
                    checks = grade_background(case, output)
            row.update(status='pass' if all(checks.values()) else 'fail',
                       output_sha256=digest(output if case['component'] == 'lane-a' else {
                           key: output.get(key) for key in ('executions', 'pending', 'reply')}),
                       checks=checks)
        except Exception as error:
            row.update(status='error', reason=type(error).__name__)
            if isinstance(error, RuntimeError):
                row['reason'] = str(error)[:200]
        connection = exchange.connection
        row.update(elapsed_ms=exchange.ms(), provider_calls=exchange.requests,
                   startup_ms=getattr(connection, 'startup_ms', None),
                   first_text_ms=getattr(connection, 'first_text_ms', None),
                   sdk_first_text_ms=getattr(connection, 'sdk_first_text_ms', None))
        return row


WIRE_KEYS = ('model', 'effort', 'instructions_sha256', 'schema_sha256', 'input_sha256', 'tools_sha256')


def matches(first, second):
    return {key: first[key] == second[key] for key in WIRE_KEYS}


def receipt_row(case, arms, live):
    a, b = (arms[name]['provider_calls'] for name in ('codex', 'deepseek'))
    first = matches(a[0], b[0]) if a and b else None
    replay = [matches(x, y) for x, y in zip(a, b)] if not live else None
    return dict(case_id=case['id'], skill=case['skill'], locale=case['locale'], arms=arms,
        first_dispatch_match=first, scripted_dispatch_matches=replay,
        matching_request_count=len(a) == len(b),
        same_served_model=(a[0].get('served_model') == b[0].get('served_model')
                           if a and b and a[0].get('served_model') else None))


async def run_native(args, cases, receipt, gateway, key):
    # Keep only a small number of local runtimes and gateway requests active.
    limit = asyncio.Semaphore(args.concurrency)
    async with Bridge(model=args.model, effort=args.effort, gateway=gateway, key=key,
                      delay=args.delay_ms / 1000, max_calls=args.max_calls).serve() as bridge:
        async def run_case(index, case):
            async with limit:
                with TemporaryDirectory(prefix='memoir-harness-') as directory:
                    order = ('codex', 'deepseek') if index % 2 == 0 else ('deepseek', 'codex')
                    arms = {}
                    for arm in order:
                        arms[arm] = await measure(case, arm, bridge, args.dsh_bin, Path(directory),
                                                  args.timeout, args.live)
                    row = receipt_row(case, arms, args.live)
                    receipt['results'].append(row)
                    receipt['live_dispatches'] = bridge.calls
                    save(args.output, receipt)
                    print(case['id'], *(arms[name]['status'] for name in ('codex', 'deepseek')), flush=True)
        await asyncio.gather(*(run_case(index, case) for index, case in enumerate(cases)))


def selected(case_id, patterns):
    return not patterns or any(fnmatch(case_id, pattern) for pattern in patterns)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsh-bin', type=Path)
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--effort', default='low')
    parser.add_argument('--case', action='append', help='Shell pattern for a case ID, repeatable')
    parser.add_argument('--scope', choices=('all', 'native', 'skills'), default='all')
    parser.add_argument('--live', action='store_true', help='Use a bounded loopback gateway for model-backed cases')
    parser.add_argument('--gateway', default='http://127.0.0.1:4000/v1')
    parser.add_argument('--env-file', type=Path, help='Read only MEMORY_SPARK_LLM_API_KEY from this file')
    parser.add_argument('--list', action='store_true', help='List scenarios without executing')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--concurrency', type=int, default=3, choices=range(1, 7))
    parser.add_argument('--timeout', type=int, default=120, choices=range(10, 301), metavar='SECONDS')
    parser.add_argument('--max-calls', type=int, default=400, choices=range(1, 401), metavar='CALLS')
    parser.add_argument('--delay-ms', type=int, default=40, choices=range(0, 1001), metavar='MS')
    args = parser.parse_args()
    os.environ.update(MEMORY_SPARK_LLM_MODEL=args.model, MEMORY_SPARK_LLM_REASONING_EFFORT=args.effort,
                      LANGFUSE_TRACING_ENABLED='false')
    with TemporaryDirectory(prefix='memoir-benchmark-catalog-') as home:
        os.environ['MEMORY_SPARK_CODEX_HOME'] = home
        agent_cases = catalog(full=True)
        cases = [row for row in agent_cases if row['component'] in ('lane-a', 'lane-b')
                 and selected(row['id'], args.case)] if args.scope != 'skills' else []
        discoveries = [row for row in agent_cases if row['task'].get('kind') == 'native-discovery'
                       and selected(row['id'], args.case)] if args.scope != 'native' else []
        planned = plan()
        # The 16 base interviewer cases already occur under lane-a in catalog.
        planned['items'] = [row for row in planned['items'] if row['skill'] != 'memoir-interviewer'
                            and selected(row['id'], args.case)] if args.scope != 'native' else []
        if args.list:
            print(json.dumps([x['id'] for x in [*cases, *planned['items'], *discoveries]], indent=2))
            return
        if not args.output or args.output.exists() or not (cases or planned['items'] or discoveries):
            parser.error('Select cases and a new --output file')
        if cases and (not args.dsh_bin or not args.dsh_bin.is_file() or not shutil.which('codex')):
            parser.error('Native cases require Codex on PATH and --dsh-bin')
        gateway, key = None, None
        if args.live:
            endpoint = urlsplit(args.gateway)
            if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or endpoint.username
                    or endpoint.query or endpoint.fragment or not endpoint.port):
                parser.error('Live gateway must be a local HTTP endpoint')
            key = (dotenv_values(args.env_file).get('MEMORY_SPARK_LLM_API_KEY') if args.env_file
                   else os.environ.get('MEMORY_SPARK_LLM_API_KEY'))
            if not key:
                parser.error('Live gateway requires MEMORY_SPARK_LLM_API_KEY')
            gateway = args.gateway.rstrip('/')
        receipt = dict(synthetic=True, model=args.model, effort=args.effort, live=args.live,
            source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            codex_version=subprocess.check_output(['codex', '--version'], text=True).strip() if cases else None,
            deepseek_version=subprocess.check_output([str(args.dsh_bin.resolve()), '--version'],
                env=dict(PATH=os.environ['PATH'], DSH_HOME=home, HOME=home), text=True).strip() if cases else None,
            planned=[x['id'] for x in [*cases, *planned['items'], *discoveries]],
            max_live_dispatches=args.max_calls if args.live else 0, live_dispatches=0,
            fixture_delay_ms=args.delay_ms, results=[], unchanged_skills=[])
        args.output.parent.mkdir(parents=True, exist_ok=True)
        save(args.output, receipt)
        if cases:
            args.dsh_bin = args.dsh_bin.resolve()
            asyncio.run(run_native(args, cases, receipt, gateway, key))
        if planned['items'] or discoveries:
            from scripts.benchmark_skill_controls import run_skills
            asyncio.run(run_skills(planned, args.output, receipt, discoveries=discoveries,
                gateway=gateway, key=key, max_calls=args.max_calls - receipt['live_dispatches']))


if __name__ == '__main__':
    main()
