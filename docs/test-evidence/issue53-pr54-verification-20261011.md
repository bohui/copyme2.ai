# Issue 53 / merged PR 54 verification — 11 October 2026 (Sydney)

## Verdict

**Not all requirements are resolved.** PR 54 supplies a tested, opt-in candidate,
not demonstrated every-turn latency/quality acceptance. Keep issue 53 open.
Two reproducible implementation issues and remaining test/evidence gaps are
described below. This review changed no application code, deployment settings,
gateway policy, customer memoirs, or GitHub issue state.

## Reviewed source

- Issue: https://github.com/bohui/copyme2.ai/issues/53
- PR: https://github.com/bohui/copyme2.ai/pull/54
- Fixed PR base: `f2f719f8a530cfbdda9c63250407215228d8232d`
- PR head: `1001f1b8046e7e102d083fb32215913142742f82`
- Merge: `87e409754fd52ab01125941cdd8033c0bdfa0be7`
- Tested checkout: `24e1edfd5879e1793213c3e885d5071eb5e44c49`
- The later `24e1edf` quotes empty Compose overrides; it is separate from PR 54.
- Existing untracked `tests/test_collector_compose_config.py` was used but not
  modified. Its three cases cover absent, empty, and explicit overrides.
- No CI result is claimed. The PR reports cloud tests, but this report lists only
  checks actually performed in this review.

## Running configuration and read-only provider receipts

API and private worker both resolved:

```json
{"model":"gpt-5.6-luna-pooled","effort":null,"prompt_version":"legacy"}
```

Both have empty collector model/effort overrides, `legacy` prompt, and legacy
reasoning effort `max`. Source hashes in both containers match the reviewed
checkout for their collector configuration, prompt, and runtime/worker modules.
**The optimized candidate is not active in the running app.**

Read-only gateway `/model/info` returned:

| Route | Underlying model | Configured effort |
| --- | --- | --- |
| `gpt-5.6-luna-pooled` | `openai/gpt-5.6-luna` | max |
| `memoir-luna-low` | `openai/gpt-5.6-luna` | low |

Read-only codex-lb key policy likewise showed active `trading-gpt56-luna` enforcing
`max` and active `memoir-background-luna-low` enforcing `low`, both on
`gpt-5.6-luna` and foreground traffic class. This verifies configured identity
and policy now, not the actual effort of an unrun candidate request. No key or
credential was printed or changed.

A matched synthetic opening prompt in current source measured 27,977 instruction
characters for `legacy` and 11,802 for `compact-v1`: **57.8% fewer characters**.
This is not a provider-token measurement or a latency improvement measurement.

## Executed checks

Counts across runs overlap; they must not be added as a unique-test total.

| Run | Observed result |
| --- | --- |
| Collector configuration, Compose interpolation, name-only opening, turn stream, workspace latency, profiler | **100 passed**, 1.32s |
| Broader default interview/photo/worker/lease/family/language/source-proof/runtime-readback set | **265 passed, 14 skipped, 9 setup errors**, 61.98s |
| Candidate-enabled interview/stream/workspace/photo/lease/family/language set | **189 passed, 4 skipped, 9 setup errors**, 10.01s |
| Nine errored photo/persistence cases rerun with candidate enabled and disposable Apple-container PostgreSQL | **9 passed**, 6.19s |
| Candidate-enabled complete-runtime readback with explicit real-PostgreSQL opt-in | **28 passed**, 6.12s |
| Five JavaScript streaming/language/photo/history/project-recovery files | **53 passed**, 0.127s |
| PR and current-worktree whitespace checks | Passed |

The nine original setup errors came from host `initdb`, before application
assertions: `could not create shared memory segment: No space left on device`.
The PostgreSQL diagnostic explicitly says this is shared-memory capacity, not
disk space. The single-user fallback also failed at the same initialization step.
The existing disposable-container backend resolved those nine cases without
changing the host kernel, installing packages, or stopping existing services.
No task-owned `memoir-issue6-pg-*` container remained after fixture cleanup.

The 14 broader skips were four explicit live-model cases plus ten opt-in
PostgreSQL readback cases. The ten PostgreSQL cases were subsequently exercised
inside the 28-pass opt-in run. The four live-model cases remain unrun.
No full-suite rerun, real-provider candidate comparison, or real-proxy browser
acceptance was performed. JavaScript tests are not browser paint measurements.

The candidate-enabled process used:

```text
MEMORY_SPARK_COLLECTOR_MODEL=memoir-luna-low
MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=low
MEMORY_SPARK_COLLECTOR_PROMPT_VERSION=compact-v1
```

These settings were limited to test subprocesses. Real-PostgreSQL verification
used `MEMOIR_TEST_POSTGRES_BACKEND=apple-container`; runtime readback additionally
used `MEMOIR_TEST_ARTIFACT_POSTGRES=1`. Test databases and worker responses were
isolated/synthetic; no live LLM was dispatched by these tests.

## Standards review

