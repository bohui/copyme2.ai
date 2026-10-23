# Published PR120 live confirmation — 24 October 2026

PR120 is merged at `53095cda0e61cc94d649787fe58d0bd761916a59`.
Main's normal publisher created reply **v4**; receipt commit
`b8d797d898a544e1b4da0d7642998b0d19811507` is pushed. Privacy review and
repair remain v6. All **93** remote pins verified. The compiled reply is
**1,994 characters**. Publication does not establish activation of a different
model route or matching versions in already running processes; shared services,
gateway policy and configuration were not changed or restarted.

**Acceptance still fails.** All 28 prepared turns completed and saved, but only
25 pass the full quality and coverage gate. Two fail; one cannot establish its
intended news-precedence condition. Two additional diagnostics confirm the
remaining stop-acknowledgement problem in English and the ready-news redirect
condition. All failures and setup problems are retained.

## Timing and comparison

The 25 passing prepared cases have a **5.67s median**, range **4.02–12.02s**:
**7/25 within 5s**, **24/25 within 10s**. Failed and inconclusive turns remain in
the 28-case denominator; their schema-valid completion times do not count as
quality-passing meaningful responses. Including both diagnostics gives 26 passes,
three failures and one inconclusive case across 30 turns. Its passing median is
5.69s; 7/26 are within 5s and 24/26 within 10s.

There is **no measured latency improvement in this repeat**. For the ten originals
that pass both the original low-route baseline and v4, medians are **5.30 → 5.69s**
(7.3% slower). For the thirteen passing in both the immediate v3/recovery cohort
and v4, medians are **5.02 → 5.67s** (12.8% slower). These are single observations
per case, with provider/cache/load drift and evaluation overhead. They neither
isolate a causal prompt-only effect nor support production percentiles. The
original baseline passes 10/16; v4 passes 15/16, which is a quality/coverage gain
rather than proof of a large latency gain.

Timing runs from canonical submission to the validated reply/question, or a
meaningful stop acknowledgement. A generic earlier acknowledgement is not enough.
First public text and durable-save times are preserved separately. Every measured
validated completion over 10s is listed here:

- English privacy: **12.02s**, quality passes. Policy/reply provider spans total
  7.33s; 4.69s remains in other application and evaluation work, not separately
  attributed by this harness.
- Chinese ready-news invitation: **11.47s**, quality fails because no clue is
  selected. Policy plus two reply calls total 9.75s; one reply repair is required.
- Diagnostic English redirect with a ready clue: **14.68s**, quality passes.
  Policy alone takes 11.05s, reply 2.36s. This is provider-bound latency, without
  a claim that a smaller prompt fixes that tail.

Chinese chronology saves at 10.0006s; its validated question is at 9.956s.
The full stage spans retain that distinction.

## Remaining failures and confirmed boundaries

The Chinese original still interprets “关于那些年，我们还可以聊些什么？” as
`user_redirect`, despite a ready inspected clue at index zero. It offers general
school/family/neighbourhood topics instead. Both news originals first return
`direct_answer` with a non-null question; strict validation rejects that
combination. English repairs to the clue; Chinese repairs to the incorrect
redirect. The clarification did not consistently resolve this routing decision.

The fresh Chinese news-plus-stop turn correctly emits no question and saves a
pause receipt, but its sole visible response is:

> 我们可以按您的节奏继续回忆。

The English diagnostic reproduces it:

> We can keep following your memories at your pace.

These generic continuation lines do not acknowledge the requested stop and cannot
qualify as meaningful stop responses. The existing news-bound schema permits only
that single locale-specific acknowledgement. Its finite safe-copy guard protects
against turning public history into personal facts, but currently prevents an
explicit stopping acknowledgement. This is a newly exposed existing constraint,
not a demonstrated regression introduced by PR120.

All 30 turns preserve the exact original source IDs/text/versions and previous
saved reply text. Current policy receipts have exact source spans. Privacy cases
remove the earlier assistant reply from governed history while preserving it in
SQL. Every cached same-turn replay makes zero model calls and returns the same
saved reply. Public clues create no personal MemoryEvent. These are source/state
witnesses, not proof that actual subsequent Lane B discovery/extraction completed.

## Fixture calibration and scope

The original 16-case setup passes with zero model calls. The first 12-control
setup fails only for the English news-plus-Sydney case: an undated move blocks
conservative automatic news-location inference. The failed setup is retained.
Its exact narration and rubric stay frozen; a declared prior-ready synthetic news
fixture is installed through ordinary begin/finish SQL RPCs. A second zero-call
setup passes all twelve.

However, canonical revalidation subsequently removes that clue before the reply
request. The reply correctly follows Sydney over the remaining school question,
but this cannot establish precedence over **ready news at dispatch**; it remains
inconclusive for that condition. A separate diagnostic uses an explicitly dated
Boston residence and Sydney move, preserves the ready clue in the actual model
input, and confirms the Sydney question. The original case is not replaced or
silently counted as passing. The second diagnostic tests English stop wording.
Both diagnostics use the existing round budget; frozen inputs and plan precede
their dispatch.

