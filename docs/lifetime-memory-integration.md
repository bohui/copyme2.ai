# Issue 60 integration and acceptance ledger

Current development decision (2026-10-14): the user authorized retirement of the legacy conversation engine and activation of the canonical engine in Supabase project `vpzhimeqmuzyzfozcjnq`. This project is in development and requires no conversation backward compatibility. Microphone recording/transcription and spoken replies remain supported through the saved canonical conversation.

Migration `202610140001_canonical_only_conversation.sql` removes the obsolete direct realtime rollout table and attestation functions. Direct realtime and raw legacy worker admissions remain denied. This is an explicit engine retirement decision, not an assertion that all external provider calls were verified terminated. The old implementation did not retain provider call IDs.

The sections below retain the historical implementation/review evidence. Their opt-in, legacy fallback and separate rollout clearance instructions are superseded by this development decision. `MEMOIR_LIFETIME_GENERATION_PAUSED` remains the generation pause control; publication, privacy, owner and lease checks remain required.

## Progressive background composition, 14 October 2026

Every five completed rounds enqueue the existing durable composer lane. Migration
`202610140004_progressive_composer_batches.sql` replaces preparation per quotation
with a bounded batch of up to five new narrator messages. One grounded summary is
saved for that batch, then the composer revises the affected existing passages.
Original narrator rows, quotations, versions and absolute offsets remain the
evidence; a summary is derived context and cannot replace or widen that evidence.

Unchanged supported passages are restored byte for byte before validation and
review. The database retains unaffected passages across snapshots. Stable storage
keys include canonical event identity, preventing unrelated paragraph IDs from
colliding. Approved or locked writing receives a proposed revision. Every source
and event dependency participates in readback and withdrawal cleanup, including
secondary sources and confirmed photograph associations.

Composition remains outside the collector/streaming request, in the existing
Temporal worker. Owner-scoped draft polling exposes only operational phases
(queued, summarising, drafting, reviewing, saving and saved). Thinking steps may
continue updating after the assistant reply finishes; polling never changes its
text or rerenders an active stream. Voice input continues through the same saved
canonical conversation.

Draft heads expose both extraction and composition progress. An exhausted
extraction retry stops the draft spinner at the five-round checkpoints and the
20-round sample; automatic retries disclose recovery while retaining originals.
The sample POST reads existing canonical work by default. Only `retry: true`
resets failed lanes. Cancellation releases the canonical lane lease and retains
completed preparation and draft checkpoints for the next worker.

The API and Temporal worker use separate local SQLite receipt-cache volumes.
Apple Container runs them in separate Linux VMs, where sharing WAL files caused
SIGBUS during concurrent commits. PostgreSQL remains the authority for canonical
inputs, outbox delivery, lanes and manuscript checkpoints; an empty worker cache
replays unfinished receipts without replacing those saved records.

The scoped live-test allowance extends conversation access without moving sample
eligibility. Its recall status carries the normal `sample_rounds` milestone so
both the API and UI still expose the sample after twenty completed rounds.

An explicit timeline correction can invalidate the old strategy during its own
commit. The correction remains committed, its stale strategy is discarded, and
the worker releases only metadata authority before claiming a fresh policy-bound
snapshot. Wording corrections use ordinary event updates instead of empty
placement patches.

Temporal lane activities send a content-free heartbeat every fifteen seconds.
A sixty-second heartbeat timeout allows redelivery after worker loss, while
PostgreSQL lease tokens and saved page checkpoints fence resumed execution.

Large testimony continues through exact bounded windows, and a backlog may require
several batches. Coverage advances only after the corresponding summary and model
proofs are saved; resource limits, original policy/lease fences and the three-draft
attempt ceiling remain enforced. This does not promise a fixed model latency or
extend an evaluation deadline.

`tests/test_progressive_composer.py` exercises the real five-to-ten-round database
flow, unchanged writing, protected proposals, secondary-source withdrawal, long
message continuation and matching repair validation. Live English and Chinese
cases use real model calls through the same composer orchestration; see
`docs/memoir-live-skill-tests.md` for their bounded scope.

## Execution and rollback

`MEMOIR_LIFETIME_MEMORY=true` selects canonical identity/admission for new verified
accounts and mapped canonical projects. Owned unmapped legacy projects retain their
explicit adapters. Existing single/multiple/unscoped histories return mapping-required;
no startup hook chooses a historical project or backfills its evidence positions.

