# Memoir five-case E2E and evaluation final report

Date: 2026-10-03 UTC  
Scope: isolated synthetic projects only; no customer memoir, private family
data, production database, migration, deployment, or shared-service restart.

## Executive result

The requested design and harness are implemented, but full live acceptance
remains blocked by provider/worker instability and six deterministic
expectation failures after one evaluator-oracle correction. Two independent
live five-case executions and a separate provider-free corrected regrade are
preserved:

1. The immutable baseline `live-five-case-shared-20261003` completed exactly
   50 rounds for each of five fictional biographies: **250/250 rounds**, with
   **160 pass, 77 deterministic failures, and 13 unavailable**. All five
   cases observed all seven life stages.
2. The post-fix `live-five-case-final-low-kinship-v4-20261003` also completed
   exactly 50 rounds for each case, but its bounded provider/worker path became
   unavailable late in Kunming and Sydney. It records **165 pass, 7 failures,
   and 78 unavailable**. It is a complete live execution receipt, not a green
   quality gate; Kunming and Sydney do not claim full observed stage coverage
   because their later rounds did not complete.
3. The provider-free corrected-oracle regrade copied the v4 traces into
   `live-five-case-final-low-kinship-v4-oracle-corrected-v2-20261003`. It
   records **166 pass, 6 failures, and 78 unavailable**. It changes only the
   Harbour round-30 expected stage from `midlife` to `young_adulthood` under
   the existing checked-in 23–30 band; it does not change the runtime stage
   schema, overwrite either live run, or add a live-provider claim.

The baseline remains immutable evidence of the original full run. The v4 run
is the current post-fix diagnostic result and must not be substituted into the
baseline totals.

| Case | Baseline pass/fail/unavailable | v4 original oracle | Corrected-oracle regrade |
|---|---:|---:|---:|
| `harbour-copper-notebook` | 25/21/4 | 40/2/8 | 41/1/8 |
| `chengdu-tea-ledger` | 34/15/1 | 46/1/3 | 46/1/3 |
| `perth-workshop-compass` | 31/15/4 | 41/2/7 | 41/2/7 |
| `kunming-garden-lanterns` | 30/19/1 | 22/1/27 | 22/1/27 |
| `sydney-platform-letters` | 40/7/3 | 16/1/33 | 16/1/33 |
| **Total** | **160/77/13** | **165/7/78** | **166/6/78** |

All three artifacts contain exactly 50 saved rounds per case. The baseline and
original v4 receipts remain immutable; the corrected column is a deterministic
regrade of copied v4 traces, not a third live execution.

The live path was the production orchestration seam:

`CodexRuntime.turn → private codex-worker → Codex CLI app-server → configured llm_provider`.

The configured provider was the existing `192.168.66.1:4000/v1` gateway with
model `gpt-5.6-luna-pooled`; the previously suspected `.68.1` endpoint was
not used. Provider token and cost fields were not exposed. The v4 receipt
records 114 private-worker requests; the baseline records 524. Both retain
`null` token/cost fields rather than estimating them.

## Reproducible inputs and evaluator boundary

Executable code, model-visible synthetic inputs, hidden truth, expected
outcomes, judge prompt, and calibration examples are separate:

- Design: [memoir-five-case-evaluation-design.md](memoir-five-case-evaluation-design.md)
- Runner: [run_memoir_five_case_evaluation.py](../scripts/run_memoir_five_case_evaluation.py)
- Evaluator: [memoir_five_case_evaluator.py](../scripts/memoir_five_case_evaluator.py)
- Model-visible inputs: [memoir_five_case_inputs.json](../tests/evaluation/memoir_five_case_inputs.json)
- Expected outcomes: [memoir_five_case_expected.json](../tests/evaluation/memoir_five_case_expected.json)
- Oracle-only corrections: [memoir_five_case_oracle_corrections.json](../tests/evaluation/memoir_five_case_oracle_corrections.json)
- Hidden truth: [memoir_five_case_truth.json](../tests/evaluation/memoir_five_case_truth.json)
- Judge prompt/calibration: [memoir_five_case_judge_prompt.md](../tests/evaluation/memoir_five_case_judge_prompt.md), [memoir_five_case_judge_calibration.json](../tests/evaluation/memoir_five_case_judge_calibration.json)

