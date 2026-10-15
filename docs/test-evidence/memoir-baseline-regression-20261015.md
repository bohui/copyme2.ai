# Memoir baseline contract repair — draft PR #69

Tested code/test commit: `90d7c91b53af01a5d9c0c6af1c02bc3264767efc`.
Base: current main `46caa5fc2c2c5af2d4f7280bea74cc75184c9cbc`, including its
acknowledgement/commentary and container changes. The subsequent evidence commit
changes only this report and its [per-case ledger](memoir-baseline-checks-20261015.json).
The original checkout was preserved; work used an isolated worktree and branch.

**Acceptance remains incomplete. Keep the PR draft.** These are author tests,
not independent review, and the complete Python aggregate remains non-green.

## Verified causes and changes

1. **Native PostgreSQL fixture portability.** The Unix-socket fixture deliberately
   has no `-p` argument. Runtime tests parsed it anyway. Two new native Unix/TCP
   endpoint regressions failed before repair. The shared fixture now exposes its
   actual disposable publication DSN, including an explicit native socket port,
   and consumers use that metadata. Hostile `PGHOST`/`PGPORT` values cannot redirect
   those tests. Existing container publication remains opt-in; no Mac is used.
2. **Acknowledgement worker framing.** Removing the transport blocker exposed
   synthetic workers returning bare JSON while current main requests NDJSON even
   for a JSON HTTP caller, to receive the acknowledgement early. The controlled
   worker now honors that protocol. Privacy, correction, accepted-source retention,
   exact retry, source/round counts, lease and replay assertions remain exercised.
   The provider rejection fixture now uses the current authority error code rather
   than the retired rollout-clearance code. No latency/model policy was rewritten.
3. **Read contract, beyond the HTTP verb.** History/receipt reads can POST exactly
   `read_user_interview_turn` with the owned project and turn ID. Two new real-SQL
   cases exercise context and receipt reads: they snapshot every public table and
   permit only one phase-row initialization; repeated reads are stable, another
   owner cannot obtain the receipt/context, and a second SQL session proves the
   documented owned-project lock. They establish no additional source, interview
   admission, round, generation lease, identity adoption or job side effect.
4. **Fail-closed identity compatibility.** Current development explicitly retired
   the legacy engine; see [the current decision](../lifetime-memory-integration.md).
   A successful identity RPC returning null permits the owned unmapped adapter.
   An RPC/schema-cache failure does not prove null and must propagate, including
   with the old legacy-only flag. The three variants now require that failure.
5. **Route spies need real publication authority.** The reproduced first aggregate
   failure returned a reply without an authority or fence. Route spies now acquire
   a live disposable SQL lease and execution fence, retained through ASGI delivery.
   Four negative JSON/stream cases prove missing authority/fence cannot publish
   the private reply. Text forwarding and stream event order remain asserted.
   Optional focus is now asserted as explicit null; the retired first-reply hint
   is asserted not to reopen the server's durable language choice. Four existing
   compatibility-case IDs were renamed/revised; they are mapped in the ledger.
6. **Lint.** All six baseline unused-binding findings reproduced. Four unreferenced
   functions and their two now-unreferenced helpers were removed, the catch binding
   was omitted, and the latency test now asserts the formerly unused reply result.
   Changed-JavaScript lint is clean; no lint rule or assertion was disabled.
7. **A product reload bug, not just a browser fixture.** Project hydration attempted
   the saved-draft read before entitlement restoration, exited as ineligible, then
   never retried when the completed-round allowance arrived. A new regression
   failed before the repair. Entitlement restoration now starts the existing read
   for eligible non-debug sessions without waiting for it. Twenty rounds loads
   the saved text; five does not. The production standalone browser verifies the
   ordinary paid round-20 draft with debugging **off**, in both locales.

The older browser service fixture also needed a complete saved-turn receipt and
separate `workspace_update` event; a saved canonical result no longer applies its
bundled legacy workspace fields. Its real history projection now verifies the
saved narrator/reply IDs and text. Browser launch accepts the installed Chromium
path; external browser requests are blocked except fulfilled synthetic Auth.

The unchanged original selection on `e190885` reproduced **37 failed / 77 passed**
(the reported 27 backend cases plus ten route-fixture cases). New DSN regressions
were **2 failed** before repair. The entitlement regression selection was
**1 failed / 12 passed** before the product fix and passes after it. All four
original stage-browser cases failed before the fixture/product investigation.
These reproductions are distinct from the complete fixed-revision results below.