Canonical routing is monotonic: once an authenticated owner has a canonical identity,
turns, reads and worker admissions remain governed even if `MEMOIR_LIFETIME_MEMORY`
is later false. That flag stops new adoption and model work; it cannot restore legacy
unbounded prompts, caches or commits. `MEMOIR_LIFETIME_GENERATION_PAUSED=true` also
pauses model work while the adoption flag stays enabled. Saved receipts, bounded reads,
explicit settings and required outbox maintenance remain available. Additive schema
remains in place; no ID rewrite, destructive reversal or deployment is part of rollback.

Legacy model/store admission and actual response publication serialize against first
canonical adoption on the authenticated owner's row. A missing authority connection
fails closed. `MEMOIR_LEGACY_ONLY_DEPLOYMENT=true` is an explicit operator assertion for
a genuinely pre-canonical deployment, only when the adoption flag is false; it is not
a safe mixed-cohort configuration. When a transactional DSN is present it always checks
mapping, regardless of this assertion. No production settings are changed by this PR.

A server-configured `MEMOIR_PUBLICATION_DATABASE_URL` is required for governed
publication. Configuring persistent production access is a separate approval gate.
The existing HTTP/PostgREST storage transport cannot hold a transaction across send.
Missing transactional publication configuration fails closed.

## Exact boundaries

- App-server admission is completed stdin write/drain under the original source,
  policy, preference, phase and lease fence. It does not claim knowledge of the
  opaque app-server's later downstream provider HTTP timing.
- API-to-worker request bodies have the same original-fence guard through transport
  consumption. In-flight work still needs separate output and commit fences.
- Actual outer ASGI send completion is the user-visible publication boundary.
  The main request-context middleware uses direct ASGI forwarding, not a buffering
  BaseHTTPMiddleware queue. CORS/request IDs/cookie CSRF/transaction behavior remain.
- Correction commits wait only for bounded active sends. Already delivered or
  network/proxy-buffered bytes cannot be recalled. Old queued chunks/results are
  discarded; newer fences never relabel old bodies.
- Read-side fences do not acquire a generation lease, so history/receipt polling can
  coexist with model work. They are captured before reading and retained unchanged.

The collector always uses a fresh ephemeral execution home because a resumed opaque
transcript cannot establish the declared input budget. Compatible-resume helpers are
unit tested, but production-compatible warm resume is not claimed. Product identity
and saved-turn idempotency are independent of an engine thread or worker volume.

## Boundedness and current evidence

Collector transport: reviewed maximum context 131,072, input 65,536 and production
framing at least 2,048; output headroom is explicit. Serialized UTF-8 bytes are a
conservative bound only for the explicitly supported byte-tokenizer-compatible
models. Actual instructions/schema/pins/current input are included. These are
mechanical limits, not semantic quality, latency or cost promises.

New narrator messages have an explicit16000-UTF8-byte admission bound before acceptance.
Accepted evidence is never silently truncated. All active privacy pins must fit their
separate16384-byte envelope; overflow stops before provider admission, retains the
accepted source and returns a maintenance-needed receipt. Ordinary historical
continuity is a separately bounded, explicitly incomplete relevant working set.

Source pages contain at most 32 records, with exact 2,048-character spans. Opaque cursors
bind owner/conversation/policy/high-water/query. A constant-size database-maintained
positive-position count/max ledger proves complete 1..high-water inventory; historical
upgrade gaps return `LIFETIME_INVENTORY_REQUIRED`, never an empty complete history.
Only an explicitly approved fixture inventory is backfilled in tests.

Checkpoint maintenance records bounded pages/chunks/tombstones and a predecessor,
then publishes against the same fence. It never marks an unread interval covered.
Current authoritative pins are rehydrated without discarding valid historical coverage
just because a question changes. Name provenance is private exact-source metadata;
withdrawal/edit clears generated name bytes, while independent explicit settings
survive. Generic stale profile writes cannot resurrect invalidated names.