The worker received only the current synthetic storyteller response and the
persisted synthetic application state. Expected outcomes and hidden truth
were post-run evaluator inputs, never worker instructions. Each trace records
the request, response, observable trajectory, state checks, UI observations,
skill grades, timing, errors, usage receipt, and a replay command.

Run artifacts:

- Immutable baseline: `var/memoir-five-case-evaluation/live-five-case-baseline-20261003/`
- Post-fix v4: `var/memoir-five-case-evaluation/live-five-case-final-low-kinship-v4-20261003/`
- Corrected-oracle regrade: `var/memoir-five-case-evaluation/live-five-case-final-low-kinship-v4-oracle-corrected-v2-20261003/`
- Five-round family-routing pilot: `var/memoir-five-case-evaluation/live-five-case-kinship-pilot-20261003/`
- Bounded Kunming replay stopped for provider latency: `var/memoir-five-case-evaluation/live-five-case-kunming-single-low-20261003/`

## Stage and skill evidence

The checked-in biographies cover `baby`, `toddler`, `childhood`,
`adolescence`, `young_adulthood`, `midlife`, and `later_life`. The immutable
baseline observed all seven in all five cases. The v4 receipt observed all
seven in Harbour, Chengdu, and Perth; the late worker failures prevent that
claim for Kunming and Sydney.

The corrected-oracle regrade skill totals below combine required positive scenarios
and explicit negative/unnecessary-call scenarios. A required positive call is
reported as invocation/output; a negative entry is reported as correct
must-not-call behavior. Unavailable rounds are not silently counted as model
passes. The regrade is provider-free and uses the saved v4 trajectories.

| Skill | Required invocation/output | Correct negative calls | Contract failures | Unavailable |
|---|---:|---:|---:|---:|
| `memoir-memory-context` | 183/250; 183/250 | n/a | 67 | 0 |
| `memoir-author-timeline` | 67/88; 67/88 | 49/52 | 24 | 0 |
| `memoir-family-tree` | 44/60; 44/60 | 44/45 | 17 | 0 |
| `memoir-place-groups` | 66/89; 66/89 | 46/47 | 24 | 0 |
| `memoir-place-journey` | 66/89; 66/89 | 46/47 | 24 | 0 |
| `place-photo-research` | 9/10; 9/10 | 54/54 | 0 | 1 |
| `memoir-composer` | 0/15; 0/15 | 54/54 | 5 | 10 |

The original v4 oracle had seven round-level failures. Six remain after the
separate oracle correction below; all are actionable and trace-backed:

- Chengdu round 44 made an unnecessary author-timeline call for an undated
  reflection.
- Harbour round 46 made unnecessary place-group and place-journey calls for an
  intentionally unresolved place.
- Kunming round 19 made an unnecessary family-tree call.
- Perth round 7 missed the required family-tree call for a known person named
  June; round 44 made an unnecessary author-timeline call.
- Sydney round 19 made an unnecessary author-timeline call.

### Oracle-only boundary correction

The Harbour round-30 mismatch was a test-design contradiction, not an app
schema decision. The application contract enumerates allowed stage labels but
does not define a numeric age cutoff. The checked-in dataset band permits
`young_adulthood` through age 30, and Harbour’s “early thirties” wording was
persisted by the runtime as `young_adulthood`. The expected outcome now records
that value for Harbour round 30 only; the other four round-30 prompts contain
explicit midlife anchors and remain `midlife`.

