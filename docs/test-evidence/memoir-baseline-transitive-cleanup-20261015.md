# PR69: default deadlines, creation coverage and transitive wrapper cleanup

Fixed source/test commit: `7884af336740044f7e4f7829092a1a174e37dd88`.
All **twelve complete affected modules** record **82 passed, one failed, zero
errors/skips** in **270.78 seconds** wall time
(JUnit 270.707 seconds). Acceptance remains incomplete.
This is not a new whole-repository aggregate.

## Native reproductions and repairs

At `a1966e10ef9b12d3392cc1a60a1bd3df157660e1`, two actual nested-wrapper
regressions fail: outer wrapper → pytest helper → inner wrapper → controlled
case/profiler. The outer returns 143 and records `verified=true` while the inner
command and original postmaster(s) still run. Both tests use the shipped outer
five-second SIGKILL grace, case-child twenty-second grace and profiler fixture
ten-second fast-stop timeout. Snapshots preserve that false success before
identity-checked test emergency teardown; the leak is not inferred from a
directory scan. Single-wrapper success did not establish this transitive path.

Each new short physical `/tmp` root now atomically registers its device/inode
identity with its inherited owner. An inner wrapper registers with the outer
before launching its command, then records its new session's command-group and
leader-birth identity. Case children inherit the case owner. Reconciliation
quiesces the registered command sessions, traverses the complete ownership graph,
verifies each original root and postmaster PID/data/command identity, and stops
the databases before removing roots. Missing or changed identity retains metadata
and refuses verification. Registration roots remain physical siblings under
`/tmp`, so wrapper depth and a long `TMPDIR` do not lengthen socket paths.
The existing default deadlines are unchanged.

The five native integration cases now pass, including both nested variants,
both single-wrapper boundaries, and the same-long-TMPDIR raw/controlled SQL
comparison. The complete run observes **17 original postmasters across eleven
native scenarios**, records all PID/start/data and stop attempts, and verifies
no original postmaster/command/case child remains running and no owned cluster
is usable. Four additional safety cases cover a four-owner sibling-root graph,
changed inode refusal, changed command-birth refusal without signalling, and
refusal to verify an empty wrapper root with missing command metadata.

## Creation-phase attribution correction

The a294 `direct_during_spawn` harness had already returned the subprocess
handle before it sent SIGTERM. Its historical passing IDs, counts and raw hashes
remain preserved, but the claimed pre-handle phase is withdrawn in the earlier
[supervision report](memoir-baseline-supervision-20261015.md) and JSON.
A guard on the old harness fails because return has already occurred; this is
a coverage gap, not a new runtime defect.

`56344c045bdc74fafb6c2a3b90342b8510f2a322` preserves that case under its accurate
delayed post-return name and adds a genuinely held-handle regression. A marker
proves the actual child exists while handle return is blocked. Cleanup begins
before return, a second SIGTERM arrives, then the exact handle is released and
the child is reaped. JSON input never reaches the child in this phase, so no
database allocation is expected. All post-start database assertions remain.
The current complete run preserves those phase markers and exact child identity.

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

The one remaining failure is
`tests/test_isolated_check_runner.py::test_timeout_stops_a_term_resistant_descendant_after_its_parent_exits`.
Its original assertion requires process absence. The descendant has exited but
remains a `Z` process reparented to PID 1 on this cloud host. The same assertion
fails on detached parent `56344c0` with the same Z/PPID-1 observation;
`stop_owned` has the same AST at parent and final source. This is classified as
an environment process-reaping failure. The assertion remains unchanged and
failed; no live descendant was observed. No test was skipped, xfailed, removed
or weakened to hide it.

## Intermediate evidence and remaining gates

The accompanying [per-case ledger](memoir-baseline-transitive-cleanup-20261015.json)
preserves the coverage guard, original/default red and green runs, 56344's
**67 passes across ten complete modules**, a196's **76 passes and one failure
across twelve complete modules**, both nested red snapshots, and current native
observers. Those checkpoints apply only to their recorded sources; a196 still
had the nested defect. The ledger includes 49
current raw-file hashes, the intermediate checkpoint's own hashes, and hashes
of all six changed source/test files. An evidence-only child leaves those files
identical to the tested source.

Fresh disposable synthetic Unix-socket PostgreSQL and fake workers are used.
Configured provider/service authority variable count is zero; no real provider,
user data, production migration, access change, merge or deployment is involved.
Native observers run only on the selected Linux/proc host; no Mac coverage is
claimed. Current main `46caa5fc2c2c5af2d4f7280bea74cc75184c9cbc` remains an ancestor.
This follow-up changes no client/SQL/migration, PR68-owned polling/attribution,
publication/replay/identity guard, pending-proposal inheritance, or other product
policy. Earlier repository-wide ledgers remain pinned to their sources.

Unresolved gates remain: the unchanged PID-1 zombie absence failure; a complete
repository aggregate at current source; pending-proposal/user contract choices;
independent current-head runtime review; live provider/judge, semantic/latency
and real Auth checks; full opt-in UI/artifact/complete-round and 250-round
acceptance; native Mac/device/binary and production execution. No full acceptance
is claimed.