The prepared harness's missing import was corrected before any launch or provider
call. Both versions and its zero-call provenance record are retained. No failed
model run is invented for that prelaunch fix.

All current policy/reply requests are live, on `gpt-5.6-luna-memoir-low`, with
**low** requested and observed. The canonical ASGI path and disposable real SQL
are exercised; earlier saved replies, B proposals and inspected news are declared
fixtures. A fresh runtime reloads each saved project. This comparison deliberately
retains the baseline's **serial policy/reply** flag. It establishes no browser
paint, deployed private-worker/Temporal, actual news discovery, pre-rollout resume,
rollback or latest combined parallel-flow acceptance.

## Full five-column comparisons

Before is the original low-route baseline. Failed baseline durations are time to
failure, not successful-response latency. Fresh controls have no matched old
baseline. The complete ten-skill scorecard has
[83 scenario rows](skill-scenario-profiling.md), including the earlier parallel
trial, all Lane B measurements and pending/unwired paths.

| skill name | work measured | before | after | result |
| --- | --- | --- | --- | --- |
| memoir-interviewer | en-news; validated reply | 6.62s; fail | 9.72s | PASS: Uses ready cited public clue after one rejected direct_answer-with-question proposal; public card and optional invitation make no autobiographical claim. |
| memoir-interviewer | en-conflict; validated reply | 5.50s; pass | 5.72s | PASS: Both acknowledgement and question leave 1962 versus 1963 unresolved. |
| memoir-interviewer | en-identity; validated reply | 15.28s; fail | 4.02s | PASS: Asks May versus Lin without asserting which sister managed the shop or inventing age order. |
| memoir-interviewer | en-chronology; validated reply | 5.12s; pass | 4.73s | PASS: States that the timing is unclear and asks which of the two narrated events came first. |
| memoir-interviewer | en-broaden_scope; validated reply | No validated reply | 4.43s | PASS: Acknowledges the completed school topic and offers early working years as a question, without asserting an employment history. |
| memoir-interviewer | en-stop; validated reply | 4.55s; pass | 5.67s | PASS: Acknowledges the whole-exchange stop and asks no further question. |
| memoir-interviewer | en-redirect; validated reply | 4.75s; pass | 5.75s | PASS: Follows the explicit Sydney topic change instead of the stale father/shop prepared question. |
| memoir-interviewer | en-privacy; validated reply | 5.35s; pass | 12.02s | PASS: Acknowledges exclusion, asks about the narrated Sydney move, and does not repeat the father/shop story or pursue that topic. |
| memoir-interviewer | zh-news; validated reply | 12.70s; fail | 11.47s | FAIL: Still labels the general same-period invitation user_redirect after an invalid direct_answer-with-question proposal. Offers general topics; no ready clue or citation selected. Safe reply but frozen news-selection gate fails. |
| memoir-interviewer | zh-conflict; validated reply | 8.23s; pass | 4.83s | PASS: Acknowledgement explicitly leaves 1962/1963 uncertain and the question seeks clarification. |
| memoir-interviewer | zh-identity; validated reply | 5.56s; pass | 5.09s | PASS: Asks whether Mei or Lin managed the shop without resolving the ambiguous pronoun. |
| memoir-interviewer | zh-chronology; validated reply | 4.87s; pass | 9.96s | PASS: Retains uncertainty over event order and asks shop before or after Sydney without asserting a sequence. |
| memoir-interviewer | zh-broaden_scope; validated reply | No validated reply | 6.29s | PASS: Ends the school topic and offers early working years without treating the topic boundary as a whole-conversation stop. |
| memoir-interviewer | zh-stop; validated reply | 5.26s; pass | 4.86s | PASS: Ends the exchange with acknowledgement only. |
| memoir-interviewer | zh-redirect; validated reply | No validated reply | 5.86s | PASS: Follows the explicit move-to-Sydney topic; does not deliver the old father/shop hint. |
| memoir-interviewer | zh-privacy; validated reply | 7.06s; pass | 8.74s | PASS: Acknowledges the exclusion and asks about moving to Sydney; does not ask about the father or add his unsupported role in the move. |
| memoir-interviewer | en-heldout-identity; validated reply | No matched older baseline | 6.42s | PASS: Acknowledgement explicitly retains uncertainty and asks Sam versus Alex; no assignment or unsupported sibling relationship. |
| memoir-interviewer | en-heldout-redirect; validated reply | No matched older baseline | 4.63s | PASS: Follows explicit settling-in-Sydney request without returning to Boston school. |
| memoir-interviewer | en-heldout-privacy; validated reply | No matched older baseline | 7.21s | PASS: Acknowledges exclusion and invites Sydney narration; no father follow-up or asserted new Sydney detail. |
| memoir-interviewer | en-heldout-stop; validated reply | No matched older baseline | 5.42s | PASS: Explicitly says the conversation stops today and asks no question. |
| memoir-interviewer | zh-heldout-identity; validated reply | No matched older baseline | 5.53s | PASS: Asks Mei versus Lin without asserting who taught bicycle repairs. |
| memoir-interviewer | zh-heldout-redirect; validated reply | No matched older baseline | 5.73s | PASS: Follows settling in Sydney and asks what was arranged first as an open question; does not assert any arrangement. |
| memoir-interviewer | zh-heldout-privacy; validated reply | No matched older baseline | 5.44s | PASS: Acknowledges the exclusion and invites Sydney experiences without reintroducing father details. |
| memoir-interviewer | zh-heldout-stop; validated reply | No matched older baseline | 4.50s | PASS: Explicitly acknowledges stopping today with no question. |
| memoir-interviewer | en-new-news-invitation; validated reply | No matched older baseline | 9.40s | PASS: Selects the ready cited clue and optional invitation without assuming the narrator attended the public fair. |
| memoir-interviewer | zh-new-news-invitation; validated reply | No matched older baseline | 5.35s | PASS: Selects the ready cited clue, invites memories neutrally, and says remembering is optional. |
| memoir-interviewer | en-new-news-redirect; validated reply | No matched older baseline | 5.05s | INCONCLUSIVE: Actual reply correctly follows Sydney over the remaining school hint, but canonical revalidation removed the prior SQL-ready news clue before reply input. Does not establish the intended ready-news-versus-redirect precedence gate. Failed zero-call original setup and controlled-prior-fixture amendment retained. |
| memoir-interviewer | zh-new-news-stop; validated reply | No matched older baseline | 4.76s | FAIL: No question, no news card, and pause outcome saved, but visible reply says we can continue reminiscing at your pace instead of acknowledging the explicit stop. This generic wording cannot qualify as meaningful stop acknowledgement. The ready-news schema allows only this continuation literal; not a demonstrated PR120 regression. |
| memoir-interviewer | en-diagnostic-ready-news-redirect; validated reply | No matched older baseline | 14.68s | PASS: Actual reply input contains the ready news clue and both prepared hints. Follows explicit Sydney-arrival topic instead, no news card or assumption of attendance; prior and source/state witnesses preserved. Meaningful validated reply14.68s exceeds target. |
| memoir-interviewer | en-diagnostic-ready-news-stop; validated reply | No matched older baseline | 4.55s | FAIL: Actual reply input has ready news. Model saves pause and no question/card, but its sole visible line says we can keep following your memories at your pace. This fails clear stopping acknowledgement; a generic continuation line is not meaningful stop text. Existing news acknowledgement enum forces this sole English literal. |