The correction is separately recorded in
[memoir_five_case_oracle_corrections.json](../tests/evaluation/memoir_five_case_oracle_corrections.json)
with `runtime_schema_changed: false` and
`baseline_artifacts_overwritten: false`. The evaluator regression test covers
the boundary and confirms the original baseline is untouched. The corrected
regrade changes the aggregate from 165/7/78 to 166/6/78; no runtime patch was
made for this classification.

Failure disposition and remaining remediation:

| Round | Evidence-backed cause | Remediation status |
|---|---|---|
| Chengdu 44 | Reflective later-life text triggered an unnecessary timeline marker; no author event/date was present. | **Guard applied post-v4**; full live recheck is blocked. |
| Harbour 46 | An ambiguous “old town beyond Launceston” request still produced place-group/journey work. | **Guard applied post-v4**; full live recheck is blocked. |
| Kunming 19 | A repeated known person (`阿青`) was emitted as a new Family person even though the turn only added place/time uncertainty. | **Idempotent-name guard applied post-v4**; full live recheck is blocked. |
| Perth 7 | Known person `June` was not recognized by focused Family recovery. | **Code fix applied and unit/pilot-tested**; the full replay was provider-latency blocked, so full-run verification remains outstanding. |
| Perth 44 | A later-life reflection triggered unnecessary timeline work. | **Guard applied post-v4**; full live recheck is blocked. |
| Sydney 19 | A date-order question about `Ben` triggered author timeline even though it described another person’s timing. | **Guard applied post-v4**; full live recheck is blocked. |

These are deterministic expectation failures, not judge findings. The applied
routing guards still need a provider-healthy live replay before they can be
called acceptance fixes.

Post-v4 hardening is now implemented for the unambiguous routing defects, but
is not retroactively included in the v4 counts: timeline recovery no longer
uses a bare `I/we` cue and drops a model timeline marker for reflective or
third-person uncertainty text; explicit place ambiguity blocks preview and
persistence; and a unique exact persisted Family name/alias is merged
idempotently when no `existing_id` is supplied. These guards have targeted
regression coverage, but the provider stopped the affected full replay before
live re-verification. The Harbour early-thirties classification is covered by
the separate oracle correction, not by a runtime taxonomy change.

The family recovery patch now cue-gates focused recovery on explicit domain
language and also recognizes a person already present in persisted Family
context (without turning arbitrary capitalized words into people). The
targeted regression suite passes, and the five-round live kinship pilot passes
5/5. A fresh full Perth replay was attempted only after provider and worker
smoke preflight passed; round 1 took 94.3s and passed, round 2 hit the bounded
150s deadline, and the replay was stopped after two saved rounds. It remains
latency-blocked rather than a full quality rerun.

## Photo-search budget and provenance

The v4 run spent the bounded planned budget: **10/10** production photo-worker
calls, two positive scenarios per case, and no external call for negative
rounds. SerpAPI/CSE results were retained as public reference metadata only.
Partial, no-match, and unavailable results remain visible; unknown rights are
not permission and no source photo was fabricated or downloaded.

The v4 photo summary records: Chengdu READY/NO_MATCH; Harbour two PARTIAL;
Perth UNAVAILABLE/PARTIAL; Kunming READY/NO_MATCH; and Sydney two PARTIAL.
The existing 24-hour public metadata cache, source/date/rights filters,
provider attribution, and cross-provider deduplication remain the production
shaped path.

### Why the 78 unavailable rounds are not one failure

The v4 per-round traces classify the 78 unavailable outcomes as follows:

| Receipt evidence | Count | Interpretation |
|---|---:|---|
| `RuntimeError: Codex worker turn failed`, 0.2–0.9s, three progress events | 57 | A clustered app-server/provider turn non-completion beginning at Kunming 25 and Sydney 20. The worker boundary returned a generic failure; the current redaction intentionally does not preserve the provider stop/error code. |
| Main turn `TimeoutError`, about 210s | 10 | Bounded runner/worker deadline reached while Codex was still waiting for completion. |
| Composer checkpoint `TimeoutError`, about 300s | 10 | Bounded private-draft/compose phase exceeded its 300s limit; the visible chat turn was already saved. |
| Photo worker `UNAVAILABLE` (`robots_denied`, HTTP 403) | 1 | Perth current-day public photo search had no usable provider result; no photo was treated as evidence. |