Required projections use a durable, inspectable outbox. The existing service worker
polls a bounded service-only maintenance RPC without an end-user token or another
user visit, including while generation is paused. Busy foreground leases release
all candidate locks; failed projections have bounded backoff and inspectable terminal
failure. This requires the existing worker/broker to be running. Optional harness artifacts
are not required for recovery or advertised as complete backups. Artifact manifests
are deltas with scoped predecessors/removals and normalized effective coverage checks.
The measured 10,000-manifest fixture produced 7,433,098 total manifest bytes and 625 current
chunks representing 40,000 logical bytes, with 174,375 live chunk-row bytes. This fixture
makes no claim about production upload rates.

## Reproducible offline checks

Use a fresh test environment with the project test dependencies and the optional
`lifetime-memory` dependency. Real database tests must use an isolated disposable
PostgreSQL 17 cluster, never a configured Supabase or production service:

```
PATH=/path/to/postgresql/17/bin:$PATH MEMOIR_TEST_POSTGRES_BACKEND=native-tcp \
  python -m pytest -q tests/test_lifetime_outer_publication.py \
  tests/test_lifetime_memory_runtime.py tests/test_lifetime_memory_commit.py \
  tests/test_lifetime_memory_source_pages.py tests/test_lifetime_memory_upgrade.py \
  tests/test_lifetime_home_recovery.py tests/test_lifetime_name_provenance.py \
  tests/test_lifetime_workspace_adapters.py tests/test_lifetime_actual_engines.py
```

Separate heavy structural gates include `test_lifetime_memory_capacity.py`,
`test_lifetime_outbox_postgres.py`, `test_lifetime_draft_coalescing.py` and
`test_lifetime_composer_capacity.py`. Coordinate resource windows; never substitute
mock storage for RLS/lock/cursor/race evidence. Run the complete Python suite and
applicable frontend/build/browser gates on the final immutable integration commit.

Interim evidence, not final acceptance:
- Clean archive of local 4b01cc1 / remote 86be131: 156 route/import tests passed;
  25 database-dependent cases explicitly skipped in that invocation.
- Independent checkpoint unit review: 196 passed.
- Isolated Git worktree pinned to 11c3906: 4,253 passed, 725 skipped in 389.28 seconds.
  Skips: 512 real-PostgreSQL/opt-in environment checks, 205 frontend/browser/AuthHTTP,
  four AppleContainer/Mocker and four live-evaluation cases. None is an acceptance pass.
- The mixed English/Chinese 10,000-turn fixture passed in 96.70 seconds, including
  exact bounded-page readback of every source, a rare turn 3 fact at turn 9,900,
  source-version correction and cold-context recovery. Admission was 42.33 seconds.
  This measures an isolated fixture, not production model latency or semantic quality.
- Integrated real-PG outer-app/runtime/home/name/source-upgrade batch:74 passed;
  one new workspace error-import issue was fixed and its isolated rerun passed.
- Final maintenance/adoption/read/outbox batch: 89 passed in 17.31 seconds, including
  real SQL authority versus both provider admission modes, outer send/adoption races,
  worker-only crash recovery without another user visit, terminal failure and contention.
- Composer: 38 capacity/safety cases passed, including both 10,000-history gates;
  a subsequent four-case actual caller/SQL renewal delta verifies phase reuse.
- Native: all seven validation stages passed, including three TypeScript configs,
  lint, 59 UI cases, 21 provider-integration cases and 41 OpenAPI operations;
  affected collection recovery checks were rerun after task pagination/retry changes.
- Selected-job 10,000-history capacity passed in 30.84 seconds: every admission
  used the real source RPC, each frozen selected-source page stayed below 20 KB,
  and export reconstructed the selected early original exactly.
- Independent 697ca1f PostgreSQL delta: 154 passed, one stale manual fixture failed
  because its envelope omitted the newly required input_digest. The fixture was
  corrected without weakening production validation. The revised-stack short composer,
  runtime, identity, commit, phase and adoption rerun passed 150 cases (two heavy
  capacity cases deliberately excluded because their separate runs passed).
- Revised-stack JavaScript: 371 passed; OpenAPI matches all 41 operations;
  phase/continuity contracts: 186 passed. Final ordinary Python aggregate is pending.
- Browser fixtures remain blocked in cloud by Chromium socket EPERM.

## Remaining acceptance gates

The bounded composer, selected-source jobs, hierarchical organiser and read APIs are
implemented. The remaining gates are specific:

