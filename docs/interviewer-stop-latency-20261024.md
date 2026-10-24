# Interviewer stop/news fixes and latency — 24 October 2026

Committed application source: `711050cab208a5dfca8cbd2361ed6c2463d86929`; before: `f190c33`. No prompt text, prompt receipts, schema baseline, provider credentials or gateway settings changed.

Both ready-news stop failures are fixed. The host renders explicit stopping, the fixed optional news invitation, and neutral prepared-clarification acknowledgements from validated state; the model still determines current intent. Prepared and continuation selections honor the highest unresolved hint. Current correction/redirect/pacing/stop decisions and exact question resolution retain precedence. The opted-in pooled + low + reply-v2 configuration dispatches policy/reply through the existing dedicated low-policy alias.

Across the 30 cases that pass in both arms, median correct-response time fell **11.17s → 5.55s (50.3%)**. Before: 30/34 meaningful replies; after: 32/34. The two existing correction-after-stop failures remain. One sample per case; these medians compare distinct scenarios and are not production percentiles.

Timing starts at canonical submission and counts the correct delivered question; selected news also requires validated citation metadata. A stop requires a retained explicit stop acknowledgement with no question/news. Generic acknowledgement and progress text do not satisfy the target. Values below are **English / Chinese**.

| skill name | work scenario measured | before | after |
| --- | --- | --- | --- |
| memoir-interviewer | Queued date conflict | 12.99s / 8.54s | 5.35s / 6.41s |
| memoir-interviewer | Queued person clarification | 7.52s / 11.78s | 4.57s / 5.07s |
| memoir-interviewer | Queued event-order clarification | 8.90s / 9.64s | 5.18s / 4.87s |
| memoir-interviewer | Ready cited news | 24.87s / 57.23s | 7.21s / 5.60s |
| memoir-interviewer | Planned topic expansion before news | 8.70s / 10.15s | 4.54s / 6.46s |
| memoir-interviewer | Stop with clarification and news | FAIL / FAIL | 4.78s / 4.88s |
| memoir-interviewer | Current topic change | 8.92s / 7.99s | 4.93s / 5.52s |
| memoir-interviewer | Privacy exclusion and topic change | 9.48s / 10.67s | 6.00s / 8.01s |
| memoir-interviewer | Clarification, expansion and news compete | 7.22s / 10.70s | 5.56s / 5.14s |
| memoir-interviewer | Answer resolves queued clarification | 11.63s / 9.99s | 9.24s / 5.44s |
| memoir-interviewer | Correction overrides stale conflict | 16.11s / 15.80s | 5.56s / 9.42s |
| memoir-interviewer | Core: Opening | 26.57s / 9.83s | 7.73s / 5.54s |
| memoir-interviewer | Core: Later story | 12.13s / 12.21s | 5.48s / 5.98s |
| memoir-interviewer | Core: Privacy exclusion | 23.71s / 19.26s | 8.40s / 5.84s |
| memoir-interviewer | Core: Resumed saved conversation | 15.61s / 17.43s | 7.26s / 5.11s |
| memoir-interviewer | Core: Stop without news | 7.19s / 14.84s | 4.99s / 4.00s |
| memoir-interviewer | Core: Correction after stop | FAIL / FAIL | FAIL / FAIL |

The failed before-news stops saved generic continuation copy at 10.84s / 6.62s. The failed core correction attempts took 15.43s / 24.11s before and 9.65s / 10.64s after; none delivered a validated reply. They use current_correction with question=null, which the existing contract rejects.

## Gates and measured path

| Gate | Before | After |
| --- | --- | --- |
| Correct response within 5 seconds | 0/34 | 8/34 — target remains unmet |
| Correct response within 10 seconds | 12/34 | 32/34 |
| Successful responses exceeding 10 seconds | 18/30 | 0/32 |
| Provider HTTP submissions | 77 | 76 |
| Gateway-reported effort | max:77 | low:76 |
| Reported input / output tokens | 113,241 / 38,369 | 107,913 / 9,122 |
| Reported cached input tokens | 5,504 | 2,688 |

Every successful after-response is under ten seconds. The Chinese core correction failure is the only after-attempt over ten seconds (10.64s). All timings, including failures and durable-save milestones, are in the evidence. Provider load/cache were not controlled; each sequential arm consumed its own saved replies/state. Monetary cost, provider-internal retries and hidden processing remain unknown.