Provider and worker health probes can therefore pass while a sustained
multi-turn run fails. The smallest external next step is for the provider or
worker operator to inspect gateway/app-server turn-completion, concurrency,
and rate-limit logs for the configured model, then rerun the one-turn worker
smoke probe followed by a single-case Perth replay at concurrency 1. The
smoke probe passed at 4.21s, but Perth round 2 immediately timed out at 150s
after round 1 took 94.3s, so the full replay was stopped rather than spending
48 more bounded turns. Receipts:
[provider-connectivity-final-check-20261003.json](../var/memoir-five-case-evaluation/provider-connectivity-final-check-20261003.json),
[codex-worker-smoke-final-20261003.json](../var/memoir-five-case-evaluation/codex-worker-smoke-final-20261003.json),
and `live-five-case-perth-named-person-final-20261003/`.

### Read-only gateway and app-server log closure

Existing local runtime logs were inspected without reading secrets, raw auth
headers, or private biography content, and without restarting or changing any
service. The authorized LiteLLM gateway log at
`~/Library/Application Support/com.apple.container/containers/llm-provider-litellm-1/stdio.log`
contains these sanitized access outcomes for `POST /v1/responses`: **1,585
HTTP 200**, **231 HTTP 403**, **3 HTTP 500**, and **2 HTTP 502**. The 500/502
blocks include `OpenAIException`/connection-closed or internal/bad-gateway
errors, supporting provider-side instability but not identifying a particular
application turn. The access lines do not include timestamps, run IDs, turn
IDs, or request IDs.

The isolated worker SQLite logs contain five older/configuration-mismatch
retries for `gpt-5.6-terra` with HTTP 403 (“key not allowed to access model”) at
2026-10-03 18:54:48–18:54:51 UTC, plus one relevant
`gpt-5.6-luna-pooled` retry at 2026-10-03 19:49:09 UTC after “stream
disconnected before completion.” That latter worker turn, internal ID
`01a1034f-b094-7012-8d5d-7cc9b9433d38`, completed after the retry. The worker
logs expose no queue/concurrency saturation fields and no ERROR-level
app-server event for the saved v4 failure; no 429 rate-limit response was
observed in the gateway access summary.

For a concrete saved synthetic failure, v4 Sydney round 20 has run ID
`live-five-case-final-low-kinship-v4-20261003`, app turn ID
`9e63224e-40c4-4583-a4c8-c31ce6496e8a`, generic `Codex worker turn failed`,
767.9 ms elapsed, and two worker requests. Its trace contains no provider
status, request ID, or timestamp, and the gateway log has no correlation key;
therefore the 500/502 entries cannot safely be assigned to that round. The
old v4 trace remains uncorrelated. The approved follow-up added privacy-safe
request-ID/timing diagnostics at the Memoir API worker client, private worker,
Codex app-server client, and configured gateway hook, then restarted only the
affected local API/worker/gateway services. A bounded invalid-model probe
verified the same request ID across the gateway authorization failure,
app-server failed turn, and API 502; the receipt is
`var/memoir-five-case-evaluation/codex-path-diagnostics-20261003.json`. This
improves future replay correlation but does not retroactively change the v4
quality totals or make the provider healthy. No new credentials or remote
access were requested, and no further long five-case rerun was started.

## Composer implementation and benchmark

The composer now keeps the full canonical request in the host for planning,
validation, and persistence, while bounded draft/review model packets select
new, changed, affected, and overlap sources. The packet includes dirty/carry
forward chapter IDs, canonical source/event/period manifests, and invalidated
IDs for deletions. A compact validation/review problem triggers one bounded
full-context repair inside the existing three-attempt ceiling. This preserves
grounding and stale-source gates rather than weakening them.

