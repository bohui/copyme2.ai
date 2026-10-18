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


# These tests invoke production admission/scheduling code with controlled replies;
# their passing status is never evidence of live model delivery.
TRIGGERS = {
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
                         production_status='unwired' if skill == 'memoir-family-tree' else 'implemented'))
                for skill, selectors in TRIGGERS.items()]
    deliveries = []
    for case in cases():
        deliveries.append(dict(input={k: case[k] for k in
            ('id', 'skill', 'instructions', 'input', 'schema')}, expected_output=dict(
                status='passed', validator=case['validator'],
                expected=case.get('expected'), scope=case.get('scope', 'isolated live output contract'))))
        deliveries[-1]['input'].update(case_id=case['id'], kind='live_contract')
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
    return {'memoir/evaluation/v2/skill-triggers': triggers,
            'memoir/evaluation/v2/skill-deliveries': deliveries}


def item_id(name, row):
    return digest([name, row])[:32]


def verify_items(name, rows, items, *, complete):
    wanted = {row['input']['case_id']: row for row in rows}
    actual = {item.input.get('case_id'): item for item in items}
    if len(actual) != len(items) or not set(actual) <= set(wanted):
        raise ValueError('unexpected_dataset_items')
    for key, item in actual.items():
        if (item.input != wanted[key]['input'] or item.expected_output != wanted[key]['expected_output']
                or str(item.status).upper() != 'ACTIVE'):
            raise ValueError('dataset_item_conflict')
    if complete and set(actual) != set(wanted):
        raise ValueError('incomplete_dataset_readback')
    return set(wanted) - set(actual)


def publish_datasets(client, definitions):
    existing, page = {}, 1
    while True:
        result = client.api.datasets.list(page=page, limit=100)
        existing.update({d.name: d for d in result.data})
        if page >= result.meta.total_pages:
            break
        page += 1
    # Preflight both datasets before any write. A resume only adds matching missing items.
    missing = {}
    for name, rows in definitions.items():
        if name in existing:
            if (existing[name].metadata or {}).get('content_sha256') != digest(rows):
                raise ValueError('dataset_content_conflict')
            missing[name] = verify_items(name, rows, client.get_dataset(name).items, complete=False)
        else:
            missing[name] = {row['input']['case_id'] for row in rows}
    for name, rows in definitions.items():
        if name not in existing:
            client.create_dataset(name=name,
                description=('Application trigger checks with controlled replies' if name.endswith('triggers')
                    else 'Real gateway delivery probes; isolated synthetic inputs, no production persistence'),
                metadata=dict(suite='memoir-skills/1', synthetic=True, contains_customer_data=False,
                              content_sha256=digest(rows), item_count=len(rows)))
        for row in rows:
            key = item_id(name, row)
            if row['input']['case_id'] in missing[name]:
                client.create_dataset_item(dataset_name=name, id=key, **row,
                    metadata=dict(skill=row['input']['skill'], case_id=row['input']['case_id'],
                                  content_sha256=digest(row), synthetic=True))
    snapshot = datetime.now(timezone.utc)
    loaded = {name: client.get_dataset(name, version=snapshot) for name in definitions}
    for name, dataset in loaded.items():
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
    from apps.api.background_skills import SKILLS
    checked['production_status'] = SKILLS[value['skill']].status
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


