#!/usr/bin/env python3
"""Plan or run the canonical five-case workflow in disposable native fixtures.

Fixture execution controls only the external provider protocol. It uses native
PostgreSQL/Temporal and the application's UserStorage/runtime/worker. It never
loads configured credentials or labels fixture output as live acceptance.
"""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.trajectory_evaluation import build_skill_manifest
from scripts.memoir_five_case_evaluator import validate_inputs


@contextmanager
def service_logs_to_stderr():
    """The CLI owns this process; reserve stdout for its JSON receipt."""
    sys.stdout.flush()
    descriptor = sys.stdout.fileno()
    saved = os.dup(descriptor)
    try:
        os.dup2(sys.stderr.fileno(), descriptor)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, descriptor)
        os.close(saved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan-only', action='store_true')
    mode.add_argument('--execute-fixture', action='store_true')
    parser.add_argument('--inputs', type=Path, default=ROOT / 'tests/evaluation/memoir_five_case_inputs.json')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'output/canonical-evaluation')
    parser.add_argument('--max-worker-requests', type=int)
    parser.add_argument('--max-seconds', type=float)
    args = parser.parse_args()
    if args.execute_fixture and (args.max_worker_requests is None or args.max_worker_requests <= 0
            or args.max_seconds is None or not math.isfinite(args.max_seconds) or args.max_seconds <= 0):
        print(json.dumps({'status': 'blocked', 'execution_started': False,
            'resources_allocated': False, 'provider_requests_started': 0,
            'blockers': ['explicit_positive_fixture_limits_required']}))
        return 3
    deadline = time.monotonic() + args.max_seconds if args.execute_fixture else None
    if not args.plan_only and not args.execute_fixture:
        print(json.dumps({'status': 'blocked', 'execution_started': False,
            'blockers': ['canonical_native_fixture_validation_pending', 'verified_provider_accounting_unavailable']}))
        return 3
    run_id = args.run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}', run_id):
        parser.error('A safe run ID is required')
    inputs_bytes = args.inputs.read_bytes()
    inputs = json.loads(inputs_bytes)
    errors = validate_inputs(inputs)
    if not errors and any(not isinstance(case.get('id'), str) or
            not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}', case['id'])
            for case in inputs.get('cases', []) if isinstance(case, dict)):
        errors.append('Safe case IDs are required for isolated receipt directories')
    if errors:
        print(json.dumps({'status': 'invalid_dataset', 'errors': errors}))
        return 2
    commit, tree = subprocess.check_output(['git', 'rev-parse', 'HEAD', 'HEAD^{tree}'], cwd=ROOT, text=True).splitlines()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=ROOT))
    plan = {
        'schema_version': 'memoir-canonical-five-case-plan/1', 'run_id': run_id,
        'status': 'planned', 'evidence_mode': 'mock_only', 'execution_started': False,
        'provider_requests_started': 0, 'private_worker_requests_started': 0,
        'application_revision': {'commit': commit, 'tree': tree, 'worktree_dirty': dirty},
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ('scripts/run_canonical_five_case_evaluation.py', 'scripts/canonical_evaluation.py',
                         'scripts/canonical_native_fixture.py', 'tests/fixtures/issue6_controlled_app_server.py',
                         'tests/memoir_postgres_workflow.py', 'tests/test_agent_commit_postgres.py',
                         'tests/test_guest_conversation_transfer.py', 'tests/test_private_rounds_postgres.py',
                         'tests/test_shared_memory_events_postgres.py')},
        'dataset': {'version': inputs['dataset_version'], 'inputs_sha256': hashlib.sha256(inputs_bytes).hexdigest()},
        'skill_manifest': build_skill_manifest(ROOT / 'skills'),
        'blockers': ['canonical_native_fixture_validation_pending', 'verified_provider_accounting_unavailable',
                     'accepted_judge_calibration_unavailable'],
        'execution_limits': {'max_worker_requests': args.max_worker_requests,
                             'max_seconds': args.max_seconds, 'max_provider_requests': 0,
                             'max_provider_input_tokens': 0, 'max_provider_output_tokens': 0},
        'cases': [{'case_id': case['id'], 'language': case['locale'],
            'owner_id': str(uuid4()), 'project_id': 'canonical-' + uuid4().hex,
            'rounds': case['rounds'], 'source_kind': 'narrator_chat',
            'checkpoints': list(range(5, 51, 5))} for case in inputs['cases']],
    }
    destination = args.output_root / run_id / 'plan.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Preserve previous evidence if a caller reuses the same run ID.
    with destination.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    if args.execute_fixture:
        from scripts.canonical_native_fixture import run_fixture
        with service_logs_to_stderr():
            result = asyncio.run(run_fixture(plan, destination.parent,
                max_worker_requests=args.max_worker_requests, deadline=deadline))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'completed' else 3
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