- The first final ordinary Python aggregate was interrupted after an evaluation
  browser adapter rejected the new readonly identity RPC and its test barrier waited
  indefinitely. It is not a passing aggregate. Explicit synthetic identity fixtures,
  the exact readonly adapter, bounded test barrier and async-body evaluation transport
  were repaired. Focused sets passed 171, 85 and 66 cases; a clean full rerun is required.
- The subsequent exact 0aaf4ab ordinary aggregate completed with 4,408 passed,
  96 failed and 873 skipped. One production worker regression detached diagnostic
  identity from its original dispatch object; 9b8b391 restores that binding while
  preserving immutable execution input. Remaining failures were explicit legacy
  authority/transport fixtures and an obsolete pause-wording assertion. The focused
  repaired set passed 322 cases, with 95 strict identity-fixture cases rerun and 58
  prompt/place cases passing separately. The fresh immutable 9b8b391 ordinary
  aggregate then passed: 4,506 passed, 873 skipped, three warnings in 473.04 seconds,
  explicit exit zero. Production logic is unchanged through 2796a12; its later
  browser-fixture/doc delta passed an independent 85-case clean-archive gate. This
  is base-full-plus-reviewed-delta evidence, not an exact 2796a12 full-suite run.
  Skips comprise 660 PostgreSQL/opt-in database cases, 205 frontend/browser/Auth-HTTP,
  four live-provider evaluations, three Mocker checks and one Apple Container check.
- Exact remote beb2dc68 (tree 22a4f07) Mac browser execution failed all three runners
  in their first case: zero passed, three failed, five later cases unexecuted and no
  explicit skips. Lifetime reads reached screenshots but retained a cookie-access
  page error; collection runners lacked the exact project-startup mock and timed out.
  Fixture repairs retain every UI assertion, add precise startup/origin tests and
  record error stacks, frame URLs and unexpected requests. Full repaired Mac cases
  remain required; native checks are separate evidence.
- Repaired remote fc9de17 (tree 0913ef7) Mac rerun passed all four lifetime-read
  cases. Each collection runner failed its immediate startup count/consent assertion
  in the first locale, leaving the second unexecuted. Later diagnostics showed
  completed startup without API/browser errors, but their mutable snapshot cannot
  prove the earlier state. A bounded completion wait and immutable pre-screenshot
  diagnostic snapshot were repaired in 99b28d5 with 13 focused regressions and
  six route cases passing. The subsequent 8744ce08/tree fb14c008 Mac run passed
  pagination EN/ZH and collection review EN/ZH: four passed, zero failed,
  unexecuted or skipped. The Mac verified lifetime/Auth/web source unchanged from
  fc9de17. All eight controlled cases are covered across those two recorded heads;
  this is not one unified current-head browser run or a live-provider test.
- Remote beb2dc68 tree and all 157 changed blob SHAs were independently verified
  against local 0aaf4ab. Later repair commits require new remote parity and review.
  No PR-triggered remote workflows or statuses were reported on that checkpoint.
- Personalized direct WebRTC remains unavailable for canonical accounts. The endpoint
  sends audio outside server publication fences; HTTP rejection does not retroactively
  govern a previously established legacy call after adoption. No current web caller was
  found, which does not prove unreachability. The user’s AC10 scope decision is pending:
  retain a disclosed gate and track safe realtime separately, or require transport parity
  before completion. Neither silence nor the safe gate constitutes approval.

Independent review of exact 4f75a70 passed 95 PostgreSQL cases in 59.40 seconds,
covering the corrected composer fence, runtime, atomic commit, identity, actual engines
and monotonic adoption. Two heavy cases were excluded because they have separate
capacity evidence. No source blocker remained in those reviewed scopes. This does not
replace the acceptance gates above or authorize merge/activation.

## W0–W6 and acceptance evidence map

- W0 / AC9: versioned contracts, project-associated read-only inventory, upgrade-gap
  detection and rollback boundaries; contract, identity and upgrade suites. Historical
  accounts remain mapping-required until an approved inventory decision.
- W1 / AC1: unique authenticated owner/product identity and canonical home/guest
  recovery; identity, home and name-provenance suites preserve original source IDs and
  current explicit phase/preference revisions.
- W2 / AC5–6: immutable admission/read/output fences, actual outer ASGI publication,
  atomic reply/phase/pointer commit, source-dependent invalidation and cold execution;
  actual-engine, runtime, monotonic-adoption, read and outer-publication suites exercise
  both execution modes, lost homes, lease races, conflicting replays and entitlement replay.
