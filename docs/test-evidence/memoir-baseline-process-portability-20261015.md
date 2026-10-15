# PR69: portable session inspection and audit corrections

Historical d373 checkpoint. The [later process-race report](memoir-baseline-process-races-20261015.md) records the current tested source and selection, which includes the ordinary proposal-overlap failure.

Fixed source/test commit: `d373e7435b6f1dc702e80cf02c567331eff7c4eb`.
All **thirteen complete affected modules** record **88 passed, one failed, zero
errors/skips** in **273.44 seconds** wall time
(JUnit 273.265 seconds). Acceptance remains incomplete.
This is not a current-source whole-repository aggregate. The separate ordinary
proposal-overlap regression is excluded from this selection and remains open.

## Portability defect and repair

`7884af3` introduced an unconditional process-table query using the `sid` column,
still present at evidence-only `d2f6ffa`. Apple's
[keyword table](https://github.com/apple-oss-distributions/adv_cmds/blob/6bed8737a34dbb54782a18f47dccf933a9967a12/ps/keyword.c)
supports `pid`, `pgid` and `stat`, but does not define `sid`; unknown keywords
set an error. Its `sess` field is a kernel pointer rather than the numeric
session ID required by the ownership guard.

Five initial regressions on d2f6ffa record **one pass and four failures** under
a restrictive Apple-compatible process-command shim. A real generic child
prints its expected output and exits zero, but the outer wrapper changes that
outcome to `cleanup_failed`/2 when reconciliation's `ps` fails. This path
allocates no PostgreSQL. The saved receipt preserves child return code zero,
wrapper code two and the failing command class.

Reconciliation now queries only `pid,pgid,stat` and calls
[`os.getsid(pid)`](https://docs.python.org/3.12/library/os.html#os.getsid)
for each live matching PID. The existing recorded group and leader-birth checks
remain, and each live member must have the exact expected numeric session ID.
Only `ProcessLookupError` permits treating a snapshotted member as exited;
permission failures and changed session identity retain metadata and fail.
Shutdown deadlines, root/device/inode checks, postmaster guards and policy
contracts are unchanged.

Six portability cases pass: generic success with the host process command and
with Apple-compatible columns; exact owned live-session SIGKILL/reaping;
a real child exiting and being reaped between snapshot and session lookup;
different-session refusal without signalling; and permission-denial refusal
without signalling. The combined focused run with all lifecycle unit cases
passes thirteen tests. The real host `ps`, `os.getsid` and fresh owned subprocesses
run on Linux; the shim rejects unsupported output keywords and delegates valid
commands to the host. **Native Mac runtime coverage remains unrun.** This does
not claim native Darwin process or PostgreSQL coverage.

## Complete affected-module outcomes

| Module | Passed | Failed |
| --- | ---: | ---: |
| `tests/test_agent_commit_postgres.py` | 8 | 0 |
| `tests/test_controlled_five_case_lifecycle.py` | 6 | 0 |
| `tests/test_controlled_native_state.py` | 1 | 0 |
| `tests/test_canonical_controlled_profile.py` | 3 | 0 |
| `tests/test_memoir_five_case_evaluator.py` | 14 | 0 |
| `tests/test_canonical_turn_publication.py` | 3 | 0 |
| `tests/test_lifetime_actual_engines.py` | 14 | 0 |
| `tests/test_controlled_supervisor_lifecycle.py` | 7 | 0 |
| `tests/test_controlled_lifecycle.py` | 7 | 0 |
| `tests/test_canonical_evaluation_cli.py` | 9 | 0 |
| `tests/test_controlled_outer_cleanup.py` | 5 | 0 |
| `tests/test_isolated_check_runner.py` | 5 | 1 |
| `tests/test_controlled_process_portability.py` | 6 | 0 |

The unchanged failure is
`tests/test_isolated_check_runner.py::test_timeout_stops_a_term_resistant_descendant_after_its_parent_exits`.
The exact original descendant is exited but retained as a `Z` process by PID 1;
the original assertion requires process absence and remains visibly failed.
`stop_owned` has the same AST as d2f6ffa, and the detached-parent comparison is
preserved in the transitive ledger. No live descendant was observed. No
assertion is skipped, xfailed, removed or weakened.

The native suite again verifies **17 original postmasters across eleven
scenarios**, including actual single/nested wrappers with shipped default
deadlines, supervisor/CLI cancellation, profiler stop faults and long TMPDIR.
Original PID/start/data and owner identities, stop attempts, short socket paths
and absent owned data paths are embedded in the ledger. The selected provider/
service authority variable count is zero; all data is disposable and synthetic.

## Audit corrections and separately verified red cleanup

The batch index's current-source and targeted-ledger pointers now name this
tested source and its new ledger. The b1e54e8 repository aggregate fields,
counts, classifications and prior checkpoint records remain unchanged.
Their scope is explicitly described so the historical aggregate is not mistaken
for acceptance at this source.

The earlier nested frozen-case red teardown failed an identity assertion inside
`emergency_cleanup` before it stopped PostgreSQL. That original failure trace and
the valid live-process leak snapshots remain intact. The old statement claiming
successful emergency teardown is withdrawn, rather than inferred from that
failed teardown.

A separate inspection at **18:25:29 UTC** on 2026-10-15 found its original
postmaster **747268**, start **2649474**, still running at its recorded data path.
At **18:26:01 UTC** a subsequent action checked PID/start, exact `postgres -D`
argv, matching `postmaster.pid`, owner UID and root device/inode before bounded
immediate stop returned zero. Only that matched synthetic allocation was removed.
The distinct **18:27:18 UTC** verification checked every original recorded red
postmaster, command and owner: none remained running; all original data and PID
files were absent. PID-1-owned exited zombies remain unreaped. These separate
before/action/after records are embedded with raw hashes in both the corrected
historical and new ledgers. The failed historical teardown stays failed.

## Scope and remaining coverage

The [complete ledger](memoir-baseline-process-portability-20261015.json) includes
all 89 per-case outcomes, generic red/green receipts, five process-command logs,
native observations, source/raw hashes and audit correction evidence.
The [historical transitive report](memoir-baseline-transitive-cleanup-20261015.md)
retains its 82-pass/one-failure checkpoint and carries the red-teardown correction.
An evidence-only child preserves the tested executable source and test files.

This selection excludes
`tests/test_progressive_rework_proposal_overlap.py::test_rework_does_not_revisit_a_completed_proposal_on_another_section`.
Its previously failing ordinary regression and pending-proposal inheritance
decision remain unresolved, unweakened and unrun here. PR68-owned client polling,
attribution and migration work remain separate. No SQL, client, product-policy,
publication/replay/identity safeguard, deployment, migration or access action
changes in this follow-up.

Outstanding gates remain: the ordinary PID-1 zombie assertion failure; native
Mac generic-command runtime coverage; independent current-head review; a full
repository aggregate at current source; the separate proposal-overlap and other
consequential product decisions; live provider/judge, semantic/latency and real
Auth checks; full opt-in UI/artifact/complete-round and 250-round acceptance;
and native device/binary or production execution. No real provider or user data
is involved and no full acceptance is claimed.
