"""Additive issue53 sequence planning/result ingestion over PR92's evaluator.

No provider, hosted client, database or generation is allocated by this module.
Imported judgments remain advisory. This diagnostic cannot authorize a release.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import time
from uuid import uuid4

from scripts import memoir_skill_eval_suite as suite
from scripts.memoir_skill_eval_application import verify_witness

ROOT = Path(__file__).resolve().parents[1]
PR92_COMMIT = '0fe69a5b66fc2b17da35398b1f79e192febc188c'
MANIFEST = ROOT / 'tests/evaluation/response_sequences.json'
MILESTONES = ('first_meaningful_text_s', 'validated_question_s', 'reply_complete_s', 'durable_save_s')
CORE = ('scripts/memoir_skill_eval_suite.py', 'scripts/memoir_skill_eval_assets.py',
        'scripts/memoir_skill_eval_application.py', 'scripts/memoir_skill_scenarios.py')
MERGED_BASE = 'bb31f44ac8cb1c31baad8db418157b96dbe0eee0'
CONTRACTS = ('public_validation', 'source_fidelity', 'language_provenance', 'ownership',
             'idempotency', 'durable_save', 'continuity')
PROVIDER_FIELDS = ('model', 'requested_effort', 'effective_effort', 'policy_receipt_sha256',
                   'usage', 'internal_attempts', 'app_retries', 'provider_retries', 'load_observation')
digest = suite.digest


def load_manifest(path=MANIFEST):
    value = json.loads(Path(path).read_text())
    if value.get('schema_version') != 'memoir-response-sequences/1' or value.get('synthetic') is not True:
        raise ValueError('synthetic_sequence_manifest_required')
    seen = set()
    for scenario in value['scenarios']:
        if scenario['id'] in seen or scenario['locale'] not in {'en-AU', 'zh-CN'}:
            raise ValueError('invalid_scenario_identity')
        seen.add(scenario['id'])
        prior, reopened, steps = [], False, set()
        for step in scenario['steps']:
            if step['id'] in steps: raise ValueError('duplicate_step')
            steps.add(step['id'])
            if step['action'] == 'reopen':
                if len(prior) < 2: raise ValueError('resume_requires_persisted_prior_turns')
                reopened = True
            elif step['action'] == 'turn':
                if step['phase'] != ('first' if not prior else 'resumed' if reopened else 'later'):
                    raise ValueError('phase_requires_genuine_sequence')
                if not step['text'].strip(): raise ValueError('empty_testimony')
                prior.append(step['id']); reopened = False
            elif step['action'] == 'replay':
                if step['target'] not in prior: raise ValueError('replay_requires_saved_turn')
            elif step['action'] != 'rollback': raise ValueError('unknown_sequence_action')
    return value


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def provenance(manifest):
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=ROOT, text=True).splitlines()
    groups = {
        'application': [p for p in tracked if p.startswith(('apps/api/', 'packages/', 'supabase/'))],
        'prompts': [p for p in tracked if p.startswith(('apps/api/prompts/', 'skills/'))
                    and p.endswith(('.md', '.json'))],
        'configuration_sources': ['compose.yml', '.env.example', 'apps/api/collector_configuration.py'],
        'evaluator': list(CORE) + ['tests/evaluation/prompts/skill-judges/policy.md',
                                  'tests/evaluation/prompts/skill-judges/memoir-interviewer.md'],
        'profiler': ['scripts/profile_first_reply.py', 'scripts/issue53_profile_sequences.py',
                     'scripts/issue53_sequence_application.py'],
    }
    frozen = {}
    for group, paths in groups.items():
        frozen[group] = {p: _file_hash(ROOT / p) for p in sorted(paths) if (ROOT / p).is_file()}
    for path in CORE:
        pinned = subprocess.check_output(['git', 'show', PR92_COMMIT + ':' + path], cwd=ROOT)
        if hashlib.sha256(pinned).hexdigest() != frozen['evaluator'][path]:
            raise ValueError('pr92_core_changed_requires_dependency_review')
    frozen['dataset'] = digest(dict(manifest=manifest,
        phase_rubrics=json.loads((ROOT / 'tests/evaluation/conversation_phase_cases.json').read_text())))
    frozen['source_revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    return frozen


def plan(*, samples=1, scenario=None, variants=None, max_skill_calls=0, max_judge_calls=0, seconds=600, timeout=120):
    if type(samples) is not int or not 1 <= samples <= 20: raise ValueError('invalid_sample_count')
    for n in (max_skill_calls, max_judge_calls): suite.Budget(n, seconds, timeout, time.monotonic)
    manifest = load_manifest()
    selected = [s for s in manifest['scenarios'] if not scenario or s['id'] in scenario]
    if not selected or scenario and set(scenario) != {s['id'] for s in selected}: raise ValueError('unknown_or_empty_scenario')
    # Unknown effective settings stay unknown. Never read inherited credentials/configuration.
    default = dict(model=None, requested_effort=None, effective_effort=None, policy_receipt_sha256=None)
    variants = deepcopy(variants or {arm: default for arm in ('baseline', 'candidate')})
    if set(variants) != {'baseline', 'candidate'} or any(set(v) != set(default) for v in variants.values()):
        raise ValueError('allowlisted_variant_descriptors_required')
    templates = {locale: suite.plan(case=[f'memoir-interviewer/grounded-question/{locale}'])['items'][0]
                 for locale in ('en-AU', 'zh-CN')}
    frozen = provenance(manifest)
    run_id, rows = str(uuid4()), []
    snapshot = datetime.now(timezone.utc).isoformat()
    for case in selected:
        for sample in range(samples):
            invocation = {arm: str(uuid4()) for arm in variants}
            for step in case['steps']:
                if step['action'] not in {'turn', 'replay'}: continue
                original = step if step['action'] == 'turn' else next(s for s in case['steps'] if s['id'] == step['target'])
                pair_id = f"{case['id']}/{step['id']}/{sample}"
                for arm in variants:
                    item = deepcopy(templates[case['locale']])
                    item.update(id=pair_id, case=case['family'], dataset_snapshot=snapshot)
                    source = item['task']['source']
                    source.update(id='synthetic-' + digest(pair_id)[:20], text=original['text'],
                                  char_end=len(original['text']), original_length=len(original['text']))
                    item['task']['instruction'] = original['text']
                    item['task']['context']['source'] = source
                    item['task']['context']['sources'] = [source]
                    item['task']['context']['opening_turn'] = original['phase'] == 'first'
                    item['task']['context']['interview_language'] = original['reply_language']
                    source['language'] = original['reply_language']
                    stopped = any('/pause/' in ref for ref in original['rubric_refs'])
                    item['gold']['facts'] = dict(stopped=stopped, question=not stopped,
                        selection_reason='pause' if stopped else None)
                    item['gold']['required'] = [original['requirement']]
                    item['content_sha256'] = digest({k:v for k,v in item.items() if k != 'content_sha256'})
                    rows.append(dict(row_id=pair_id + '/' + arm, pair_id=pair_id, scenario_id=case['id'],
                        step_id=step['id'], arm=arm, sample=sample, locale=case['locale'], phase=step['phase'],
                        action=step['action'], invocation_id=invocation[arm], item=item,
                        input_sha256=digest(original['text']), expected_work=original['work']))
    value = dict(schema_version='memoir-response-profile-plan/1', run_id=run_id, scenarios=selected,
        rows=rows, variants=variants, provenance=frozen, dispatches=0,
        judge_definition=suite.judge_definition('memoir-interviewer'),
        dependency=dict(pr=92, commit=PR92_COMMIT, merged_base=MERGED_BASE, status='merged_framework_acceptance_limits_remain'),
        budgets=dict(max_skill_calls=max_skill_calls, max_judge_calls=max_judge_calls,
                     seconds=seconds, timeout=timeout, live_dispatches=0),
        human_acceptance='pending_bilingual_heldout', semantic_acceptance='not_established')
    value['plan_sha256'] = digest(value)
    return value


def check_plan(planned):
    if planned.get('plan_sha256') != digest({k:v for k,v in planned.items() if k != 'plan_sha256'}):
        raise ValueError('plan_changed')


def context(planned, row):
    return dict(run_id=planned['run_id'], source_revision=planned['provenance']['source_revision'],
        source_content_sha256=digest(planned['provenance']), invocation_id=row['invocation_id'])


def _index(values, planned):
    wanted = {r['row_id'] for r in planned['rows']}
    if any(r.get('row_id') not in wanted for r in values) or len({r['row_id'] for r in values}) != len(values):
        raise ValueError('duplicate_or_unplanned_result')
    return {r['row_id']:r for r in values}


def _sequence(planned, row, capture, prior_capture):
    case = next(s for s in planned['scenarios'] if s['id'] == row['scenario_id'])
    steps = case['steps'][:next(i for i,s in enumerate(case['steps']) if s['id'] == row['step_id'])+1]
    expected = [s['text'] for s in steps if s['action'] == 'turn']
    sources = capture['after']['sources']
    if ([s['text'] for s in sources] != expected or len({s['id'] for s in sources}) != len(sources)
        or any(s['version'] != 1 or s['user_id'] != capture['owner_id'] or s['project_id'] != capture['project_id'] for s in sources)):
        raise ValueError('lost_or_foreign_testimony')
    before = capture['before']
    if prior_capture is not None and before != prior_capture['after']:
        raise ValueError('persisted_sequence_chain_missing')
    if prior_capture is None and (before['sources'] or before['replies']):
        raise ValueError('first_turn_prestate_not_empty')
    if row['phase'] == 'resumed':
        resume = capture.get('resume') or {}
        if (resume.get('before_close') != before or resume.get('after_reopen') != before
            or not resume.get('new_runtime') or not before['session'] or len(before['replies']) < 2):
            raise ValueError('persisted_resume_witness_missing')
    if row['action'] == 'replay':
        if capture['dispatches'] or before != capture['after'] or not capture['output'].get('cached'):
            raise ValueError('saved_replay_regenerated_or_changed')
        saved = [r for r in before['replies'] if r['source_id'] == capture['output']['canonical_result']['accepted_source_id']]
        if len(saved) != 1 or saved[0]['reply'] != capture['output']['canonical_result']['reply']:
            raise ValueError('saved_replay_reply_changed')
    else:
        if sources[:-1] != before['sources'] or capture['after']['replies'][:-1] != before['replies']:
            raise ValueError('prior_state_changed')
        if len(capture['after']['replies']) != len(sources): raise ValueError('durable_reply_missing')
        packets = capture.get('packet_readbacks') or []
        if not packets or packets[-1]['current']['narrator']['original'] != expected[-1]:
            raise ValueError('current_testimony_packet_missing')
        tail = packets[-1]['tail']
        if ([t['narrator']['original'] for t in tail] != [s['text'] for s in before['sources']]
            or [t.get('assistant', {}).get('text') for t in tail] != [r['reply'] for r in before['replies']]):
            raise ValueError('prior_exchange_packet_missing')
        current_step = steps[-1]
        if sources[-1]['language'] != current_step['reply_language']:
            raise ValueError('language_provenance_mismatch')
        if (capture['after']['replies'][-1]['source_id'] != sources[-1]['id']
            or capture['after']['replies'][-1]['reply'] != capture['output']['canonical_result']['reply']):
            raise ValueError('durable_reply_readback_mismatch')
    rollback = next((s for s in steps if s['action'] == 'rollback'), None)
    if rollback and capture.get('future_configuration') != planned['variants']['baseline']:
        raise ValueError('future_rollback_configuration_witness_missing')


def verify_capture(planned, row, result, capture, directory, prior_capture=None, *, expected_dispatches):
    path = Path(directory) / capture['sequence_receipt_path']
    if path.is_symlink() or not path.resolve().is_relative_to(Path(directory).resolve()):
        raise ValueError('sequence_receipt_location')
    independent = json.loads(path.read_text())
    body = {k:v for k,v in capture.items() if k not in {'sequence_receipt_path','sequence_receipt_sha256'}}
    if independent != body or digest(independent) != capture['sequence_receipt_sha256']:
        raise ValueError('sequence_readback_changed')
    if capture.get('context') != context(planned, row): raise ValueError('current_run_context_required')
    if capture.get('plan_sha256') != planned['plan_sha256'] or capture.get('row_id') != row['row_id']:
        raise ValueError('current_plan_row_required')
    if capture['output'] != result.get('output'): raise ValueError('output_readback_mismatch')
    if capture['dispatches'] != expected_dispatches:
        raise ValueError('independent_runner_dispatch_ledger_mismatch')
    if capture.get('configuration') != planned['variants'][row['arm']]: raise ValueError('configuration_mismatch')
    if set(capture.get('contracts', {})) != set(CONTRACTS) or any(v != 'pass' for v in capture['contracts'].values()):
        raise ValueError('required_deterministic_contract_missing')
    _sequence(planned, row, capture, prior_capture)
    if row['action'] != 'replay':
        # PR92 owns current-run/dispatch/source/receipt validation. Do not reproduce it.
        verify_witness(row['item'], result['output'], capture['witness'], directory,
                       expected_context=context(planned, row), dispatches=expected_dispatches)
    if digest(capture.get('stream_observation')) != result.get('stream_observation_sha256'):
        raise ValueError('stream_observation_mismatch')
    if result.get('timings') != capture['stream_observation'].get('timings'):
        raise ValueError('timing_readback_mismatch')
    observation = capture['stream_observation']
    events = observation['events']
    elapsed = [e['elapsed_s'] for e in events]
    if (any(type(t) not in (int,float) or not math.isfinite(t) or t < 0 for t in elapsed)
        or elapsed != sorted(elapsed)):
        raise ValueError('invalid_stream_clock')
    from scripts.issue53_sequence_application import StreamObservation
    clock = iter([0, *elapsed])
    replay = StreamObservation(observation['meaningful_excerpt'], clock=lambda:next(clock))
    for event in events: replay.observe({k:v for k,v in event.items() if k != 'elapsed_s'})
    if (replay.timings != observation['timings'] or replay.public != observation['public_text']
        or row['action'] != 'replay' and replay.timings['durable_save_s'] is None):
        raise ValueError('public_milestone_evidence_missing')
    return dict(status='pass', scope='controlled_sequence_contracts', semantic_quality='separate')


def blind_side(planned, row):
    flipped = int(digest([planned['run_id'], row['pair_id']])[-1], 16) % 2
    return ('A' if row['arm'] == 'baseline' else 'B') if not flipped else ('B' if row['arm'] == 'baseline' else 'A')


def blind_packets(planned, results, journal=None):
    """Existing PR92 judge packets, with arm/configuration/timing labels removed."""
    check_plan(planned); index = _index(results, planned)
    pairs = {}
    definition = planned['judge_definition']
    for row in planned['rows']:
        if row['row_id'] not in index: continue
        value = index[row['row_id']]
        if value.get('execution') != 'completed' or 'output' not in value: continue
        side = blind_side(planned, row)
        task = deepcopy(row['item']['task'])
        scenario = next(s for s in planned['scenarios'] if s['id'] == row['scenario_id'])
        task['sequence_requirements'] = scenario['steps'][:next(i for i,s in enumerate(scenario['steps']) if s['id'] == row['step_id'])+1]
        binding = dict(output_sha256=digest(value['output']), task_sha256=digest(task))
        evidence = dict(output=value['output'], task=task, binding=binding)
        capture = (journal or {}).get('rows', {}).get(row['row_id'])
        if capture:
            evidence['witnesses'] = {k:deepcopy(capture[k]) for k in ('before','after','packet_readbacks')}
        packet = dict(item_id=digest(row['pair_id']), evidence=dict(output=value['output'], task=task, binding=binding),
            gold=row['item']['gold'], instructions=definition['compiled_text'],
            evaluator_sha256=definition['compiled_sha256'], publication=definition['publication'])
        packet['evidence'] = evidence
        pairs.setdefault(row['pair_id'], {})[side] = packet
    for pair in pairs.values():
        pair['human_preference_contract'] = dict(kind='separate_blinded_human_annotation_not_model_prompt',
            required_fields=['status','citations','rationale','critical_violations','response_id','model','preferred_side','reviewer_kind'],
            preferred_side=['A','B','tie'], citations=['A.output','B.output','task'],
            rationale='Cite concrete supplied facts and public output evidence. Missing evidence requires unavailable.',
            provenance='Independent reviewer identity and host-issued review receipt; human heldout acceptance remains separate.')
        pair['packet_sha256'] = digest(pair)
    return pairs


def _latency(rows):
    pairs = {}
    for row in rows: pairs.setdefault(row['pair_id'], []).append(row)
    complete = [p for p in pairs.values() if len(p) == 2 and all(r['execution'] == 'completed'
        and r['contracts']['status'] == 'pass' for r in p)]
    result = dict(planned_pairs=len(pairs), matched_complete_pairs=len(complete),
                  outcomes={s:sum(r['execution'] == s for r in rows) for s in ('completed','failed','timed_out','unavailable')})
    result['milestones'] = {}
    for key in MILESTONES:
        values = {arm:[r['timings'].get(key) for pair in complete for r in pair if r['arm'] == arm] for arm in ('baseline','candidate')}
        valid = {arm:[v for v in group if type(v) in (int,float) and math.isfinite(v) and v >= 0] for arm,group in values.items()}
        result['milestones'][key] = {arm:dict(observed=len(v), unknown=len(values[arm])-len(v),
            median_s=statistics.median(v) if v else None, samples_s=v, p95_s=None) for arm,v in valid.items()}
    result['paired_deltas'] = []
    for pair in complete:
        arms = {r['arm']:r for r in pair}
        deltas = {}
        for key in MILESTONES:
            b, c = (arms[a]['timings'].get(key) for a in ('baseline','candidate'))
            deltas[key] = c-b if all(type(v) in (int,float) and math.isfinite(v) and v >= 0 for v in (b,c)) else None
        result['paired_deltas'].append(dict(pair_id=pair[0]['pair_id'], candidate_minus_baseline_s=deltas))
    return result


def compare(planned, results, journal, reviews, *, directory):
    check_plan(planned); index = _index(results, planned)
    if journal and (journal.get('run_id') != planned['run_id'] or journal.get('plan_sha256') != planned['plan_sha256']):
        raise ValueError('current_run_journal_required')
    captures = journal.get('rows', {})
    if set(captures) - {r['row_id'] for r in planned['rows']}: raise ValueError('unplanned_capture')
    calls = journal.get('budget', {}).get('calls', [])
    planned_rows = {r['row_id']:r for r in planned['rows']}
    if journal and (journal.get('budget', {}).get('dispatched') != len(calls)
        or len(calls) > planned['budgets']['max_skill_calls']):
        raise ValueError('independent_runner_budget_required')
    identities = [c.get('dispatch_id') for c in calls]
    responses = [c.get('response_id') for c in calls if c.get('response_id')]
    if (any(not identity for identity in identities) or len(set(identities)) != len(identities)
        or len(responses) != len(set(responses))):
        raise ValueError('duplicate_or_missing_dispatch_identity')
    for call in calls:
        row = planned_rows.get(call.get('row_id'))
        if (row is None or row['action'] == 'replay' or call.get('item_id') != row['item']['id']
            or any(call.get(k) != v for k,v in context(planned,row).items())
            or not call.get('request_sha256') or call.get('status') not in {'completed','failed'}):
            raise ValueError('unplanned_or_stale_runner_dispatch')
    packets = blind_packets(planned, results, journal)
    rows, previous = [], {}
    for row in planned['rows']:
        value = deepcopy(index.get(row['row_id'], {}))
        status = value.get('execution', 'unavailable')
        if status not in {'completed','failed','timed_out','unavailable'}: raise ValueError('invalid_execution_status')
        item = {k:row[k] for k in ('row_id','pair_id','arm','locale','phase','scenario_id','sample')}
        item.update(execution=status, timings=value.get('timings', {}),
            reason=value.get('reason', 'not_run'),
            # This offline adapter has no provider-policy/usage attestor. Raw
            # imported metrics cannot become verified observations by proximity
            # to an otherwise valid source/save receipt.
            provider_metrics={key:None for key in PROVIDER_FIELDS},
            imported_provider_metrics=dict(source='unverified_import', values=deepcopy(value.get('provider_metrics', {}))),
            contracts=suite.unavailable('independent_current_run_evidence_required'),
            semantic=suite.unavailable('blind_comparison_required'), evidence_mode=value.get('evidence_mode', 'unknown'))
        sequence_key = (row['scenario_id'], row['sample'], row['arm'])
        capture = captures.get(row['row_id'])
        if capture and status == 'completed':
            try:
                seed = journal.get('seeds', {}).get(digest([row['scenario_id'],row['sample']]))
                if (not seed or digest(seed['canonical_state']) != seed['baseline_sha256']
                    or seed['baseline_sha256'] != seed['candidate_sha256']
                    or capture.get('matched_seed_sha256') != seed['baseline_sha256']
                    or capture.get('pre_state_sha256') != digest(capture['before'])):
                    raise ValueError('matched_seed_or_prestate_mismatch')
                item['contracts'] = verify_capture(planned, row, value, capture, directory, previous.get(sequence_key),
                    expected_dispatches=[c for c in calls if c['row_id'] == row['row_id']])
                item.update(matched_seed_sha256=capture['matched_seed_sha256'], pre_state_sha256=capture['pre_state_sha256'])
                item['runner_observations'] = dict(source='verified_controlled_runner_ledger',
                    calls=[{k:c.get(k) for k in ('model','usage','live_model_dispatch','status')}
                           for c in calls if c['row_id'] == row['row_id']])
                previous[sequence_key] = capture
            except (ValueError, KeyError, TypeError, OSError) as error:
                item['contracts'] = dict(status='fail', reason=str(error) if isinstance(error, ValueError) else type(error).__name__)
        review = reviews.get(row['pair_id'])
        if review and row['pair_id'] in packets and item['contracts']['status'] == 'pass':
            pair = packets[row['pair_id']]
            try:
                if set(pair) != {'A','B','packet_sha256','human_preference_contract'} or review['packet_sha256'] != pair['packet_sha256']:
                    raise ValueError('blind_packet_binding_mismatch')
                side = blind_side(planned, row)
                judged = review[side]
                pair_rows = [r for r in planned['rows'] if r['pair_id'] == row['pair_id']]
                evaluated_models = {c.get('model') for r in pair_rows for c in captures.get(r['row_id'], {}).get('dispatches', [])}
                evaluated_models |= {index.get(r['row_id'], {}).get('provider_metrics', {}).get('model') for r in pair_rows}
                if judged['model'] in evaluated_models or not judged['model']: raise ValueError('judge_not_independent')
                item['semantic'] = suite.quality(judged, pair[side]['evidence'])
                comparison = suite.quality(review['comparison'], {'A.output':pair['A']['evidence']['output'],
                    'B.output':pair['B']['evidence']['output'], 'task':pair['A']['evidence']['task']})
                item['comparison'] = comparison
                if review['comparison'].get('reviewer_kind') != 'human':
                    raise ValueError('separate_human_preference_annotation_required')
                if review['comparison']['model'] in evaluated_models or not review['comparison']['model']:
                    raise ValueError('comparison_not_independent')
                if not {'A.output','B.output','task'} <= set(comparison['citations']): raise ValueError('paired_evidence_citations_required')
                preferred = review['comparison']['preferred_side']
                if preferred not in {'A','B','tie'}: raise ValueError('invalid_blind_preference')
                item['comparison'] = {**comparison, 'preferred_side':preferred}
                item['semantic_regression'] = row['arm'] == 'candidate' and preferred not in {side,'tie'}
            except (KeyError, ValueError, TypeError) as error:
                if item['semantic']['status'] != 'fail':
                    item['semantic'] = suite.unavailable('invalid_paired_judgment_' + type(error).__name__)
        rows.append(item)
    for pair_id in {r['pair_id'] for r in rows}:
        pair = [r for r in rows if r['pair_id']==pair_id]
        hashes = [r.get('pre_state_sha256') for r in pair]
        for row in pair:
            row['paired_prestate_equal'] = len(hashes)==2 and all(hashes) and hashes[0]==hashes[1]
            row['context_confound'] = 'none' if row['paired_prestate_equal'] else 'later_variant_histories_may_differ_or_evidence_missing'
    failed = any(r['contracts']['status'] == 'fail' or r['semantic']['status'] == 'fail'
                 or r.get('comparison', {}).get('status') == 'fail' or r.get('semantic_regression') for r in rows)
    return dict(schema_version='memoir-response-profile-comparison/1', run_id=planned['run_id'],
        plan_sha256=planned['plan_sha256'], status='failed' if failed else 'incomplete', release_accepted=False,
        rows=rows, latency=dict(overall=_latency(rows),
            by_locale={l:_latency([r for r in rows if r['locale'] == l]) for l in sorted({r['locale'] for r in rows})},
            by_phase={p:_latency([r for r in rows if r['phase'] == p]) for p in sorted({r['phase'] for r in rows})},
            by_locale_phase={l:{p:_latency([r for r in rows if r['locale']==l and r['phase']==p])
                for p in sorted({r['phase'] for r in rows if r['locale']==l})} for l in sorted({r['locale'] for r in rows})}),
        measurement_scope='controlled_or_imported_receipts_not_live_latency_acceptance',
        acceptance=dict(deterministic='failed' if failed else 'inspect_each_row', model_quality='advisory_only',
            human='pending_bilingual_heldout', live='not_run', provider_policy='requires_actual_receipt',
            latency='descriptive_samples_no_release_sla', dependency=planned['dependency']))