- W3 / AC3–4, AC7: complete-tail proof, scoped exact-span retrieval, validated durable
  checkpoint coverage and current typed pins; context/source-page/checkpoint/continuity
  suites cover 39/40/41 and 100/1,000/10,000 boundaries, rare early facts, uncertainty,
  source-version changes and a single event backed by 1,100 sources. Actual composer
  caller/SQL renewal reuses completed phases under stable input identity and fresh CAS.
- W4 / AC2, AC10: real 10,000-source admission/readback, bounded event/draft/source
  pages, coalesced receipt suffixes, protected-prose proposal CAS, independent editions,
  selected-source exact exports and hierarchical cross-page grouping. Source-capacity,
  draft-coalescing, composer, read-API and collection suites cover these flows. Per-request
  limits remain explicit; no lifetime prefix is silently substituted for full evidence.
- W5 / AC8: durable required obligations with unattended service-worker recovery and
  inspectable failure; optional content-addressed delta artifacts with exact effective
  coverage/removals and tenant/epoch checks. Outbox/artifact/worker suites include crash
  without another visit, unchanged uploads, large manifests and growing 10,000-turn homes.
- W6 / AC9–10: clean pinned archives/worktrees and independent real PostgreSQL review,
  regression gates and documented approvals. Scoped passes are evidence, not a whole-ticket
  completion claim. The base full aggregate and reviewed fixture delta are green;
  all eight controlled browser cases pass across the recorded equivalent sources.
  Final clearance-gate source/tests, remote checks and the realtime decision remain.

## Evaluation and later approvals

Paid/live semantic, latency and cost evaluation has not run. Before any such run,
obtain explicit provider/model/tokenizer versions, spend ceiling and data authorization.
Use English/Chinese strata, rare early facts, ambiguous names/dates, corrections,
withdrawals, contradictory claims and abstention cases. Human-review supported claims
and preservation of uncertainty; record queue, retrieval and model timings separately.
The audit's proposed p95/hard budgets and recall/quality targets are experimental,
not approved SLAs. Fake-provider structural tests cannot establish those metrics.

Production schema application, historical mappings/backfills, deployment/activation,
retention or GC deletion, credentials/access changes and real-data export remain
separate approval gates. Retention proposals should expire disposable cursor/job/home
metadata only after approved audit/rollback requirements; this code performs no
production cleanup and promises no immediate erasure of historical backups.

## Reviewed phase dependency

PR #61 was human-merged as aba51cc0f50495249ebc7ad903c5f13b59c34fba; PR #62 now
targets main. Its merge adds only separate issues53–55 evidence beyond the reviewed
phase head, with no phase source changes. The stack incorporates PR #61 head fe18dc2d220770d3d2e0ab0a01beec88acbd7c4d,
whose verified tree is abe839e5bbd329d27e67c3ecbcb1eb9f5009628a. Its version-one
phase envelope no longer includes a pause control. Issue #60 preserves explicit
selection, preferred phase and revision through pins/recovery. Topic-specific privacy
deferrals and operator generation suspension remain separate controls. The local
phase owner retains responsibility for phase behavior and outstanding phase findings.

## Direct realtime clearance boundary (source-only rollout interlock)

A default-closed database interlock is implemented with scoped independent source
review. It does not revoke any call and is not operational clearance. Its
monotonic stages are `legacy_only`, `draining`, then `canonical_ready`:

1. The migration default permits no new canonical identity adoption or governed
   model admission. Existing mapped safe reads and saved-receipt replay retain
   their ordinary privacy fences.
2. An operator-only transition blocks new direct realtime admission under the same
   database authority used by canonical adoption and purpose-specific provider
   request guards. Already admitted or connected calls are still in flight.
3. Before a separately authorized clearance, an operator must verify termination
   of every pre-existing call and in-flight creation through authoritative external
   evidence. A bounded reference records that attestation; the application cannot
   establish its truth from a missing local registry, process restart or assumed TTL.
4. Only then may separately approved clearance enable canonical adoption/provider
   admission. No backward transition may re-enable ungoverned direct calls.

No database stage has been changed outside isolated synthetic tests. No deployment,
operator clearance or access change is authorized by these tests. The interlock
addresses a safe activation boundary; it does not provide direct WebRTC parity or
by itself resolve the AC10 product-scope decision. The later approved release
boundary is recorded below.

