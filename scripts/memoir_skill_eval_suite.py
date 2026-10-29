"""Ten-skill evaluation planning and evidence-bound offline execution.

No credentials, SDK client or network transport is allocated here. External
adapters must be supplied by a caller; the CLI runs available deterministic
code and reports other execution unavailable. Controlled tests inject only
external-service boundaries. Hosted publication remains a separate gate.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from uuid import uuid4

from scripts.memoir_live_skill_cases import scenario_cases
from scripts.run_memoir_live_skills import save

ROOT = Path(__file__).resolve().parents[1]
KNOWN = frozenset('memoir-' + name for name in (
    'interviewer', 'author-timeline', 'composer', 'family-tree', 'memory-context',
    'place-journey', 'place-groups', 'place-photo-research', 'historical-news-research', 'story-game'))
PHASES = ('interview', 'extract', 'progressive', 'proposal', 'integration', 'review', 'group', 'discover', 'publish', 'play')
JUDGES = ROOT / 'tests/evaluation/prompts/skill-judges'
PHOTO_UPSTREAM_DEPENDENCIES = [
    dict(id='photo-locality-compound-query', upstream_head='d4c6f58d15450df69742342d1b6104bdf04f4772',
         scope='photo_research.py:_crawl4ai_source_images', affects='issue90/story19',
         status='integrated_prerequisite',
         behavior='Compound landmark/city queries require source-backed containing geography.'),
    dict(id='photo-locality-image-geography', upstream_head='d4c6f58d15450df69742342d1b6104bdf04f4772',
         scope='photo_research.py:_crawl4ai_source_images', affects='issue90/story19',
         status='integrated_prerequisite',
         behavior='Explicit image geography governs locality; reject foreign image geography and do not infer geography from caption wording.'),
]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identity(item):
    return '/'.join(item[key] for key in ('skill', 'case', 'locale'))


def inventory():
    from apps.api.background_skills import SKILLS
    from apps.api.prompt_catalog import PROMPT_PATHS
    owners = {name.split('/')[2] for name in PROMPT_PATHS if name.startswith('memoir/skills/')}
    actual = set(SKILLS) | owners
    if actual != KNOWN:
        raise ValueError('unmapped_skill_inventory: ' + ', '.join(sorted(actual ^ KNOWN)))
    result = {}
    for skill in sorted(actual):
        definition = asdict(SKILLS[skill]) if skill in SKILLS else dict(
            name=skill, execution='model', runner='foreground_collector', status='implemented', trigger='foreground_turn')
        definition['prompt_sources'] = []
        for name, relative in sorted(PROMPT_PATHS.items()):
            if not name.startswith('memoir/skills/' + skill + '/'):
                continue
            from apps.api.prompt_artifact import load_prompt_artifact
            from apps.api.prompt_composition import render_prompt_artifact
            from apps.api.model_request import prompt_manifest
            path = ROOT / relative
            load_prompt_artifact(path)
            manifest=prompt_manifest([name],render_prompt_artifact(path))
            pin=manifest['artifacts'][0]
            definition['prompt_sources'].append(dict(name=name,path=relative,version=pin['version'],
                status=pin['status'],sha256=pin['sha256'],composition=dict(
                    sha256=manifest['prompt_sha256'],components=manifest['artifacts'][1:])))
        result[skill] = definition
    return json.loads(json.dumps(result))


def judge_definition(skill):
    paths = [JUDGES / 'policy.md', JUDGES / (skill + '.md')]
    components, texts = [], []
    for path in paths:
        from scripts.prompt_registry import EVALUATION_PROMPT_PATHS
        name = next(name for name, relative in EVALUATION_PROMPT_PATHS.items() if ROOT / relative == path)
        content = path.read_text()
        sha = hashlib.sha256(content.encode()).hexdigest()
        receipt = path.with_name(path.name + '.langfuse.json')
        pin = None
        if receipt.exists():
            from apps.api.prompt_artifact import load_prompt_artifact
            load_prompt_artifact(path)
            pin = json.loads(receipt.read_text())
            if pin['name'] != name: raise ValueError('judge_prompt_receipt_owner_mismatch')
        components.append(dict(name=name, path=str(path.relative_to(ROOT)), sha256=sha,
                               version=pin['version'] if pin else None))
        texts.append(content)
    compiled = '\n\n'.join(texts)
    return dict(name='memoir/evaluation/' + skill + '/quality', kind='quality',
        compiled_text=compiled, compiled_sha256=hashlib.sha256(compiled.encode()).hexdigest(),
        components=components, publication='pinned' if all(c['version'] for c in components) else 'unpublished',
        hosted_evaluator_version=None, enabled=False)


def definitions(skills):
    result = []
    implementation = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for skill in skills:
        result.append(dict(name='memoir/evaluation/' + skill + '/contract', kind='contract',
            implementation_sha256=implementation, hosted_evaluator_version=None, enabled=False))
        result.append(judge_definition(skill))
    return result


def plan(*, skill=None, phase=None, locale=None, case=None):
    catalog = inventory()
    items = scenario_cases()
    if len(items) != 160 or len({c['id'] for c in items}) != 160 or {c['skill'] for c in items} != set(catalog):
        raise ValueError('incomplete_scenario_inventory')
    for name in catalog:
        subset = [c for c in items if c['skill'] == name]
        if len(subset) != 16 or len({c['case'] for c in subset}) != 8:
            raise ValueError('incomplete_scenario_families')
    filters = dict(skill=skill, phase=phase, locale=locale, id=case)
    for field, values in filters.items():
        if values and not set(values) <= {c[field] for c in items}:
            raise ValueError('unknown_' + field)
    selected_items = [c for c in items if all(not values or c[key] in values for key, values in filters.items())]
    if not selected_items or case and set(case) != {c['id'] for c in selected_items}:
        raise ValueError('empty_or_cross_phase_selection')
    selected = sorted({c['skill'] for c in selected_items})
    all_datasets = {s: 'memoir/evaluation/skills/' + s for s in catalog}
    snapshot = datetime.now(timezone.utc).isoformat()
    for c in items:
        c.update(content_sha256=digest(c), dataset=all_datasets[c['skill']], dataset_snapshot=snapshot)
    workflow_items = [dict(id='workflow/source-to-private-draft/' + language, locale=language,
        task=dict(action='accepted testimony, event extraction, progressive private draft, source withdrawal', synthetic=True),
        expected_output=dict(witnesses=['source_versions', 'event_revisions', 'composer_checkpoints', 'withdrawal_readback']))
        for language in ('en-AU', 'zh-CN')]
    calibration_items = [dict(id='calibration-' + split + '-' + s, skill=s, split=split,
        task=dict(action='independent synthetic judgment calibration', synthetic=True,
            example='unsupported claim' if split == 'development' else 'missing required witness'),
        expected_output=dict(human_label=None, human_reviewed=False, critical_violation_label=None))
        for s in catalog for split in ('development', 'holdout')]
    return dict(schema_version='memoir-skill-evaluation/3', inventory=catalog, selected_skills=selected,
        upstream_dependencies=deepcopy(PHOTO_UPSTREAM_DEPENDENCIES) if 'memoir-place-photo-research' in selected else [],
        items=selected_items, catalog_items=items,
        datasets=[*all_datasets.values(), 'memoir/evaluation/workflows', 'memoir/evaluation/judge-calibration'],
        dataset_snapshot=snapshot, dataset_snapshot_kind='local_plan_timestamp',
        evaluators=definitions(catalog), http_dispatches=0, synthetic=True,
        human_calibration='pending_human_labels',
        workflow_items=workflow_items, calibration_items=calibration_items,
        calibration={split: [c['id'] for c in calibration_items if c['split'] == split and c['skill'] in selected]
                     for split in ('development', 'holdout')},
        publication=dict(status='blocked', reasons=['merged_main_judge_publication_required',
            'installed_langfuse_evaluator_and_rule_interfaces_unverified'],
            rules_enabled=False, dataset_targets=[all_datasets[s] for s in selected]))


def packet(item):
    """Build a fresh production request, with no gold, rubric or expected output."""
    from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
    skill, task = item['skill'], deepcopy(item['task'])
    schema = None
    if skill == 'memoir-memory-context':
        from apps.api.background_profile import profile_contract, profile_packet
        instructions, schema = profile_contract(task['page'])
        payload = profile_packet(task['page'])
    elif skill == 'memoir-interviewer':
        from apps.api.conversation_reply import reply_candidates, reply_instructions
        from apps.api.lifetime_memory_continuity import governed_collector_schema
        task['context'].update(reply_contract='reply-v2', two_lane_memory=True)
        instructions = reply_instructions()
        schema = governed_collector_schema(task['context'])
        payload = {**task['context'], 'reply_language': item['locale'],
            'brief': {'hints': [dict(index=index, **hint)
                for index, hint in enumerate(reply_candidates(task['context']))]}}
    elif skill in {'memoir-author-timeline', 'memoir-place-journey'}:
        from apps.api.lifetime_memory_lane_engine import lane_contract, EXTRACTION_WINDOW_CONTRACT
        instructions, schema = lane_contract('extract', item['locale'], two_lane=skill == 'memoir-place-journey')
        payload = dict(schema_version=1, sources=task.get('sources', [task['source']]),
            events=task.get('saved_events', []), interview_context={}, preferences=dict(language=item['locale']),
            coverage=dict(scope='source_window', snapshot_id=item['id'], source_high_water=1, complete=False),
            window_contract=EXTRACTION_WINDOW_CONTRACT)
    elif skill == 'memoir-family-tree':
        instructions = load_prompt_artifact(prompt_path('memoir/skills/memoir-family-tree/instructions'))
        payload = dict(source=task['source'], saved_people=[])
    elif skill == 'memoir-story-game' and item['phase'] == 'proposal':
        from apps.api.memoir_story_game import load_story_game_skill
        from apps.api.story_game_selection import ScenePool
        instructions = load_story_game_skill() + '\n\n' + load_prompt_artifact(prompt_path('memoir/skills/memoir-story-game/proposal'))
        schema, payload = ScenePool.model_json_schema(), task
    else:
        raise ValueError('requires_application_adapter')
    return dict(item_id=item['id'], skill='memoir-author-timeline' if skill == 'memoir-place-journey' else skill,
                evaluated_skill=skill, execution='embedded' if skill == 'memoir-place-journey' else 'model',
                locale=item['locale'], instructions=instructions,
                input=payload, schema=schema)


def validate(item, output):
    """Production validators plus independent gold; never accept model status fields."""
    skill, task, facts = item['skill'], item['task'], item['gold']['facts']
    if skill == 'memoir-place-groups':
        actual = dict(groups=len({p['city_key'] for p in output['places']}),
                      pins=sum(p['pin'] is not None for p in output['places']), places=len(output['places']))
        if actual != facts: raise ValueError('grouping_gold_mismatch')
    elif skill == 'memoir-memory-context':
        from apps.api.background_profile import validate_profile
        from jsonschema import Draft202012Validator
        Draft202012Validator(packet(item)['schema']).validate(output)
        original = task['page']['source']
        for change in output['profile_patch']:
            for ref in change['source_refs']:
                start, end = ref['char_start'], ref['char_end']
                if (type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(original['text'])
                    or original['text'][start:end] != ref['quote']):
                    raise ValueError('profile_original_character_span')
        value = validate_profile(output, task['page'])
        if {c['field']: c['value'] for c in value['profile_patch']} != facts:
            raise ValueError('profile_gold_mismatch')
    elif skill == 'memoir-interviewer':
        from apps.api.lifetime_memory_continuity import validate_governed_collector_result
        from jsonschema import Draft202012Validator
        Draft202012Validator(packet(item)['schema']).validate(output)
        result = validate_governed_collector_result(output, packet(item)['input'])
        outcome = result['strategy_outcome']
        if result['stopped'] != facts['stopped'] or bool(outcome['question_delivered']) != facts['question']:
            raise ValueError('interviewer_control_mismatch')
        if facts['selection_reason'] and outcome['selection_reason'] != facts['selection_reason']:
            raise ValueError('interviewer_current_intent')
    elif skill == 'memoir-author-timeline':
        from apps.api.memory_events import validate_extraction
        from jsonschema import Draft202012Validator
        Draft202012Validator(packet(item)['schema']).validate(output)
        originals = {(s['id'], s['version']): s for s in task['sources'] if s['status'] == 'active'}
        def exact_refs(node):
            if isinstance(node, list):
                for child in node: exact_refs(child)
            elif isinstance(node, dict):
                if {'source_id', 'version', 'quote'} <= node.keys():
                    source = originals.get((node['source_id'], node['version']))
                    if source is None: raise ValueError('event_unauthorized_source')
                    start, end, quote = node.get('char_start'), node.get('char_end'), node['quote']
                    if start is None and end is None:
                        if source['text'].count(quote) != 1: raise ValueError('event_ambiguous_quote')
                    elif (type(start) is not int or type(end) is not int
                        or not 0 <= start < end <= len(source['text']) or source['text'][start:end] != quote):
                        raise ValueError('event_original_character_span')
                for child in node.values(): exact_refs(child)
        exact_refs(output)
        value = validate_extraction(output, task['sources'], task['saved_events'])
        if not facts['min_events'] <= len(value) <= facts['max_events']: raise ValueError('event_gold_omission')
        for event in value:
            if event.get('person_ids'): raise ValueError('invented_person_identity')
    elif skill == 'memoir-place-journey':
        from apps.api.two_lane_memory import derived_hints
        from apps.api.memory_events import validate_extraction
        from jsonschema import Draft202012Validator
        Draft202012Validator(packet(item)['schema']).validate(output)
        validate_extraction(dict(events=output['events']), [task['source']], [])
        places = derived_hints(output, dict(source=task['source']))['place_journeys']
        if len(places) != len(output['place_journeys']): raise ValueError('ungrounded_places')
        expected = dict(**{'two-cities': ['Sydney', 'Perth'], 'correction': ['Perth'], 'current-evidence': ['Hobart'],
                          'homonym': ['Perth'], 'suburb': ['Chatswood']}).get(item['case'], [])
        translations = dict(Sydney='悉尼', Perth='珀斯', Hobart='霍巴特', Chatswood='车士活')
        expected = [translations[p] for p in expected] if item['locale'] == 'zh-CN' else expected
        if [p['place'] for p in places] != expected: raise ValueError('place_gold_mismatch')
        if item['case'] == 'homonym' and not any(x in places[0]['hierarchy'] for x in ('United Kingdom', '英国')):
            raise ValueError('place_country_mismatch')
    elif skill == 'memoir-family-tree':
        from apps.api.family_context import extract_family_tree_context, FAMILY_TREE_MARKER_START, FAMILY_TREE_MARKER_END
        _, tree = extract_family_tree_context(output)
        if isinstance(output, str) and (FAMILY_TREE_MARKER_START in output or FAMILY_TREE_MARKER_END in output):
            if tree is None or output.count(FAMILY_TREE_MARKER_START) != 1 or output.count(FAMILY_TREE_MARKER_END) != 1:
                raise ValueError('malformed_family_marker')
        if item['phase'] == 'integration': raise LookupError('unwired_canonical_family_runner')
        people = (tree or {}).get('people', [])
        if not facts['min_people'] <= len(people) <= facts['max_people']:
            raise ValueError('family_identity_count')
        if facts['names'] and sorted(p['name'] for p in people) != sorted(facts['names']):
            raise ValueError('family_name_grounding')
        if item['case'] == 'explicit-mother' and people[0].get('family_title') != 'mother':
            raise ValueError('family_kinship_grounding')
        if item['case'] == 'relationship-direction':
            by_name = {p['name']: p['id'] for p in people}
            mei, alex = facts['names']
            if not any(r['from_person_id'] == by_name[mei] and r['to_person_id'] == by_name[alex]
                and r['relationship_type'] == 'parent' for r in tree.get('relationships', [])):
                raise ValueError('family_relationship_direction')
        if item['case'] == 'privacy' and any(p.get('visibility') != 'private' or p.get('include_in_print') is not False for p in people):
            raise ValueError('family_privacy')
    elif skill == 'memoir-story-game':
        from apps.api.story_game_selection import validate_pool
        validate_pool(task, output)
        raise LookupError('missing_application_authority_and_original_chapter_witness')
    else:
        raise LookupError('missing_application_witness_adapter')


def validate_workflow(item, output, witnesses, directory=None, *, application_context=None, application_dispatches=None):
    if witnesses.get('kind') == 'controlled_application':
        from scripts.memoir_skill_eval_application import verify_witness
        return verify_witness(item, output, witnesses, directory, expected_context=application_context,
                              dispatches=application_dispatches)
    elif item['skill'] == 'memoir-composer':
        if witnesses.get('storage') != 'isolated_in_memory' or not output.get('checkpoints'):
            raise LookupError('composer_checkpoint_witness_missing')
        # Actual _compose validated schema, evidence and immutable carry-forward.
        if any(p.get('publication_approved') is True for p in output['checkpoints']):
            raise ValueError('invented_publication_approval')
    elif item['skill'] == 'memoir-historical-news-research':
        if output['status'] == 'unavailable' and not witnesses.get('completed_source_reads'):
            raise LookupError('historical_service_unavailable')
        clues = output.get('clues', [])
        if item['case'] in {'conflicting-sources', 'publication-date', 'unsupported-claim', 'unavailable-source'}:
            if clues: raise ValueError('unsupported_historical_claim')
        elif not clues:
            raise ValueError('missing_supported_historical_clue')
        if any(c.get('evidence_status') != 'inspected' or c.get('event_id') for c in clues):
            raise ValueError('history_personal_evidence_separation')
        if any('Alex' in q or '亚历克斯' in q for q in witnesses['queries']):
            raise ValueError('private_query_leak')
    elif item['skill'] == 'memoir-place-photo-research':
        photos = output['items']
        if item['case'] == 'unavailable-provider': raise LookupError('photo_service_unavailable')
        if item['case'] in {'wrong-place', 'unverified-lead'}:
            if photos: raise ValueError('unverified_photo_accepted')
        elif not photos:
            raise ValueError('missing_inspected_photo')
        for photo in photos:
            if not photo.get('attribution') or not photo.get('source_url'):
                raise ValueError('photo_attribution_missing')
            if any(photo.get('allowed_actions', {}).get(a) is True for a in ('download', 'publish', 'print')):
                raise ValueError('photo_rights_not_independently_granted')
        if item['case'] == 'relaxed-match' and any(p.get('period_match') != 'any_time' for p in photos):
            raise ValueError('photo_relaxed_period_unlabelled')
        if item['case'] == 'ranking':
            if [p['source_url'] for p in photos] != item['gold']['facts']['ranked_source_urls']:
                raise ValueError('photo_capture_and_distance_order')
    else:
        raise LookupError('unknown_application_workflow')


class Budget:
    def __init__(self, maximum, seconds, timeout, clock, *, max_bytes=256000):
        if type(maximum) is not int or not 0 <= maximum <= 1000 or not 0 < seconds <= 3600 or not 0 < timeout <= 240:
            raise ValueError('invalid_budget')
        self.maximum, self.started, self.seconds, self.timeout, self.clock = maximum, clock(), seconds, timeout, clock
        self.deadline = self.started + seconds
        self.max_bytes = max_bytes
        self.calls = []
        self.on_change = lambda: None

    async def dispatch(self, adapter, request, *, require_completion=True):
        if len(self.calls) >= self.maximum or self.clock() >= self.deadline: raise RuntimeError('budget_exhausted')
        if len(json.dumps(request, ensure_ascii=False).encode()) > self.max_bytes:
            raise LookupError('request_evidence_size_exhausted')
        record = dict(item_id=request['item_id'], request_sha256=digest(request), status='started',
                      response_id=None, model=None, usage=None)
        self.calls.append(record)  # Failed dispatches consume allowance, before awaiting transport.
        self.on_change()
        try:
            async with asyncio.timeout(min(self.timeout, self.deadline - self.clock())):
                reply = await adapter.call(deepcopy(request))
            if len(json.dumps(reply, ensure_ascii=False).encode()) > self.max_bytes:
                raise ValueError('response_evidence_size_exhausted')
            if not isinstance(reply, dict) or require_completion and (
                not isinstance(reply.get('response_id'), str) or not reply['response_id']
                or not isinstance(reply.get('model'), str) or not reply['model']):
                raise ValueError('missing_completion_identity')
            record.update(status='completed', response_id=reply.get('response_id'), model=reply.get('model'), usage=reply.get('usage'))
            return reply
        except BaseException as error:
            record.update(status='failed', error_class=type(error).__name__)
            raise
        finally:
            self.on_change()

    def receipt(self):
        return dict(max_dispatches=self.maximum, dispatched=len(self.calls), calls=self.calls,
                    max_elapsed_seconds=self.seconds, per_call_seconds=self.timeout,
                    provider_internal_attempts=None, monetary_cost=None)


def quality(reply, evidence):
    statuses = {'pass', 'partial', 'fail', 'unavailable', 'not_applicable'}
    required = {'status', 'citations', 'rationale', 'critical_violations', 'response_id', 'model'}
    if not required <= reply.keys() or reply['status'] not in statuses:
        raise ValueError('malformed_judgment')
    citations, critical = reply['citations'], reply['critical_violations']
    if (not isinstance(citations, list) or not isinstance(critical, list)
        or not all(isinstance(c, str) and c for c in critical)
        or not isinstance(reply['rationale'], str) or not reply['rationale'].strip()
        or len(reply['rationale']) > 1000 or any(c not in evidence for c in citations)
        or reply['status'] in {'pass', 'partial', 'fail'} and not citations):
        raise ValueError('invalid_judge_citations')
    return dict(status='fail' if critical else reply['status'], citations=citations,
                rationale=reply['rationale'], critical_violations=critical, calibration='advisory')


def unavailable(reason):
    return dict(status='unavailable', reason=reason)


def hosted_contract(item, output, binding, application_receipt):
    """Caller must load the independent host receipt, never from model output."""
    if not application_receipt or not binding:
        return unavailable('independent_application_receipt_required')
    matches = [r for r in application_receipt.get('results', []) if r['case_id'] == item['id']]
    if len(matches) != 1: return unavailable('receipt_item_mismatch')
    expected = matches[0]
    if (expected.get('binding') != binding or binding.get('run_id') != application_receipt['run_id']
        or not application_receipt.get('source_revision') or not application_receipt.get('source_content_sha256')
        or binding.get('source_revision') != application_receipt['source_revision']
        or binding.get('source_content_sha256') != application_receipt['source_content_sha256']
        or binding.get('item_id') != item['id'] or binding.get('dataset') != item['dataset']
        or binding.get('item_sha256') != item['content_sha256'] or binding.get('output_sha256') != digest(output)
        or binding.get('input_sha256') != digest(item['task'])
        or binding.get('dataset_snapshot') != item['dataset_snapshot']):
        return unavailable('receipt_binding_mismatch')
    return deepcopy(expected['contract'])


def report(receipt):
    lines = ['# Memoir skill evaluation (offline)', '',
        'Scope: ' + receipt['scope'] + '. Quality scores are advisory; human calibration is pending.', '',
        '| Skill | Planned | Contract pass | Completed | Positive delivery | Quality pass | Unavailable |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for skill, counts in receipt['coverage'].items():
        lines.append('| ' + skill + ' | ' + ' | '.join(str(counts[k]) for k in
            ('planned', 'contract_pass', 'completed', 'positive_delivery', 'quality_pass', 'unavailable')) + ' |')
    lines += ['', '| Item | Execution | Contract | Delivery | Quality | Reason |', '| --- | --- | --- | --- | --- | --- |']
    for row in receipt['results']:
        lines.append('| ' + ' | '.join((row['case_id'], row['execution'], row['contract']['status'],
            str(row['positive_delivery']), row['quality']['status'], row.get('reason', ''))) + ' |')
    for dependency in receipt.get('upstream_dependencies', []):
        lines += ['', 'Upstream dependency ' + dependency['id'] + ' (' + dependency['status'] + '): ' + dependency['behavior']]
    lines += ['', 'Remaining gates: merged-main prompt publication; installed Langfuse evaluator/rule interface verification;',
        'disabled synthetic-only rules and hosted score readbacks; live provider delivery; full-scenario persisted-state/browser witnesses;',
        'human-reviewed calibration development labels and separate held-out labels. Family canonical execution is unwired.',
        'PR88 and PR94 are integrated prerequisites. This report does not establish full issue acceptance.', '']
    return '\n'.join(lines)


async def run(planned, directory, *, skill=None, history_provider=None, photo_provider=None, composer_provider=None, application=None, sdk_judge=None, managed_judge=None,
              max_skill_calls=160, max_judge_calls=160, seconds=1800, timeout=120,
              max_evidence_bytes=256000, clock=time.monotonic):
    if sdk_judge is not None and managed_judge is not None: raise ValueError('judge_executors_must_be_exclusive')
    if not 1 <= max_evidence_bytes <= 2 * 1024 * 1024: raise ValueError('invalid_evidence_limit')
    skill_budget, judge_budget = (Budget(n, seconds, timeout, clock, max_bytes=max_evidence_bytes)
                                 for n in (max_skill_calls, max_judge_calls))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (directory / 'receipt.json').exists(): raise ValueError('existing_run_must_be_preserved')
    judge = sdk_judge if sdk_judge is not None else managed_judge
    receipt = dict(schema_version=planned['schema_version'], run_id=str(uuid4()), status='running',
        upstream_dependencies=deepcopy(planned.get('upstream_dependencies', [])),
        scope='controlled_offline', dataset_snapshot=planned['dataset_snapshot'],
        source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        source_content_sha256=digest({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__), ROOT / 'scripts/memoir_skill_scenarios.py', ROOT / 'scripts/memoir_live_skill_cases.py',
                ROOT / 'scripts/memoir_skill_eval_assets.py', ROOT / 'scripts/memoir_skill_eval_workflows.py',
                ROOT / 'scripts/run_memoir_skill_evaluation.py', ROOT / 'scripts/prompt_registry.py',
                ROOT / 'scripts/publish_langfuse_prompts.py', ROOT / 'scripts/memoir_skill_eval_application.py',
                ROOT / 'scripts/memoir_skill_eval_browser.py', ROOT / 'tests/test_conversation_attribution.py',
                ROOT / 'tests/test_story_game_runtime_postgres.py', ROOT / 'tests/controlled_policy.py']}),
        prompt_inventory=planned['inventory'], evaluator_definitions=planned['evaluators'],
        judge_executor='sdk' if sdk_judge else 'managed' if managed_judge else 'none',
        human_calibration=planned['human_calibration'], results=[], coverage={}, budgets={})
    for item in planned['items']:
        receipt['results'].append(dict(case_id=item['id'], skill=item['skill'], phase=item['phase'], locale=item['locale'],
            execution='not_run', positive_case=item['positive_case'], positive_delivery=False,
            canonical_delivery=False,
            evidence_mode='controlled_offline', live_delivery=False,
            contract=unavailable('not_run'), quality=unavailable('not_run'), reason='not_run'))

    def persist():
        receipt['budgets'] = dict(skill=skill_budget.receipt(), judge=judge_budget.receipt())
        for name in planned['selected_skills']:
            rows = [r for r in receipt['results'] if r['skill'] == name]
            receipt['coverage'][name] = dict(planned=len(rows), completed=sum(r['execution'] == 'completed' for r in rows),
                unavailable=sum(r['execution'] != 'completed' for r in rows),
                contract_pass=sum(r['contract']['status'] == 'pass' for r in rows),
                positive_delivery=sum(r['positive_delivery'] for r in rows),
                quality_pass=sum(r['quality']['status'] == 'pass' for r in rows))
            receipt['coverage'][name]['canonical_delivery'] = sum(r.get('canonical_delivery') is True for r in rows)
            receipt['coverage'][name]['browser_observed'] = sum(bool((r.get('witnesses') or {}).get('browser_observed')) for r in rows)
        save(directory / 'receipt.json', receipt)
    skill_budget.on_change = judge_budget.on_change = persist
    persist()
    for item, row in zip(planned['items'], receipt['results'], strict=True):
        try:
            if len(json.dumps(item, ensure_ascii=False).encode()) > max_evidence_bytes:
                raise LookupError('evidence_size_exhausted')
            output, completion, witnesses = None, None, None
            application_context, application_dispatches, verified = None, None, None
            if item['skill'] == 'memoir-place-groups':
                if clock() >= skill_budget.deadline: raise LookupError('skill_deadline_exhausted')
                from apps.api.place_groups import resolve_place_groups
                output = resolve_place_groups(deepcopy(item['task']['places']), allow_provider=False)
            elif application is not None and application.supports(item):
                # Admission belongs to this runner, including for injected adapters.
                if len(skill_budget.calls) >= skill_budget.maximum: raise LookupError('skill_budget_exhausted')
                if clock() >= skill_budget.deadline: raise LookupError('skill_deadline_exhausted')
                application_context = dict(run_id=receipt['run_id'], source_revision=receipt['source_revision'],
                    source_content_sha256=receipt['source_content_sha256'], invocation_id=str(uuid4()))
                row['application_context'] = deepcopy(application_context)
                dispatch_start = len(skill_budget.calls)
                output, witnesses = await application.execute(item, skill_budget, directory,
                    deepcopy(application_context))
                application_dispatches = deepcopy(skill_budget.calls[dispatch_start:])
                if len(skill_budget.calls) > skill_budget.maximum: raise ValueError('application_dispatch_overrun')
                if clock() >= skill_budget.deadline: raise LookupError('skill_deadline_exhausted')
                if not isinstance(witnesses, dict) or witnesses.get('kind') != 'controlled_application':
                    raise LookupError('independent_application_receipt_required')
            elif item['skill'] == 'memoir-historical-news-research' and history_provider is not None:
                from scripts.memoir_skill_eval_workflows import history
                output, witnesses = await history(item, history_provider, skill_budget)
            elif item['skill'] == 'memoir-place-photo-research' and photo_provider is not None:
                from scripts.memoir_skill_eval_workflows import photo
                output, witnesses = await photo(item, photo_provider, skill_budget, max_evidence_bytes)
            elif item['skill'] == 'memoir-composer' and composer_provider is not None:
                from scripts.memoir_skill_eval_workflows import composer
                output, witnesses = await composer(item, composer_provider, skill_budget)
            elif skill is None:
                raise LookupError('unwired' if planned['inventory'][item['skill']]['status'] == 'unwired' else 'skill_adapter_unavailable')
            elif item['skill'] in {'memoir-place-photo-research', 'memoir-historical-news-research', 'memoir-composer'}:
                # These require application orchestration/source witnesses, not a generic prompt quiz.
                raise LookupError('application_workflow_adapter_required')
            elif item['skill'] == 'memoir-story-game':
                raise LookupError('game_authority_and_phase_witness_adapter_required')
            else:
                request = packet(item)
                if len(json.dumps(request, ensure_ascii=False).encode()) > max_evidence_bytes:
                    raise LookupError('evidence_size_exhausted')
                try:
                    completion = await skill_budget.dispatch(skill, request)
                except RuntimeError as error:
                    if str(error) == 'budget_exhausted': raise LookupError('skill_budget_exhausted') from None
                    raise
                output = completion['output']
            if len(json.dumps(output, ensure_ascii=False).encode()) > max_evidence_bytes:
                raise LookupError('output_size_exhausted')
            row.update(execution='completed', output=output, completion=completion, reason='')
            try:
                if witnesses is not None:
                    verified = validate_workflow(item, output, witnesses, directory,
                        application_context=application_context, application_dispatches=application_dispatches)
                else:
                    validate(item, output)
                row['contract'] = dict(status='pass', evidence=['output', 'task'])
            except LookupError as error:
                row['contract'] = unavailable(str(error))
                row['reason'] = str(error)
            except Exception as error:
                row['contract'] = dict(status='fail', reason=type(error).__name__)
            row['production_status'] = planned['inventory'][item['skill']]['status']
            row['canonical_delivery'] = False
            if witnesses and witnesses.get('kind') == 'controlled_application' and row['contract']['status'] == 'pass':
                row['canonical_delivery'] = verified['canonical_delivery']
                row['evidence_mode'] = 'controlled_disposable_application'
            row['witnesses'] = witnesses
            row['binding'] = dict(run_id=receipt['run_id'], item_id=item['id'], item_sha256=item['content_sha256'],
                input_sha256=digest(item['task']), output_sha256=digest(output), dataset=item['dataset'],
                dataset_snapshot=item['dataset_snapshot'], source_revision=receipt['source_revision'],
                source_content_sha256=receipt['source_content_sha256'],
                packet_sha256=skill_budget.calls[-1]['request_sha256'] if completion else None,
                request_sha256s=[c['request_sha256'] for c in skill_budget.calls if c['item_id'] == item['id']],
                witnesses_sha256=digest(witnesses))
            if application_context:
                row['binding'].update(application_invocation_id=application_context['invocation_id'],
                    application_dispatches_sha256=digest(application_dispatches))
            row['positive_delivery'] = item['positive_case'] and row['contract']['status'] == 'pass'
            persist()  # Independent application receipt exists before any judge or hosted score.
            evidence = dict(output=output, task=item['task'], binding=row['binding'])
            if witnesses is not None: evidence['witnesses'] = witnesses
            if judge is None:
                row['quality'] = unavailable('judge_adapter_unavailable')
            elif row['contract']['status'] == 'unavailable':
                row['quality'] = unavailable('required_application_witness_missing')
            else:
                definition = judge_definition(item['skill'])
                judge_packet = dict(item_id=item['id'], evidence=evidence, gold=item['gold'],
                    instructions=definition['compiled_text'], evaluator_sha256=definition['compiled_sha256'], publication=definition['publication'])
                if len(json.dumps(judge_packet, ensure_ascii=False).encode()) > max_evidence_bytes:
                    row['quality'] = unavailable('judge_evidence_size_exhausted')
                else:
                    try:
                        reply = await judge_budget.dispatch(judge, judge_packet)
                        evaluated_models = {c['model'] for c in skill_budget.calls if c['item_id'] == item['id'] and c['model']}
                        if reply['model'] in evaluated_models: raise ValueError('judge_not_independent')
                        row['quality'] = quality(reply, evidence)
                        row['quality'].update(evaluator_sha256=definition['compiled_sha256'],
                            components=definition['components'], completion={k: reply.get(k) for k in ('response_id', 'model', 'usage')})
                    except RuntimeError as error:
                        row['quality'] = unavailable('judge_budget_exhausted' if str(error) == 'budget_exhausted' else 'judge_failed')
                    except Exception as error:
                        row['quality'] = unavailable('invalid_or_failed_judgment_' + type(error).__name__)
        except LookupError as error:
            row.update(execution='unavailable', positive_delivery=False, canonical_delivery=False,
                reason=str(error), contract=unavailable(str(error)), quality=unavailable('execution_unavailable'))
        except Exception as error:
            row.update(execution='unavailable', positive_delivery=False, canonical_delivery=False, reason='skill_dispatch_' + type(error).__name__,
                contract=unavailable('execution_unavailable'), quality=unavailable('execution_unavailable'))
        except BaseException:
            receipt['status'] = 'incomplete'
            persist()
            (directory / 'report.md').write_text(report(receipt))
            raise
        persist()
    failed = any(r['contract']['status'] == 'fail' or r['quality']['status'] == 'fail' for r in receipt['results'])
    complete = bool(receipt['results']) and all(r['contract']['status'] == 'pass' and
        r['quality']['status'] in {'pass', 'not_applicable'} for r in receipt['results'])
    receipt['status'] = 'failed' if failed else 'passed' if complete else 'incomplete'
    persist()
    (directory / 'report.md').write_text(report(receipt))
    return receipt


def main(argv=None, *, services=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Execute available offline code; unavailable adapters stay visible')
    parser.add_argument('--skill', action='append', choices=sorted(KNOWN))
    parser.add_argument('--phase', action='append', choices=PHASES)
    parser.add_argument('--locale', action='append', choices=('en-AU', 'zh-CN'))
    parser.add_argument('--case', action='append')
    parser.add_argument('--output-root', type=Path, default=ROOT / 'var/skill-evaluation' / str(uuid4()))
    parser.add_argument('--max-skill-calls', type=int, default=160)
    parser.add_argument('--max-judge-calls', type=int, default=160)
    parser.add_argument('--seconds', type=float, default=1800)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--controlled-application', action='store_true', help='Use isolated synthetic application/SQL fixtures')
    parser.add_argument('--browser-url', help='Task-owned frontend for controlled game play witnesses')
    parser.add_argument('--browser-executable', default='/usr/bin/chromium')
    args = parser.parse_args(argv)
    try:
        planned = plan(skill=args.skill, phase=args.phase, locale=args.locale, case=args.case)
        Budget(args.max_skill_calls, args.seconds, args.timeout, time.monotonic)
        Budget(args.max_judge_calls, args.seconds, args.timeout, time.monotonic)
    except ValueError as error:
        parser.error(str(error))
    if not args.execute:
        print(json.dumps(planned, ensure_ascii=False, indent=2))
        return 0
    services = dict(services or {})
    if args.controlled_application:
        from scripts.memoir_skill_eval_application import ControlledApplication
        services['application'] = ControlledApplication(browser_url=args.browser_url, browser_executable=args.browser_executable)
    result = asyncio.run(run(planned, args.output_root, **services, max_skill_calls=args.max_skill_calls,
        max_judge_calls=args.max_judge_calls, seconds=args.seconds, timeout=args.timeout))
    print(json.dumps(dict(status=result['status'], receipt=str(args.output_root / 'receipt.json'))))
    return 0 if result['status'] == 'passed' else 1