def readback(client, experiment_id, expected_count, started_at):
    result = client.api.experiments.list_items(from_start_time=started_at,
        experiment_id=experiment_id, fields='core,dataset,io,scores', limit=100)
    items = result.data
    if result.meta.cursor or len(items) != expected_count:
        return dict(status='pending', items=len(items), expected_items=expected_count)
    scored = sum(bool(item.scores) for item in items)
    return dict(status='verified' if scored == expected_count else 'pending',
                items=len(items), scored_items=scored, expected_items=expected_count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Publish missing datasets and execute; default is a zero-call plan')
    parser.add_argument('--phase', choices=('all', 'triggers', 'deliveries'), default='all')
    parser.add_argument('--case', action='append', choices=[r['input']['case_id'] for rows in datasets().values() for r in rows],
                        help='Select one case; repeat to recheck a bounded subset')
    parser.add_argument('--credential-file', type=Path, default=Path.home() / 'llm_provider/.env')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'var/skill-evaluation')
    args = parser.parse_args()
    definitions = {name: rows for name, rows in datasets().items()
                   if args.phase == 'all' or name.endswith(args.phase)}
    phase_cases = {row['input']['case_id'] for rows in definitions.values() for row in rows}
    if args.case and not set(args.case) <= phase_cases:
        parser.error('Selected case does not belong to the requested phase')
    if not args.execute:
        print(json.dumps({name: dict(items=len(rows), content_sha256=digest(rows))
                          for name, rows in definitions.items()}, indent=2))
        return 0
    from dotenv import dotenv_values
    from scripts.export_langfuse_prompts import export_prompts
    config = {**dotenv_values(args.env_file, interpolate=False), **os.environ}
    if args.phase != 'triggers' and not all(config.get(k) for k in
            ('MEMORY_SPARK_LLM_BASE_URL', 'MEMORY_SPARK_LLM_API_KEY', 'MEMORY_SPARK_LLM_MODEL')):
        raise ValueError('existing_gateway_configuration_required')
    client = prompt_client(args.credential_file)
    projects = client.api.projects.get().data
    if len(projects) != 1 or projects[0].id != 'cmut9t75w00071z02n8bdv7it':
        raise ValueError('unexpected_langfuse_project')
    prompts = export_prompts(client, check=True)
    loaded, snapshot = publish_datasets(client, definitions)
    if args.case:
        for dataset in loaded.values():
            dataset.items = [item for item in dataset.items if item.input['case_id'] in args.case]
    run_id = 'skills-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = args.output_root.expanduser().resolve() / run_id
    directory.mkdir(parents=True, mode=0o700)
    started_at = datetime.now(timezone.utc)
    receipt = dict(schema_version='memoir-skill-evaluation/1', run_id=run_id,
        started_at=started_at.isoformat(), status='running', results=[], calls=[], experiments=[],
        source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        prompt_versions={p['name']: p['version'] for p in prompts}, skill_manifest=manifest(),
        dataset_version=snapshot.isoformat(), limits=dict(max_calls=48, live_seconds=1800,
            per_call_seconds=120, per_trigger_group_seconds=300, concurrency=1, transport_retries=0),
        limitations=['Controlled trigger checks do not certify live end-to-end model scheduling.',
            'Family-tree is unwired in the canonical application; its standalone output probe is separate.',
            'The isolated story-game output probe checks rejection; successful generation/publication needs the separate UI campaign.',
            'Prose quality needs human review; deterministic contract passes are not editorial acceptance.',
            'Gateway internal attempts and monetary cost are unavailable.'])
    save(directory / 'datasets.json', definitions)
    save(directory / 'receipt.json', receipt)
    provider = TracedProvider(config, receipt, directory, langfuse=client, timeout=120,
        deadline=time.monotonic() + 1800, max_calls=48, effort='max')
    contract_cases = {c['id']: c for c in cases()}

    async def task(*, item, **_kwargs):
        value = item.input
        before, tick = len(receipt['calls']), time.monotonic()
        try:
            if value['kind'] == 'controlled_application_checks':
                result = await asyncio.to_thread(run_trigger, value, directory)
            elif value['kind'] == 'live_contract':
                output, _ = await provider.call(value['case_id'], value['skill'], value['instructions'],
                                               value['input'], value['schema'])
                validate_case(contract_cases[value['case_id']], output)
                result = dict(status='passed', output=output)
            elif value['kind'] == 'live_composer':
                result = dict(status='passed', checks=await compose(provider, value['locale']))
            else:
                result = dict(status='passed', checks=await native_search(provider, value['skill']))
        except Exception as error:
            result = dict(status='failed', reason=type(error).__name__)
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
            evidence=('controlled application checks' if value['kind'] == 'controlled_application_checks'
                      else 'live gateway output checked against independent contract validators'))
        receipt['results'].append(result)
        save(directory / 'receipt.json', receipt)
        print(json.dumps({k: result[k] for k in ('case_id', 'status', 'elapsed_seconds', 'http_dispatches')}
                         | {'reason': result.get('reason')}, ensure_ascii=False), flush=True)
        return result

    # Verify v4 experiments directly; the legacy dataset-run GET API is retired.
    for name, dataset in loaded.items():
        if not dataset.items:
            continue
        if name.endswith('deliveries'):
            provider.deadline = time.monotonic() + 1800
        result = dataset.run_experiment(name='Memoir skill ' + name.rsplit('-', 1)[-1],
            run_name=run_id + '-' + name.rsplit('-', 1)[-1], task=task, evaluators=[evaluate],
            max_concurrency=1, metadata=dict(suite='memoir-skills/1', synthetic=True,
                source_revision=receipt['source_revision'], dataset_version=snapshot.isoformat()))
        experiment = dict(dataset=name, dataset_id=dataset.id, experiment_id=result.experiment_id,
                          expected_items=len(dataset.items), sdk_items=len(result.item_results))
        receipt['experiments'].append(experiment)
        client.flush()
        experiment['readback'] = readback(client, result.experiment_id, len(dataset.items), started_at)
        save(directory / 'receipt.json', receipt)
    verification_deadline = time.monotonic() + 30
    while any(e['readback']['status'] != 'verified' for e in receipt['experiments']):
        if time.monotonic() >= verification_deadline:
            break
        time.sleep(3)
        for experiment in receipt['experiments']:
            if experiment['readback']['status'] != 'verified':
                experiment['readback'] = readback(client, experiment['experiment_id'],
                    experiment['expected_items'], started_at)
    statuses = {r['status'] for r in receipt['results']}
    receipt['status'] = ('failed' if 'failed' in statuses else 'incomplete' if not receipt['results']
        or not receipt['experiments'] or 'unavailable' in statuses
        or any(e['readback']['status'] != 'verified' for e in receipt['experiments']) else 'passed')
    receipt['completed_at'] = datetime.now(timezone.utc).isoformat()
    save(directory / 'receipt.json', receipt)
    lines = ['# Memoir skill evaluation', '', 'Run: `' + run_id + '`', '',
             '| Skill | Trigger checks | Live deliveries |', '| --- | --- | --- |']
    for skill in manifest()['skills']:
        columns = []
        for controlled in (True, False):
            rows = [r for r in receipt['results'] if r['skill'] == skill and
                    (r['kind'] == 'controlled_application_checks') == controlled]
            counts = Counter(r['status'] for r in rows)
            columns.append(', '.join(f'{n} {status}' for status, n in counts.items()) or 'not selected')
        lines.append('| ' + skill + ' | ' + ' | '.join(columns) + ' |')
    lines += ['', *receipt['limitations'], '']
    (directory / 'report.md').write_text('\n'.join(lines))
    print(json.dumps(dict(status=receipt['status'], directory=str(directory),
                          experiments=receipt['experiments']), indent=2), flush=True)
    return 0 if receipt['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
