#!/usr/bin/env python3
"""Plan the canonical five-case workflow without starting any runtime/service.

Execution remains gated on the reviewed fixture launcher and actual-provider
accounting. This command never loads .env, authenticates, creates credentials,
or labels a plan as executed/live acceptance.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.trajectory_evaluation import build_skill_manifest
from scripts.memoir_five_case_evaluator import validate_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-only', action='store_true')
    parser.add_argument('--inputs', type=Path, default=ROOT / 'tests/evaluation/memoir_five_case_inputs.json')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--output-root', type=Path, default=ROOT / 'output/canonical-evaluation')
    args = parser.parse_args()
    if not args.plan_only:
        print(json.dumps({'status': 'blocked', 'execution_started': False,
            'blockers': ['canonical_fixture_launcher_not_wired', 'verified_provider_accounting_unavailable']}))
        return 3
    run_id = args.run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}', run_id):
        parser.error('A safe run ID is required')
    inputs_bytes = args.inputs.read_bytes()
    inputs = json.loads(inputs_bytes)
    errors = validate_inputs(inputs)
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
            for name in ('scripts/run_canonical_five_case_evaluation.py', 'scripts/canonical_evaluation.py')},
        'dataset': {'version': inputs['dataset_version'], 'inputs_sha256': hashlib.sha256(inputs_bytes).hexdigest()},
        'skill_manifest': build_skill_manifest(ROOT / 'skills'),
        'blockers': ['canonical_fixture_launcher_not_wired', 'verified_provider_accounting_unavailable',
                     'accepted_judge_calibration_unavailable'],
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
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
