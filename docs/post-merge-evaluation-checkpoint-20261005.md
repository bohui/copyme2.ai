# Reviewed landing and evaluation follow-up

PR11 merged at `2026-10-05T13:05:05Z` as
`602bf77f50f6a6d4a88e7f2a1bf886dff2c65914`, tree
`6a63232bf1d8742d0b83561b99fdc011ab0ba600`. The two parents are exactly
`a4d8abf810eefa1ec36cc219710f8ac954bb52e9` and reviewed
`b7b9cde7b3413c63e706cb5ca4eb759fd16fcec8`. Main's tree is identical to the
reviewed integration. GitHub ordinary merge was constrained by expected head;
no protections were bypassed and no branch was deleted.

The final head/base/check/protection/deployment inspection found main unchanged,
PR11 mergeable/CLEAN, no classic protection or applicable rules, no attached
checks, no workflows/environments/webhooks/recent deployment records, and no
known automatic deployment/migration trigger. Empty check lists were not called
passes. No deployment, migration or shared restart was invoked.

Current PR3/9/10 heads are verified ancestors of that main commit. GitHub marked
PR3 merged automatically; PR9 and PR10 were closed as incorporated with exact
ancestry comments. All three source branches and the integration branch remain.
Issues 2, 6 and gaps 12–15 are confirmed open. The earlier
[disposition](landing-issue-disposition-20261005.md) is the pre-landing evidence
snapshot; these verified landing facts supersede its pending-merge wording.
No pending live acceptance became a pass merely because the integration landed.

## New lightweight work from exact main

Branch `codex/post-merge-evaluation-20261005` starts at exact merged main.
While the quant owner runs the heavy replay, no PostgreSQL/Temporal fixture or
browser/API task service was started. All new checks use filesystem data and
one tiny task-owned loopback synthetic HTTP spy, which is stopped by the test.

**Budget defect (#14):** the legacy five-case command accepted
`--mode live --skip-preflight` despite unavailable actual-provider accounting.
The public CLI reproduction made two synthetic private-worker requests.
Runner version 5 now refuses live execution before environment/auth loading or
any provider/worker call. Skipping preflight, resuming or regrading cannot bypass
that gate; a missing saved round could previously fall through to a new turn.
Read-only `--preflight-only` remains available. A fresh blocked attempt is saved
without overwriting existing run evidence. Direct live execution remains gated
until the reviewed canonical launcher and verified upstream enforcement exist.

**Canonical planning (#12):** the new command writes a provider-free plan:

```sh
.venv/bin/python scripts/run_canonical_five_case_evaluation.py \
  --plan-only --run-id exact-main-plan --output-root output/canonical-evaluation
```

It retains the five original 50-round input sequences, allocates distinct
synthetic owner/project IDs, records every checkpoint 5/10/.../50 and pins input,
skill/reference and source hashes plus actual Git commit/tree/dirty state. It
does not load .env, authenticate, create accounts/credentials, grade outputs or
start a runtime. A plan reports `planned`, `mock_only`, `execution_started=false`
and zero started requests; it names the missing launcher/accounting/calibration
blockers. Reusing a run ID does not overwrite the previous plan.

This is planning progress, not a completed canonical launcher or 250-round run.
The source hash and dirty-state fields distinguish a working-tree prototype from
the exact published code used later for execution.

## Validation and remaining work

Public CLI red/green reproductions passed after the fixes. The final focused
lightweight command passed **32 tests, zero skips/failures/errors**, in 1.26s:

```sh
.venv/bin/python scripts/run_isolated_check.py \
  --output-dir output/mac-validation/post-merge --name post-merge-light-final-02 \
  --timeout 90 -- .venv/bin/python -m pytest -q \
  tests/test_canonical_evaluation_cli.py \
  tests/test_memoir_five_case_evaluator.py tests/test_evaluation_budget.py
```

No model, judge, photo-provider or new Langfuse publication was made. Browser
read-only visibility was retried: Chrome still reported zero windows, so #15
browser proof remains unavailable despite the user reporting sign-in. No
browser permission/settings changes were attempted.

Next: cloud-review this follow-up head before landing it. Parent coordinates a
heavy-fixture window for native launcher implementation/validation while quant
replay runs. Implement and verify actual upstream accounting and prices/hard
spend cap, obtain the numerical live approval, and resolve existing judge
configuration/calibration without creating credentials or inventing setup.
Then run the bounded pilot and five distinct 50-round datasets on exact main,
with invocation/output evaluation and durable/browser tracing evidence. Keep
all failures/unavailable outcomes and follow the fix/review/land/retest loop.

Temporary macOS caps and local Langfuse repair remain as previously approved.
Persistent host installation is still only a proposal pending approval.
