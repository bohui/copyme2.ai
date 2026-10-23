# Post-merge Lane B question-handoff review

**Acceptance: fail.** The merged plumbing works in controlled checks, but fresh
live replies do not yet establish every requested background-priority behavior.
The configured foreground model route also enforces maximum reasoning.

PR117 is merged at `718edee`; the reviewed source is present in `cad0a62`.
Main's publisher generated genuine reply v2 and strategy-proposal v2 receipts.
All 93 prompt pins passed `make prompt-check`; receipt commit `527fc73` was
pushed to main. No shared model setting or running service was changed by this
review.

## Scope and measurement

Sixteen frozen bilingual cases cover ready news, conflicting dates, person
identity, chronology, topic expansion, stop, explicit redirection and privacy.
The current turn uses real policy/reply generation, canonical ASGI streaming,
publication guards, and disposable PostgreSQL. Its earlier saved reply and
source-bound Lane B proposals/news are declared controlled fixtures. Every
current turn constructs a fresh runtime and reloads the saved project.

This is not live background-extraction/news-discovery, deployed private-worker,
Temporal, browser-paint or pre-rollout-session acceptance. The earlier actual
news-search baseline still returned zero inspected useful clues. No customer
memoir was used. Model responses, inputs, stream events, saved SQL witnesses,
source/helper hashes, failed attempts and cleanup are retained in the evidence.

The timing below ends at the delivered validated question, or stop
acknowledgement. It is a conservative meaningful-response bound. Earlier public
text includes generic acknowledgements and is **not** automatically counted as
meaningful. There is one sample per case; no tail percentiles or service-level
claim is justified.

## Route finding

Read-only gateway `/model/info` maps both aliases to `openai/gpt-5.6-luna`:

| Alias | Configured effort | Observed live effort |
| --- | --- | --- |
| Current `gpt-5.6-luna-pooled` | max | max, despite requested low |
| Existing collector-approved `gpt-5.6-luna-memoir-low` | low | low |

The current-route diagnostic stopped after three completed English cases and
one cancelled chronology turn, preserving all nine attempts. The low route was
used only in an isolated task runtime; `.env`, gateway policy and shared services
were not changed. Two additional stateless request replays took 4.85s and 2.69s;
they establish neither backend latency nor valid delivery. The news replay was
still structurally invalid.

| Matched case | Current route / max | Isolated low route | Quality limitation |
| --- | ---: | ---: | --- |
| English news | 63.43s | 6.62s | Neither selected the ready clue. The current route needed repair. Ordinary school questions can be safe, but this does not pass the frozen news-selection coverage gate. |
| English conflicting years | 11.87s | 5.50s | Current route treated continuation as pacing and asked an ordinary shop question; low route delivered the pending date clarification. |
| English person identity | 14.77s | 15.28s | Current route preserved uncertainty. Low route streamed an acknowledgement asserting Lin managed the shop, then asked which sister managed it. Its repairs preserved that already streamed assertion. |

These are single samples with separate runtime/source IDs and observed cache
variation. Faster termination of an incorrect answer is not successful latency.

## Full isolated low-route results

| Scenario | English seconds / result | Chinese seconds / result |
| --- | --- | --- |
| Ready news | 6.62; school follow-up, no clue selected | 12.70; ordinary walks question, no clue selected |
| Conflicting dates | 5.50; pending confirmation delivered | 8.23; pending confirmation delivered |
| Person identity | 15.28; question delivered, acknowledgement settles its uncertainty | 5.56; pending confirmation delivered |
| Chronology | 5.12; pending confirmation delivered | 4.87; pending confirmation delivered |
| Expand topic/period | No saved reply; three invalid proposals | No saved reply; three invalid proposals |
| Stop | 4.55; no follow-up | 5.26; no follow-up |
| Explicit redirection | 4.75; Sydney follow-up | No reply; two incomplete privacy reviews |
| Privacy exclusion/redirection | 5.35; Sydney follow-up | 7.06; Sydney follow-up |

Thirteen of sixteen unique cases saved. Ten pass the full frozen behavior and
semantic review: median **5.30s**, **3/10 within 5s**, **10/10 within 10s**. Across
all thirteen saved cases, including failing behavior/quality, the median is
5.50s; English identity and Chinese news exceed ten seconds. The ten-case
quality-passing subset does not establish all-case acceptance.