1. **Incorrect model attribution (reproduced).** With runtime/evaluation model
   `legacy-route` and collector override `memoir-luna-low`, the actual thread
   dispatch selects `memoir-luna-low`, but the primary trajectory context,
   correlation, and provider metadata still say `legacy-route`.
   `apps/api/codex_runtime.py` sets root context from `self.model` and forwards
   the unchanged correlation after resolving the override. README's evaluation
   documentation requires model correlation metadata. Record resolved collector
   routing separately/correctly throughout the experiment and add a regression
   assertion; otherwise baseline/candidate evidence can be mislabelled.

   The controlled production-runtime probe returned:

   ```json
   {"actual_dispatch_model":["memoir-luna-low"],"trajectory_context_model":"legacy-route","trajectory_correlation_model":"legacy-route","provider_metadata_model":"legacy-route","conversation_saved":true}
   ```

2. **Artifact-link failure coverage gap (static, pre-existing behavior).** The
   changed workspace/readback tests exercise delayed artifact linking and failed
   Family persistence, but not an artifact-link write that fails. Existing runtime
   handling treats artifact synchronization failure as recoverable enrichment.
   Passing the new success barrier does not establish failed-link job-retention
   behavior. Add that negative case before claiming coverage of every durable
   workspace failure. This is not a newly introduced production defect in PR 54.

No additional substantive standards/style finding was retained. The separate
Compose quoting follow-up passed the real Mocker interpolation checks.

## Spec review

3. **Uncontrolled JSON configuration failure (reproduced).** Invalid collector
   effort/prompt configuration raises `ValueError`. Non-streaming API and worker
   handlers translate `RuntimeError`, not this error. An authenticated private
   worker JSON request with invalid effort returned HTTP 500,
   `text/plain`, `Internal Server Error`. The same request accepting NDJSON
   returned the expected controlled error event. Translate server-configuration
   failure to a sanitized structured failure and cover both interfaces. Validation
   is bounded and happens before model dispatch, but the JSON failure envelope is
   missing. This affects misconfiguration, not valid normal chat.

4. **Populated resumed-planning acceptance remains incomplete.** The new resume
   test proves selected route/effort, unchanged current narration, smaller prompt,
   and rollback dispatch. Its planning context is empty and generated proposal
   fixed. It does not prove useful unasked candidates survive a pre-rollout resume,
   answered candidates retire, and the next question continues correctly. The
   broader candidate-enabled tests now cover correction, photos, language and
   stop validation; actual generated behavior and populated multi-turn/resume
   continuity still need acceptance evidence.

5. **Live release gate remains unverified, deliberately.** Current configured
   same-model/effort policy was verified read-only during this review, but no
   merged-candidate matched first/later/resumed latency/quality experiment or
   real-proxy browser smoke exists from this review. The deployed candidate is
   still disabled. This is consistent with rollout documentation, but cannot
   satisfy issue 53's faster-every-turn outcome or close the issue.

No material production scope expansion was found.

## All 48 issue requirements

Numbers below refer to issue 53's numbered user stories, assessed together with
its implementation/testing decisions. They are not 48 independently passing
unit tests. **Covered** means supported by inspected code and executed controlled
checks; it does not certify live-provider quality or every production condition.
**Partial** means implementation evidence exists but a required scenario or live
acceptance is missing. **Pending** means the outcome has not been demonstrated.

