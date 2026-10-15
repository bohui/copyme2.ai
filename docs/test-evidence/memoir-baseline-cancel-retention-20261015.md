# PR69 residual cancellation P2: retain supervisor-owned allocations

The residual fast-stop failure is repaired in `3a2243131583e6ffcab75d5b6b2af99fe0f320e9`.
The Linux/proc prerequisite gate follows in `d08aa215b9a1670727d1a89248957ce8e5028219`; all final affected-module checks
use that exact fixed source/test commit. The draft remains incomplete overall
acceptance. This follow-up changes three Python files; no product policy,
publication/replay/identity guard or production migration changes.

Previously, the child fixture's `TemporaryDirectory` removed the allocation when
its bounded fast stop raised. The parent then saw no data/PID file and removed
its now-empty root while the detached postmaster was still running. Both a
nonzero fast-stop command and a command exceeding its ten-second deadline
reproduce a sleeping live postmaster (`/proc` state `S`) after cancellation.
The red tests independently retain the exact PID/start identity and data path,
and stop only that verified daemon during emergency test teardown.

A caller-supplied `directory_root` now explicitly delegates allocation deletion
to the supervising caller. The fixture still attempts its bounded fast stop;
its exception is not suppressed. It leaves data and `postmaster.pid` intact
until the parent reconciles the original allocation with immediate stop. Normal
standalone fixtures with no supplied root retain their existing directory
lifetime. The parent removes its private root only after its existing shutdown
verification succeeds; uncertainty remains a visible error with retained state.

The native regression now covers graceful cancellation, an unresponsive child,
fast stop returning 42, and fast stop exceeding the actual ten-second fixture
deadline. Each failure-path test records that fast and immediate stop see the
same postmaster PID and data path, then requires no running postmaster or stop
command, a reaped child, and absent allocation/root directories. Existing
cleanup assertions are retained. An already-exited daemon zombie may remain
with this cloud PID 1; it is not a running server or usable cluster.

The command shim injects only the external fast-stop fault. PostgreSQL startup,
SQL, immediate stop and process checks remain real and task-owned. No real user
data, external provider/source contact, production/security action, Mac work or
unrelated process cleanup occurred. The pending-proposal inheritance policy
and other consequential decisions remain open.

## Fixed-source results

The seven complete affected modules pass **49 tests, zero failures/errors and
zero skips**, in **140.62 seconds wall time** (JUnit 140.546 seconds). All four
native shutdown modes run on Linux; the two prerequisite simulations pass as
unit checks rather than contributing skipped native cases. Three changed Python
files parse, and whitespace checks pass.

| Runtime reproduction / selection | Result |
| --- | --- |
| Failed child fast stop before the fix | 1 failed; live postmaster after allocation deletion |
| Timed-out child fast stop before the fix | 1 failed; live postmaster after allocation deletion |
| Four native modes after retention fix | 4 passed |
| Seven affected modules at retention-only `3a22431` | 47 passed |
| Unsupported-platform/missing-proc prerequisite before guard | 2 failed before any server allocation |
| Guard plus four native modes after platform fix | 6 passed, no skips on Linux |
| Seven complete modules at final source `d08aa21` | 49 passed, no skips |

The [per-case evidence](memoir-baseline-cancel-retention-20261015.json) includes
exact postmaster identities, fast/immediate-stop observations, absence of each
owned allocation/root, all selected outcomes and 22 raw evidence hashes. The
case child and stop commands are reaped; no running task-owned server survives.
The old graceful/unresponsive-child checks did not cover a failed child fast
stop. Their earlier evidence remains historical, with this missing failure path
now reproduced explicitly rather than inferred safe from an empty directory scan.

## Scope of validation

The seven complete affected modules cover the shared native fixture, four
cancellation modes, controlled state restore, hostile-config canonical profiling,
five-case delivery/receipts, canonical publication/replay and actual-engine
ordering. Source/tests stay fixed for that selection. The original whole-repo
aggregate, JavaScript/specification, large-budget and other application checks
are preserved at their earlier tested commits; they are not claimed as reruns
of this follow-up. Live provider, full opt-in browser/artifact/complete-round,
real Auth, semantic/latency, device/native binaries, production and independent
runtime acceptance remain unrun or outstanding unless separately evidenced.


## Process-identity platform prerequisite

Independent source review found that the native lifecycle observer itself read
Linux `/proc` after PostgreSQL startup without gating the platform. The tests
now check Linux plus `/proc/self/stat` availability before checking PostgreSQL
tools or allocating any server. Four native ownership/shutdown regressions still
run unchanged on the selected Linux host. On an unsupported host these four
cases explicitly skip with a Linux/proc identity prerequisite reason.

Two additional unit cases simulate an unsupported platform and missing `/proc`
on this Linux host. A sentinel forbids even a PostgreSQL tool probe; both failed
before the guard was added and now verify the prerequisite gate. These are
Linux-hosted guard tests, not Mac execution or Mac lifecycle coverage. No native
Mac or other non-Linux coverage is claimed. The shutdown ownership, PID/start
identity, fallback identity and server-exit assertions are preserved.
