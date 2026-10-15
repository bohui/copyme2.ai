# Canonical baseline tooling continuation

The historical ledger and complete `165f330bd13051f66daeb3d172727a21e2dd202a`
checkpoint remain authoritative for those runs. This continuation does not turn
remaining historical failures into passes by diagnosis or by changing labels.
The next aggregate must record its own exact commit, every failure/error/skip,
and the separately bounded large correctness checks.

## Controlled delivery and resume

`scripts/canonical_turn.py` consumes the production canonical turn response
through actual ASGI delivery. Authenticated `UserStorage`, database identity,
provider admission, leases, persistence and publication guards execute normally.
The caller retains its HTTP storage facade between rounds; each turn still
closes its publication scope and lease. Evaluation correlation and redacted
worker evidence remain a private driver sidecar, outside public governed results.
Canonical checkpoint reads consume the frozen canonical read response under its
SQL publication guard. They do not read the retired legacy draft adapter.

The controlled five-case path runs each case in a separate subprocess with its
own disposable native Unix-socket PostgreSQL database. It inherits no configured
database/provider authority. JSON snapshots restore only scoped synthetic rows
into another new disposable database. Generated columns are recomputed; all
new turns still use normal canonical authority. A legacy saved place display
can survive resume without being promoted into canonical narrator evidence.
The resumed fixture/pilot regressions retain their Perth + Hobart and zero
geocoding-contact assertions. A second native regression restores canonical
identity, original sources, completed rounds and places, then accepts another
turn through actual SQL publication. Telemetry publication remains with an
explicitly supplied parent publisher, using minimized receipts; it is not
configured or sent by the native child.

The controlled canary uses an explicitly selected `synthetic-byte-bpe` model,
records requested/effective names separately and remains `mock_only`. Its scoped
broker now performs the required canonical receipt coverage scan before queuing
work. Its streamed private endpoint honors NDJSON. Native regression coverage
retains ten original rounds, two drafts, exact source/round counts, single-attempt
background joins and story-free Temporal histories. The live pinned
`gpt-5.6-luna` name has no reviewed canonical collector/lane token bound. Live
execution refuses before store/provider work pending an approved model binding;
no new model alias or byte-token exemption is installed.

## Progressive selected-section rework

The existing approved behaviour is documented in
`docs/workspace-memory-actions-acceptance.md`: select current saved writing,
keep the original until review, preserve original evidence and other sections,
and do not change canonical event facts, rounds, phase or formal authority.
The old rework predicate only recognized legacy evidence/photo partition keys.
Progressive admission now requires a real, current stored writing identity with
all original source/event dependencies. Editorial pages use bounded exact source
spans and selected prior writing. They advance independently of canonical event
and message-summary cursors. The canonical composer treats the selected writing
as requested revision rather than immutable unchanged prose.

The stored selected key controls the target. Model presentation IDs cannot route
a proposal to a sibling. SQL rejects multiple rewritten blocks, another event
scope, expanded original evidence, stale publication and conflicting replays.
Existing proposal CAS, ownership, privacy, draft/review evidence and authenticated
readback remain in force. The predecessor lookup uses the requested edition;
another edition's latest root cannot reset its event cursor. Copied application
conflicts retain current main's `PT409` behaviour. No production migration was
run.

New/updated fixtures build actual schema-valid drafts and execute the real
JavaScript plan/validator/renderer. Their per-chapter revisions distinguish a new
chapter from the manuscript revision. At `cd73917`, nine older photo/rework regressions remained failing and
preserved: seven enumerate legacy partitions, one strands an invalidated request,
and one expects an instruction bound to an old policy root to survive a global
photo-plan policy change. The current producer stores progressive passages and
declares `assets=[]`. The stranded-request recovery is now repaired independently;
its new native test keeps originals/rounds unchanged and finishes the current
lane without rebinding the old instruction. The other eight failures remain;
the old epoch-retention expectation needs a policy decision. The
separate corrected 16-case stored-image matrix remains narrower evidence about
validated synthetic catalogs, exact dependencies and preservation. It does not
establish a production upload-to-composer asset mapping or live rendered-image
acceptance. An authenticated photo-plan change can also advance policy authority;
the new regression preserves stored original bytes while rejecting the stale
root/request rather than bypassing that policy fence.

