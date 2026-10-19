#!/usr/bin/env python3
"""Evaluate all Memoir skill triggers and deliveries from pinned Langfuse datasets."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.langfuse_prompt_client import prompt_client
from scripts.memoir_live_skill_cases import cases, validate_case
from scripts.run_memoir_live_skills import LiveProvider, compose, manifest, native_search, save
from scripts.memoir_skill_inventory import skill_inventory
from scripts.memoir_skill_judge import SkillJudge, evaluator_plan, judge_prompt


# These tests invoke production admission/scheduling code with controlled replies;
# their passing status is never evidence of live model delivery.
TRIGGERS = {
    'memoir-interviewer': [
        'tests/test_interview_plan.py',
        'tests/test_interview_strategy.py',
    ],
    'memoir-author-timeline': [
        'tests/test_background_skill_workflow.py::test_readiness_reports_saved_skill_with_actual_turn_and_source_coverage',
        'tests/test_background_skill_workflow.py::test_reply_only_is_skipped_not_model_applied_and_hidden_when_thinking_off',
        'tests/test_canonical_turn_publication.py::test_controlled_delivery_and_replay_keep_sql_authority_until_asgi_send',
    ],
    'memoir-composer': [
        'tests/test_background_skill_workflow.py::test_only_existing_profile_and_composer_schedules_advance_on_round_milestones',
        'tests/test_progressive_composer.py::test_first_chapter_after_empty_checkpoints_starts_at_chapter_revision_zero',
        'tests/test_progressive_composer.py::test_second_checkpoint_keeps_unchanged_prose_and_uses_only_the_new_messages_for_summary',
    ],
    'memoir-family-tree': [
        'tests/test_family_context.py::test_family_feature_requires_paid_family_entitlement_and_configured_price',
        'tests/test_family_context.py::test_each_skill_rejects_the_other_domain_and_timeline_can_link_to_saved_people',
        'tests/test_memoir_skill_evaluation.py::test_current_registry_requires_the_real_trigger_and_rejects_unbound_skills[memoir-family-tree]',
    ],
    'memoir-historical-news-research': [
        'tests/test_historical_news_runtime.py::test_saved_reply_releases_lease_before_research_and_later_turn_consumes_clue',
        'tests/test_historical_news_runtime.py::test_optional_research_never_breaks_a_saved_reply',
        'tests/test_historical_news_runtime.py::test_failed_delivery_releases_resources_without_external_research',
        'tests/test_historical_news.py::test_background_research_is_bounded_deduplicated_cached_and_never_fabricates',
    ],
    'memoir-memory-context': [
        'tests/test_background_profile_postgres.py::test_default_cadence_config_and_high_round_coalescing',
        'tests/test_background_profile_postgres.py::test_manual_blank_locks_stop_latch_release_and_honest_skip',
        'tests/test_background_profile.py::test_no_model_profile_dispositions_do_not_load_the_skill',
        'tests/test_background_profile.py::test_profile_contract_limits_targets_and_never_targets_saved_manual_reference',
    ],
    'memoir-place-groups': [
        'tests/test_place_groups.py',
        'tests/test_background_skill_workflow.py::test_completed_optional_service_receipts_do_not_expire',
    ],
    'memoir-place-journey': [
        'tests/test_background_skill_workflow.py::test_shared_place_pass_is_embedded_not_a_second_model_request',
        'tests/test_background_skill_workflow.py::test_shared_place_pass_reports_skipped_when_no_place_was_derived',
        'tests/test_place_journey.py::test_place_journey_marker_must_match_the_current_storyteller_message',
        'tests/test_place_journey.py::test_explicit_place_uncertainty_blocks_mapping_even_when_a_city_is_named',
    ],
    'memoir-place-photo-research': [
        'tests/test_background_skill_workflow.py::test_slow_photo_runner_cannot_hold_A_or_memory_and_cache_is_not_a_new_call',
        'tests/test_place_photo_pages.py::test_stable_pages_reuse_one_search_and_reject_other_queries',
        'tests/test_place_photo_pages.py::test_endpoint_pages_retain_authorization_and_do_not_repeat_discovery',
    ],
    'memoir-story-game': ['tests/test_memoir_story_game.py', 'tests/test_story_game_runtime.py',
                         'tests/test_story_game_runtime_postgres.py'],
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def datasets():
    triggers = [dict(input=dict(case_id=skill + '-triggers', skill=skill,
                               kind='controlled_application_checks', selectors=selectors),
                     expected_output=dict(status='passed', skips=0,
                         production_status=skill_inventory()[skill]['production_status']))
                for skill, selectors in TRIGGERS.items()]
    deliveries = []
    for case in cases():
        deliveries.append(dict(input=dict(case_id=case['id'], skill=case['skill'], packet=case['input'],
            kind='deterministic' if case.get('execution') == 'deterministic' else 'live_contract'), expected_output=dict(
                status='passed', validator=case['validator'],
                expected=case.get('expected'), scope=case.get('scope', 'isolated live output contract'))))
        deliveries[-1]['metadata'] = dict(locale=case.get('locale') or next(
            (locale for locale in ('en-AU', 'zh-CN') if case['id'].endswith(locale)), 'en-AU'),
            case_family=case.get('case_family', case['id']),
            expected_action='skip' if ('reject-' in case['id'] or 'missing-authority' in case['id']
                                      or (case['validator'] == 'profile' and not case.get('expected'))
                                      or case['id'].startswith('interviewer-pause-')) else 'deliver')
    for locale in ('en-AU', 'zh-CN'):
        deliveries.append(dict(input=dict(case_id='composer-pipeline-' + locale,
            skill='memoir-composer', kind='live_composer', locale=locale, checkpoints=[5, 10]),
            expected_output=dict(status='passed', unchanged_passages_preserved=True,
                                 new_original_evidence_retained=True)))
    for skill in ('memoir-historical-news-research', 'memoir-place-photo-research'):
        deliveries.append(dict(input=dict(case_id=skill + '-native-discovery', skill=skill,
            kind='live_native_search', public_place='Sydney, Australia',
            capture_period='2000' if skill == 'memoir-historical-news-research' else '1980s'),
            expected_output=dict(status='passed', native_tool_receipt=True,
                                 independently_inspected_source=True)))
    expected = set(manifest()['skills'])
    if set(TRIGGERS) != expected or {r['input']['skill'] for r in deliveries} != expected:
        raise ValueError('missing_skill_coverage')
    result = {f'memoir/evaluation/skills/{skill}': [] for skill in sorted(expected)}
    for row in triggers + deliveries:
        row.setdefault('metadata', {})
        row['metadata'].setdefault('locale', row['input'].get('locale'))
        row['metadata'].update(skill=row['input']['skill'], synthetic=True,
            contains_customer_data=False, execution_scope=(
                'controlled' if row['input']['kind'] == 'controlled_application_checks' else 'isolated'))
        result['memoir/evaluation/skills/' + row['input']['skill']].append(row)
    return result


def item_id(name, row):
    return digest([name, row['input']['case_id']])[:32]


def verify_items(name, rows, items, *, complete):
    wanted = {row['input']['case_id']: row for row in rows}
    actual = {item.input.get('case_id'): item for item in items}
    if len(actual) != len(items) or not set(actual) <= set(wanted):
        raise ValueError('unexpected_dataset_items')
    for key, item in actual.items():
        if (item.input != wanted[key]['input'] or item.expected_output != wanted[key]['expected_output']
                or item.id != item_id(name, wanted[key]) or str(item.status).upper() != 'ACTIVE'):
            raise ValueError('dataset_item_conflict')
    if complete and set(actual) != set(wanted):
        raise ValueError('incomplete_dataset_readback')
    return set(wanted) - set(actual)


def publish_datasets(client, definitions, *, update=False):
    existing, page = {}, 1
    while True:
        result = client.api.datasets.list(page=page, limit=100)
        existing.update({d.name: d for d in result.data})
        if page >= result.meta.total_pages:
            break
        page += 1
    # Preflight both datasets before any write. A resume only adds matching missing items.
    missing, retired = {}, {}
    for name, rows in definitions.items():
        if name in existing:
            if (existing[name].metadata or {}).get('suite') != 'memoir-skills/2':
                raise ValueError('unowned_dataset')
            items = client.get_dataset(name).items
            if not update:
                wanted = {row['input']['case_id'] for row in rows}
                items = [item for item in items if str(item.status).upper() != 'ARCHIVED'
                         or item.input.get('case_id') in wanted]
                missing[name] = verify_items(name, rows, items, complete=False)
                retired[name] = []
            else:
                wanted = {row['input']['case_id']: row for row in rows}
                if len({item.input['case_id'] for item in items}) != len(items):
                    raise ValueError('duplicate_hosted_case')
                for item in items:
                    if item.id != item_id(name, {'input': item.input}):
                        raise ValueError('dataset_item_identity_conflict')
                actual = {item.input['case_id']: item for item in items}
                missing[name] = {key for key, row in wanted.items() if key not in actual
                    or actual[key].input != row['input'] or actual[key].expected_output != row['expected_output']
                    or str(actual[key].status).upper() != 'ACTIVE'
                    or any((actual[key].metadata or {}).get(k) != v for k, v in row.get('metadata', {}).items())}
                retired[name] = [item for key, item in actual.items() if key not in wanted
                                 and str(item.status).upper() != 'ARCHIVED']
        else:
            missing[name] = {row['input']['case_id'] for row in rows}
            retired[name] = []
    for name, rows in definitions.items():
        if name not in existing:
            client.create_dataset(name=name,
                description='Skill contract, execution and quality cases; synthetic controlled/isolated inputs.',
                metadata=dict(suite='memoir-skills/2', synthetic=True, contains_customer_data=False))
        for row in rows:
            key = item_id(name, row)
            if row['input']['case_id'] in missing[name]:
                client.create_dataset_item(dataset_name=name, id=key,
                    input=row['input'], expected_output=row['expected_output'], status='ACTIVE',
                    metadata={**row.get('metadata', {}), 'case_id': row['input']['case_id'],
                              'content_sha256': digest(row), 'synthetic': True})
        for item in retired[name]:
            client.create_dataset_item(dataset_name=name, id=item.id, status='ARCHIVED')
    snapshot = datetime.now(timezone.utc)
    loaded = {name: client.get_dataset(name, version=snapshot) for name in definitions}
    for name, dataset in loaded.items():
        dataset.items = [item for item in dataset.items if str(item.status).upper() == 'ACTIVE']
        verify_items(name, definitions[name], dataset.items, complete=True)
    return loaded, snapshot


def junit_result(path, exit_code):
    if not path.exists():
        return dict(status='unavailable', reason='missing_test_receipt', exit_code=exit_code)
    root = ET.parse(path).getroot()
    counts = Counter()
    for case in root.iter('testcase'):
        status = next((s for s in ('error', 'failure', 'skipped') if case.find(s) is not None), 'passed')
        counts[status] += 1
    if counts['failure'] or counts['error']:
        status = 'failed'
    elif exit_code or counts['skipped'] or not counts['passed']:
        status = 'unavailable'
    else:
        status = 'passed'
    return dict(status=status, counts=dict(counts), exit_code=exit_code,
                evidence='production code with controlled provider replies; disposable local PostgreSQL')


def run_trigger(value, directory):
    folder = directory / value['case_id']
    folder.mkdir(mode=0o700)
    junit = folder / 'junit.xml'
    command = [sys.executable, str(ROOT / 'scripts/run_isolated_check.py'),
        '--output-dir', str(folder), '--name', 'trigger', '--timeout', '300', '--',
        sys.executable, '-m', 'pytest', '-q', *value['selectors'], '--junitxml=' + str(junit)]
    with (folder / 'runner.log').open('w') as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
    checked = junit_result(junit, result.returncode)
    checked['production_status'] = skill_inventory()[value['skill']]['production_status']
    if checked['status'] == 'passed' and checked['production_status'] != 'implemented':
        checked.update(status='unavailable', reason=checked['production_status'],
                       admission_checks_status='passed')
    return checked


def evaluate(*, output, **_kwargs):
    from langfuse.experiment import Evaluation
    if output['status'] == 'unavailable':
        return Evaluation(name='availability', value='unavailable', data_type='CATEGORICAL',
                          comment=output.get('reason', 'incomplete execution evidence'))
    return Evaluation(name='contract_pass', value=int(output['status'] == 'passed'),
                      comment=output.get('reason', output['evidence']), data_type='NUMERIC')


def evaluate_quality(*, output, **_kwargs):
    from langfuse.experiment import Evaluation
    quality = output.get('quality', {})
    return Evaluation(name='skill_quality', value=quality.get('score', 'unavailable'),
        data_type='CATEGORICAL', comment='Advisory; calibration pending. ' +
        quality.get('reasoning', quality.get('reason', 'judge_not_run')))


def select_datasets(definitions, *, phase='all', skill=None, locale=None, case_ids=None):
    selected = {}
    for name, rows in definitions.items():
        matches = [row for row in rows if
            (not skill or row['input']['skill'] == skill) and
            (phase == 'all' or (row['input']['kind'] == 'controlled_application_checks') == (phase == 'triggers')) and
            (not locale or row.get('metadata', {}).get('locale') in {None, locale}) and
            (not case_ids or row['input']['case_id'] in case_ids)]
        if matches:
            selected[name] = matches
    return selected


class TracedProvider(LiveProvider):
    def __init__(self, *args, langfuse, **kwargs):
        super().__init__(*args, **kwargs)
        self.langfuse = langfuse

    async def call(self, case_id, skill, instructions, packet, schema=None, *, search=False):
        failure = None
        with self.langfuse.start_as_current_observation(name=case_id, as_type='generation',
                input=dict(instructions=instructions, packet=packet), metadata=dict(skill=skill)) as span:
            try:
                value, response = await super().call(case_id, skill, instructions, packet, schema, search=search)
                record = self.receipt['calls'][-1]
                usage = record.get('usage') or {}
                span.update(output=value, model=record['served_model'],
                    usage_details={key: usage[key] for key in ('input_tokens', 'output_tokens', 'total_tokens')
                                   if isinstance(usage.get(key), int)},
                    metadata=dict(skill=skill, response_id=record['provider_response_id'],
                                  requested_model=record['requested_model'], effort=record['effort']))
            except Exception as error:
                # Do not send transport exception strings (which can contain credentials).
                span.update(level='ERROR', status_message=type(error).__name__)
                failure = error
        if failure is not None:
            raise failure
        return value, response


def readback(client, experiment_id, expected_count, started_at, *, expected=None):
    result = client.api.experiments.list_items(from_start_time=started_at,
        experiment_id=experiment_id, fields='core,dataset,io,scores', limit=100)
    items = result.data
    if result.meta.cursor or len(items) != expected_count:
        return dict(status='pending', items=len(items), expected_items=expected_count)
    if expected is not None:
        identities = [getattr(item, 'experiment_item_id', None) for item in items]
        if len(set(identities)) != len(identities) or set(identities) != set(expected):
            return dict(status='conflict', reason='experiment_item_identity')
        for item in items:
            wanted = expected[item.experiment_item_id]
            if (item.input != wanted['input'] or item.expected_output != wanted['expected_output']
                    or item.output != wanted['output'] or item.experiment_dataset_id != wanted['dataset_id']):
                return dict(status='conflict', reason='experiment_content_binding')
            scores = {}
            for score in item.scores or []:
                scores.setdefault(score.name, []).append(score.value)
            output = wanted['output']
            required = {'skill_quality': output['quality']['score']}
            required.update({'availability': 'unavailable'} if output['status'] == 'unavailable' else
                            {'contract_pass': int(output['status'] == 'passed')})
            if any(name not in scores for name in required):
                return dict(status='pending', reason='required_scores_missing')
            if any(scores[name] != [value] for name, value in required.items()):
                return dict(status='conflict', reason='experiment_score_binding')
    scored = sum(bool(item.scores) for item in items)
    return dict(status='verified' if scored == expected_count else 'pending',
                items=len(items), scored_items=scored, expected_items=expected_count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Publish missing datasets and execute; default is a zero-call plan')
    parser.add_argument('--phase', choices=('all', 'triggers', 'deliveries'), default='all')
    parser.add_argument('--skill', choices=manifest()['skills'])
    parser.add_argument('--locale', choices=('en-AU', 'zh-CN'))
    parser.add_argument('--judge', choices=('off', 'sdk'), default='off',
                        help='Independent quality judging requires published prompt pins; off runs contract checks only')
    parser.add_argument('--judge-model', help='Use this model on the existing gateway for independent judging')
    parser.add_argument('--max-calls', type=int, default=48)
    parser.add_argument('--max-judge-calls', type=int, default=48)
    parser.add_argument('--update-datasets', action='store_true',
                        help='Apply reviewed item updates/archives using stable IDs before execution')
    parser.add_argument('--case', action='append', choices=[r['input']['case_id'] for rows in datasets().values() for r in rows],
                        help='Select one case; repeat to recheck a bounded subset')
    parser.add_argument('--credential-file', type=Path, default=Path.home() / 'llm_provider/.env')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'var/skill-evaluation')
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 256 or not 1 <= args.max_judge_calls <= 256:
        parser.error('Call limits must be between 1 and 256')
    catalog = datasets()
    definitions = select_datasets(catalog, phase=args.phase, skill=args.skill, locale=args.locale)
    phase_cases = {row['input']['case_id'] for rows in definitions.values() for row in rows}
    if args.case and not set(args.case) <= phase_cases:
        parser.error('Selected case does not belong to the requested phase')
    if args.case:
        definitions = select_datasets(definitions, case_ids=args.case)
    if not args.execute:
        print(json.dumps(dict(
            skills=manifest()['skills'], selected_cases=[row['input']['case_id'] for rows in definitions.values() for row in rows],
            datasets={name: dict(items=len(rows), content_sha256=digest(rows)) for name, rows in definitions.items()},
            evaluators=evaluator_plan(), judge_executor=args.judge,
            limits=dict(skill_calls=args.max_calls, judge_calls=args.max_judge_calls),
            http_dispatches=0), indent=2))
        return 0
    if args.judge == 'sdk':
        try:
            for skill in {row['input']['skill'] for rows in definitions.values() for row in rows
                          if row['input']['kind'] not in {'controlled_application_checks', 'deterministic'}}:
                judge_prompt(skill)
        except ValueError:
            parser.error('Judge prompts need valid published pins; merge reviewed main and run make prompt-sync first')
    from dotenv import dotenv_values
    from scripts.export_langfuse_prompts import export_prompts
    config = {**dotenv_values(args.env_file, interpolate=False), **os.environ}
    needs_model = any(row['input']['kind'] not in {'controlled_application_checks', 'deterministic'}
                      for rows in definitions.values() for row in rows)
    if needs_model and not all(config.get(k) for k in
            ('MEMORY_SPARK_LLM_BASE_URL', 'MEMORY_SPARK_LLM_API_KEY', 'MEMORY_SPARK_LLM_MODEL')):
        raise ValueError('existing_gateway_configuration_required')
    client = prompt_client(args.credential_file)
    projects = client.api.projects.get().data
    if len(projects) != 1 or projects[0].id != 'cmut9t75w00071z02n8bdv7it':
        raise ValueError('unexpected_langfuse_project')
    prompts = export_prompts(client, check=True)
    publication = {name: rows for name, rows in catalog.items() if name in definitions}
    loaded, snapshot = publish_datasets(client, publication, **({'update': True} if args.update_datasets else {}))
    selected_rows = {row['input']['case_id']: row for rows in definitions.values() for row in rows}
    for dataset in loaded.values():
        dataset.items = [item for item in dataset.items if item.input['case_id'] in selected_rows]
    run_id = 'skills-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = args.output_root.expanduser().resolve() / run_id
    directory.mkdir(parents=True, mode=0o700)
    started_at = datetime.now(timezone.utc)
    receipt = dict(schema_version='memoir-skill-evaluation/1', run_id=run_id,
        started_at=started_at.isoformat(), status='running', results=[dict(
            case_id=row['input']['case_id'], skill=row['input']['skill'], kind=row['input']['kind'],
            status='not_run', quality=dict(score='unavailable', reason='not_run'))
            for row in selected_rows.values()], calls=[], experiments=[],
        source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        prompt_versions={p['name']: p['version'] for p in prompts}, skill_manifest=manifest(),
        dataset_version=snapshot.isoformat(), judge_executor=args.judge, judge_calls=[],
        acceptance_scope='contracts_and_advisory_quality' if args.judge == 'sdk' else 'contracts_only',
        limits=dict(max_calls=args.max_calls, max_judge_calls=args.max_judge_calls, live_seconds=1800,
            per_call_seconds=120, per_trigger_group_seconds=300, concurrency=1, transport_retries=0),
        limitations=['Controlled trigger checks do not certify live end-to-end model scheduling.',
            'Family-tree is unwired in the canonical application; its standalone output probe is separate.',
            'The isolated story-game output probe checks rejection; successful generation/publication needs the separate UI campaign.',
            'Prose quality needs human review; deterministic contract passes are not editorial acceptance.',
            'Gateway internal attempts and monetary cost are unavailable.'])
    save(directory / 'datasets.json', definitions)
    save(directory / 'receipt.json', receipt)
    provider = TracedProvider(config, receipt, directory, langfuse=client, timeout=120,
        deadline=time.monotonic() + 1800, max_calls=args.max_calls, effort='max')
    judge = None
    if args.judge == 'sdk' and needs_model:
        judge_directory = directory / 'judges'
        judge_directory.mkdir(mode=0o700)
        judge_config = {**config, 'MEMORY_SPARK_LLM_MODEL': args.judge_model or config['MEMORY_SPARK_LLM_MODEL']}
        judge_provider = TracedProvider(judge_config, {'calls': receipt['judge_calls']}, judge_directory, langfuse=client,
            timeout=120, deadline=time.monotonic() + 1800, max_calls=args.max_judge_calls, effort='low')
        judge = SkillJudge(judge_provider)
    contract_cases = {c['id']: c for c in cases()}

    async def task(*, item, **_kwargs):
        value = item.input
        before, tick = len(receipt['calls']), time.monotonic()
        result = {}
        try:
            if value['kind'] == 'controlled_application_checks':
                result = await asyncio.to_thread(run_trigger, value, directory)
            elif value['kind'] == 'live_contract':
                case = contract_cases[value['case_id']]
                output, _ = await provider.call(value['case_id'], value['skill'], case['instructions'],
                                               value['packet'], case['schema'])
                result = dict(status='failed', artifact=output)
                validate_case(case, output)
                result['status'] = 'passed'
            elif value['kind'] == 'deterministic':
                from apps.api.place_groups import resolve_place_groups
                result = dict(status='passed', artifact=resolve_place_groups(value['packet']['places'], allow_provider=False))
                validate_case(contract_cases[value['case_id']], result['artifact'])
            elif value['kind'] == 'live_composer':
                result = dict(status='passed', checks=await compose(provider, value['locale']))
                result['artifact'] = [json.loads((directory / f"composer-{value['locale']}-{round}.json").read_text())
                                      for round in (5, 10)]
            elif value['kind'] == 'live_native_search':
                result = dict(status='passed', checks=await native_search(provider, value['skill']))
                path = directory / ('photo-sources.json' if value['skill'] == 'memoir-place-photo-research' else 'historical-sources.json')
                result['artifact'] = json.loads(path.read_text())
            else:
                raise ValueError('unknown_skill_adapter')
        except Exception as error:
            result = {**result, 'status': 'failed', 'reason': type(error).__name__}
            message = str(error)
            if type(error) in (ValueError, RuntimeError) and message.replace('_', '').isalnum() and len(message) < 90:
                result['reason'] = message
            if isinstance(error, (TimeoutError, httpx.HTTPError)) or message == 'live_call_budget_exhausted':
                result['status'] = 'unavailable'
            if len(receipt['calls']) > before:
                record = receipt['calls'][-1]
                result['reason'] = record.get('json_failure_kind') or record.get('rejection_category') or result['reason']
        result.update(case_id=value['case_id'], skill=value['skill'], kind=value['kind'],
            elapsed_seconds=round(time.monotonic() - tick, 3), http_dispatches=len(receipt['calls']) - before,
            evidence=('actual deterministic grouping; zero skill model calls' if value['kind'] == 'deterministic' else
                      'controlled application checks' if value['kind'] == 'controlled_application_checks'
                      else 'live gateway output checked against independent contract validators'))
        result['execution'] = ('unavailable' if result['status'] == 'unavailable' else
            'controlled' if value['kind'] == 'controlled_application_checks' else
            'completed' if result['status'] == 'passed' else 'failed')
        result['delivery'] = ('correct_skip' if result['status'] == 'passed' and
            selected_rows[value['case_id']].get('metadata', {}).get('expected_action') == 'skip' else
            'isolated_output' if result['status'] == 'passed' and value['kind'] != 'controlled_application_checks' else 'not_observed')
        result['quality'] = (dict(score='not_applicable', reason='controlled_or_numeric_check')
            if value['kind'] in {'controlled_application_checks', 'deterministic'} else
            dict(score='unavailable', reason='judge_disabled', calibration='pending'))
        if judge is not None:
            try:
                result['quality'] = await judge.evaluate(selected_rows[value['case_id']], result)
            except Exception as error:
                result['quality'] = dict(score='unavailable', reason=type(error).__name__, calibration='pending')
        receipt['results'] = [result if item['case_id'] == value['case_id'] else item for item in receipt['results']]
        save(directory / 'receipt.json', receipt)
        print(json.dumps({k: result[k] for k in ('case_id', 'status', 'elapsed_seconds', 'http_dispatches')}
                         | {'reason': result.get('reason')}, ensure_ascii=False), flush=True)
        return result

    # Verify v4 experiments directly; the legacy dataset-run GET API is retired.
    readback_bindings = {}
    for name, dataset in loaded.items():
        if not dataset.items:
            continue
        result = dataset.run_experiment(name='Memoir skill ' + name.rsplit('/', 1)[-1],
            run_name=run_id + '-' + name.rsplit('/', 1)[-1], task=task, evaluators=[evaluate, evaluate_quality],
            max_concurrency=1, metadata=dict(suite='memoir-skills/2', synthetic=True,
                source_revision=receipt['source_revision'], dataset_version=snapshot.isoformat()))
        experiment = dict(dataset=name, dataset_id=dataset.id, experiment_id=result.experiment_id,
                          expected_items=len(dataset.items), sdk_items=len(result.item_results))
        receipt['experiments'].append(experiment)
        client.flush()
        outputs = {row['case_id']: row for row in receipt['results']}
        expected = {item.id: dict(input=item.input, expected_output=item.expected_output,
                    output=outputs[item.input['case_id']], dataset_id=dataset.id) for item in dataset.items}
        readback_bindings[result.experiment_id] = expected
        experiment['readback'] = readback(client, result.experiment_id, len(dataset.items), started_at, expected=expected)
        save(directory / 'receipt.json', receipt)
    verification_deadline = time.monotonic() + 30
    while any(e['readback']['status'] == 'pending' for e in receipt['experiments']):
        if time.monotonic() >= verification_deadline:
            break
        time.sleep(3)
        for experiment in receipt['experiments']:
            if experiment['readback']['status'] == 'pending':
                experiment['readback'] = readback(client, experiment['experiment_id'],
                    experiment['expected_items'], started_at, expected=readback_bindings[experiment['experiment_id']])
    statuses = {r['status'] for r in receipt['results']}
    quality_statuses = {row['quality']['score'] for row in receipt['results']}
    receipt['contract_status'] = ('failed' if 'failed' in statuses else
        'incomplete' if not statuses or statuses & {'unavailable', 'not_run'} else 'passed')
    receipt['quality_status'] = ('not_run' if args.judge == 'off' else
        'failed' if 'fail' in quality_statuses else 'incomplete' if quality_statuses & {'partial', 'unavailable'} else 'passed')
    receipt['status'] = ('failed' if 'failed' in statuses or (args.judge == 'sdk' and 'fail' in quality_statuses) else 'incomplete' if not receipt['results']
        or not receipt['experiments'] or statuses & {'unavailable', 'not_run'}
        or (args.judge == 'sdk' and quality_statuses & {'partial', 'unavailable'})
        or any(e['readback']['status'] != 'verified' for e in receipt['experiments']) else 'passed')
    receipt['completed_at'] = datetime.now(timezone.utc).isoformat()
    save(directory / 'receipt.json', receipt)
    lines = ['# Memoir skill evaluation', '', 'Run: `' + run_id + '`', '',
             '| Skill | Contract checks | Execution | Delivery scope | Quality (advisory) |',
             '| --- | --- | --- | --- | --- |']
    for skill in manifest()['skills']:
        columns = []
        rows = [r for r in receipt['results'] if r['skill'] == skill]
        for column in ('status', 'execution', 'delivery', 'quality'):
            counts = Counter((row['quality']['score'] if column == 'quality' else row.get(column, 'not_run')) for row in rows)
            columns.append(', '.join(f'{n} {status}' for status, n in counts.items()) or 'not selected')
        lines.append('| ' + skill + ' | ' + ' | '.join(columns) + ' |')
    lines += ['', *receipt['limitations'], '']
    (directory / 'report.md').write_text('\n'.join(lines))
    print(json.dumps(dict(status=receipt['status'], directory=str(directory),
                          experiments=receipt['experiments']), indent=2), flush=True)
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
