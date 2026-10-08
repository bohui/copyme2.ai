"""Dedicated issue 14 deny-only entry point; no provider configuration is read.

This is admission wiring, not actual-provider enforcement or a live launcher.
Existing canary launchers, bridges and the semantic-judge CLI are untouched.
"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.issue14_execution_admission import (
    AdmissionDenied, Issue14Admission, require_issue14_admission,
)


def run_evaluation(*, admission, run_id, source_revision, role='collector',
                   runtime_factory=None, worker_factory=None, judge_factory=None):
    """Check before factories can read config, create homes or contact services.

    Factories are intentionally never invoked: a future provider-capable runner
    requires its own reviewed implementation, not removal of one gate here.
    """
    require_issue14_admission(admission, run_id=run_id,
        source_revision=source_revision, role=role)
    raise AdmissionDenied('execution_not_implemented')  # Defensive, no live path.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--role', default='collector')
    args = parser.parse_args(argv)
    admission = None
    try:
        admission = Issue14Admission.deny_only(run_id=args.run_id,
            source_revision=args.source_revision)
        run_evaluation(admission=admission, run_id=args.run_id,
            source_revision=args.source_revision, role=args.role)
    except AdmissionDenied as error:
        receipt = admission.receipt() if admission is not None else {
            'mode': 'deny_only', 'live_ready': False, 'actual_provider_requests': None,
            'real_provider_token_or_cost_limits_verified': False}
        print(json.dumps({**receipt, 'status': 'blocked', 'reason': str(error)}, sort_keys=True))
        return 3
    finally:
        if admission is not None:
            admission.close()
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
