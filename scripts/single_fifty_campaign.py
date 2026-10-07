#!/usr/bin/env python3
"""Plan one isolated fifty-input campaign and inspect receipt shape offline.

This module cannot execute a campaign, load authentication, allocate services or
change the historical ten-turn canary. Complete receipt shape is not acceptance.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
INPUTS_PATH = 'tests/evaluation/memoir_five_case_inputs.json'
INPUTS_SHA256 = 'e7f705bc4a96537b01cb5cde7d412972bdd929de49d339bc6b1a95bc9cb43927'
REQUIRED_CLEANUP = ('postgres_removal_verified', 'temporal_closed',
    'gateway_guard_finished', 'gateway_resources_finished', 'gateway_bridge_finished',
    'remote_actor_absence_verified')
SOURCE_FILES = (INPUTS_PATH, 'scripts/single_fifty_campaign.py',
    'scripts/fifty_round_budget_contract.py', 'scripts/canonical_evaluation.py',
    'scripts/canonical_native_fixture.py', 'scripts/native_canary_launcher.py',
    'scripts/canary_app_launcher.py', 'scripts/canary_gateway_actor.py',
    'scripts/canary_gateway_binding.py', 'scripts/canary_gateway_bridge.py',
    'scripts/canary_send_guard.py', 'scripts/canary_worker.py', 'scripts/task_runtime.py',
    'apps/api/codex_runtime.py', 'apps/api/codex_worker_service.py', 'apps/api/codex_agent.py',
    'apps/api/canonical_composer.py', 'apps/api/memoir_preview.py', 'apps/api/memory_event_worker.py',
    'apps/api/memory_events.py', 'apps/api/trajectory_evaluation.py', 'apps/api/recall.py',
    'apps/api/main.py', 'apps/api/story_routes.py', 'apps/api/supabase_routes.py',
    '.env.example', 'compose.yml', 'tests/evaluation/memoir_five_case_expected.json',
    'tests/evaluation/memoir_five_case_truth.json')
BLOCKERS = ('security_hotfix_review_required', 'campaign_execution_path_not_implemented',
    'new_campaign_budget_approval_required', 'consumer_account_binding_not_verified',
    'actual_role_configuration_not_verified', 'exact_main_cloud_review_required',
    'native_resource_and_runtime_validation_not_run', 'durable_and_browser_evidence_not_run')


def _git(root, *args):
    # Read-only local Git calls receive no application credentials or HOME.
    return subprocess.check_output(['git', *args], cwd=root, text=True,
        env={'PATH': os.environ.get('PATH', os.defpath), 'LC_ALL': 'C',
             'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1'}).strip()


def _sha(path, root):
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Source pins must be ordinary files inside the checkout')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_campaign_plan(*, case_id, family_enabled, run_id=None, root=ROOT):
    """Build a non-authorizing plan from one checked-in, unchanged input case."""
    from scripts.fifty_round_budget_contract import build_budget_proposal
    root = Path(root)
    run_id = str(uuid4()) if run_id is None else run_id
    if str(UUID(run_id)) != run_id or type(family_enabled) is not bool:
        raise ValueError('A fresh UUID and explicit Family setting are required')
    raw = (root / INPUTS_PATH).read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUTS_SHA256:
        raise ValueError('The pinned original input bundle differs')
    inputs = json.loads(raw)
    case = next((case for case in inputs['cases'] if case['id'] == case_id), None)
    if case is None or len(case['rounds']) != 50 or any(
            not isinstance(text, str) or not text.strip() for text in case['rounds']):
        raise ValueError('Select one original fifty-input case')
    revision, tree = _git(root, 'rev-parse', 'HEAD', 'HEAD^{tree}').splitlines()
    dirty = bool(_git(root, 'status', '--porcelain=v1'))
    owner, project = str(uuid4()), 'campaign-' + uuid4().hex
    roots = [{'case_id': case_id, 'round': ordinal, 'owner_id': owner, 'project_id': project,
        'trace_id': hashlib.sha256(f'{run_id}:{case_id}:{ordinal}'.encode()).hexdigest()[:32],
        'original_input_sha256': hashlib.sha256(text.encode()).hexdigest(), 'status': 'not_run'}
        for ordinal, text in enumerate(case['rounds'], 1)]
    budget = build_budget_proposal(family_enabled=family_enabled)
    if budget.get('approval_status') != 'unapproved' or budget.get('live_execution_authorized') is not False:
        raise ValueError('A budget proposal cannot grant campaign authorization')
    skills = _git(root, 'ls-files', 'skills').splitlines()
    mismatched = [name for name, expected in budget['derivation_file_sha256'].items()
                  if _sha(root / name, root) != expected]
    blockers = list(BLOCKERS) + (['source_worktree_dirty'] if dirty else [])
    if mismatched: blockers.append('budget_call_graph_source_drift')
    return {'schema_version': 'memoir-single-fifty-plan/1', 'run_id': run_id,
        'status': 'planned_blocked', 'live_ready': False, 'execution_started': False,
        'credentials_loaded': False, 'provider_requests_started': 0,
        'source_revision': revision, 'source_tree': tree, 'source_worktree_dirty': dirty,
        'source_sha256': {name: _sha(root / name, root) for name in SOURCE_FILES},
        'skill_source_sha256': {name: _sha(root / name, root) for name in skills},
        'dataset': {'version': inputs['dataset_version'], 'inputs_sha256': INPUTS_SHA256,
                    'selection': 'one_case_only', 'selected_case_id': case_id},
        'cases': [{'case_id': case_id, 'language': case['locale'], 'family_enabled': family_enabled,
            'owner_id': owner, 'project_id': project, 'source_kind': 'narrator_chat',
            'rounds': deepcopy(case['rounds']), 'data_created': False}],
        'round_roots': roots, 'checkpoints': [{'case_id': case_id, 'milestone': n,
            'checkpoint_id': f'{case_id}:{n}', 'trace_id': roots[n - 1]['trace_id'],
            'status': 'not_run'} for n in range(5, 51, 5)],
        'budget': budget, 'budget_source_audit': {
            'derivation_matches_current_files': not mismatched, 'mismatched_paths': sorted(mismatched)},
        'historical_canary': {'rounds': 10, 'checkpoints': 2, 'actual_request_cap': 80,
            'wall_seconds': 900, 'request_seconds': 60, 'applies_to_this_campaign': False},
        'entitlement': {'mode': 'isolated_synthetic_backend', 'normal_free_account_round_limit': 20,
            'fixture_admission': 'not_verified', 'real_subscription_or_billing_change': False},
        'configuration': {'policy': 'preserve_actual_role_routing', 'role_model_overrides': {},
            'installed_role_configuration': 'not_verified', 'consumer_account_binding': 'not_verified',
            'required_roles': ['collector', 'workspace', 'memory_context', 'author_timeline', 'composer'],
            'required_config': ['MEMORY_SPARK_LLM_MODEL', 'MEMORY_SPARK_LLM_REASONING_EFFORT',
                'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', 'MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT',
                'MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT']},
        'coverage': {'canonical_50_input_pipeline': 'planned_not_run',
            'ten_saved_draft_checkpoints': 'planned_not_run', 'original_source_and_event_readback': 'not_run',
            'postgres_temporal': 'not_run', 'browser_login_recovery': 'not_covered',
            'free_account_20_round_gate': 'separate_required_test', 'model_quality': 'not_graded',
            'voice': 'excluded_from_campaign', 'all_five_cases_250_rounds': 'not_requested'},
        'evidence_contract': {'required_cleanup': list(REQUIRED_CLEANUP),
            'join_keys': ['run_id', 'case_id', 'round_id', 'trace_id', 'observation_id',
                          'request_id', 'job_id', 'checkpoint_id'],
            'actual_request_counts': 'independent_provider_receipt_required',
            'on_budget_timeout_failure_or_cancellation': 'stop_and_preserve_incomplete_receipt'},
        'blockers': blockers, 'next_work': ['review_and_approve_exact_campaign_envelope',
            'adapt_isolated_execution_and_linkage_without_changing_legacy_canary',
            'verify_hotfixed_exact_main_native_config_and_consumer_account',
            'run_controlled_native_checks_before_any_separately_admitted_live_campaign']}


def assess_campaign_receipt(plan, receipt):
    """Inspect claimed canonical receipt shape; never establish live acceptance.

    The future runner must additionally verify request/job joins and independent
    native/provider/storage evidence. This function does not dispatch or read it.
    """
    if not isinstance(plan, dict) or not isinstance(receipt, dict):
        raise ValueError('Plan and receipt must be objects')
    errors, completed, saved = [], 0, 0
    expected = plan['cases'][0]
    if len(plan['cases']) != 1 or len(expected['rounds']) != 50:
        raise ValueError('Assessment requires one fifty-input plan')
    if any(receipt.get(key) != plan[key] for key in ('run_id', 'source_revision', 'source_tree')):
        errors.append('source_or_run_identity_differs')
    cases = receipt.get('cases', [])
    case = cases[0] if isinstance(cases, list) and len(cases) == 1 and isinstance(cases[0], dict) else {}
    if (type(case.get('family_enabled')) is not bool or any(case.get(key) != expected[key]
            for key in ('case_id', 'owner_id', 'project_id', 'language', 'family_enabled'))):
        errors.append('case_scope_differs')
    rounds = case.get('rounds', [])
    if not isinstance(rounds, list): rounds = []; errors.append('round_records_invalid')
    seen, sources, source_order = set(), set(), []
    for record in rounds:
        if not isinstance(record, dict): errors.append('round_record_invalid'); continue
        ordinal = record.get('round')
        if type(ordinal) is not int or not 1 <= ordinal <= 50 or ordinal in seen:
            errors.append('round_identity_invalid'); continue
        seen.add(ordinal)
        if ordinal != len(seen): errors.append('round_sequence_differs')
        if record.get('status') != 'completed' or record.get('background_settled') is not True:
            continue
        source_id = record.get('accepted_source_id')
        view = record.get('canonical_state') or {}
        original = view.get('sources', []) if isinstance(view, dict) else []
        valid_sources = (isinstance(original, list) and len(original) == ordinal
            and all(isinstance(item, dict) for item in original))
        if (not isinstance(source_id, str) or not source_id or source_id in sources or not valid_sources
                or [item.get('text') for item in original] != expected['rounds'][:ordinal]
                or any(type(item.get('sequence')) is not int for item in original)
                or [item.get('sequence') for item in original] != list(range(1, ordinal + 1))
                or [item.get('id') for item in original] != source_order + [source_id]
                or any(type(item.get('version')) is not int or item['version'] < 1 for item in original)
                or type(view.get('completed_rounds')) is not int or view['completed_rounds'] != ordinal
                or not isinstance(view.get('processing'), dict)
                or type(view['processing'].get('extracted_through')) is not int
                or view['processing']['extracted_through'] != ordinal):
            errors.append('canonical_source_or_extraction_differs'); continue
        sources.add(source_id)
        source_order.append(source_id)
        completed += 1
    checkpoints = case.get('checkpoints', [])
    if not isinstance(checkpoints, list): checkpoints = []; errors.append('checkpoint_records_invalid')
    milestones = set()
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, dict): errors.append('checkpoint_record_invalid'); continue
        milestone, draft = checkpoint.get('milestone'), checkpoint.get('draft') or {}
        if (type(milestone) is not int or milestone not in range(5, 51, 5) or milestone in milestones
                or milestone > completed or not isinstance(draft, dict)
                or type(draft.get('revision')) is not int or draft['revision'] <= 0
                or type(draft.get('covered_round')) is not int or draft['covered_round'] != milestone):
            errors.append('checkpoint_identity_or_saved_state_differs'); continue
        milestones.add(milestone)
        saved += 1
    if receipt.get('status') != 'completed' or case.get('status') != 'completed':
        errors.append('terminal_run_incomplete')
    if receipt.get('execution_started') is not True: errors.append('execution_not_recorded')
    if len(rounds) != 50 or completed != 50: errors.append('fifty_completed_rounds_not_recorded')
    if len(checkpoints) != 10 or saved != 10: errors.append('ten_saved_checkpoints_not_recorded')
    cleanup = receipt.get('cleanup') or {}
    if not isinstance(cleanup, dict) or any(cleanup.get(name) is not True for name in REQUIRED_CLEANUP):
        errors.append('cleanup_verification_missing')
    counts = {}
    for key in ('provider_requests_started', 'guarded_send_entries'):
        value = receipt.get(key)
        if value is not None and (type(value) is not int or value < 0):
            errors.append('invalid_' + key); value = None
        counts[key] = value
    if (not isinstance(receipt.get('evidence_mode'), str)
            or receipt['evidence_mode'] not in {'mock_only', 'guarded_live_campaign'}):
        errors.append('unsupported_evidence_mode')
    if counts['provider_requests_started'] is None:
        errors.append('actual_request_count_unknown')
    return {'receipt_shape_complete': not errors, 'completed_rounds': completed, 'saved_checkpoints': saved,
        **counts, 'request_count_evidence': 'reported_not_independently_verified',
        'errors': sorted(set(errors)), 'live_ready': False, 'acceptance_status': 'not_established',
        'model_quality': 'not_graded', 'unverified_dimensions': ['request_observation_job_links',
            'native_resource_ownership', 'actual_provider_accounting', 'browser_login_recovery']}


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message): self.exit(2, 'Invalid campaign options; credentials are not accepted.\n')
    parser = SafeParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--plan-only', action='store_true')
    modes.add_argument('--execute', action='store_true')
    parser.add_argument('--case-id')
    parser.add_argument('--family-mode', choices=('enabled', 'disabled'))
    parser.add_argument('--run-id')
    parser.add_argument('--output-root', required=True, type=Path)
    args = parser.parse_args()
    if args.execute:
        print(json.dumps({'status': 'blocked', 'execution_started': False, 'credentials_loaded': False,
            'provider_requests_started': 0, 'blockers': list(BLOCKERS)}))
        return 3
    if args.case_id is None or args.family_mode is None:
        parser.error('Explicit case and Family mode are required')
    try:
        if args.output_root.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError('Evidence output must be outside the source checkout')
        plan = build_campaign_plan(case_id=args.case_id, family_enabled=args.family_mode == 'enabled',
                                   run_id=args.run_id)
        directory = args.output_root / plan['run_id']
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        path = directory / 'plan.json'
        with path.open('x', encoding='utf-8') as stream:
            json.dump(plan, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'status': plan['status'], 'manifest': str(path), 'live_ready': False,
                          'execution_started': False, 'provider_requests_started': 0}))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({'status': 'blocked', 'error_class': type(error).__name__,
                          'execution_started': False, 'credentials_loaded': False, 'provider_requests_started': 0}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
