#!/usr/bin/env python3
"""Offer simultaneous bilingual Mira turns and Atlas jobs to the benchmark runtimes."""
import argparse
import asyncio
from collections import Counter
from contextlib import nullcontext
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.agent_lock import AgentTurnBusyError
from apps.api.two_lane_memory import RuntimeCapacity
from scripts.benchmark_pydantic_ai import ARMS, measure
from scripts.deepseek_benchmark_transport import Bridge
from scripts.memoir_agent_eval_cases import catalog
from scripts.pydantic_benchmark_transport import ComparisonRuntimes, comparison_body
from scripts.run_memoir_live_skills import save


def tree_rss():
    rows = [tuple(map(int, line.split())) for line in subprocess.check_output(
        ['/bin/ps', '-axo', 'pid=,ppid=,rss='], text=True).splitlines()]
    owned = {os.getpid()}
    while children := {pid for pid, parent, _ in rows if parent in owned and pid not in owned}:
        owned.update(children)
    return round(sum(rss for pid, _, rss in rows if pid in owned) / 1024, 2)


def p95(values):
    values = sorted(values)
    return round(values[math.ceil(.95 * len(values)) - 1], 2) if values else None


def summary(rows):
    passed = [row for row in rows if row['status'] == 'pass']
    return dict(offered=len(rows), status=dict(Counter(row['status'] for row in rows)),
        admitted=sum('wait_ms' in row for row in rows),
        p95_wait_ms=p95(row['wait_ms'] for row in passed),
        p95_first_text_ms=p95(row['wait_ms'] + row['first_text_ms'] for row in passed
                              if row['first_text_ms'] is not None),
        p95_completion_ms=p95(row['wait_ms'] + row['elapsed_ms'] for row in passed))


async def wave(bridge, runtimes, arm, profile, offered, mira, atlas):
    if profile == 'worker':
        capacity = RuntimeCapacity()
    elif profile == 'pool':
        capacity = RuntimeCapacity(total=16, background=4, queue_limit=0)
    else:
        capacity = None
    gates = {True: asyncio.Semaphore(12), False: asyncio.Semaphore(4)}
    start = asyncio.Event()
    finish = asyncio.Event()
    active = peak = 0
    idle_rss = await asyncio.to_thread(tree_rss)
    memory = [idle_rss]

    async def sample():
        while not finish.is_set():
            memory.append(await asyncio.to_thread(tree_rss))
            try:
                await asyncio.wait_for(finish.wait(), .20)
            except TimeoutError:
                pass

    async def turn(index, case, interactive):
        nonlocal active, peak
        await start.wait()
        try:
            front = gates[interactive] if profile == 'pool' else nullcontext()
            admission = capacity.slot(interactive=interactive) if capacity is not None else nullcontext()
            async with front, admission:
                wait = (time.perf_counter() - started) * 1000
                active += 1
                peak = max(peak, active)
                try:
                    with TemporaryDirectory(prefix='memoir-load-') as directory:
                        row = await measure(case, arm, bridge, None, Path(directory), 45, False,
                                            runtimes=runtimes)
                    row = {key: row[key] for key in ('status', 'first_text_ms', 'elapsed_ms')}
                    row['wait_ms'] = round(wait, 2)
                finally:
                    active -= 1
        except AgentTurnBusyError:
            row = {'status': 'queue_full'}
        except TimeoutError:
            row = {'status': 'queue_timeout'}
        return dict(index=index, case_id=case['id'], lane='mira' if interactive else 'atlas', **row)

    jobs = [asyncio.create_task(turn(i, atlas[i % len(atlas)], False)) for i in range(8)]
    jobs += [asyncio.create_task(turn(i, mira[i % len(mira)], True)) for i in range(offered)]
    sampling = asyncio.create_task(sample())
    started = time.perf_counter()
    start.set()
    try:
        async with asyncio.timeout(150):
            rows = await asyncio.gather(*jobs)
        elapsed = time.perf_counter() - started
    finally:
        finish.set()
        await sampling
    assert active == 0 and (capacity is None or capacity.waiting == 0)
    lanes = {lane: summary([row for row in rows if row['lane'] == lane]) for lane in ('mira', 'atlas')}
    return dict(arm=arm, profile=profile, offered_mira=offered, active_peak=peak,
        duration_ms=round(elapsed * 1000, 2), successful_per_second=round(
            sum(lane['status'].get('pass', 0) for lane in lanes.values()) / elapsed, 2),
        idle_rss_mib=idle_rss, peak_rss_mib=max(memory), lanes=lanes, turns=rows)


async def run(args):
    cases = catalog(full=True)
    mira = [case for case in cases if case['id'].startswith('lane-a/memoir-interviewer/grounded-question/')]
    atlas = [case for case in cases if case['id'].startswith('lane-b/introduction/')]
    assert {case['locale'] for case in mira} == {case['locale'] for case in atlas} == {'en-AU', 'zh-CN'}
    bridge = Bridge(model='gpt-6.1-sol', effort='low', delay=.10, normalize=comparison_body)
    runtimes = ComparisonRuntimes(bridge, args.aas_core, args.node)
    receipt = dict(model=bridge.model, effort=bridge.effort, live=False, delay_ms=100,
        profiles={'worker': 'one worker, 4 active, 2 Atlas, 8 queued per lane',
                  'pool': 'client queue, 12 Mira and 4 Atlas active',
                  'embedded': 'uncapped warm-runtime burst, no app admission'},
        atlas_per_wave=8, results=[])
    async with bridge.serve(), runtimes.serve():
        for profile in args.profile:
            arms = ARMS[1:] if profile == 'embedded' else ARMS
            for index, offered in enumerate(args.turns):
                rotation = index % len(arms)
                for arm in arms[rotation:] + arms[:rotation]:
                    row = await wave(bridge, runtimes, arm, profile, offered, mira, atlas)
                    receipt['results'].append(row)
                    save(args.output, receipt)
                    print(profile, offered, arm, row['active_peak'], row['lanes']['mira']['status'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--aas-core', type=Path, required=True)
    parser.add_argument('--node', default='node')
    parser.add_argument('--profile', nargs='+', choices=('worker', 'pool', 'embedded'),
                        default=['worker', 'pool', 'embedded'])
    parser.add_argument('--turns', nargs='+', type=int, choices=(50, 100, 300), default=[50, 100, 300])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Select a new output file')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ.update(MEMORY_SPARK_LLM_MODEL='gpt-6.1-sol', MEMORY_SPARK_LLM_REASONING_EFFORT='low',
                      LANGFUSE_TRACING_ENABLED='false')
    asyncio.run(run(args))


if __name__ == '__main__':
    main()