## Pending proposals across later editorial roots

A further native SQL reproduction uses actual schema-validated synthetic drafts
and controlled phase receipts. A completely processed root has a pending proposal
for A; the application then admits rework for B. Saving B leaves A's stored bytes
unchanged at that point, but the next page queues A again. This does not establish
an actual overwrite or exposure. The [retained failing regression](../../tests/test_progressive_rework_proposal_overlap.py)
records the gap and is part of the next complete suite.

The predecessor lookup currently uses completed roots, while
`set_lifetime_private_draft_proposal` accepts only the latest proposed root and a
section in that same snapshot. Carrying pending proposals into later roots also
needs a review-CAS inheritance contract; changing only the cursor would strand
review of the older proposal. Decision: inherit pending proposals unchanged and
review them against the latest root digest, or wait for existing decisions before
admitting another rework. The published patch does not relax any review guard or
claim this interaction repaired.

## Benchmark and dataset decisions still needed

The old profiler asks for legacy/compact prompt comparison and thread resume.
Canonical execution always uses `lifetime-v1` and fresh ephemeral homes. Its six
old assertions remain preserved. A separately versioned controlled candidate,
`scripts/profile_canonical_controlled.py`, clones actual SQL prestate, alternates
pair order, carries identical synthetic input/turn identity, executes canonical
runtime/private-worker publication, and stops at the first failed delivery.
Requested settings and actual prompt/home policy are separate fields. Its
controlled app-server is checked in; provider model calls are zero. Two tests
cover matched real state and the failure stop. This is a candidate benchmark
contract, not a completed legacy comparison or semantic/latency acceptance.

Decision: adopt an explicitly canonical configuration comparison, or keep the
old legacy prompt/resume benchmark blocked. Do not restore retired engines or
claim that changing the old requested prompt setting changes the actual prompt.

The generic `apps/api/evaluation_cases.py` dataset also expects retired inline
family/timeline/task markers, and one export case starts from assistant-style
saved memory without canonical original provenance. Decision: approve a separately
versioned canonical dataset and its expected product effects, or keep those legacy
cases blocked. Do not import assistant prose as original testimony or invent
collection readiness/publication authority to satisfy the old fixture. The
canonical evaluation driver and native controlled cases are repaired independently.

Previously recorded workspace access decisions remain open: older five-round
opt-in expectations versus current access rules, and NO_MATCH-before-geocoding
versus current target gating. No unrelated product policy is rewritten here.

No real user data, external model/geocoding/photo calls, production migrations,
Mac execution, merges or deployments were used. Full 250-round/live/provider,
real-Auth, device/native-binary and independent cloud runtime acceptance remain
separate checks unless explicitly evidenced in the final ledger.


## Complete continuation checkpoint and follow-ups

The complete `cd739174823a1fc907b2ee845f7a86c8c059e9c4` aggregate records 5,429
passes, 576 failures, 21 setup errors, 249 skips and three warnings in 1,379.35
seconds wall time. All seven larger-budget correctness cases pass. Every outcome
and disposition is preserved in `memoir-baseline-checkpoint-cd73917-20261015.json`.
Two pure orchestration fixtures and one unrealistic migration-order fixture were
newly failing at that checkpoint. The corrected pure boundaries retain the
original 15/50-round, checkpoint, correlation and 180-reservation assertions and
make no native claim. Upgrade tests now stage a real prefix and verify data
preservation before forward migrations. Seven focused follow-up checks pass.
The next aggregate uses one fixed commit after these repairs; this checkpoint
is complete evidence for its own source and is not final acceptance.

## Final fixed-commit aggregate

