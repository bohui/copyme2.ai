# Live comparison after PR119

PR119 was merged at `a6759d5`. Main's normal publisher created reply **v3**,
privacy review **v6** and repair codes **v6**. All **93** remote pins verified;
receipt commit `79458f2` is pushed. The comparison below uses those genuine
published sources. No shared gateway policy or service setting changed.

**Acceptance remains failed.** The first live cohort fixed the six previously
failing handoff cases, but exposed an invalid privacy offset. A repeated cohort
then exposed inconsistent news selection and a gateway 502. Neither failure is
excluded. The remaining prompt correction is a review candidate, not a measured
improvement.

## Measurement and results

The frozen sixteen originals and eight fresh bilingual controls use the canonical
ASGI turn, live policy/reply calls and disposable PostgreSQL. Earlier saved
replies, source-bound B proposals and inspected news are declared setup fixtures.
Each current turn reloads saved state through a fresh runtime. There is no live
news discovery, deployed-worker, Temporal, pre-rollout session or browser-paint
claim in these measurements.

Timing ends at the validated reply/question, or stop acknowledgement. This is a
conservative meaningful-text bound; a generic earlier acknowledgement does not
qualify. Full first-text, validation and durable-save times are retained. These
are one-sample observations per case/arm, with provider/cache/load drift and
different source IDs; no tail percentile or isolated causal speed claim follows.

| Cohort | Full quality/behavior gate | Median among passing cases | Within 5s | Within 10s | Calls |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prior low-route baseline | 10/16 | 5.30s | 3/10 | 10/10 | 41 |
| Published PR119, first original cohort | 15/16 | 4.60s | 10/15 | 15/15 | 31 |
| First fresh controls | 8/8 | 4.87s | 4/8 | 8/8 | 16 |
| Privacy-recovery code, repeated originals | 14/16 | 5.03s | 5/14 | 14/14 | 31 |
| Repeated controls | 8/8 | 5.46s | 2/8 | 8/8 | 16 |

The subsets differ. For the nine cases that passed both the old baseline and
first new cohort, medians are 5.26s and 4.60s (12.5% lower). The same-sized
intersection with the recovery cohort is 5.26s and 5.02s (4.5% lower).
More successful cases is the clearer result; these repeats do not establish a
large prompt-only latency gain. Every delivered reply in these cohorts is under
7.1 seconds. Failed turns remain in the full-case denominators.

| Original case | Prior low baseline | Published PR119 | Recovery-code repeat |
| --- | --- | --- | --- |
| English ready news | 6.62s; clue skipped | 6.76s; cited clue selected | 7.09s; clue skipped |
| English person identity | 15.28s; acknowledgement incorrectly settles identity | 4.22s; uncertainty retained | 4.51s; uncertainty retained |
| English topic expansion | Three invalid proposals, no save | 4.57s; new period offered | 4.48s; new period offered |
| Chinese ready news | 12.70s; clue skipped | 5.68s; cited clue selected | 5.85s; cited clue selected |
| Chinese topic expansion | Three invalid proposals, no save | 4.82s; new period offered | 5.17s; new period offered |
| Chinese redirection | Two incomplete reviews, no reply | 4.43s; Sydney question | 5.40s; Sydney question |
| English privacy | 5.35s; passes | Invalid offset, no reply | 6.42s; passes |
| Chinese privacy | 7.06s; passes | 6.89s; passes | Policy-provider HTTP 502, no reply |

All completed current turns kept exact originals and versions, replayed cached
requests without generation, and left the earlier saved reply text unchanged.
Public clues created no personal MemoryEvent. Stop responses had no question;
explicit topic changes and exclusions overrode old hints. These state checks do
not establish subsequent real B extraction or independent semantic review.
Semantic labels are the assistant's explicit source/output review, separate
from structural assertions; saving is never sufficient for a semantic pass.

Read-only gateway inspection still maps both aliases to `openai/gpt-5.6-luna`:
the configured pooled route enforces **max**, while the isolated collector-approved
`gpt-5.6-luna-memoir-low` route enforces **low**. Completed requests report low.
The 502 has unavailable effort/usage, not zero usage. Running services were only
inspected; activation of a different collector route was not performed.

## Privacy failure and implemented recovery

The model quoted `Please do not bring up my father again.` exactly, but supplied
`[0,40)` for its **39** Unicode characters. The original validator correctly
rejected it. Previously a claimed-complete review exited the retry loop before
that validation, so this failure never used the already allowed second attempt.

Commit `36219c3` validates a claimed-complete result before leaving that loop.
An otherwise schema-valid result that fails those checks is rejected unchanged
and sent back as the untrusted previous review with the bounded `invalid_review`
code. One fresh reassessment remains
available. Incomplete and invalid results share the existing two-attempt ceiling;
two invalid results leave policy pending, with no reply or receipt saved. No
coordinates, required fields, restrictions or source metadata are normalized or
discarded. Transport/configuration/SQL failures retain their existing behavior.

A separate confirmation replays that exact captured invalid result as a declared
controlled first response, then makes **two real calls**: policy reassessment and
reply. The model returns `[0,39)`, preserving the exclusion. The canonical turn
saves this reply in **7.14s**:

> Understood—I won’t bring up your father again. We’ll focus on your move to Sydney.
>
> What was the move to Sydney like for you?

The previous saved reply and exact two sources remain intact. This is live
reassessment after controlled failure injection, not an entirely live first
attempt or a second independent latency sample of the original outage.

The fix passed **97 focused HTTP/SQL/streaming checks**, including English and
Chinese, opening acknowledgement, duplicate controls, invalid offsets,
contradictory completion reasons, repeated failure, cached replay and no writes
before acceptance. The required research suite passed **604 JavaScript,
466 API/database and 95 standalone** checks. Cleanup was verified.

## Remaining correction prepared for review

On the repeat, the English model assigned `user_redirect` to an open invitation
for ideas, although no different topic was requested. It then ignored the ready
clue. This is a safe response but fails the frozen selection-coverage gate.

The candidate reply prompt distinguishes an **explicit topic change** from an
**open invitation for ideas alone**. Highest relevant hints still lead; actual
stops, exclusions, corrections, pacing and different-topic requests still win.
Equivalent wording is shortened to keep the compiled reply instruction at
**1,994 characters**, including governed dispatch. Validators and eligibility
are unchanged. The prompt has its prior genuine v3 receipt until reviewed main
publication creates the next real version; no live loader bypass is permitted.
The final wording passed 110 focused selection/strict-validation/prompt checks
and the required 604 JavaScript, 466 API/database and 95 standalone checks,
with verified cleanup. These offline passes do not establish its live behavior.

All 96 provider-bound attempts in this round are retained: 95 completed, one
HTTP 502, no cancellations and no model judges, within the predeclared 120-call
ceiling. This round is closed. A new bounded confirmation must repeat the
originals and controls after the remaining prompt reaches reviewed main. Its
prepared manifest has sixteen originals, eight repeated controls and four new
held-outs, a 64-call ceiling including retries, no judges and the same route and
timing boundaries. It refuses unpublished reply content before any dispatch.
Earlier Lane B profile, summary, composer, outline and research quality blockers
remain open; game remains last. #53 is not complete.

[Evidence index](evidence/lane-b-handoff-comparison-20261024.json) identifies the
lossless synthetic archive, full outputs and inputs, source/receipt/schema hashes,
all plans/harnesses, state witnesses, explicit semantic review, tests and cleanup.
