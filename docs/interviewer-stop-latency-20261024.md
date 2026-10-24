# Interviewer stop/news fixes and latency — 24 October 2026

Original cohort source: `711050cab208a5dfca8cbd2361ed6c2463d86929`; before: `f190c33`. The correction follow-up below uses `50aa0c89f2229e51c5953d079877bff4ebc47297` and updates the fresh-install SQL baseline in place. Prompt text, prompt receipts, provider credentials and gateway settings are unchanged.

Both ready-news stop failures are fixed. The host renders explicit stopping, the fixed optional news invitation, and neutral prepared-clarification acknowledgements from validated state; the model still determines current intent. Prepared and continuation selections honor the highest unresolved hint. Current correction/redirect/pacing/stop decisions and exact question resolution retain precedence. The opted-in pooled + low + reply-v2 configuration dispatches policy/reply through the existing dedicated low-policy alias.

Across the 30 cases that pass in both arms, median correct-response time fell **11.17s → 5.55s (50.3%)**. Before: 30/34 meaningful replies; after: 32/34. Both remaining correction-after-stop failures now pass the follow-up below. The 32/34 count describes the original cohort, and the other cases have not been reprofiled on the new fix. One sample per case; these medians compare distinct scenarios and are not production percentiles.

Timing starts at canonical submission and counts the correct delivered question; selected news also requires validated citation metadata. A stop requires a retained explicit stop acknowledgement with no question/news. Generic acknowledgement and progress text do not satisfy the target. Values below are **English / Chinese**. The correction row uses the new follow-up; every other after-row remains from `711050c`.

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
| memoir-interviewer | Core: Correction after stop | FAIL / FAIL | 6.35s / 5.17s (follow-up) |

The failed before-news stops saved generic continuation copy at 10.84s / 6.62s. The original core correction attempts took 15.43s / 24.11s before and 9.65s / 10.64s in the first after-cohort; none delivered a validated reply. Both reason guards formerly rejected current_correction with question=null. These failed receipts remain in the evidence; the follow-up now saves both replies.

## Original 34-case gates and measured path

| Gate | Before | After |
| --- | --- | --- |
| Correct response within 5 seconds | 0/34 | 8/34 — target remains unmet |
| Correct response within 10 seconds | 12/34 | 32/34 |
| Successful responses exceeding 10 seconds | 18/30 | 0/32 |
| Provider HTTP submissions | 77 | 76 |
| Gateway-reported effort | max:77 | low:76 |
| Reported input / output tokens | 113,241 / 38,369 | 107,913 / 9,122 |
| Reported cached input tokens | 5,504 | 2,688 |

In the original 34-case after-cohort, every successful response was under ten seconds. Its Chinese core correction failure was the only after-attempt over ten seconds (10.64s). All timings, including failures and durable-save milestones, are in the evidence. Provider load/cache were not controlled; each sequential arm consumed its own saved replies/state. Monetary cost, provider-internal retries and hidden processing remain unknown.

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

This is local canonical ASGI/disposable SQL with a local PostgREST adapter and controlled seed/Lane B findings. Live discovery, deployed worker/Temporal, browser paint, simultaneous Lane B contention, and long-history cross-route checkpoint warming remain unmeasured. No shared-service deployment or prompt publication was performed. The correction follow-up resolves both remaining failures. Five seconds remains unmet.

## Review follow-up: two pending clarifications

After the benchmark, review found that resolving the first clarification could let a projected news/ordinary hint replace a second unresolved clarification from an older plan. Commit `c8f5711dc7973c15c7b0344f2408ffb93524902f` keeps the full queue’s next unresolved clarification and consults projected candidates only when none remains. Six reason/news combinations fail on the prior head and pass with the fix; 309 foreground checks plus the required 604 web, 485 Python and 95 skill checks pass. No live provider calls or production validation were performed for this follow-up. The original cohort remains measured at `711050c`; the correction row is updated by the next section. Full latency acceptance remains unclaimed.


## Correction after stop follow-up

Commit `50aa0c89f2229e51c5953d079877bff4ebc47297` permits a correction with no follow-up in both the reply-v2 adapter and the SQL save guard. Such a reply retains `current_correction`, extraction work and a no-question outcome, so it does not start new news research. Corrections with a question still work; pauses/direct answers cannot carry a question, other missing-question reasons still reject, and fabricated current-source anchors still reject. The SQL change stays in the fresh-install baseline as required by `AGENTS.md`.

Both original six-turn conversations were rerun unchanged, with a fresh runtime/storage loading each language’s own saved replies, privacy restriction and stop. All 12 turns saved. Both corrections acknowledge only the room’s Newcastle location, preserve the excluded father topic, and contain no follow-up question or invitation. Exact cached replay made no additional model calls. Both actual saved live corrections and their cached replies also pass the production client VM replay, preserving the prior stop bubble.

| work scenario measured | previous failing run (`711050c`) | after (`50aa0c8`) | durable save |
| --- | --- | --- | --- |
| English correction after stop | FAIL after 9.65s; 4 calls | PASS, meaningful text 6.35s; 2 calls | 6.88s |
| Chinese correction after stop | FAIL after 10.64s; 4 calls | PASS, meaningful text 5.17s; 2 calls | 5.66s |

Meaningful time starts at canonical submission and requires text identifying the corrected room location; a generic prefix does not qualify. Completion was 6.87s / 5.65s, with primary return at 7.03s / 5.76s. Both corrections pass ten seconds; neither meets five seconds. A failed baseline has no quality-qualified response time, so no percentage improvement in meaningful latency is claimed.

The rerun used 26 of the fixed 40 allowed HTTP submissions: 12 policy and 14 reply, zero judges. Each correction needed one policy and one reply call, without repair. One resumed-turn reply per language incorrectly used `direct_answer` with a question and was repaired under the existing guard; both attempts are retained. Reported usage was 35,238 input / 2,853 output tokens, zero cached input tokens, and all 26 calls reported low effort. Provider load/cache remain uncontrolled; one sample per case does not establish a latency SLO.

The frozen live core fixture has inactive strategy rollout, matching its prior cohort, so it does not save strategy-outcome rows. The two controlled-provider API/database/client regressions exercise active strategy, persist the correction outcome, and assert that no new news research is queued. Four focused unit regressions fail before the adapter fix; both API saves still fail until the SQL guard is fixed. Current checks pass: 346 foreground, 604 web, 487 required Python and 95 skill tests, plus all 93 published prompt pins. Source hashes and frozen inputs were reverified, and disposable live state cleanup is verified.

The original 34-case results and failures remain in the structured evidence alongside this follow-up; the other 32 table cases were not rerun on this fix. Live background extraction, deployed worker/Temporal, browser paint and production acceptance remain unmeasured. No prompts were published and no shared service was deployed.
