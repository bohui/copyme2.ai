# PR 58 review follow-up — 12 October 2026 (Sydney)

## Result

Addressed the [review comment](https://github.com/bohui/copyme2.ai/pull/58#issuecomment-6109235714)
with a reproduced startup save-gating fix, expanded backend acceptance cases,
real-proxy smoke and explicit negative full-suite evidence. **Issue 53 remains
open.** Faster quality-preserving generated replies have not passed the release
gate. Normal model, maximum effort, full legacy prompt and service flags remain
unchanged. No candidate rollout or shared gateway policy change was made.

Application base/head examined: `20dbeb40143409ca7882756dcf7281309c9b94ab` /
`d7eb7af87600e9e56a5fff2c86d6562a41b5c8bc`, plus this follow-up's source changes.
Relevant running API/private-worker source hashes matched that head. The deployed
worker uses Codex 0.156.1; host profiling uses 0.155.1. These versions must not be
silently treated as the same experiment pin. The profiler now records its binary
version, or unavailable, alongside the application revision/source hash.

## Reproduced and fixed

The fixed introduction keeps the composer available while painting. Its completion
then unconditionally reset `state.loading`, even if the storyteller had started a
generated turn. A red JavaScript regression reproduced this independently of any
provider. Removing that redundant reset makes the generated turn retain ownership
of the busy flag until saving or controlled failure. Introductory copy, model
requests, source history and reply quality are unchanged. Existing project-navigation
fencing still applies.

The normal-route real-proxy smoke also observed early readiness before the fix.
An initial cloned-stream observer could race the UI; a separate red/green test now
requires observation of the native reader before the UI consumes each unchanged
packet. The final native-reader run against the corrected production frontend passes.
Reload comparison uses rendered `innerText`, not `textContent` which omits `<br>`
line breaks. Earlier incomplete runs are not successful acceptance evidence.

## Backend acceptance coverage

The existing backend streaming profiler has an opt-in `--extended` mode: 40 matched
baseline/candidate generations covering both languages and short, long-stress,
Family and public-reference cases, plus two unpaired rollback generations. Rollback
resumes the **actual just-generated candidate history**, clears operator overrides,
and preserves sources, saved plan and Family context. Tests distinguish candidate
history from baseline history rather than assuming identical replies prove rollback.

The frozen bound is 42 foreground generations, at most 84 application app-server
turns, 120 seconds per generation, 1,200 seconds overall, stop at first failure.
Those are not exact upstream request budgets. The default remains the existing
24-generation campaign. Neither extended nor combined-candidate live comparison was
dispatched in this follow-up. Long repeated synthetic text is a completeness stress
case, not representative emotional-story quality acceptance. Controlled provider
coverage is plumbing/contract evidence, not semantic equivalence.

## Confirmed routing confound and proposed next step

[Safe request-shape receipts](issue53-request-shape-20261012.json) use the real Linux
worker/app-server with fresh tenant-owned homes and a loopback provider that returns
400. **No upstream model was called.** The existing `memoir-luna-low` alias makes
Codex advertise seven tools and changes instruction layout; the normal pooled route
advertises none. Gateway policy still maps both to the same underlying model, with
max versus low effort. Therefore the previous trial was not an effort-only harness
comparison. This does not prove the cause of every prior slowdown.

A proposed `gpt-5.6-luna-memoir-low` alias produced the same request sizes/layout and
empty tool set as the baseline on Codex 0.156.1. That name is **not provisioned or
live-policy-verified**. Operator approval was requested before adding it to the
local gateway. The concrete change would copy the existing low-route entry and
change only its alias, preserving underlying model, endpoint, credentials and low
policy; leave all existing aliases/shared max policy/defaults unchanged.

After approval/provisioning, verify the new policy read-only, pin one app-server
version and run bounded matched backend quality/latency comparisons. A compatible
alias is not itself evidence of faster or equally good replies. Do not close 53 or
enable a default based on this preflight or the browser smoke.

## Verification

Counts overlap; they are not a unique-test sum. No CI pass is claimed.

| Check | Observed result |
| --- | --- |
| Default backend configuration/preparation/profiler/language/name/plan/photo/real PostgreSQL readback/lease/stream set | 192 passed, 23.01s; final profiler version metadata checked separately |
| Profiler + existing Codex runtime tests | 80 passed, 6.19s |
| Final profiler, including version metadata and extended cases | 5 passed (result recorded after the metadata addition) |
| JavaScript streaming/navigation/history/photo/project restore/observer set | 59 passed, 0.188s |
| Production frontend build, Node 24 + Webpack | Passed; non-fatal next-intl webpack cache warnings |
| Corrected production frontend desktop/phone save-gating, reload and fresh-tab controlled smoke | 6 passed, 10 deselected, 19.63s |
| Real production web proxy → running API → private Linux worker → live provider → Supabase save/reload | 3/3 saved; no early unlock, duplicate reply or reload resubmission |
| Full Python suite attempted | 4,009 passed, 69 failed, 194 skipped, 39 setup errors, 536.82s; **not green** |

The full-suite failures include macOS `/bin/true` assumptions, a locale SQL fixture
that does not use the Apple-container backend and fails `initdb`, and older
controlled-provider fixtures producing unstructured replies. A disposable base
snapshot comparison selected 107 matching cached failed node IDs: 68 failed, one
passed and 38 errored. The cache also contained stale IDs; the snapshot lacks Git
metadata and has different browser prerequisites. This is evidence of several
pre-existing failures, **not proof that every head failure is unrelated**.
The initial snapshot command had unavailable node IDs and ran no tests; it is not
verification. Temporary snapshots were removed after their subprocesses finished.

A low/compact-enabled controlled set had 189 passes and one failed fixture assertion
expecting the legacy `test-model` route while the collector override correctly selected
`memoir-luna-low`. Its normal-configuration counterpart passes. Do not describe that
entire candidate-enabled run as green or as live semantic-quality acceptance.

### Final real-proxy smoke

Task-owned production frontend on 3347 forwarded to the unchanged running API on
8010. No browser auth/API/provider/stream replacements. A new synthetic anonymous
memoir `project_d6dbb01585ee` was used; its saved test exchanges remain for readback.
Frontend/backend/smoke source SHA-256:
`49645bfe6e0e28977995103b7000ecafd57f5ab4068f96b0534e88657e7e761d`.

| Case | First public text | First rendered text | Validated reply | Conversation saved |
| --- | ---: | ---: | ---: | ---: |
| First/name | 8.509s | 8.513s | 10.102s | 10.102s |
| Later/name change | 7.401s | 7.402s | 8.464s | 8.464s |
| Reloaded/resumed pause | 4.065s | 4.066s | 4.569s | 4.576s |

One question in each non-stop reply; none after the pause. The saved prior reply
restored exactly once and reload dispatched no new turn. These are normal-route
smoke observations, not candidate speed improvement, production percentiles, or
comprehensive quality evidence. Synthetic accounts/projects were not deleted.
Six individually capped smoke invocations dispatched ten foreground requests in
total while developing/verifying the check; only the final three-turn invocation
completed every assertion. Exact upstream request/retry counts remain unavailable.

## Closure gate still outstanding

The compatible dedicated route requires approval/provisioning and live policy
verification. Representative matched first/later/resumed quality and latency,
long/Family/reference/rollback live evidence, and a resolved final verification
position remain necessary. The no-normal-response-quality-loss requirement is
unchanged. Issue 53 must stay open until those gates genuinely pass.

## Replacement cloud verification and repairs — 12 October 2026 (Sydney)

This addendum supersedes any inference that the earlier failed suite was cleared
by a partial baseline comparison. The original 69-failure/39-error raw log and
node list were not available. The earlier aggregate is retained above as
historical evidence, not relabelled as a pass.

### Revisions and isolation

- Original PR head: `ba9abfe5c405ca29752c4872389057ee88ed048b`.
- Original base: `20dbeb40143409ca7882756dcf7281309c9b94ab`.
- Concurrent main update integrated without conflicts:
  `5c11fb5b2ce9497651ca9f262ff5afe41254639b` (historical-news PR #57).
- Source candidate: `b4abd390e2b79a73aa69f53423d70233d0a57111`,
  tree `4e07114370cd8c74a7a4c551e75ce5686bf20201`.
- The comprehensive run collected at `f2f79eb304a2c6ee8cf44ae4f4ff6b8135bef2cc`;
  later changes are whitespace/test-fixture cleanup and the explicitly rerun
  legacy/candidate trajectory assertion, not new production behavior.

Verification uses a fresh task-owned HOME and explicit environment allowlist,
no inherited provider credentials, fresh PostgreSQL clusters, loopback-only
services, synthetic narrators, and controlled provider boundaries. No live LLM
or paid provider request, deployment, remote migration, or production data change
was made. Collector candidates remain disabled by default.

Native PostgreSQL is 17.11, not the historical container pin 17.6. Temporal CLI
1.9.1 (server 1.32.0) was obtained from its official GitHub release and verified
against the published SHA-256:
`09a0326a51db84d02735e53542b9ebd8c4758daf47482a9ab0abce15844e60d5`.
Node is 24.19.0; the production frontend build uses Next.js 16.3.6.
These are functional regression pins, not a matched live latency experiment.

### Reproduced issues and fixes

1. Native PostgreSQL setup required Unix-domain sockets unavailable in this
   executor. An explicit `native-tcp` fixture option uses a randomly allocated
   loopback port and disables Unix sockets. It sanitizes inherited `PG*` settings,
   specifies the owned superuser/database, reports startup logs, and stops partial
   or completed clusters. Real multi-session RLS, locking and atomicity remain
   enabled. UTF-8 is explicit rather than the previous SQL_ASCII default.
2. Locale collection generated a random UUID in a node ID. Two collections
   demonstrated different IDs. A fixed nonexistent synthetic actor preserves
   rejection coverage and makes all 39 IDs reproducible.
3. The candidate route assertion was genuinely stale: its default run passed,
   while the configured collector correctly selected `memoir-luna-low`. The test
   now explicitly covers both legacy and overridden routes; it does not compute
   expectations from the implementation or enable a production candidate.
4. Four photo-browser fixture JS tests pass the exact original base and fail the
   original PR head: the new origin guard requires `location.protocol`, missing
   from the Node browser context. The context now supplies it, with additional
   tests proving opaque origins never touch storage.
5. `test_single_collector_observation::test_original_source_preparation_reaches_only_the_owned_collector_boundary`
   passes the exact original base and fails the head because its synthetic lease
   lacks the new parallel-read interface. The synthetic seam was updated while
   independent real lease/concurrency tests remain intact. This is a concrete
   base-pass/head-fail node; absent the old raw log, it cannot be asserted to be
   the anonymous one in the prior report.
6. Older native provider fixtures emitted unstructured collector text, bypassed
   required app-state initialization, or implicitly downloaded Temporal. They now
   use schema-valid extraction proposals only at the controlled collector seam,
   explicitly initialize their in-memory API fixture, and can use an existing
   official Temporal executable. Real runtime, worker, database, workflow,
   validation, persistence, and existing assertions still run.
7. A baseline production defect prevented Chinese/emoji-first completed exchanges
   from entering the private-round ledger under the C locale. The original
   `[:print:]` check is locale-dependent even with UTF-8. An additive migration
   replaces it with an exact prefix check while retaining the delimiter,
   nonempty narrator/reply checks, advisory lock, deduplication and outbox
   semantics. Red Chinese/emoji tests reproduce the loss; English and malformed
   exchange coverage is retained. No historical rows are rewritten and this
   migration has not been applied to a remote database.
8. A baseline production defect retained an unchanged passage in the section
   ledger yet rendered a provider rewrite after withdrawal changed a sample
   between chapter and storyline. Restoration now preserves eligible immutable
   blocks across that narrow presentation change. Full event-set containment,
   unique destination ownership, collision rejection and existing canonical
   evidence validation prevent unrelated, mixed/withdrawn, empty-scope or
   ambiguous sections from being imported.
9. The migration harness assumed the entire directory still contained the
   original eight files and replayed every later one-shot DDL. It now preserves
   the exact foundational prefix/replay checks, exercises all forward migrations,
   and checks source/ID/private/RLS preservation. Data-importer idempotence is
   tested separately on the current schema. Native evidence is labelled 17.11;
   the explicit Apple-container path still enforces its requested 17.6 pin.
10. Remote Make report tests now create an empty synthetic environment file
    rather than depend on an untracked developer `.env`. Missing Python/Next
    dependencies were supplied from matching existing local installations.

### Verification status

Counts overlap and must not be added as unique tests.

- Original-head production code with native transport fixture adaptation: 4,093 passed, 22 failed, 198 skipped,
  2 setup errors, 450.71 seconds. Raw node IDs and traces are retained in the
  accompanying machine-readable verification evidence. This was not green.
- Native lease/locale preflight: 45 passed, including all 39 locale SQL cases.
- Repaired native canary/canonical/Temporal/private-round set: 41 passed.
- Repaired existing API/provider/lease contract set: 51 passed.
- Candidate-enabled backend/configuration/real-PG set: 245 passed. A broader
  candidate run first exposed one further legacy-only trajectory model assertion
  (243 passed, one failed); explicit legacy/override cases repair it. Final
  trajectory file on the committed candidate: 35 passed.
- Final provenance and real withdrawal regression set: 45 passed.
- Independent provenance/transport/Temporal-option review probes: 47 passed.
- Integrated JS plus historical-news rendering: 350 passed, zero skips.
- Production frontend build: passed; only non-fatal next-intl cache warnings.
- Specification audit: all 63 specified routes represented (125 application routes).
- Mobile OpenAPI snapshot: 36 operations match.
- Named deterministic acceptance catalogue: 55/55 passed.

Comprehensive integrated run with browser gates enabled: **4,283 passed,
71 failed, 94 setup errors, 8 skipped**, 642.55 seconds. All 165 unsuccessful
cases were independently classified from their exact JUnit outcomes:

- 129 missing Playwright headless-browser executable (55 failures, 74 errors).
- 32 Chromium Unix-socket launch denials (16 failures, 16 errors).
- 4 pinned family-renderer fixture DNS setup errors.

No remaining backend assertion failure was observed in this run. The overall
suite is **not green**. The eight skips are one Apple-native campaign, three
Mocker compose checks, and four explicitly opt-in live-provider followups.
They were not added by these repairs. Installing the official Playwright
headless runtime also failed because its download was not a valid ZIP archive.
The owned production frontend was stopped after the run; PostgreSQL and Temporal
fixtures completed their cleanup.

[Machine-readable outcomes, every unsuccessful node/skip reason, and trace/log
hashes](issue53-pr58-verification-20261012.json) accompany the
[initial native reproduction log](issue53-pr58-head-native-20261012.log.gz) and
[comprehensive integrated log](issue53-pr58-integrated-full-20261012.log.gz).
The logs are gzip-compressed, retain the original tracebacks, and contain only
task-owned synthetic test data.

No GitHub check runs or status entries were reported for the original head;
that is not a CI pass. Legacy branch-protection metadata returned 403 to the
integration. The published candidate's checks must be rechecked separately.

### Remaining acceptance gates

Chromium launch in this executor fails before browser assertions with
`process_singleton_posix: socket() failed: Operation not permitted`. An approved
escalation with a fresh task-owned HOME produces the same result. Browser tests
were attempted with gates enabled, not altered to skip or weakened. Successful
Node/HTTP/build checks do not substitute for real browser acceptance.

Issue #53 remains open. The earlier negative routing pilot and prompt timeout
are still negative evidence. Normal-route 3/3 saved smoke is not proof of
candidate improvement. Representative matched first/later/resumed semantic
quality and latency, long/Family/reference/rollback live evaluation, and the
extended live campaign remain unrun. No new such campaign is authorized here.
Do not merge or enable the candidate on the strength of this repair slice.