Scoped clearance evidence before the final combined-pin gate:
- 28 isolated database/pure admission cases cover default denial, forged transition,
  operator CAS, existing identity recovery, actual multipart admission versus drain,
  ready commit/rollback, queued-exclusive lock ordering and lease-wait accounting.
- Four actual HTTP cases preserve one accepted source and exact retry in direct and
  worker modes, both JSON and streaming; three preaccept cases preserve honest
  nonacceptance and fixed public errors without exposing database diagnostics.
- Composer clearance handling passes 44 short cases plus 63 provenance/photo cases:
  repeated deferral preserves sources, checkpoints and required obligations without
  spending generation-failure attempts, and resumes after synthetic readiness.
- Selected jobs pass 36 database cases, including the bounded 10,000-history fixture,
  plus five dispatch cases with the real local Temporal test server. Pending model
  jobs cannot starve deterministic exports while clearance is closed; typed deferral
  preserves the accepted manifest and checkpoint.

These fixtures attest only their isolated synthetic environment. The final combined
source still requires pinned independent testing and the native-enabled aggregate.

### Exact clearance checkpoint results and subsequent blocker

The independent clean `3d03633` gate passed 105 cases (one heavy case reserved),
using native PostgreSQL and the official local Temporal CLI. The full native-enabled
aggregate on that same immutable source then completed in 1,163.09 seconds with
5,235 passed, 213 skipped and five failed. The five failures were photo HTTP
acceptance fixtures failing at admission; an adapter serialized authoritative JSON
`null` as an empty body. Its faithful repair is separately pinned at `7ea132d`: all six real PostgreSQL
cases passed, including the five original failures and a new JSON-null regression.
This does not relabel the original failed aggregate as green.

The 213 skips comprise 205 frontend/browser/Auth-HTTP cases, four live-provider
evaluations, three unavailable Mocker checks and one Apple Container check. All
660 previously skipped database/opt-in cases were exercised. The eight controlled
Mac cases above are separate evidence, not substitutes for all 205 browser cases.

A subsequent source review found a policy-completeness blocker: a request with more
than eight literal privacy controls, or a process interruption after accepting a
source but before persisting its controls, could leave accepted restrictions
unapplied. The pending repair must make new-source policy application atomic,
validate the full input before acceptance for clear limit errors, and fence private
publication/admission when historical accepted policy lacks completeness proof.
Existing incomplete evidence must remain recoverable without pretending a fresh
request was accepted or silently replaying older settings. Until this repair and
its independent integrated tests pass, source clearance remains withheld. This is
a code-level finding, not evidence of production exposure.


### Atomic literal-policy repair contract

SQL027 now independently parses supported literal controls and applies every one
inside authoritative new-source acceptance or explicit source-edit transactions.
The parser has fixed Unicode whitespace and word-boundary semantics shared with
Python, exact original spans, and a request limit of eight controls / 500 characters
per control. Overflow rolls back acceptance; the API runs the same pure check for
a clear preaccept 413. It never truncates restrictions. Source/span identities are
stable through the subsequent collector commit, so controls are not duplicated.

New/raw imports, unmatched historical accepted sources, and preexisting mapped
histories without proof remain behind indexed pending-policy/inventory guards.
Private body publication, model admission and dependent jobs fail closed. Bounded
owner-scoped metadata remains available; a fresh request is never mislabeled as
accepted because an older source needs review. JSON maintenance errors distinguish
pending-source identifiers from the current source, if the latter was actually
accepted. Streaming failures retain the fixed safe terminal error; they do not
promise the JSON metadata contract.

Existing histories require separately reviewed operator reconciliation. Editing or
withdrawing one historical source cannot clear a conversation-wide incomplete
inventory. No authenticated caller can assert completeness, and older preferences
are never blindly replayed over newer explicit settings. Synthetic bulk fixtures
invoke the real private parser over their exact generated originals; this is not a
production reconciliation procedure or approval.

Composer and selected-job workers defer pending policy without losing checkpoints
or consuming generation failures, using metadata-only owner/lease checks. Both
blockers are filtered before bounded polling so ready tenants retain progress.
Required memory obligations use the same eligibility and per-candidate rollback
rule, preserving attempts when an exact pending-policy race occurs after selection.
Unrelated authority errors are not reclassified as maintenance.

