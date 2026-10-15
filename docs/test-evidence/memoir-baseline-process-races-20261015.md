# PR69: snapshot/fork/reap and creator-exit cleanup races

Historical focused 51ca checkpoint. The [later complete cloud aggregate](memoir-baseline-cloud-aggregate-20261015.md) records current whole-cloud outcomes and separately attributed parent-verified cloud/Mac updates.

Exact tested source/test commit: `51ca7fe5629f74f6a657a7a2e611d86dabf91bf8`.
Fifteen complete affected modules plus the complete ordinary proposal-overlap
module record **97 passed, two failed, zero errors/skips** across **sixteen
selected modules** in **269.1 seconds** wall time
(JUnit 269.049 seconds). Both failures remain ordinary
failures. Acceptance is incomplete; this is not a whole-repository aggregate.

## Snapshot race: confirmed runtime/tooling defect

The deterministic regression uses real process enumeration and processes:

1. A registered new-session leader waits without a descendant; real `ps`
   captures that leader in its owned group.
2. The session-lookup hook releases a pipe handshake. The actual leader forks a
   same-group/session descendant, waits for its identity marker, then exits.
3. The test reaps the leader and the real `os.getsid(leader)` raises
   `ProcessLookupError`. The new descendant remains running.

At ae174/d373, reconciliation skips the missing captured PID, concludes that
the group is empty, reports `verified=true`, removes the identity root, and
issues no signal while the descendant is in `S` state. Three real fork/reap
variants preserve that false success before separately verified individual-PID
test teardown. The four-case new snapshot suite records **four red failures**.
No PostgreSQL or provider is allocated by this reproduction.

Reconciliation now takes a fresh process-table snapshot whenever a captured
live member disappears during session lookup. It verifies the fresh members'
numeric sessions and preserves the recorded group and leader-birth checks.
An early birth check refuses a known changed leader before enumeration; the
existing check immediately before group signalling remains. Repeatedly unstable
snapshots have a bounded refresh budget and per-command timeout, then retain
metadata and raise. No unknown group is signalled as a fallback.

The successful fresh-snapshot case observes and verifies the real descendant,
stops only its registered group, and removes the root after shutdown. Fresh
descendants with a changed session or denied inspection remain unsignalled with
metadata retained; separate guarded test teardown stops their exact individual
PIDs. An unstable-snapshot unit case verifies bounded refusal without signals.
Generic success, Apple-compatible columns, leader-birth refusal and existing
session/permission refusal cases remain passing. Incomplete live command-birth
metadata is still refused, rather than converted to verified cleanup.

## Creator-exit race: confirmed test-harness defect

Five new cases start an actual `scripts.controlled_five_case` creator and a
fresh native PostgreSQL cluster. The creator is held after allocation; no
generation/provider work is performed. During its emergency command-line
inspection the test kills the actual creator and either leaves its exited
zombie or reaps it. The original helper then sees an empty or missing proc
command and aborts before attempting PostgreSQL stop, while the recorded
postmaster is still running. The pre-fix native selection records **three
failures and two passes**, including a recorded-birth mismatch that the old
running predicate silently skipped.

The helper now checks birth/state before and after command inspection, including
a missing proc file. A verified gone/zombie creator needs no signal and permits
independent exact-identity database cleanup. A live creator with changed birth,
changed command, or unavailable command identity still raises and retains the
allocation; those negative cases are not suppressed. Postmaster command
inspection uses the same revalidation helper. A creator disappearing just before
its signal is accepted only after rechecking its recorded identity/state.

Both real exit variants now perform exactly one immediate stop of the original
database and remove its owned allocation. The three refusal variants preserve
the live database/root until separate exact-identity test teardown stops them.
All five creators are reaped by their test owner. The records distinguish helper
cleanup from subsequent test teardown, avoiding any inference from a failed
teardown or absent directory. The older historical failed-teardown claim remains
withdrawn, with its separately verified later cleanup preserved in earlier
ledgers.

## Complete selected-module outcomes

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
| `tests/test_controlled_process_snapshot.py` | 4 | 0 |
| `tests/test_controlled_emergency_cleanup.py` | 5 | 0 |
| `tests/test_progressive_rework_proposal_overlap.py` | 0 | 1 |

All four focused modules pass **22 cases** after both repairs. The complete
fixed-source selection verifies **22 instrumented original postmasters across
sixteen native scenarios**, including the eleven existing supervisor/CLI,
profiler, actual single/nested wrapper/default-deadline and long-TMPDIR scenarios
and five new creator-inspection scenarios. Original PID/start/data/owner
identities, stop attempts, short sockets and subsequent observations show every
recorded postmaster stopped and original owned data paths absent. Intentional
refusal observations are shown before their separate guarded test teardown.

Two remaining failures are classified and retained without skip, xfail, deletion
or weakened assertion:

- `tests/test_isolated_check_runner.py::test_timeout_stops_a_term_resistant_descendant_after_its_parent_exits`:
  the exact descendant has exited but remains a PID-1-owned `Z` process. The
  ordinary assertion requires absence and stays failed. `stop_owned` has the
  same AST as ae174; no live descendant is observed. The earlier detached-parent
  comparison remains historical evidence.
- `tests/test_progressive_rework_proposal_overlap.py::test_rework_does_not_revisit_a_completed_proposal_on_another_section`:
  reworking B queues completed pending proposal A again while A's stored bytes
  remain unchanged. Inheritance into the latest review authority versus waiting
  for existing decisions remains an unresolved consequential contract. The
  ordinary failure is included and reproduced at this source; no SQL, cursor,
  review/publication guard or product-policy choice is changed.

## Evidence, iterations and remaining coverage

The [complete ledger](memoir-baseline-process-races-20261015.json) embeds all 99
outcomes, real red and green process/creator observations, independently verified
test teardowns, original native identities, eight Apple-compatible process-call
logs, all four changed source/test hashes and 72
raw evidence hashes. An evidence-only child preserves the tested code/tests.
Current batch pointers identify this source and ledger; historical b1e54e8
aggregate fields/counts/classifications and all earlier checkpoints remain
unchanged.

The ledger also retains two implementation/probe iterations: an initial snapshot
repair had sixteen passes and one birth-refusal message failure before early
birth validation was added; a preliminary creator probe held stdin open and was
interrupted before a valid reproduction. EOF was corrected before the recorded
native red run. Neither provisional result is claimed as final acceptance or a
separate product defect. Raw logs/XML remain hashed and classified.

All execution uses disposable synthetic data, fake workers and zero configured
provider/service authority variables on the selected Linux/proc host. Native
cases explicitly require those prerequisites before allocation. The
Apple-compatible shim delegates supported commands to real Linux `ps`, and
`os.getsid`/process operations are real Linux operations; **native Mac runtime
coverage remains unrun**. Existing short-root ownership, 5/20/10-second shipped
deadlines and PR68-owned client polling/attribution/migration work remain
separate and unchanged. No real user/provider, deployment, migration, access or
operator action is involved.

Independent re-review of the final exact head must be routed through the parent
thread and remains outstanding. Other gates remain the two ordinary failures
and consequential proposal policy; native Mac/non-Linux coverage; a current
whole-repository aggregate; live provider/judge, semantic/latency and real Auth;
full opt-in UI/artifact/complete-round and 250-round acceptance; and native
device/binary or production execution. No full acceptance is claimed.