## Budget, verification and next approved candidate

The round is closed at **62/64 actual provider-bound attempts**: thirty policy
calls and thirty-two reply calls, all completed HTTP 200; no cancellations and no
model judges. The two unused attempts are not reallocated. Zero-call setup failures
remain in their own evidence. All disposable SQL/process cleanup is verified.

PR120's implementation had already passed 97 focused privacy/HTTP/SQL/streaming
checks and 110 focused reply/selection/strict-validation/prompt checks. The final
required research suite passed 604 JavaScript, 466 API/database and 95 standalone
checks. Those are the observed pre-merge checks for PR120, not claimed checks for
subsequent changes. The analysis independently verifies the recorded state,
request boundary, policy spans and effort witnesses for all thirty live turns.

The user has approved the next focused candidate: give same-period idea requests
a positive top-hint rule, clarify the question/reason repair feedback, and add
explicit stopping copies to the finite news-safe acknowledgement inventory. The
prepared wording compiles to **1,997 characters**. Source/privacy/strict validation,
model, effort and transport remain in scope to preserve; no extra classifier call
is proposed. This candidate is not included in the measurements above. It needs
implementation/regression checks, review, main publication and its own frozen live
comparison. The observed extra reply calls cost 2.7–3.5s each, so avoiding them is
a plausible benefit, not a measured future gain.

Profile/summary, composer, attribution, actual news/photo discovery and deployed
acceptance blockers remain open. Selected-outline baseline analysis is
[preserved separately](lane-b-selected-outline-baseline-20261024.md); its transport
proposal remains unimplemented. Game remains last. #53 and the all-skills goal are
not complete.

[Evidence index](evidence/lane-b-handoff-confirmation-20261024.json) and its
[lossless synthetic archive](evidence/lane-b-handoff-confirmation-20261024.json.gz)
retain all exact inputs/outputs, requests, SSE, SQL witnesses, source/schema/prompt
provenance, explicit semantic verdicts, frozen manifests/plans, setup amendments,
harnesses, checks and cleanup receipts. Semantic review is the assistant's direct
source/output review, not independent human review or a model judge.