## Complete pinned verification

Both full Python runs used the same dependencies, native PostgreSQL, preinstalled
Temporal CLI, two file-scoped workers and a 60-second per-test limit. Neither
checkout changed during its completed run. Eight new Python cases were added.

| Check | PR code `90d7c91` | Unmodified current main `46caa5f` |
| --- | ---: | ---: |
| Full Python collected | 6,239 | 6,231 |
| Passed | 5,328 | 5,216 |
| Failed | 641 | 716 |
| Setup errors | 21 | 50 |
| Skipped | 249 | 249 |
| Duration | 1,128.22 s | 1,087.53 s |

All **662** remaining failure/error IDs also fail on current main; **657** have
identical normalized failure summaries. Four remaining cases advance beyond the
old DSN blocker and fail later. Matching IDs do not establish identical causes or
make a failure acceptable. There are **zero PR-only failing/error IDs**.
**104** prior failures/errors now pass, including two explicitly revised canonical
contract cases; the other 102 retain their IDs. Eight new cases also pass.

| Other complete check on the pinned code | Result |
| --- | --- |
| Node + composer + historical-news aggregate | 501 passed; zero failures/skips |
| Runtime / reads / route / native transport files | 25 / 67 / 26 / 25 passed; zero failures/skips |
| Actual engine + collector files | 76 passed; zero failures/skips |
| Complete phase module | 64 passed, 7 stale fixture/admission failures; new SQL read cases pass |
| Complete subscription stream diagnostics | 36 passed, 5 raw-worker contract fixture failures |
| Standalone production Chromium | 4 passed, en-AU and zh-CN |
| Registered browser-service fixture checks | 13 passed |
| Mobile domain/API Node | 87 passed |
| Mobile UI / integration Jest | 66 / 21 passed; 8 / 1 suites |
| Mobile types, lint, OpenAPI and native config | Passed; no device/native-binary execution |
| Production webpack + standalone build | Passed |
| Changed-JavaScript lint / syntax / whitespace | Passed; zero unused-binding findings |
| Specification acceptance | 55/55 passed |
| Localization / route audit | 647 messages; 63 required routes among 125 app routes |

Five aggregate failures exhausted the 60-second limit in large capacity checks.
Dedicated 600-second reruns kept all assertions and passed **all six 10,000-item
checks**, including the disposition check that already passed in the aggregate.
The three rerun commands took 330.57 s, 136.92 s and 73.31 s. Aggregate failures are
retained. These are bounded-correctness checks, not production latency SLAs.

## Every remaining failure/error is classified

The ledger contains each of the 662 IDs, its assertion/setup summary and repository
frames, current-main outcome, comparison signature, classification and source
reason. It also lists every skip, all 104 improvements, case renames and raw JUnit
SHA-256 values. Full raw JUnit logs remain in the task executor; they are not
substituted for the per-case published evidence.

| Classification | Cases | Meaning |
| --- | ---: | --- |
| Stale fixtures / retired contracts | 568 | Removed runtime APIs, missing canonical envelopes/authority, old identity, publisher, stream or rollout contracts |
| Source-identified product/tooling compatibility defects | 65 | 43 route-reflection, 13 section-rework, 7 synthetic evaluation-adapter and 2 shell startup cases |
| Environment / aggregate time budget | 6 | Five capacity limits, separately passed; one zombie-process interaction |
| Unresolved functional product-or-fixture failures | 23 | No causal claim or assertion waiver; exact cases retained for canonical reproduction |

The 23 unresolved cases cover nine photo/rewrite invariants, six latency-profiler
expectations, two resumed-place CLI expectations, two composer deferral invariants,
two Temporal dispatch/coalescing cases, one extraction-worker result and one native
canary result. Baseline sameness alone does not classify these as stale tests.

Concrete separate blockers found while classifying:

- **Section rework:** current reads return `progressive:<event>:<writing>` IDs,
  while `workspace_rework_partition_current` still recognizes only the former
  event/source/version/hash/photo key. The actual read-head ID is rejected as
  `section changed`. The new progressive composer and the old rework membership
  validator need reconciliation; weakening its ownership/evidence checks is not
  proposed.
