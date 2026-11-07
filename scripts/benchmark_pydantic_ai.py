#!/usr/bin/env python3
"""Three-way Memoir Mira and Atlas benchmark with bounded live dispatch."""
import argparse
import asyncio
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.benchmark_agent_harness import matches, measure, selected
from scripts.deepseek_benchmark_transport import Bridge
from scripts.memoir_agent_eval_cases import catalog
from scripts.memoir_skill_eval_suite import digest
from scripts.pydantic_benchmark_transport import ComparisonRuntimes, comparison_body
from scripts.run_memoir_live_skills import save

ARMS = ('codex', 'advanced_aas', 'pydantic')


def compare(arms, live):
    reference = arms['codex']['provider_calls']
    result = {}
    for arm in ARMS[1:]:
        calls = arms[arm]['provider_calls']
        result[arm] = dict(
            first=matches(reference[0], calls[0]) if reference and calls else None,
            same_count=len(reference) == len(calls),
            all_steps=None if live else [matches(a, b) for a, b in zip(reference, calls)],
        )
    return result


async def run(args, cases, receipt, gateway, key):
    limit = asyncio.Semaphore(args.concurrency)
    bridge = Bridge(model=args.model, effort=args.effort, gateway=gateway, key=key,
                    max_calls=args.max_calls, normalize=comparison_body)
    runtimes = ComparisonRuntimes(bridge, args.aas_core, args.node)
    async with bridge.serve(), runtimes.serve():
        async def run_case(index, case):
            async with limit:
                with TemporaryDirectory(prefix='memoir-agent-compare-') as directory:
                    rotation = index % len(ARMS)
                    order = ARMS[rotation:] + ARMS[:rotation]
                    arms = {}
                    for arm in order:
                        arms[arm] = await measure(case, arm, bridge, None, Path(directory), args.timeout,
                                                  args.live, runtimes=runtimes)
                    receipt['results'].append(dict(case_id=case['id'], skill=case['skill'],
                        locale=case['locale'], component=case['component'], order=order, arms=arms,
                        wire=compare(arms, args.live)))
                    receipt['live_dispatches'] = bridge.calls
                    save(args.output, receipt)
                    print(case['id'], *(arms[arm]['status'] for arm in ARMS), flush=True)

        async with asyncio.timeout(args.deadline):
            await asyncio.gather(*(run_case(index, case) for index, case in enumerate(cases)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aas-core', type=Path, help='Built @aas/core package directory')
    parser.add_argument('--node', default='node', help='Node 22 or later')
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--effort', default='low')
    parser.add_argument('--case', action='append', help='Shell pattern for a case ID, repeatable')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--gateway', default='http://127.0.0.1:4000/v1')
    parser.add_argument('--env-file', type=Path, help='Read only MEMORY_SPARK_LLM_API_KEY')
    parser.add_argument('--max-calls', type=int, default=450, choices=range(1, 551), metavar='CALLS')
    parser.add_argument('--concurrency', type=int, default=4, choices=range(1, 7))
    parser.add_argument('--timeout', type=int, default=90, choices=range(10, 181), metavar='SECONDS')
    parser.add_argument('--deadline', type=int, default=1200, choices=range(30, 1801), metavar='SECONDS')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    os.environ.update(MEMORY_SPARK_LLM_MODEL=args.model, MEMORY_SPARK_LLM_REASONING_EFFORT=args.effort,
                      LANGFUSE_TRACING_ENABLED='false')
    cases = [case for case in catalog(full=True) if case['component'] in ('lane-a', 'lane-b')
             and selected(case['id'], args.case)]
    if args.list:
        print(json.dumps([case['id'] for case in cases], indent=2))
        return
    if not cases or not args.output or args.output.exists():
        parser.error('Select cases and a new --output file')
    if not args.aas_core or not (args.aas_core / 'dist/query/query.js').is_file() or not shutil.which('codex'):
        parser.error('Provide --aas-core and install Codex on PATH')
    gateway, key = None, None
    if args.live:
        endpoint = urlsplit(args.gateway)
        if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or not endpoint.port
                or endpoint.username or endpoint.query or endpoint.fragment):
            parser.error('Live gateway must be a loopback HTTP endpoint')
        config = dotenv_values(args.env_file) if args.env_file else os.environ
        key = config.get('MEMORY_SPARK_LLM_API_KEY')
        if not key:
            parser.error('Live gateway requires MEMORY_SPARK_LLM_API_KEY')
        gateway = args.gateway.rstrip('/')
    receipt = dict(synthetic=True, model=args.model, effort=args.effort, live=args.live,
        source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, cwd=ROOT).strip(),
        codex_version=subprocess.check_output(['codex', '--version'], text=True).strip(),
        pydantic_ai_version=version('pydantic-ai-slim'),
        aas_core_version=json.loads((args.aas_core / 'package.json').read_text())['version'],
        aas_query_sha256=digest((args.aas_core / 'dist/query/query.js').read_text()),
        concurrency=args.concurrency, max_live_dispatches=args.max_calls if args.live else 0,
        live_dispatches=0, planned=[case['id'] for case in cases], results=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save(args.output, receipt)
    asyncio.run(run(args, cases, receipt, gateway, key))


if __name__ == '__main__':
    main()
