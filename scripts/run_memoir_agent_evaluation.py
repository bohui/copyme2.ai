#!/usr/bin/env python3
"""Evaluate current Lane A, native Lane B and skills; optionally publish SDK experiments.

Plan is zero-call. Synthetic inputs only. Live generation, controlled host tools,
independent code checks and advisory semantic judgments have distinct evidence.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.memoir_agent_eval_cases import catalog
from scripts.memoir_skill_eval_suite import Budget, digest, inventory, packet, validate
from scripts.run_memoir_live_skills import LiveProvider, native_search, save


def judge_selection(cases, maximum):
    """Stratify by component/skill instead of judging only the earliest replies."""
    groups = {}
    for case in cases:
        if case['skill'] not in {'memoir-family-tree', 'memoir-story-game'}:
            groups.setdefault((case['component'], case['skill']), []).append(case['id'])
    ordered = [sorted(values, key=digest) for _, values in sorted(groups.items())]
    result = []
    while any(ordered) and len(result) < maximum:
        for values in ordered:
            if values and len(result) < maximum:
                result.append(values.pop(0))
    return set(result)


def validate_judgment(value):
    from apps.api.trajectory_evaluation import JUDGE_RUBRIC
    if (not isinstance(value, dict) or value.get('status') not in {'observed', 'exploratory', 'evaluated', 'scored', 'pass', 'partial', 'fail', 'unavailable'}
            or not isinstance(value.get('scores'), dict)):
        raise ValueError('invalid_judge_shape')
    value = deepcopy(value)
    comments = value.get('comments')
    if isinstance(comments, list) and comments and all(isinstance(c, str) and c.strip() for c in comments):
        value['comments'] = {key: '\n'.join(comments) for key in value['scores']}
    if not isinstance(value.get('comments'), dict):
        raise ValueError('invalid_judge_comments')
    if value['status'] == 'unavailable' and value['scores']:
        raise ValueError('unavailable_judge_cannot_score')
    for key, number in value['scores'].items():
        if (key not in JUDGE_RUBRIC or type(number) not in (int, float) or not 0 <= number <= 1
                or not isinstance(value['comments'].get(key), str) or not value['comments'][key].strip()
                or not any(ref in value['comments'][key] for ref in ('observed-1', 'final_state', 'task'))):
            raise ValueError('invalid_or_unsupported_judge_score')
    return value


def dataset_rows(cases):
    """Withhold gold, evaluator instructions and production prompts from task input."""
    groups = {}
    for case in cases:
        row = dict(input=dict(case_id=case['id'], component=case['component'], skill=case['skill'],
                              locale=case['locale'], task=case['task']), expected_output=case['gold'])
        groups.setdefault(case['component'], []).append(row)
    return {'memoir/evaluation/v4/' + group + '/' + digest(rows)[:12]: rows for group, rows in groups.items()}


async def background(case, config, directory, timeout):
    """Real Codex tool loop and production capability checks, disposable host work."""
    from apps.api.memoir_background_agent import BackgroundSkills, SOURCE_SKILLS
    from apps.api.memoir_skill_agent import run_skill_agent
    from apps.api.model_configuration import background_model, background_effort
    from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
    remaining = deepcopy(case['task']['work'])
    executions = []
    fence = dict(user_id=str(uuid4()), project_id='synthetic-agent-evaluation')

    class Broker:
        async def rpc(self, name, **arguments):
            if name == 'read_user_historical_news':
                return dict(enabled=False)
            if name != 'read_memoir_background_work':
                raise ValueError('unexpected_evaluation_rpc')
            return deepcopy(remaining)

    class Executor:
        async def execute_lane(self, lane_id, **arguments):
            executions.append(dict(lane=lane_id, **deepcopy(arguments)))
            if lane_id == 'composer' and any(l['id'] == 'timeline' for l in remaining['lanes']):
                return dict(status='deferred')
            remaining['lanes'] = [l for l in remaining['lanes'] if l['id'] != lane_id]
            if lane_id == 'timeline':
                remaining.pop('source_work', None)
            return dict(status='finished')

    class Publisher:
        @asynccontextmanager
        async def guard(self, _fence):
            yield

    skills = BackgroundSkills(fence, Broker(), Executor())
    work = await skills.work()
    if not work['work']:
        return dict(model_invoked=False, executions=[], pending=False, skill_receipt=None)
    from apps.api.llm_tracing import trace_origin
    with trace_origin('evaluation'):
        result = await run_skill_agent(command=[shutil.which('codex') or 'codex', 'app-server'],
            home_root=directory / 'native', base_url=config['MEMORY_SPARK_LLM_BASE_URL'],
            api_key=config['MEMORY_SPARK_LLM_API_KEY'], model=background_model(config), effort=background_effort(config),
            instructions=load_prompt_artifact(prompt_path('memoir/shared/background-agent')),
            packet=dict(lane='B', **work, locale=case['locale'], budget=dict(max_tool_calls=32, seconds=timeout)),
            skills=[*SOURCE_SKILLS, 'memoir-composer'], execute=skills.execute, work=skills.work,
            process_source=skills.process_source, source_skills=SOURCE_SKILLS, publisher=Publisher(), fence=fence,
            schema=dict(type='object', additionalProperties=False, properties=dict(status=dict(type='string', const='finished')), required=['status']),
            timeout=timeout, apply_owner=False, trace_name='evaluation/memoir-background-agent', phase='orchestrate')
    pending = await skills.work()
    return dict(model_invoked=True, executions=executions, pending=bool(pending['work']),
                reply=result['reply'], skill_receipt=result['skill_receipt'])


def grade_background(case, output):
    execution_order = [e['lane'] for e in output['executions']]
    actual = [s for e in output['executions'] for s in e.get('source_work', {}).get('skills', [])]
    expected = case['gold']['skills']
    checks = dict(completed=not output['pending'], dependency_order=execution_order == case['gold']['execution_order'])
    if expected is not None:
        checks['skill_selection'] = len(actual) == len(set(actual)) and set(actual) == set(expected)
    if output['model_invoked']:
        checks['finished_contract'] = json.loads(output['reply']) == dict(status='finished')
        receipt = output['skill_receipt']
        checks['read_before_execute'] = set(actual) <= set(receipt['skills_read'])
    else:
        checks['no_unnecessary_model'] = not case['task']['work']['lanes']
    return checks


def grade_reply(case, output):
    from apps.api.lifetime_memory_continuity import validate_governed_collector_result
    result = validate_governed_collector_result(output, case['task']['context'])
    checks = dict(production_contract=True)
    facts = case['gold'].get('facts', {})
    if 'stopped' in facts:
        checks['narrator_stop'] = result['stopped'] == facts['stopped']
    if 'question' in facts:
        checks['question_delivery'] = bool(result['strategy_outcome']['question_delivered']) == facts['question']
    return checks


def review_split(case_id):
    family = case_id.rsplit('/', 1)[0] if case_id.rsplit('/', 1)[-1] in {'en-AU', 'zh-CN'} else case_id
    return 'holdout' if int(digest(family)[0], 16) % 3 == 0 else 'development'


class Runner:
    def __init__(self, args, config, directory, *, client=None):
        self.args, self.config, self.directory, self.client = args, config, directory, client
        self.started = time.monotonic()
        self.receipt = dict(schema_version='memoir-agent-evaluation/1', run_id=directory.name,
            started_at=datetime.now(timezone.utc).isoformat(), synthetic=True, contains_customer_data=False,
            source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            working_diff_sha256=hashlib.sha256(subprocess.check_output(['git', 'diff', '--', 'apps', 'scripts', 'skills'], cwd=ROOT)).hexdigest(),
            evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            implementation_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                'scripts/memoir_agent_eval_cases.py', 'scripts/memoir_skill_eval_suite.py',
                'scripts/memoir_skill_scenarios.py', 'scripts/run_memoir_live_skills.py',
                'scripts/memoir_skill_eval_workflows.py', 'apps/api/memoir_skill_agent.py',
                'apps/api/memoir_background_agent.py', 'apps/api/conversation_reply.py')},
            inventory=inventory(), calls=[], results=[], experiments=[],
            limits=dict(direct_http_calls=args.max_calls, native_runs=args.max_native_runs,
                native_tool_calls_per_run=32, seconds=args.seconds, per_case_seconds=args.timeout),
            native_runs=0, native_provider_request_count=None, monetary_cost=None,
            human_calibration='pending; semantic judgments are advisory and use the same configured model',
            scope='Live model proposals and native tool selection with isolated host tools; no canonical saves or browser delivery')
        provider_type, options = LiveProvider, {}
        if client:
            from scripts.run_memoir_skill_evaluation import TracedProvider
            from apps.api import llm_tracing
            llm_tracing._client_cache = client
            provider_type, options = TracedProvider, dict(langfuse=client)
        self.provider = provider_type(config, self.receipt, directory, timeout=args.timeout,
            deadline=self.started + args.seconds, max_calls=args.max_calls,
            effort=config.get('MEMORY_SPARK_LLM_REASONING_EFFORT') or 'low', **options)
        self.judge_ids = set()
        self.replay = None
        self.persist()

    async def advisory(self, case, row):
        from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
        from apps.api.trajectory_evaluation import build_judge_prompt
        instructions = load_prompt_artifact(prompt_path('memoir/evaluation/trajectory-judge/system'))
        evidence = dict(task=case['task'], expected_outcomes=case['gold'],
            ordered_steps=[dict(id='observed-1', output=row['output'], evidence_scope=self.receipt['scope'])],
            final_state=dict(canonical_delivery=False, witnesses=row.get('witnesses'), checks=row['checks']))
        text, raw = await self.provider.call(case['id'] + '/advisory', 'evaluation-judge', instructions,
            json.loads(build_judge_prompt(evidence)))
        judgment = validate_judgment(json.loads(text))
        return dict(**judgment, calibrated=False, acceptance_role='advisory', same_model=True,
                    response_id=raw['id'], model=raw.get('model'))

    def persist(self):
        save(self.directory / 'receipt.json', self.receipt)

    async def call(self, request):
        value, raw = await self.provider.call(request['item_id'], request['skill'], request['instructions'],
            request['input'], request.get('schema'))
        return dict(output=value, response_id=raw['id'], model=raw.get('model'), usage=raw.get('usage'))

    async def task(self, *, item, **_kwargs):
        case = self.by_id[item.input['case_id']]
        started, before = time.monotonic(), len(self.receipt['calls'])
        row = dict(case_id=case['id'], component=case['component'], skill=case['skill'], locale=case['locale'],
            repeat=getattr(self, 'repeat', 1),
            status='unavailable', checks={}, canonical_delivery=False, semantic=None)
        try:
            remaining = self.started + self.args.seconds - started
            if remaining <= 0:
                raise LookupError('run_deadline_exhausted')
            async with asyncio.timeout(min(self.args.timeout, remaining)):
                if self.replay is not None:
                    original = self.replay[case['id']]
                    if original['input_sha256'] != digest(item.input):
                        raise ValueError('replay_input_changed')
                    row.update(output=deepcopy(original['output']), evidence_mode='retained_live_output_regraded',
                        replay=dict(source_output_sha256=digest(original['output']),
                            source_evidence_mode=original.get('evidence_mode'), source_gold_sha256=original['gold_sha256'],
                            source_status=original['status']))
                    row['checks'] = (grade_reply(case, row['output']) if case['component'] == 'lane-a'
                                     else grade_background(case, row['output']))
                elif case['component'] == 'lane-a':
                    row['evidence_mode'] = 'live_reply_proposal'
                    from apps.api.conversation_reply import reply_instructions, reply_schema
                    from apps.api.conversation_reply_transport import reply_messages
                    instructions = reply_instructions()
                    view = {**case['task']['view'], 'instructions': instructions}
                    value, _ = await self.provider.call(case['id'], case['skill'], instructions, {},
                        reply_schema(case['task']['context']), messages=reply_messages(view, ''))
                    row['output'] = value
                    row['checks'] = grade_reply(case, value)
                elif case['component'] == 'lane-b':
                    row['evidence_mode'] = 'live_native_tool_loop_with_controlled_domain_operations'
                    if self.receipt['native_runs'] >= self.args.max_native_runs:
                        raise LookupError('native_run_budget_exhausted')
                    self.receipt['native_runs'] += 1
                    self.persist()
                    row['output'] = await background(case, self.config, self.directory, min(self.args.timeout, remaining))
                    row['checks'] = grade_background(case, row['output'])
                elif case['task'].get('kind') == 'native-discovery':
                    row['evidence_mode'] = 'live_native_search_and_independent_source_inspection'
                    row['output'] = await native_search(self.provider, case['skill'])
                    row['checks']['independent_public_source'] = True
                else:
                    scenario = case['scenario']
                    row['evidence_mode'] = 'live_skill_proposal'
                    if case['skill'] == 'memoir-family-tree':
                        raise LookupError('canonical_family_runner_unwired')
                    if case['skill'] == 'memoir-story-game':
                        raise LookupError('game_requires_authority_and_browser_workflow; not certified by a prompt probe')
                    if case['skill'] == 'memoir-place-groups':
                        row['evidence_mode'] = 'deterministic_production_function'
                        from apps.api.place_groups import resolve_place_groups
                        value = resolve_place_groups(deepcopy(case['task']['places']), allow_provider=False)
                    elif case['skill'] == 'memoir-composer':
                        row['evidence_mode'] = 'live_composition_with_in_memory_checkpoints'
                        from scripts.memoir_skill_eval_workflows import composer
                        from scripts.memoir_skill_eval_suite import validate_workflow
                        budget = Budget(self.args.max_calls - len(self.receipt['calls']), min(remaining, self.args.timeout),
                            self.args.timeout, time.monotonic)
                        value, witnesses = await composer(scenario, self, budget)
                        row['output'], row['witnesses'] = value, witnesses
                        validate_workflow(scenario, value, witnesses)
                    else:
                        request = packet(scenario)
                        request['item_id'] = case['id']
                        value = (await self.call(request))['output']
                    row['output'] = value
                    if case['skill'] != 'memoir-composer':
                        validate(scenario, value)
                    row['checks']['production_and_gold_contract'] = True
                row['status'] = 'pass' if all(row['checks'].values()) else 'fail'
        except (LookupError, TimeoutError) as error:
            row['reason'] = str(error) if isinstance(error, LookupError) else 'case_timeout'
        except Exception as error:
            row.update(status='fail', reason=type(error).__name__)
            if type(error) in (ValueError, RuntimeError) and len(str(error)) < 100 and str(error).replace('_', '').isalnum():
                row['reason'] = str(error)
            latest = self.receipt['calls'][-1] if len(self.receipt['calls']) > before else {}
            if latest.get('rejection_category'):
                row['reason'] = latest['rejection_category']
            if latest.get('status') == 'failed' and not row.get('output') and 'http_status' not in latest:
                row['status'] = 'unavailable'
        row['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if case['id'] in self.judge_ids and row.get('output') is not None:
            try:
                row['semantic'] = await self.advisory(case, row)
            except Exception as error:
                row['semantic'] = dict(status='unavailable', reason=type(error).__name__, acceptance_role='advisory')
        row['direct_http_calls'] = len(self.receipt['calls']) - before
        row['input_sha256'], row['gold_sha256'] = digest(item.input), digest(item.expected_output)
        self.receipt['results'].append(row)
        self.persist()
        print(json.dumps({k: row.get(k) for k in ('case_id', 'status', 'reason', 'elapsed_seconds')}, ensure_ascii=False), flush=True)
        return row


def scores(*, output, **_kwargs):
    from langfuse import Evaluation
    result = [Evaluation(name='execution_available', value=int(output['status'] != 'unavailable'), data_type='NUMERIC')]
    if output['status'] != 'unavailable':
        result.append(Evaluation(name='contract_pass', value=int(output['status'] == 'pass'),
            comment=output.get('reason', 'Independent code checks; proposal scope only'), data_type='NUMERIC'))
    result += [Evaluation(name=name, value=int(value), data_type='NUMERIC') for name, value in output['checks'].items()]
    semantic = output.get('semantic') or {}
    result += [Evaluation(name='advisory.' + name, value=value, data_type='NUMERIC',
        comment=semantic['comments'][name] + ' [Uncalibrated; same model; advisory only]')
        for name, value in semantic.get('scores', {}).items()]
    result.append(Evaluation(name='latency_seconds', value=output['elapsed_seconds'], data_type='NUMERIC'))
    return result


def verify_experiment(client, experiment_id, rows, results, started_at):
    """Read back exact inputs, gold, outputs and every external score, with paging."""
    expected = {row['input']['case_id']: row for row in rows}
    local = {row['case_id']: row for row in results}
    items, cursor = [], None
    while True:
        page = client.api.experiments.list_items(from_start_time=started_at, experiment_id=experiment_id,
            fields='core,dataset,io,scores', limit=100, score_limit=50, cursor=cursor)
        items += page.data
        cursor = page.meta.cursor
        if not cursor:
            break
    def decoded(value):
        return json.loads(value) if isinstance(value, str) else value
    seen = set()
    for item in items:
        input_value, gold, output = decoded(item.input), decoded(item.expected_output), decoded(item.output)
        case_id = input_value.get('case_id') if isinstance(input_value, dict) else None
        if case_id not in expected or case_id in seen:
            raise ValueError('unexpected_or_duplicate_experiment_item')
        seen.add(case_id)
        if input_value != expected[case_id]['input'] or gold != expected[case_id]['expected_output'] or output != local[case_id]:
            raise ValueError('experiment_evidence_readback_mismatch')
        expected_scores = {s.name: s.value for s in scores(output=local[case_id])}
        actual_scores = {s.name: s.value for s in item.scores or []}
        if any(actual_scores.get(name) != value for name, value in expected_scores.items()):
            return dict(status='pending', items=len(items), reason='scores_not_visible')
    return dict(status='verified' if seen == set(expected) else 'pending', items=len(items),
                verified_inputs_outputs_scores=len(seen), expected_items=len(expected))


def write_report(receipt, directory):
    lines = ['# Memoir agent and skill evaluation', '', receipt['scope'], '',
        '| Component / skill | Pass | Fail | Unavailable |', '| --- | ---: | ---: | ---: |']
    groups = sorted({(r['component'], r['skill']) for r in receipt['results']})
    for component, skill in groups:
        counts = Counter(r['status'] for r in receipt['results'] if r['component'] == component and r['skill'] == skill)
        lines.append(f"| {component} / {skill} | {counts['pass']} | {counts['fail']} | {counts['unavailable']} |")
    lines += ['', '| Case | Result | Reason |', '| --- | --- | --- |']
    lines += [f"| {r['case_id']} | {r['status']} | {r.get('reason', '')} |" for r in receipt['results']]
    lines += ['', '## Advisory semantic judgments', '',
        '| Case | Judge status | Scores |', '| --- | --- | --- |']
    lines += [f"| {r['case_id']} | {r['semantic']['status']} | {json.dumps(r['semantic'].get('scores', {}))} |"
        for r in receipt['results'] if r.get('semantic')]
    lines += ['', '## Evidence limits', '',
        '- Lane A uses current production prompts, native message projection, reply schema and validator via the gateway.',
        '- Lane B uses the actual Codex tool loop and production SkillTools/BackgroundSkills. Domain operations use disposable controlled state.',
        '- Generation and contract success do not establish a saved reply, persisted timeline, UI footprint or camera state.',
        '- Family-tree has no canonical runner. Game publication requires a separate authorized application/browser workflow.',
        '- These task-specific code checks are not human editorial acceptance. Human semantic calibration is pending.',
        '- Direct HTTP dispatches are counted; native provider attempts, gateway retries and monetary cost are not established.', '']
    (directory / 'report.md').write_text('\n'.join(lines))
    cases = {c['id']: c for c in catalog(full=True)}
    save(directory / 'human-review.json', dict(schema_version='memoir-human-review/1',
        review_status='pending', reviewer=None, reviewed_at=None,
        instructions='Review observed task/output against gold, cite evidence, and label without seeing model identity. Keep development and holdout labels separate.',
        examples=[dict(case_id=r['case_id'], split=review_split(r['case_id']), task=cases[r['case_id']]['task'],
            gold=cases[r['case_id']]['gold'], output=r.get('output'), human_reviewed=False,
            human_label=None, rationale=None) for r in receipt['results']]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--replay-receipt', type=Path, help='Regrade retained Lane A/B outputs; no model dispatch or advisory calls')
    parser.add_argument('--component', action='append', choices=['lane-a', 'lane-b', 'skills'])
    parser.add_argument('--case', action='append')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--max-calls', type=int, default=128)
    parser.add_argument('--max-native-runs', type=int, default=16)
    parser.add_argument('--judge-cases', type=int, default=12, help='Stratified same-model advisory sample; included in direct HTTP cap')
    parser.add_argument('--seconds', type=float, default=1800)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--gateway-url', help='Existing gateway origin reachable from this host; no routing changes')
    parser.add_argument('--credential-file', type=Path, default=Path.home() / 'llm_provider/.env')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'var/agent-evaluation')
    args = parser.parse_args(argv)
    if not (1 <= args.repeat <= 5 and 1 <= args.max_calls <= 1000 and 0 <= args.max_native_runs <= 100 and 0 <= args.judge_cases <= 100
            and 0 < args.timeout <= 240 and 0 < args.seconds <= 3600):
        parser.error('invalid evaluation limits')
    cases = catalog(full=args.full)
    if args.case and not set(args.case) <= {c['id'] for c in cases}:
        parser.error('unknown case; use --full to select an extended case')
    cases = [c for c in cases if (not args.component or c['component'] in args.component) and (not args.case or c['id'] in args.case)]
    if not cases:
        parser.error('empty selection')
    if not args.execute:
        print(json.dumps(dict(cases=[c['id'] for c in cases], count=len(cases), repetitions=args.repeat,
            direct_http_call_cap=args.max_calls, native_run_cap=args.max_native_runs, seconds=args.seconds,
            http_dispatches=0, dataset_names=list(dataset_rows(cases))), indent=2))
        return 0
    from dotenv import dotenv_values
    from scripts.backend_operation_lock import backend_operation_lock
    from scripts.langfuse_prompt_client import prompt_client
    from scripts.run_memoir_skill_evaluation import publish_datasets
    config = {**dotenv_values(args.env_file, interpolate=False), **os.environ}
    if args.gateway_url:
        config['MEMORY_SPARK_LLM_BASE_URL'] = args.gateway_url
    if not args.replay_receipt and not all(config.get(k) for k in ('MEMORY_SPARK_LLM_API_KEY', 'MEMORY_SPARK_LLM_BASE_URL', 'MEMORY_SPARK_LLM_MODEL')):
        raise ValueError('existing_gateway_configuration_required')
    # Native provider_config reads these two operator settings from its process.
    # Do not load unrelated services, keys or database settings into the process.
    for key in ('MEMORY_SPARK_LLM_MODEL', 'MEMORY_SPARK_LLM_REASONING_EFFORT'):
        if config.get(key):
            os.environ[key] = config[key]
    directory = args.output_root.resolve() / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:6])
    directory.mkdir(parents=True, mode=0o700)
    with backend_operation_lock():
        client = prompt_client(args.credential_file) if args.publish else None
        runner = Runner(args, config, directory, client=client)
        runner.by_id = {c['id']: c for c in cases}
        runner.judge_ids = judge_selection(cases, args.judge_cases)
        if args.replay_receipt:
            if any(c['component'] not in {'lane-a', 'lane-b'} for c in cases):
                parser.error('replay supports Lane A/B outputs; select --component lane-a and/or lane-b')
            original = json.loads(args.replay_receipt.read_text())
            rows = [r for r in original['results'] if r['case_id'] in runner.by_id]
            if len(rows) != len(cases) or {r['case_id'] for r in rows} != set(runner.by_id) or any('output' not in r for r in rows):
                raise ValueError('replay_requires_one_observed_output_per_selected_case')
            runner.replay, runner.judge_ids = {r['case_id']: r for r in rows}, set()
            runner.receipt.update(scope='Retained live agent outputs regraded with current code; zero model dispatches',
                replay=dict(source_run_id=original['run_id'], source_evaluator_sha256=original['evaluator_sha256'],
                    source_receipt_sha256=hashlib.sha256(args.replay_receipt.read_bytes()).hexdigest()))
        loaded, snapshot = publish_datasets(client, dataset_rows(cases)) if client else (None, None)
        definitions = dataset_rows(cases)
        try:
            for repeat in range(args.repeat):
                runner.repeat = repeat + 1
                if client:
                    for name, dataset in loaded.items():
                        experiment = dataset.run_experiment(name='Memoir current agents and skills',
                            run_name=directory.name + f'-repeat{repeat + 1}-' + name.split('/')[-2], task=runner.task,
                            evaluators=[scores], max_concurrency=1,
                            metadata=dict(synthetic=True, suite='memoir-agent-evaluation/1', repeat=repeat + 1,
                                source_revision=runner.receipt['source_revision'], dataset_version=snapshot.isoformat(),
                                scope=runner.receipt['scope']))
                        client.flush()
                        # Preserve the experiment ID even when readback fails.
                        hosted = dict(dataset=name, experiment_id=experiment.experiment_id,
                            expected_items=len(dataset.items), readback=dict(status='pending'))
                        runner.receipt['experiments'].append(hosted)
                        runner.persist()
                        results = runner.receipt['results'][-len(dataset.items):]
                        started_at = datetime.fromisoformat(runner.receipt['started_at'])
                        verification = verify_experiment(client, experiment.experiment_id, definitions[name], results, started_at)
                        deadline = time.monotonic() + 30
                        while verification['status'] != 'verified' and time.monotonic() < deadline:
                            time.sleep(2)
                            verification = verify_experiment(client, experiment.experiment_id, definitions[name], results, started_at)
                        hosted['readback'] = verification
                        runner.persist()
                else:
                    from types import SimpleNamespace
                    for case in cases:
                        value = next(row for rows in dataset_rows([case]).values() for row in rows)
                        asyncio.run(runner.task(item=SimpleNamespace(input=value['input'], expected_output=value['expected_output'])))
            runner.receipt['status'] = ('publication_pending' if any(e['readback']['status'] != 'verified'
                for e in runner.receipt['experiments']) else 'complete_with_findings')
        finally:
            if client:
                client.flush()
            runner.receipt['elapsed_seconds'] = round(time.monotonic() - runner.started, 3)
            runner.persist()
            write_report(runner.receipt, directory)
        print(json.dumps(dict(directory=str(directory), counts=dict(Counter(r['status'] for r in runner.receipt['results'])),
            experiments=runner.receipt['experiments']), indent=2))
        return 0 if runner.receipt.get('status') == 'complete_with_findings' and all(r['status'] == 'pass'
            for r in runner.receipt['results']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
