# PR69: four independently reproduced source-review findings

All four findings reproduced on synthetic disposable native PostgreSQL/services,
with external calls blocked before dispatch. Four task-only commits repair them
at fixed source/test head `b1e54e8e65bbb0facc1edeb2d2bb90db99212788`.
No pending-proposal inheritance or other consequential product decision was made.
The draft remains incomplete acceptance.

## Complete fixed-commit results

The completed Python aggregate collected **6,282 records: 5,438 passed, 574
failed, 21 setup errors and 249 skipped**, with four warnings, in **1,339.13
seconds wall time** (JUnit 1,327.407 seconds). Source/test head remained fixed
throughout. All four newly collected cases pass, and the existing five-case
receipt test passes its strengthened visible-character assertion. There are no
newly failing IDs compared with the preserved complete `e15c0fb` run.

| Check on the fixed source head | Result |
| --- | --- |
| Affected eight-module selection | 78 passed, 8 retained failures |
| Five guard cases for the four findings | All passed in affected and complete suites |
| Seven large correctness cases, 600-second allowance | 7 passed, 684.15 seconds wall |
| JavaScript | 501 passed, zero skips |
| Specification acceptance | 55 passed |
| Changed Python syntax / whitespace | 10 files parse; git diff check passed |

All **595 failures/errors** and **249 skips** are individually recorded in the
[follow-up ledger](memoir-baseline-review-four-20261015.json). Dispositions remain
569 stale fixtures/retired contracts, 10 identified tooling/fixture compatibility
cases, 7 environment/case-budget cases and 9 unresolved functional/authority
cases. The six aggregate timeouts remain failed checks despite their separately
passing large-budget reruns. Matching IDs alone does not establish intended
behaviour or make an unmet assertion pass. One synthetic row timestamp differs;
manual trace review confirms the identical unresolved photo-policy assertion.
The eight affected-selection failures are seven old photo-layout expectations
and that same photo-policy decision. The 21 setup errors retain the recorded
browser identity and removed workspace/queue fixture causes.

All 249 skips comprise 214 frontend/locale/historical-browser conditions, 12 live
provider gates, 10 complete-round gates, 4 artifact gates, 6 unavailable Mocker
Compose CLI checks, 2 unavailable Supabase CLI splitter checks and 1 PostgreSQL
TCP opt-in. No new skip was introduced to pass the four regressions.

Mobile, web build and selected standalone Chromium checks were not repeated at
this follow-up head; their earlier `e15c0fb` results remain historical evidence.
Full opt-in frontend/UI/artifact/complete-round gates, full 250-round acceptance,
live provider/judge/semantic or production-latency acceptance, real Auth,
Mac/device/native binaries and independent cloud runtime acceptance remain
unrun or outstanding. The controlled app-server and provider sentinels make no
model quality claim.

## Findings and repairs

| Finding | Red reproduction | Repair and preserved assertion |
| --- | --- | --- |
| P1 controlled profiler inherits research/gateway authority | A qualified synthetic Perth birth/place input reaches historical discovery twice while the receipt claims zero requests; sentinels prevent real discovery/source calls | `bad5f54`: an allowlisted environment covers the entire campaign, including SQL/publication cleanup; historical research is explicitly disabled and inherited provider, worker and proxy settings are absent. The hostile-config regression checks actual canonical worker delivery, zero discovery/inspection and no non-mock HTTP transport, cleanup isolation, and exact restoration of the caller environment. |
| P2 another edition masks a stale secondary event | English A+B writing and Chinese A-only writing share a partition key. A normal `apply_user_memory_events` update advances B to revision 2 without changing policy epoch. The broad partition predicate remains true and dispatch raises PT409 for the stale English request | `9e34703`: retirement and dispatch share the same owner/project/locale/partition/event and requested-root resolver. It excludes later snapshots and mismatched policy/preference/root authority. The regression retires the English request, preserves stored prose, composes an unrelated English request, drains canonical progress and returns the lane idle. Other editions cannot validate that requested section. |
| P2 child cancellation orphans native PostgreSQL | Cancel immediately after real `pg_ctl` startup; the Python child exits while its exact cluster directory survives. The red test explicitly stops/removes only that allocation | `3771838`: SIGTERM cancels the child's owning async task so finally runs. The parent allows a bounded grace period, then stops only clusters under the child's preallocated private directory if force-kill is needed. Cleanup is shielded against repeated caller cancellation; uncertain cleanup retains the directory and fails visibly. Native regressions verify normal cancellation and an intentionally unresponsive child, reaped child status, stopped PostgreSQL and absent cluster/root directories. |
| P2 canonical visible-character accounting | A real canonical round delivers 71 visible characters but records `visible_delta_chars=0` | `b1e54e8`: feed delivered canonical `text_delta` text into the existing counter. The native round trace asserts a positive count equal to the exact delivered event text; legacy callbacks remain separate and are not counted twice. |

No original behaviour assertion was removed, skipped, xfailed or relaxed to get
these results. The optional fixture event selection constructs consistent
outline/summary/disposition metadata and passes the actual schema validator and
renderer before native SQL commit. No publication, replay, identity or lease
guard is replaced.

## Evidence provenance

The first static rerun lacked this worktree's web dependency link. Its module
resolution failure is retained. The link was restored to the already installed
checkout dependencies; the initial Python aggregate was gracefully interrupted
and excluded as incomplete. A fresh complete aggregate starts after restoration.
Source and test files remain fixed for the complete run.

Red/green XML and logs live at `/tmp/memoir-review4-*`; final hashes and all
remaining per-case dispositions are in the accompanying JSON. The earlier
`e15c0fb` complete report and ledger remain unchanged as historical evidence.
No earlier pass or classification alone proves a new-head assertion passes.

All native PostgreSQL checks use this task's owned Unix-socket clusters. Cloud
PID 1 may retain an already-exited daemon zombie; lifecycle assertions require
no running postmaster, no usable cluster, an absent owned cluster/root directory
and a reaped case child. They do not claim this process can reap PID 1's unrelated
historical zombies. No broad process cleanup occurs.

The known pending-proposal overlap regression remains an ordinary failing test.
A decision is still needed between inheriting pending proposals under later-root
review authority and waiting for existing decisions before another rework. Other
benchmark, legacy dataset, model-bound and photo/access policy decisions remain
in the existing contract record. No guard is relaxed to choose them implicitly.

PR68's polling, attribution and readiness migrations remain with its owner. Its
three overlap paths are unchanged by these four follow-up commits. No real user
data, live provider/source/geocoding/photo contact, production migration,
deployment, merge, access/security-policy change, Mac or native-device work was
used. Evidence remains `mock_only`; semantic/production-latency acceptance and
independent cloud runtime acceptance remain outstanding.