- **Evaluation tooling:** `scripts/memoir_fifty_browser.py:338` assumes every
  `router.routes` item has `.path`; FastAPI 0.143.0 includes `_IncludedRouter`.
  Separately, the synthetic evaluation adapters omit required canonical context.
  Normal ASGI route dispatch is not shown broken by this reflection failure.
- **Container startup:** the fixture creates `.env`, but `/bin/sh` cannot source
  `.env` by bare filename when the current directory is absent from PATH. The
  current-main `_container-up` dot command needs a portable explicit path. The
  active owner's container/security configuration was preserved here.
- **Withdrawal storage:** an unchanged SQL assertion intermittently finds original
  synthetic text in raw section/proposal storage after withdrawal. Fresh isolated
  current-main repeats yielded one failure and four passes, in addition to an
  earlier isolated pass. It passes in the pinned aggregate. This is a **potential
  product purge defect**, not dismissed as test order or environment. User-visible
  exposure is unestablished; the original assertion remains intact.
- **Descendant check:** an isolated reproduction found the parent absent and its
  descendant in `/proc` state `Z`, a zombie rather than a running child. This
  container/reaping interaction remains a failed check.

## Policy, ownership and unrun scope

The browser's `NO_MATCH` case characterizes current main: the workspace waits for
an actual map target, then opens on a later `READY` result. The earlier Issue60
compatibility document expected it to remain available before geocoding. That
older requirement is **not fulfilled or waived by this characterization pass**.
The owner must decide whether to restore it or keep the current target-gated
policy. Ordinary opt-in round-five draft access is also still a product-policy
gap. This PR repairs already eligible round-20 reload and does not change either
threshold/debug or map-availability policy.

PR68 belongs to its existing owner. Shared files are the client and stage-browser
test; overlap is lint cleanup, saved-draft hydration and fixture compatibility.
No readiness migration, attribution or polling/recovery implementation is copied.

The aggregate's **249 skips** are enumerated individually in the ledger. They
include other frontend/Auth/Chromium variants, live-model evaluations, complete-
round/artifact opt-ins, Supabase CLI, Mocker and a guest-container endpoint. Only
four stage-browser scenarios and the 13 offline fixture checks were separately
run. Other browser scenarios remain unrun. No independent agent review, live
provider quality/cost evaluation, real memoir access, production migration,
deployment, merge or physical-device testing was performed.

Exploratory serial aggregates were interrupted during implementation/rebase and
when changing runners; none is a completed gate. The historical 647-failure /
275-error report is not assumed baseline-verified. The two completed pinned
comparisons above replace that assumption with current per-case evidence.

## Reproduction

Use the task's existing test dependencies (pytest-timeout 2.4.0 and pytest-xdist
3.8.0 were installed into `/tmp/memoir-test-tools`, without changing source or the
shared virtualenv):

```sh
export PATH=/workspace/copyme2.ai/.venv/bin:/workspace/.tools/postgresql/usr/lib/postgresql/17/bin:$PATH
export LD_LIBRARY_PATH=/workspace/.tools/postgresql/usr/lib/x86_64-linux-gnu
export PYTHONPATH=/tmp/memoir-test-tools:.
export MEMOIR_TEST_TEMPORAL_CLI=/workspace/.tools/temporal/temporal
export PYTHONHASHSEED=0
python -m pytest -q -n 2 --dist=loadfile --timeout=60 --timeout-method=signal --tb=short --junitxml=/tmp/memoir-check.xml
node --test tests/js/*.test.mjs skills/memoir-composer/tests/*.test.mjs tests/historical-news/*.test.mjs
npm run check:mobile
npx eslint apps/web/client/memoir/client.js tests/js/stream-latency.test.mjs tests/js/private-draft-stream.test.mjs
npm --prefix apps/web run build -- --webpack
```

For the browser, copy `public` and `.next/static` to the generated standalone app
as described by the installed Next `output` guide, then run
`HOSTNAME=127.0.0.1 PORT=3143 node apps/web/.next/standalone/apps/web/server.js`.
In a second shell:

```sh
MEMOIR_BROWSER_URL=http://127.0.0.1:3143 MEMOIR_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q tests/test_stage_readiness_browser.py tests/test_browser_story_routes.py
```

The six long rerun IDs and their outcomes are in `capacity_reruns` in the ledger;
run them with `--timeout=600`. Versions and environment limits are recorded there.
Only newly allocated synthetic databases/services were used.