Observed successful-case policy/reply span medians fell 3.36s/5.75s → 2.06s/2.35s; the remaining local/context/save span median fell 1.87s → 1.25s. These are separate diagnostic medians, not additive estimates of one typical turn. Policy remains before reply; privacy review, source/version/ownership guards and fenced saves remain active. Lane B production is not moved into the current reply.

## Evidence and quality

[Sanitized aggregate and per-case timing/quality results](test-evidence/interviewer-stop-latency-20261024.json). Full synthetic request/output/state transcripts and execution logs are retained in the local task evidence; they are excluded from this public review branch.

All 22 final handoff cases pass semantic inspection and state checks: clarification outranks expansion/news, planned expansion outranks optional news, current intent overrides the queue, exact answers remove old clarifications, selected news consumes its matching clue once, stops leave it unused, sources/prior replies stay unchanged, and cached replay is exact with no extra model call. Public news creates no personal event. Actual model-request hints witness each priority claim; privacy can remove a forbidden hint before admission.

Fresh unseen negation/quotation controls pass 4/4 in each arm. They continue with one unresolved clarification rather than treating quoted or negated stopping as current intent. The final host neutral acknowledgement prevents the unpunctuated duplicate-question failure found in an earlier trial. Semantic review is by Codex against the frozen source/intent rubric, with known variant labels and deterministic state checks; no human-review claim or separate LLM judge.

Two earlier topic-ending controls are inconclusive for queued expansion: privacy review paused the school topic and removed the candidate’s mixed-source evidence before reply admission in both arms. The actual queued-expansion competition remains covered by the passing original bilingual cases. Earlier rejected low-route trials, a gateway 502 during Chinese-stop policy review, and the matched confirmation repeat are retained in the archive; the table uses the final clean-source cohort.

## Changes and verification

| Change | Measured reason | Retained contract / rollback |
| --- | --- | --- |
| Render stop, clarification and news copy in the host; defer their acknowledgement until validated | Before stops saved continuation; news rewrites and a valid stop quote caused repairs; a later trial repeated an unpunctuated clarification | Fixed optional public invitation, explicit stopping, one question, no invented attendance; source and cached state unchanged |
| Enforce ordered unresolved hints after validating the original proposal | A lower ordinary hint could bypass ready news after repairs | Current intent and exact resolutions still override; ordinary adaptation of the top hint remains valid |
| Accept a verified unused stop anchor | The current source quote was valid but rejected solely because no question was delivered | Fabricated/ambiguous anchors still reject; no question evidence is created for a stop |
| Dedicated low-policy route for pooled + low + reply-v2 | All 77 before-calls requested low but reported max | Other aliases/versions/efforts unchanged; set max to retain pooled policy; route authorization required |

- `make test-place-research`: 604 web checks, 479 Python checks, 95 skill unit checks pass. The first isolated run lacked an installed web dependency; reusing the existing repository dependency directory resolved setup, the full command passed, and its temporary symlink was removed.
- Focused foreground contracts: 303 pass, including bilingual serial/revisable suppression of unpunctuated clarification questions; the regression fails 4/4 against untouched main.
- Policy/streaming regressions: 32 pass.
- `make prompt-check`: all 93 exact published pins verify; zero new prompt versions.
- Four final saved API responses (EN/ZH news and stops), their cached references and previous bubbles pass the production client VM replay. This does not measure browser paint.
- The broader legacy collector-configuration file still has 32 failures on untouched f190c33 because tests mock removed methods. Whole-repository pytest acceptance is not claimed.

The optimization made 377 additional metered HTTP submissions within expanded fixed caps totaling 522; the existing before cohort had 77. This includes rejected trials, controls, validation retries and the gateway failure, with zero judge calls. Every disposable live database root has verified cleanup. Full outputs and failed attempts are preserved locally. The public data contains metrics and status checks, with no request/response payloads, provider identifiers, local paths, credentials or environment files.

This is local canonical ASGI/disposable SQL with a local PostgREST adapter and controlled seed/Lane B findings. Live discovery, deployed worker/Temporal, browser paint, simultaneous Lane B contention, and long-history cross-route checkpoint warming remain unmeasured. No shared-service deployment or prompt publication was performed. Five seconds and the two existing correction-after-stop failures remain the next interviewer work.
