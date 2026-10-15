# PR69: supervisor termination and self-owned profiler databases

Both independently reproduced P2 paths are repaired at fixed source/test commit
`a294f8b6cc47952d1e85b2003352f36dec69a347`. The complete affected selection records **66 passed,
zero failures/errors/skips across ten modules** in **226.86 seconds wall time**
(JUnit 226.787 seconds). Draft acceptance remains
incomplete; this is not a whole-repository aggregate.

## Reproductions and behaviour

Four new native red cases fail on the original executable source at `6177248`:
SIGTERM of the direct supervisor and the actual evaluation CLI each leaves an
unresponsive case child plus a running detached postmaster; failed and timed-out
profiler fast stops each leave its baseline/candidate postmasters running after
automatic directory deletion. Test observers retain exact PID/start/data
identities and clean only those allocations during emergency red teardown.
No real provider, user data or production service is involved.

SIGTERM now cancels registered diagnostic owners through a shared scope. Nested
and concurrent calls share a handler, which is restored after the last owner
finishes. Existing shielded cleanup survives repeated signals. The evaluation
CLI reports cancellation with exit code 143. An in-flight process creation task
is retained and shielded so cleanup can obtain, terminate and reap its child.

The default `controlled_database()` path now owns a private root and delegates
inner allocation deletion to it. Its finally block reconciles that root after
`generator.close()`, including a failed/timed-out closer. The same reconciliation
serves the case supervisor: it checks private root boundaries, the PID file's
data identity and a matching `postgres -D` command before a bounded immediate
stop. Uncertain identity or failed reconciliation retains metadata and raises.
A successful fallback does not suppress the original profiler stop failure.
The raw test fixture's no-root directory lifetime is unchanged; controlled
callers no longer use that unprotected default allocation path.

## Complete affected-module results

| Module | Passed |
| --- | ---: |
| `tests/test_agent_commit_postgres.py` | 8 |
| `tests/test_controlled_five_case_lifecycle.py` | 6 |
| `tests/test_controlled_native_state.py` | 1 |
| `tests/test_canonical_controlled_profile.py` | 3 |
| `tests/test_memoir_five_case_evaluator.py` | 14 |
| `tests/test_canonical_turn_publication.py` | 3 |
| `tests/test_lifetime_actual_engines.py` | 14 |
| `tests/test_controlled_supervisor_lifecycle.py` | 6 |
| `tests/test_controlled_lifecycle.py` | 2 |
| `tests/test_canonical_evaluation_cli.py` | 9 |

The six new native scenarios cover direct calls, cancellation during process
creation, the actual CLI, two concurrent CLI cases, and profiler fast-stop
failure/timeout. They verify shutdown for **nine original postmasters**, exact
stop PID/data identities, no surviving case child and absent owned directories.
Two unit checks cover nested/concurrent signal-handler restoration and refusal
to signal an unrelated PID while retaining its identity file. No original
shutdown assertion was deleted, skipped, xfailed or relaxed.

The first four red cases fail, the corresponding first four green cases pass,
and the expanded eight-case selection passes before the complete fixed-commit
run. An exploratory in-flight-spawn probe also passed before explicit shielding;
it is preserved as a passing probe, not claimed as another red reproduction.
Seven changed Python files parse and whitespace checks pass. All selected
native observations ran on Linux/proc; unsupported hosts are explicitly gated
before allocation, and no Mac/native non-Linux coverage is claimed. Cloud PID 1
may retain already-exited daemon zombies; the tests require no running original
postmaster or usable cluster, and verify the supervisor-owned child is gone.

[Per-case outcomes, allocation identities and 30 raw evidence hashes](memoir-baseline-supervision-20261015.json)
record the exact scope. Raw XML/logs remain under `/tmp/memoir-supervision-*`;
final native observers are retained in the selected cloud pytest workspace.
Earlier lifecycle checks did not cover supervisor SIGTERM or failed profiler
closers. Their evidence stays historical, rather than establishing these paths
safe from an empty directory scan.

## Remaining gates

The whole repository aggregate was not repeated at this source. Its preserved
`b1e54e8` ledger, and the earlier 49-case `d08aa21` selection, remain evidence for
their own source and are not current-head aggregate acceptance. Live provider/
judge, semantic or production latency, real Auth, full opt-in UI/artifact/
complete-round and 250-round acceptance, Mac/device/native binaries, production
execution and independent runtime acceptance remain unrun or outstanding unless
separately delivered.

Pending-proposal inheritance and other recorded consequential product decisions
remain open. No SQL/migration, client, PR68 ownership, publication/replay/identity
guard, credential/access policy, real provider call, merge or deployment changes.