Deterministic synthetic packet benchmark receipt:
[composer-incremental-packet-benchmark-20261003.json](../var/memoir-five-case-evaluation/composer-incremental-packet-benchmark-20261003.json)

- canonical sources: 40; compact model sources: 7;
- source text: 19,176 → 3,360 characters (**82.5% lower**);
- draft packet: 59,556 → 34,313 bytes (**42.4% lower**);
- review packet: 59,558 → 34,315 bytes (**42.4% lower**);
- successful phase-call budget remains 3 before/after; index packet unchanged.

The corrected live orchestration receipt is
[composer-incremental-live-benchmark-20261003-v3.json](../var/memoir-five-case-evaluation/composer-incremental-live-benchmark-20261003-v3.json).
Both full and compact `compose_candidate` paths reached the real index phase
with one worker request each, but the configured provider returned a
non-completing composer response before draft/review:

- full: 8,068.8 ms, one request, `RuntimeError`, unsuccessful;
- compact: 8,882.6 ms, one request, `RuntimeError`, unsuccessful.

Therefore no live full-vs-compact latency winner or semantic consistency claim
is made. The packet-size reduction is measured; successful live phase latency
remains unavailable until the provider returns valid structured composer
responses.

## UI audit and fixes

The isolated source-aligned browser audit passed desktop/mobile layout, fixed
header and composer, loading/send/response rendering, nested history manual
scrollback, locale switching and persistence, workspace map/photo/timeline
visibility, and a bounded policy-epoch conflict/retry journey. Evidence is in
[memoir-ui-audit-20261003.md](memoir-ui-audit-20261003.md) and
`var/memoir-five-case-evaluation/ui-audit-20261003/`.

The policy bug was fixed in `apps/api/main.py` and
`apps/web/client/memoir/client.js`: a stale session epoch now resynchronizes
once on resume and retries the same answer options once. The patched browser
journey observed the intentional first `409`, resume `200`, retry `200`, and
completed agent turn. The old shared `memory-spark-web-1` image on port 3010
was not restarted; source-aligned verification used an isolated host pair.
Microphone permission/real audio, family entitlement UI, and full-book UI
were not claimed as verified.

Coverage distinction: the desktop/mobile screenshots and policy-retry journey
were real browser executions against the isolated source-aligned host pair;
the read-only port-3010 container inspection did not mutate or deploy that
shared service. The 31 passing Node UI/state tests are unit/state checks, not
browser runs. Six Python browser tests were skipped because an isolated source
frontend was not configured. Live runner UI observations for maps/photos/
timeline are application-state receipts, not claims that every panel was
visually exercised in a browser.

## LLM-native web-search capability

The read-only provider model catalog exposed no tool capability metadata. The
runtime config does not set `web_search = "live"` or
`supports_standalone_web_search = true`; local Codex feature flags also show
the standalone search path disabled/under development. Those facts alone do
not prove the provider lacks search.

A single bounded authenticated POST `/responses` probe used the existing
provider credentials and a synthetic question with a native-looking
`web_search` tool request. It returned HTTP 200, but the observable response
had no web-search item and no citation host. The durable result is
`inconclusive_no_search_evidence`, not unsupported and not a capability pass:
[provider-web-search-probe-20261003-escalated.json](../var/memoir-five-case-evaluation/provider-web-search-probe-20261003-escalated.json).

No new key, subscription, permission, provider, or search wiring was added.
The safe future design is a flag-off provider-native adapter in parallel with
SerpAPI/CSE, enabled only after an observable tool/citation preflight, then
subject to the existing provenance, date, rights, URL, and deduplication
filters.

## Validation receipts

Completed after the source changes:

