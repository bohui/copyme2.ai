#!/usr/bin/env python3
"""Prepare the ten-round canary manifest. Execution is deliberately blocked.

No auth loading, reservation, services or provider calls are implemented here.
The actual gateway binding must be reviewed before a live launcher is added.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID, uuid4


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
INPUTS_SHA256 = 'e7f705bc4a96537b01cb5cde7d412972bdd929de49d339bc6b1a95bc9cb43927'
APPROVED_ACCOUNT_BINDING = 'b45a626039b65a68ace979d43215b7c4ea36048e5ee32744034e4134905961fa'
BLOCKERS = ['installed_gateway_dispatch_binding_unavailable',
    'runtime_consumer_account_binding_unavailable',
    'durable_and_browser_evidence_not_run']
TELEMETRY_SOURCE_REVISION = '9d337087cc865fa801b81da7e4c12d35b0ac277c'
TELEMETRY_IMPLEMENTATION_REVISION = '701032f608a7d4c35b3ad098cf3ff1ec7c705563'
TELEMETRY_MERGE_REVISION = '6e907c64a093c0aaf76cbb9dc6380e23c16205df'


def build_manifest(*, run_id, source_revision):
    if str(UUID(run_id)) != run_id or not re.fullmatch('[a-f0-9]{40}', source_revision):
        raise ValueError('Pinned source revision and fresh UUID run ID are required')
    raw = (ROOT / 'tests/evaluation/memoir_five_case_inputs.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != INPUTS_SHA256:
        raise ValueError('Original inputs changed')
    original = {c['id']: c for c in json.loads(raw)['cases']}
    cases, roots, checkpoints = [], [], []
    for case_id, family in [('harbour-copper-notebook', True), ('chengdu-tea-ledger', False)]:
        case = original[case_id]
        owner_id, project_id = str(uuid4()), 'canary-' + uuid4().hex
        cases.append({'case_id': case_id, 'owner_id': owner_id, 'project_id': project_id,
            'language': case['locale'], 'family_enabled': family,
            'rounds': case['rounds'][:5], 'data_created': False})
        for ordinal in range(1, 6):
            trace_id = hashlib.sha256(f'{run_id}:{case_id}:{ordinal}'.encode()).hexdigest()[:32]
            roots.append({'case_id': case_id, 'round_id': str(ordinal), 'trace_id': trace_id,
                'project_id': project_id, 'owner_id': owner_id, 'status': 'not_run',
                'gateway_request_ids': [], 'background_job_ids': []})
        checkpoints.append({'case_id': case_id, 'milestone': 5,
            'checkpoint_id': case_id + ':5', 'trace_id': roots[-1]['trace_id'],
            'draft_saved': False, 'background_job_ids': []})
    allocation = {'collector_and_broad_workspace': 20, 'canonical_extraction': 10,
        'initial_locale': 2, 'focused_place': 10, 'focused_family': 15,
        'event_preparation': 10, 'composer_draft_and_review': 12}
    from apps.api.trajectory_evaluation import build_skill_manifest, EVALUATION_RUBRIC_VERSION
    pins = ('tests/evaluation/memoir_five_case_inputs.json',
        'tests/evaluation/memoir_five_case_expected.json', 'tests/evaluation/memoir_five_case_truth.json',
        'tests/evaluation/memoir_five_case_oracle_corrections.json',
        'tests/evaluation/memoir_five_case_judge_calibration.json',
        'tests/evaluation/memoir_five_case_judge_prompt.md',
        'scripts/canonical_evaluation.py', 'scripts/canary_app_launcher.py',
        'scripts/canary_worker.py', 'scripts/canary_gateway_binding.py',
        'scripts/canary_gateway_bridge.py', 'scripts/canary_gateway_auth.py',
        'scripts/native_canary_launcher.py', 'scripts/memoir_five_case_evaluator.py',
        'tests/memoir_postgres_workflow.py', 'tests/test_agent_commit_postgres.py',
        'tests/test_shared_memory_events_postgres.py',
        'scripts/canary_send_guard.py', 'scripts/task_runtime.py',
        'apps/api/codex_runtime.py', 'apps/api/codex_worker_service.py',
        'apps/api/temporal_workflows.py', 'apps/api/memory_event_worker.py',
        'apps/api/canonical_composer.py', 'apps/api/trajectory_evaluation.py')
    if (ROOT / 'scripts/canary_gateway_actor.py').is_file():
        pins += ('scripts/canary_gateway_actor.py',)
    tree = subprocess.run(['git', 'rev-parse', '--verify', source_revision + '^{tree}'],
        cwd=ROOT, text=True, capture_output=True)
    # Source ancestry proves integration only, never native or durable acceptance.
    telemetry_integrated = subprocess.run(['git', 'merge-base', '--is-ancestor',
        TELEMETRY_MERGE_REVISION, source_revision], cwd=ROOT, capture_output=True).returncode == 0
    blockers = list(BLOCKERS)
    if not telemetry_integrated:
        blockers.append('telemetry_revision_integration_pending')
    from scripts.canary_gateway_actor import expected_source_hashes
    return {'schema_version': 'memoir-codexlb-app-canary/2',
        'run_id': run_id, 'source_revision': source_revision, 'inputs_sha256': INPUTS_SHA256,
        'source_tree': tree.stdout.strip() if tree.returncode == 0 else None,
        'gateway_source_sha256': expected_source_hashes(),
        'integration_provenance': {
            'host_app_input_checkpoint': 'c9cc0710625027c4d6578ffbdb94b8bd3c7ba99d',
            'actor_guard_checkpoint': '5f7b069742b17d9b70146dd87e130dceb25818dc',
            'combined_revision': source_revision, 'exact_merged_main_acceptance': False},
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in pins},
        'skill_manifest': build_skill_manifest(ROOT / 'skills'),
        'evaluator_version': EVALUATION_RUBRIC_VERSION,
        'source_claim': 'task integration; not exact merged main acceptance',
        'telemetry_dependency': {'pull_request': 18, 'source_revision': TELEMETRY_SOURCE_REVISION,
            'implementation_revision': TELEMETRY_IMPLEMENTATION_REVISION,
            'merge_revision': TELEMETRY_MERGE_REVISION,
            'status': ('source_integrated_durable_evidence_pending' if telemetry_integrated
                       else 'source_integration_unverified'), 'durable_evidence': 'not_run'},
        'status': 'planned_blocked', 'live_ready': False, 'execution_started': False,
        'credentials_loaded': False, 'reservation_created': False, 'provider_requests_started': 0,
        'envelope_status': 'conditionally_approved_after_exact_implementation_review',
        'proposed_account_binding': APPROVED_ACCOUNT_BINDING,
        'requested_model': 'gpt-5.6-luna', 'served_model': 'not_verified',
        'proposed_limits': {'maximum_actual_requests': 80, 'concurrency': 1,
            'wall_seconds': 900, 'request_seconds': 60, 'transport_retries': 0,
            'activity_redeliveries': 0, 'account_failover': False,
            'judge_calls': 0, 'photo_calls': 0, 'geocoding_calls': 0, 'paid_routes': 0},
        'logical_allocation': allocation, 'logical_allocation_total': sum(allocation.values()),
        'included_semantic_repair_calls': 18,
        'repair_details': {'family': '5 initial focused passes + up to 10 additional passes',
            'composer': '4 initial draft/review calls + up to 8 repair calls'},
        'completion_guaranteed': False, 'token_limits_enforced': False,
        'cases': cases, 'round_roots': roots, 'checkpoints': checkpoints,
        'evidence': {name: 'not_run' for name in ('real_app_replies', 'private_drafts',
            'gateway_requests', 'gateway_usage', 'background_joins', 'langfuse_api',
            'langfuse_database', 'browser')}, 'blockers': blockers,
        'acceptance_scope': 'Ten-round canary only; no all-seven-skills or 250-round acceptance'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--plan-only', action='store_true')
    modes.add_argument('--execute', action='store_true')
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    if args.execute:
        print(json.dumps({'status': 'blocked', 'execution_started': False,
            'credentials_loaded': False, 'reservation_created': False,
            'provider_requests_started': 0, 'blockers': BLOCKERS}))
        return 3
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    manifest = build_manifest(run_id=str(uuid4()), source_revision=revision)
    destination = args.output_root / manifest['run_id']
    destination.mkdir(parents=True, mode=0o700)
    with (destination / 'manifest.json').open('x', encoding='utf-8') as output:
        output.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': manifest['status'], 'manifest': str(destination / 'manifest.json'),
        'execution_started': False, 'provider_requests_started': 0}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
