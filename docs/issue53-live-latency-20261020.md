# Issue 53: collector latency and release evidence

Current-source acceptance after PR105 is tracked in
[the 21 October follow-up](issue53-current-acceptance-20261021.md). The cohorts
below predate the added source-policy round trip and remain historical.

The target is meaningful text within **5 seconds**, with **10 seconds** as the
fallback. PR [101](https://github.com/bohui/copyme2.ai/pull/101) is merged;
the candidate is not enabled in the shared app and issue 53 is not accepted yet.

## Routing and measured improvement

Read-only verification of the exact configured consumer key confirms that the
existing `gpt-5.6-luna-pooled` collector route enforces maximum reasoning. The
dedicated `gpt-5.6-luna-memoir-low` route enforces low reasoning for the same
underlying model. The shared upstream key policy and other roles were not changed.

The completed historical cohort C, at `a864bc50`, saved all 80 application rows:
76 generated turns and four cached replays, with no corrective invocation. Its
supervisor timed out during database cleanup; an independent completion audit
verified the rows and reconciled cleanup. The original failed receipt remains.

The fair comparison excludes four future rollback generations, leaving 36
generated turns per arm across both languages and first, later and resumed turns.

| Milestone | Pooled/max median | Dedicated/low median | Dedicated/low maximum |
| --- | ---: | ---: | ---: |
| First public text | 19.044 s | 4.528 s | 7.035 s |
| Validated question, 34 turns per arm | 22.859 s | 5.923 s | 9.130 s |
| Complete public reply | 21.144 s | 5.952 s | 9.483 s |
| Durable conversation save | 21.154 s | 5.994 s | 9.499 s |

First public text improved approximately 76%; all 36 candidate replies completed
within ten seconds. These results establish the routing benefit, but **are not
current release acceptance**. Review subsequently found extra-question, grounding
and pacing defects. Generic acknowledgements do not count as meaningful text;
complete replies give a conservative bound. Small-sample maxima are not production
percentiles or guarantees. Input/cache differences, independent histories after
the initial seed, and uncontrolled gateway load limit causal attribution.

## Fixes now prepared

The change preserves normal validation, bounded correction, source retention,
fenced saving and the separate reply/save milestones. It removes observed repair
triggers: ambiguous exact quotes, unnecessary explicit evidence offsets, extra
questions in acknowledgements, and confusion over current-message work decisions.

The pure-pause prompt fix, PR [104](https://github.com/bohui/copyme2.ai/pull/104),
was merged with the user's approval. Publication ran from main through the normal
workflow. Collector-plan version 2 and strategy-selection version 4 receipts were
committed at `7ebf541`; `make prompt-check` verified all **81** published pins.
There was no publication from a feature branch. Twelve real-worker regressions
covering both languages and legacy/active selection then passed with 13 native
attempts, no background calls, and verified home cleanup.

Comparison H at `8e7a561` stopped after 47 of 80 planned application rows: **46
saved, one failed, 33 unrun**, with 49 native invocations, no background dispatch,
and verified worker-home cleanup. The failure exposed a host-side intent bug:
Chinese “不想聊厨房” matched positive “想聊”, forcing a question even when the
model correctly acknowledged the exclusion. Commit `2725650` corrects that match.
Both captured native proposals now validate; `703795c` adds English/Chinese
streamed HTTP/SQL regressions proving exact exclusion persistence, extraction,
one saved exchange and one collector request.

Bilingual review also found “sister” translated as “姐姐”, adding an unstated age
relationship. Commit `0651502` strengthens shared acknowledgement/question schema
guidance to preserve unspecified kinship in translation. The focused regression
suite then passed **193 checks**. This guidance still needs its native regression;
schema validation alone cannot establish semantic fidelity.

H also contains candidate replies above the preferred fallback: a Chinese
emotional turn completed at 15.108 seconds, a Chinese pause at 18.359, and an
English language-switch turn at 10.141. Across the 23 saved candidate rows, first
public text had a 5.512-second median and complete replies a 6.720-second median;
20 completed within ten seconds. The failed candidate row remains separate.
These outliers prevent claiming that the workload meets ten seconds on every
turn. H is incomplete and is not acceptance evidence for current code.

## Checks and retained failures

At published source `8e7a561`:

- Collector/question/plan/worker checks: **184 passed**.
- Combined regressions: **427 passed, one failed** on a stale lane lease. The
  exact isolated rerun passed; the timing cause is unproven. This was not one
  all-green combined run.
- Required `make test-place-research`: **588 web, 432 Python, 95 skill tests**.
- Updated bilingual matrix: **10 checks per locale passed**, covering all 80
  application rows and mobile replay; eight negative-stream checks per locale
  were excluded here and had passed in the earlier full matrix at `91528c7`.

At `2725650`, **152** strategy/question/engine/runtime checks passed; the three
focused exclusion checks passed. At `703795c`, both additional real SQL/HTTP
exclusion regressions passed. These results do not substitute for a complete
current-source live campaign.

Earlier campaigns and failures remain retained in the
[public evidence](test-evidence/issue53-every-turn-followup-20261020.json):
D/E had upstream failures/timeouts; F saved 30 replies but failed the pure-stop
work contract; G stopped on incorrect evidence offsets; H stopped on the negative
intent bug. Fixes address those observed defects; unsuccessful rows are not
counted as successful latency samples.

A subsequent native probe completed model generation but failed at the local
publication database guard before reply delivery. A cleanup timeout then masked
the initial error. A browser setup probe made no model calls and exposed missing
configuration in replaced shared containers. Existing project configuration is
now supplied explicitly to task-owned ephemeral workers/API. Shared services
were not changed. Further live checks acquire the existing backend operation
lock to avoid overlapping another local stack operation.

## Outstanding acceptance gates

The current code needs a complete bounded matched live comparison and bilingual
review of every public reply, genuine pre-rollout session continuation and
rollback, long-source wire retention and independent extraction readback, and the
small real web-proxy/browser smoke. Local publication connectivity must be
resolved before those measurements resume. Candidate activation follows those
gates and remains pending.

The prepared collector configuration is
`MEMORY_SPARK_COLLECTOR_MODEL=gpt-5.6-luna-memoir-low` with
`MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=low`, applied consistently to API,
private worker and background worker. Capture the existing values for rollback;
preserve other role overrides and published prompt pins. Saved historical
replies must replay unchanged, and rollback affects future generations only.

## Current-source verification after the fixes

At source `e8bb0e95106eb85fbc3f9a9ebaa6a59520af10f4`, the bounded matched
acceptance run `var/issue53-worker-profile-20261020i` completed all 80 planned
rows: 40 pooled/max baseline rows and 40 dedicated/low candidate rows. All 80
rows were saved, there were no application failures, no background dispatches,
and the independent completion audit reconciled worker-home cleanup. The
candidate used the dedicated low-effort route for 38 rows; the two deliberate
rollback rows used the pooled route and are excluded from the fair comparison.

For the remaining 36 generated candidate turns, first public text had a
4.294-second median, a 7.332-second maximum, 25/36 within five seconds, and
36/36 within ten seconds. The matched pooled baseline had a 13.332-second
median and only 9/36 within ten seconds. Candidate validated-question timing
was 5.475 seconds median (32 observed, all within ten seconds); complete and
saved replies were 5.487 and 5.493 seconds median respectively. One candidate
pause route took 13.62 seconds to complete after text had already appeared at
3.453 seconds, so the first-text target is met while the all-complete-replies
ten-second target is not yet universal. This is a current observation, not a
production percentile or guarantee.

The audit also verified exact source and history wire fidelity, 76 generated
rows, four cached replays, 78 native calls including retries, and zero
unexpected roles. A bounded bilingual contract review of the 38 candidate
replies found 19 English and 19 Chinese outputs, 38 durable saves, and four
expected no-question stop/exclusion replies. Human semantic review of every
public exchange remains required before enabling the candidate.

The narrow continuity fix at `6c105704` canonicalizes an asserted, null-spanned
control quote when the model includes a preceding pacing sentence. This keeps
the deterministic host-owned literal and avoids a repair retry after text has
already streamed. A fresh candidate-only native replay passed the former
Chinese negative-topic outlier, a Chinese redirect, and the translated
unspecified-sibling case: the negative-topic turn rendered first text at 4.276
seconds and saved at 5.190 seconds after one native attempt; the redirect saved
at 4.543 seconds. The translation reply used neutral `姐妹` wording and saved
at 7.645 seconds. Evidence is retained in
`var/issue53-negation-probe-20261020g`. The focused collector, engine, and
continuity suite passes **235 checks**, including explicit-offset rejection.
Two subsequent full-cohort attempts are retained but excluded from acceptance:
one stopped on a candidate worker stream/contract failure, and one was stopped
after repeated pooled/max gateway timeouts and busy 409s. Both disposable
worker homes were removed.

Follow-up checks covered existing sessions in both locales: resumed turns,
saved replay, deliberate rollback, and long sources all saved in the retained
`var/issue53-existing-sessions-20261020e` evidence. That runner stopped before
recording its optional background wrapper result, but its 16 recorded rows were
saved with no row failures. A separate candidate-only background acceptance run
then passed both an English correction and a Chinese name-clue case in one
iteration each; retrieval completed and all source, memory, and event counts
were present. Its original receipt recorded cleanup before the process exited;
the post-process cleanup audit found no remaining task homes.

The isolated real-proxy browser smoke now passes four turns: a profile-neutral
opening, a later saved turn, a name correction, and a resumed pause. Every
turn returned HTTP 200 NDJSON, streamed visible text before completion, saved
without early unlock, and rendered each current reply once. Reload restored all
accepted testimony. The canonical fence hid one stale older reply after a
preference revision and exposed later valid replies; this is expected and is
kept separate from the native matched-fence replay checks. Optional readiness
requests emitted non-blocking 500s in the disposable harness, while the turn
stream and storage audit had no failures.

## Remaining release gate

PR 101 remains a draft and the candidate remains disabled. The first-response
latency improvement is substantial and the current browser/native structural
gates pass, but release acceptance still needs a human bilingual semantic
review of the held-out public replies and broader confirmation of the patched
complete-reply path. The 80-row cohort still contains the pre-fix outlier in
its recorded metrics; the targeted post-fix replay is not a replacement for a
full rerun or a production percentile. No production or shared-service
configuration was changed.