```text
py_compile runtime/preview/private_drafts/main/benchmark/search probe: passed
pytest final runtime/domain/evaluator regression suites: 172 passed (the
earlier changed-runtime subset was 104 passed)
pytest tests/test_memoir_five_case_evaluator.py: 9 passed
Node composer/progressive suite: 62 passed
Node UI/state suite: 31 passed
pytest evaluator/config/browser adapters: 11 passed, 6 expected browser skips
```

The corrected-oracle regrade was provider-free and completed for all 250
saved rounds: **166 pass, 6 deterministic failures, 78 unavailable**. It did
not issue a provider request. The original v4 summary remains unchanged.

The six skips require an isolated source frontend and are not represented as
passes. The semantic judge integration does exist: `OpenAICompatibleJudge` can
submit the compact trace prompt to the same configured provider. A one-sample,
no-retry exploratory run on completed Chengdu round 1 made one call, but hit a
20.1s `ReadTimeout`; the receipt is
`live-five-case-final-low-kinship-v4-20261003/semantic-judge.json`. A separate
sample of an unavailable round was correctly marked `not_judged` without a
provider call. The calibration manifest also fails the required
`human-reviewed` validation (`ValueError`), so even a future scored response
would remain provisional and non-gating until human calibration is approved.
No judge-only greenwashing was used.

## Remaining blockers and replay

1. Provider latency/turn-completion instability remains the dominant live
   blocker. V4 Kunming and Sydney late-round worker failures and the stopped
   sequential replay are preserved rather than retried without a bounded
   budget. The read-only logs support provider errors and a stream disconnect,
   but do not prove queue/concurrency saturation or correlate one gateway
   status to the saved Sydney round 20. The new diagnostics receipt proves
   correlation for a later bounded synthetic failure; a provider-healthy
   replay is still required to attach that evidence to successful five-case
   turns.
2. Live model invocation still misses some positive author-timeline and
   family-tree cases and occasionally calls negative place/timeline skills.
   The focused known-person family fix is unit-tested and pilot-tested, but a
   fresh full Perth replay is still required when provider latency permits.
3. Composer success/latency comparison and semantic consistency remain
   unavailable until the provider returns valid structured index/draft/review
   responses.
4. The exploratory semantic judge timed out once, and no human-approved
   calibration is available; no semantic score is an acceptance result.
5. The shared web container remains stale relative to source; normal rollout
   requires explicit deployment authorization. Browser microphone behavior was
   not exercised.
6. Provider token/cost accounting is unavailable, and Codex host/worker
   version alignment remains a reproducibility risk.

The reusable worker smoke probe is
[memoir_codex_worker_smoke_probe.py](../scripts/memoir_codex_worker_smoke_probe.py).

Resume/replay examples (fresh isolated worker and existing configured secrets
are required for live commands):

```bash
# Deterministically inspect or regrade the completed v4 traces without calls.
python3 scripts/run_memoir_five_case_evaluation.py \
  --mode live --run-id live-five-case-final-low-kinship-v4-20261003 \
  --resume --regrade --skip-preflight

# Deterministically regrade with the corrected Harbour round-30 oracle.
python3 scripts/run_memoir_five_case_evaluation.py \
  --mode live --run-id live-five-case-final-low-kinship-v4-oracle-corrected-v2-20261003 \
  --resume --regrade --skip-preflight

# Static composer packet benchmark; no provider call.
python3 scripts/benchmark_memoir_composer_incremental.py \
  --output var/memoir-five-case-evaluation/composer-incremental-packet-benchmark-20261003.json

# Provider/search capability probe is bounded to one synthetic request.
python3 scripts/memoir_provider_web_search_probe.py \
  --output var/memoir-five-case-evaluation/provider-web-search-probe-replay.json
```

No claim is made that every bug in every untested environment is fixed. The
receipts above identify exactly what passed, what was unavailable, what was
mock-only or skipped, and which full reruns still depend on provider health.