News non-selection is a missing behavior witness rather than fabricated public
history or a demonstrated privacy leak. Current explicit redirection is allowed
to outrank hints; these results do not prove that news will be preferred when
appropriate. English identity is a material uncertainty failure. Review was by
the assistant against source and output, not an independent human or model
judge.

For saved cases, cached retry made no new generation and exact original sources
were retained. The previous saved reply text stayed unchanged, including on
privacy turns. No public clue created a personal MemoryEvent. These observations
do not replace the broader ownership/withdrawal/disconnect regression suite.

## Causes exposed by the live runs

1. Priority is implicit in array order. The compact packet supplies `purpose`
   labels but does not explicitly tell the model that index zero has highest
   priority. Both news cases chose ordinary personal hints instead.
2. The wire requires prepared/adapted reasons whenever `hint` is selected, while
   the model sometimes uses a current-intent reason. Valid questions then need
   another full model call to fix the envelope.
3. Hint evidence is host-owned, but the model also fills `quote` with the current
   message. Both topic-expansion cases repeatedly chose the correct background
   question with incompatible reason/quote fields. Strict validation correctly
   rejected them; the quote failure fell back to generic repair guidance.
4. A pending clarification can be asserted as fact in the early acknowledgement.
   Once streamed, repair preserves it. Final schema success did not fix the
   contradictory English identity response.
5. Privacy review treated `我们换个话题，聊聊搬到悉尼的事情。` as an unresolved request
   to pause an unnamed old topic. Both review attempts stayed incomplete, so the
   application correctly failed closed. A routine redirection must be
   distinguished from an explicit exclusion/pause with an unresolved target.

## Proposed next correction — not implemented

| Change | Retained boundary / verification |
| --- | --- |
| Explicit priority data in `reply_packet` | Keep current controls first, the same eligible hints, strict SQL/source authority and optional neutral cited news. Do not force irrelevant news over current instructions. |
| Clarify the compact reply wire and schema descriptions | With a hint: its index, prepared/adapted reason, `quote=null`; host owns its exact evidence. Distinguish continuation from pacing and keep pending uncertainty out of acknowledgement. Preserve all invalid-quote/foreign-source rejections. |
| Give hint-quote errors an actionable repair code | Reject the original malformed proposal, then ask the model to regenerate the proper envelope. Never discard invalid metadata before validation. |
| Clarify routine subject switches in privacy guidance | Explicit exclusions/pauses still require exact spans and fail closed on unresolved targets; a normal subject change alone creates no privacy restriction. |
| Repeat the frozen cohort and fresh held-outs on the existing low route | No shared activation until the quality gates pass. Keep stop/privacy/prior-reply preservation and real SQL/client regression checks; retain every failed/repaired run. |

The unapplied reply draft plus governed dispatch is **1,978 characters**, below
the 2,000-character limit; the policy draft is 1,199 characters. No additional
LLM phase, tools, permissions, evidence relaxation or database schema is proposed.
Runtime/model/repair prompts and the operator route remain unchanged pending
approval of this new change set. Main-only prompt review/publication still
applies.

## Budget and cleanup

The original ceiling was 48 calls, including calibration and repairs: nine
current-route attempts, two stateless probes and 37 low-route calls exhausted
it. Two Chinese controls therefore initially dispatched zero calls. A separate
predeclared eight-call confirmation budget ran only those original unsubmitted
cases; it used four calls. Total: **52 attempts, 51 completed and one intentional
cancellation**; no judge calls. The cancelled call has unknown final usage.
Neither cap denial is counted as a completed case.

The stack startup temporarily held the backend lock; the isolated cohort waited
for release and did not interrupt it. Zero-call fixture preparation covered all
sixteen cases. Initial dependency-path and cleanup-registration mistakes remain
in the logs; the separate verified cleanup follow-up is retained. All final
task-owned SQL/process cleanup receipts are verified. No failed run was removed
or counted as passing.

[Evidence index](evidence/lane-b-handoff-review-20261023.json) records the gates,
counts, provenance and SHA-256 of its lossless gzip companion. The archive
contains complete owned synthetic provider/ASGI/SQL records, the frozen cases,
hash-matched harness versions, review drafts, failed runs and cleanup receipts.

The subsequent post-merge `make test-place-research` run passed on the same
application sources: 604 JavaScript, 466 API/database and 95 standalone checks,
with verified native cleanup. These controlled regressions do not resolve the
six live review failures. Its receipt/log are retained in the separate photo
baseline evidence archive and the shared campaign's `checks/` directory.