| ID | Requirement | Status and evidence / remaining work |
| --- | --- | --- |
| 1 | Prompt meaningful text on every answer | Pending: no candidate live every-turn comparison; deployment is legacy. |
| 2 | Fast preferred-name opening | Partial: name/work/stream contract passed; candidate live speed pending. |
| 3 | Faster second and later answers | Pending: candidate-enabled controlled tests are not latency evidence. |
| 4 | Faster resumed conversations | Partial: resume route selection tested; real resumed latency pending. |
| 5 | Existing projects benefit without story migration | Partial: per-generation resolution and unchanged storage; candidate not deployed. |
| 6 | Mixed introduction retains story details | Partial: complete input and work selection covered; generated semantic quality pending. |
| 7 | Grounded long/emotional continuation | Partial: long source preserved; generated emotional/grounding quality unverified. |
| 8 | One useful follow-up at a time | Partial: structured one-question validation covered; usefulness requires live quality review. |
| 9 | Concrete grounded acknowledgement | Partial: validation/prompt retained; actual candidate generation unrun. |
| 10 | Remember relevant recent exchanges | Partial: context plumbing retained; populated multi-turn continuity acceptance missing. |
| 11 | Preserve name/context on resume | Partial: route/resume and exact input tested; real provider-history continuity pending. |
| 12 | Text before optional workspace completes | Covered: stream/workspace independence regressions passed. |
| 13 | Visible text distinct from safe save | Covered: partial text/save/failure regressions passed. |
| 14 | Next-answer readiness after save | Partial: backend/JavaScript behavior covered; real-proxy browser smoke pending. |
| 15 | Optional chapters/timeline/family/references do not block reply | Covered: existing save/workspace seam and candidate regressions passed; no polling dependency added. |
| 16 | Minimal reply avoids extraction | Covered: name-only one-pass/reply-only regressions passed. |
| 17 | Short/rich clues still extracted | Partial: model-boundary proposals and source preservation covered; live extraction decisions pending. |
| 18 | Corrections affect future work | Partial: controlled correction and canonical photo persistence covered; live multi-turn acceptance pending. |
| 19 | Respect pauses/stops promptly | Partial: stop/proposal contract covered; actual candidate stop behavior/latency pending. |
| 20 | Chinese and exact original names | Partial: exact-name/language contracts passed; low-route semantic quality pending. |
| 21 | English receives latency improvement | Pending: no English candidate latency comparison. |
| 22 | Later explicit language changes | Covered: candidate-enabled language/persistence regressions passed; live quality remains separate. |
| 23 | Ground photographs in identification/metadata | Partial: validation and real-SQL photo cases passed; generated associations still require quality acceptance. |
| 24 | Public references are not personal evidence | Partial: prompt/validation distinction retained; candidate semantic acceptance pending. |
| 25 | Place cue/journey is not biography | Partial: terminology/instructions retained; generated compliance unverified. |
| 26 | Entitled relevant Family context | Partial: family authorization/context tests passed; candidate's generated use unverified. |
| 27 | Keep payment/recall/ownership checks | Covered: fenced entitlement reuse and unchanged gating with relevant regressions. |
| 28 | Correct/reject malformed proposals before questions | Covered: candidate-enabled correction/validation/publication tests passed. |
| 29 | Retry without duplicate accepted/saved exchanges | Covered: idempotent retry/source/plan regressions passed. |
| 30 | Replay saved replies without regeneration | Covered: saved replay bypasses new/invalid configuration; regression passed. |
| 31 | Clear disconnect/save failure behavior | Covered: streaming failure/cancellation checks passed. |
| 32 | Isolate account/project private context | Partial: relevant worker and real-SQL owner-scoped checks passed; actual Linux tenant-UID isolation was not rerun. |
| 33 | Independent collector route/effort configuration | Covered: local/worker first/later/resume and unaffected-role tests passed. |
| 34 | Verify effective upstream reasoning | Partial: current configured gateway/key policy read back; actual candidate request effort remains unverified. |
| 35 | Current config on existing session's next generation | Covered at controlled interface: start/resume routing tested; real persisted-provider acceptance still pending. |
| 36 | Leave shared max key unchanged | Covered: no policy mutation; current shared max enforcement verified. |
| 37 | Reversible rollback without story rewrites | Partial: controlled rollback passed; deployed multi-turn rollback acceptance unrun. |
| 38 | Bounded unavailable/misconfigured route behavior | Partial: no-fallback test passed; JSON misconfiguration failure envelope is defective (finding 3). |
| 39 | Separately measure first text/question/save | Partial: existing HTTP profiler/tests retain distinctions; candidate end-to-end report missing. |
| 40 | Safe phase/route/effort/retry/outcome diagnostics | Partial: safe requested/unavailable-effort receipt covered; stale model attribution (finding 1) and full provider-request comparison remain. |
| 41 | First/subsequent/resumed latency reports | Pending: no merged-candidate representative report. |
| 42 | Distributions plus failures/tails | Pending: no fixed-sample matched report; no p95 claim is justified. |
| 43 | Prompt reduction preserves interview behavior | Partial: 57.8% smaller matched instructions and deterministic regressions; semantic continuity/quality acceptance pending. |
| 44 | Optimize reads safely | Covered: one entitlement read per fenced turn, no cross-turn cache or new parallel I/O. |
| 45 | Deterministic backend streaming primary seam | Covered: existing backend/configuration/stream/correction/SQL checks executed; frontend is secondary. |
| 46 | Bounded isolated synthetic live measurements | Partial: existing profiler remains; no candidate live experiment with representative cases/budget was dispatched. |
| 47 | Quality/latency comparison before optimized default | Pending acceptance: no comparison; correctly still disabled. |
| 48 | Record comparable configuration/source versions | Partial: source/prompt/route pins exist; stale attribution must be corrected and matched live versions/results recorded. |

## What remains before closing issue 53

1. Correct findings 1 and 3 and add backend regression assertions.
2. Add populated saved-planning/multi-turn/resume acceptance, retaining useful
   unasked candidates and retiring answered ones. Address the artifact-link
   negative-test gap if claiming complete workspace failure coverage.
3. Freeze cases, sample count, total request budget/deadline and quality/latency
   criteria. Compare baseline, routing-only, prompt-only where feasible, and
   combined candidate on a pinned revision, in both languages and first/later/
   resumed turns. Include failed/timed-out/corrected calls, actual provider
   policy/token/cache observations, and visible/question/save timings.
4. Complete generated quality acceptance and the small real-proxy browser smoke.
   Do not substitute schema validity or instruction-size reduction for these.
5. Enable the optimized default only after that gate passes; verify a next
   generated turn on an existing conversation and a subsequent rollback turn.

**Axis summary:** Standards: 2 findings, worst is incorrect model attribution.
Spec: 3 findings, including reproduced JSON error handling and missing release
evidence. No production change or rollout was performed by this verification.
