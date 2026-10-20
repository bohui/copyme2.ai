# Issue 53: collector latency and release evidence

The target is meaningful text within **5 seconds**, with **10 seconds** as the
fallback. PR [101](https://github.com/bohui/copyme2.ai/pull/101) remains a draft;
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