Scoped repair evidence: 142 parser/atomic tests (108 pure, 34 real PostgreSQL),
31 composer policy/clearance tests, 48 selected-job PostgreSQL cases plus 11 route/
Temporal cases, and a 79-pass runtime/engine/obligation batch whose sole failed
barrier fixture initially locked a deleted lease row. The corrected obligation and receipt gate passed 12 cases, including a real
after-selection race and both pending-table fairness cases. Immutable combined
review and the refreshed native aggregate remain required before acceptance. No
production data, deployment, clearance or historical reconciliation was changed.

### Full atomic-policy checkpoint regression result

The independent clean `1c64005` native gate passed 163 cases in 54.17 seconds.
Remote `cfcacfa89f8bc1ceb939c17811c151fadfdc70bd` was independently verified to
have the same tree, `4b2c5a9105c799bfea46ec0572abdc54b0059cb9`.

The full native aggregate on that source completed with 5,388 passed, 213 skipped
and three failed in 1,270.65 seconds. The mapped-home fixture still expected
private access despite its new historical-policy inventory marker. Two read-lock
fixtures assumed source acceptance left no profile, although atomic acceptance now
creates one. Their corrected setup must explicitly remove only the synthetic
owner's profile after acceptance and before read capture, preserving the original
read-only and first-profile lock assertions. These failed runs are retained as
failed evidence; targeted repair and final aggregate results are recorded separately.

The reviewed read/home repair passes 136 native cases with zero skips (20.91s),
including all three failures above. An exact pending-policy exception now produces
a fixed 503, `LIFETIME_POLICY_PENDING`, Retry-After and no-store only before any
response-start attempt. It emits neither the private snapshot nor its headers.
ASGI 2.3/2.4 tests prove that uncertain/partial starts, body errors and guard-exit
errors never cause a second response; unrelated errors and cancellation retain
their original behavior. The source repair still requires the final pinned
independent rerun and refreshed full native aggregate.

## Final offline native verification

The clean, immutable production-source pin
`2ad1659fe61202141c530f1d634a4254884409e3` (tree
`bf1baad6a57e845ece03f31899126009e4e9fe4b`, remote equivalent
`ed21b73736307decd6305aeec07e869a4c0ae67e`) completed the full native-enabled
aggregate with **5,403 passed, zero failed, 213 skipped, five warnings, exit 0** in
1,349.68 seconds. Native PostgreSQL, the provider-free artifact opt-in and the
official local Temporal CLI were enabled. No source changed during that run.
This final record is an evidence-only documentation update; it does not represent
another full test execution on a different hash.

The 213 skips remain explicit: 205 frontend/browser/Auth-HTTP cases, four live
provider evaluations, three unavailable Mocker cases and one Apple Container case.
The separately verified eight controlled Mac cases cover the #60 lifetime and
collection fixtures across their recorded unchanged-frontend heads. They do not
claim all broader browser scenarios, physical-device coverage, real-data provider
quality, live latency or cost acceptance. Earlier failed runs above are preserved;
their fixes are now included in the successful final aggregate.

Release-scope decision and remaining external gates:
- On 2026-10-12 the user approved keeping direct WebRTC audio disabled for this
  release for migrated/canonical accounts, as disclosed in the proposal, and
  tracking safe realtime audio separately. Legacy-only direct SDP remains subject
  to the existing staged gate; no global legacy route change was approved. This
  resolves only the
  disclosed AC10 feature-scope choice; it does not establish transport parity or
  waive other acceptance checks. Ordinary conversation and transcription remain
  within the implemented scope.
- Preserve the default-closed adoption/provider interlock. Blocking new direct
  calls does not terminate existing or in-flight legacy calls. The scope decision
  is not an operational clearance attestation and does not authorize production
  adoption, activation, migration, deployment or historical reconciliation.
- Production migrations, historical identity/policy reconciliation, deployment,
  provider evaluation and activation require their separate approvals. No actual
  migration, reconciliation, call termination or clearance attestation was done.
- Operational clearance requires authoritative termination evidence for all older
  calls/in-flight creations after every relevant ingress blocks new direct calls.
- Required remote checks and final merge/whole-ticket acceptance remain with the
  parent review. No PR-triggered workflow/status or external review was reported
  at the latest verified checkpoint. This draft does not close #60.