The completed aggregate at `e15c0fbeb3b2fe5658fee9ea6361c98062deaca4`
records 5,434 passes, 574 failures, 21 setup errors, 249 skips and three warnings
in 1,289.34 seconds wall time. All seven large correctness cases pass with their
separate 600-second allowance; the aggregate's six case timeouts remain failures.
The two pure orchestration fixtures, migration-history fixture and stranded
request recovery now pass. The pending-proposal overlap regression above remains
an ordinary failing test, with no review-authority relaxation.

The [final report](memoir-baseline-final-20261015.md) and
[complete current per-case ledger](memoir-baseline-current-checks-20261015.json)
record every remaining failure/error, skip, classification and unrun check.
Acceptance remains incomplete. Later evidence-only commits preserve the tested
source and test files unchanged.


## Four source-review repairs after the complete checkpoint

The four follow-up findings are independently reproduced and repaired at
`b1e54e8e65bbb0facc1edeb2d2bb90db99212788`: controlled-profiler offline authority,
exact requested locale/root retirement after a secondary event change, bounded
case-child/native-cluster cancellation cleanup, and delivered visible-character
accounting. The complete follow-up run records 5,438 passes, 574 failures,
21 setup errors, 249 skips and four warnings; all five guard cases pass. All
seven large correctness checks pass separately; aggregate timeouts remain failed.
The [follow-up report](memoir-baseline-review-four-20261015.md) and
[complete follow-up ledger](memoir-baseline-review-four-20261015.json) preserve
reproductions, every remaining case, prerequisites and unrun checks. Earlier
complete ledgers remain unchanged. No pending-proposal inheritance, benchmark,
legacy dataset, model-bound or other product-policy decision is resolved here.


## Residual fast-stop failure and process-identity platform coverage

The earlier graceful/unresponsive-child evidence did not establish cleanup when
the child's own bounded fast stop failed and TemporaryDirectory erased the
allocation. Real nonzero and ten-second-timeout reproductions left a running
postmaster after that deletion. `3a2243131583e6ffcab75d5b6b2af99fe0f320e9` makes
caller-supplied allocation roots explicitly supervisor-owned through shutdown
reconciliation. Both fault variants now preserve the original PID/data identity
for real parent immediate stop; standalone no-root fixture lifetime is unchanged.

The source-derived portability finding is addressed by
`d08aa215b9a1670727d1a89248957ce8e5028219`: Linux/proc identity availability is
checked before PostgreSQL tools/allocation. Four native ownership regressions
run on the selected Linux host; two unit simulations test the unavailable
platform/proc gate. No Mac execution or native non-Linux coverage is claimed.
All seven complete affected modules pass 49 tests with no failures or skips at
that fixed source. The full repository aggregate was not repeated for this
follow-up; its earlier b1e54e8 results remain historical. The
[follow-up report](memoir-baseline-cancel-retention-20261015.md) and
[per-case/process evidence](memoir-baseline-cancel-retention-20261015.json)
record scope, red/green cases, identities, hashes and unrun checks. No pending
proposal inheritance or other consequential product decision changes.


## Supervisor SIGTERM and profiler-owned allocation reconciliation

The d08aa21/6177248 checks did not cover SIGTERM killing the supervisor or the
default profiler path losing metadata when a closer failed. Four native cases
reproduce those two paths. `a294f8b6cc47952d1e85b2003352f36dec69a347` adds shared
SIGTERM-to-owner cancellation with shielded cleanup, retained in-flight child
creation, and reconciled private roots for default controlled_database calls.
The native scenarios stop nine original postmasters across direct/CLI,
concurrent, creation and profiler fast-stop fault paths. Unknown ownership or
reconciliation failure remains visible and retains metadata. The original
profiler closer failure is not silently converted into success.

All ten complete affected modules pass 66 tests with no failures or skips at
that fixed source. This is not a new whole-repository aggregate; earlier whole
and focused results remain pinned to their own sources. The
[supervision report](memoir-baseline-supervision-20261015.md) and
[per-case/process evidence](memoir-baseline-supervision-20261015.json) record red/
green results, allocation identities, hashes, platform limits and remaining
gates. No pending-proposal inheritance or other product-policy choice changes.
