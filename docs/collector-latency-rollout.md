# Collector latency: opt-in source change (issue #53)

## Status and scope

This change supplies **off-by-default candidates**, not release acceptance or a
latency SLA. Normal generation retains its model, maximum effort and full legacy
prompt. Gateway keys, credentials, other agent routes, customer data, schema and
transport are unchanged. The bounded [quality-first follow-up](test-evidence/issue53-quality-first-resolution-20261011.md)
records exploratory live comparisons: prompt-only stopped on a timeout; routing-only
completed but increased median usable-save time. Configured same-model/effort policy
was verified read-only. Neither pilot passed release acceptance; do not enable a
candidate or claim semantic equivalence from schema success alone.

Every future generated conversational turn resolves the server configuration,
including persisted-thread resumes and server-owned conversational actions.
The no-model introduction and committed-result replay stay unchanged. The
normal thread/resume request receives the current model and instructions, while
each collector turn (including its existing bounded corrective proposal) receives
the effort override. Authorized provider thread history is retained; route errors
fail explicitly rather than falling back to the shared maximum-effort route.
Existing worker history compaction policy is unchanged.

## Configuration and rollback

Set these on **both API and private worker** (Compose forwards the same values):

| Variable | Default | Opt-in meaning |
| --- | --- | --- |
| `MEMORY_SPARK_COLLECTOR_MODEL` | empty | Override only collector route; `memoir-luna-low` is a candidate requiring provider verification |
| `MEMORY_SPARK_COLLECTOR_REASONING_EFFORT` | empty | Override collector requested effort, e.g. `low`; otherwise preserve existing effort behavior |
| `MEMORY_SPARK_COLLECTOR_PROMPT_VERSION` | `legacy` | `compact-v1` selects the reduced collector contract |

These are deployment/operator inputs, never public interview request fields.
Unknown prompt versions and invalid effort values fail before worker runtime-home
writes or model dispatch. JSON turn/greeting/worker requests return a sanitized
503 with `COLLECTOR_CONFIGURATION_INVALID`; streams use controlled errors.
Configuration is resolved at generation time, not cached
on session construction. Process environment changes normally require an operator
restart; they do not require new memoirs or rewriting existing threads.

Rollback: clear the two overrides and restore `legacy` in both services, applying
those deployment settings through the normal operator process. The next generated
turn resumes with legacy configuration; prior sources, question plans, saved
replies and event/photo identities remain untouched. Do not enable the candidate
as a default until the acceptance gate below passes.

## Preserved boundaries

The reduced base prompt removes research, composition and unrelated product
responsibilities. The existing structured interview contract/schema and complete
current source remain unchanged. Saved profile, entitled Family context, recent
memory context, active events, planning and photo identities are still supplied.
No new testimony truncation, shortcut classifier, surname heuristic or artificial
acknowledgement is introduced. Existing acknowledgement validation, complete-plan
validation/persistence before question exposure, corrective-proposal bound,
NDJSON events, quota, lease and cancellation contracts remain in force.

A previously duplicated entitlement read is reused only inside the same fenced
turn. It is never cached across turns. Independent session, memory and profile
reads overlap after acceptance/policy checks; every read settles on failure or
cancellation before the client closes or lease releases. Dependent locale/profile
writes remain ordered and fenced. No concurrent runtime-home writers are introduced.
Optional workspace work remains independently scheduled; failed artifact linking
retains the claimed job and checkpointed uploaded paths for recovery, without
turning a saved conversation into a failed reply.

## Diagnostics

The existing allowlisted diagnostic stream adds `collector_configuration` with
route/model, prompt version, requested effort and `effective_effort=unavailable`.
A requested `low` value is **not** evidence that the upstream key honored it.
Execution model metadata records the selected route; an original supplied experiment
model label is retained separately as `requested_model` when different.
Use existing app-server raw-delta, turn-progress and subscription stream diagnostic
receipts to distinguish preparation, dispatch, meaningful text, complete validated
question and durable `conversation_saved`. A model turn may include the existing
bounded correction; count its upstream requests separately. Missing provider
metrics remain unavailable, never zero. Do not log credentials, narrator content,
private plans or reasoning to obtain timing evidence.

## Required matched acceptance before rollout

A reviewer/operator must first freeze synthetic cases, sample counts, total call
budget and deadline, baseline/candidate configuration versions, and the matched
quality/latency acceptance criterion. No numerical production SLA is assumed.
No further live calls or deployment are authorized by this document. The follow-up
keeps the user's no-normal-response-quality-loss requirement as a hard release gate.

Use the existing backend streaming interview/profiling seam and deployed
API/private-worker/proxy path, not a new generation harness. Compare on one pinned
application revision:

1. Legacy route + legacy prompt (baseline)
2. Verified dedicated same-model low route + legacy prompt
3. Legacy route + compact-v1 (where feasible)
4. Dedicated low route + compact-v1

Cover both supported languages; first/name-only, short factual clue, rich/long
story, second/later reply, corrections, pauses, photo discussion, explicit language
switch and resumed pre-rollout conversations. Include a subsequent rollback turn.
Use isolated synthetic identities; preserve customer memoirs. Obtain a read-only
provider policy receipt proving the underlying model and effective effort for
each route. Record actual provider retries, input/cache tokens and available load
observations; label cache/context differences as confounds.

Report first meaningful public text, validated question completion and durable
save distributions together with failures/timeouts, extraction/grounding and
contract-quality outcomes. Report medians and tail percentiles only when the frozen
sample size supports them; a small-sample maximum is not production p95. A faster
acknowledgement alone cannot pass if completion/save or semantic quality regresses.
Schema correctness alone is not semantic quality. Keep a small existing real-proxy
browser smoke check for rendering, duplication and save-gated next-answer readiness.

Until deterministic regressions and this matched live quality/latency comparison
pass, issue #53 remains incomplete and the candidate stays disabled.

## Existing bounded profiler

With the existing gateway environment configured for an isolated process, use:

```sh
python3 scripts/profile_first_reply.py conversation --timeout 120 --deadline 1200 --review
python3 scripts/profile_first_reply.py conversation --candidate-model memoir-luna-low --candidate-effort low --candidate-prompt-version legacy --timeout 120 --deadline 1200 --review
```

The first command compares max/legacy to max/compact. The second compares
pooled/max/legacy to dedicated/low/legacy. Both freeze 24 foreground generations,
at most 48 application app-server turns and a stop-at-first-failure rule; these
are not exact upstream request budgets. The same runtime/private-worker stream
and real app-server execute against isolated in-memory storage and temporary homes.
Provider-free optional workspace adapters avoid expanding the live campaign.
This does not substitute for deployed API/proxy, real SQL save, Linux tenant UID,
real image perception or comprehensive semantic-quality acceptance.

Default output excludes testimony/private planning. `--review` includes only the
public replies to the checked-in synthetic cases. Settings and temporary homes
are restored/removed on exit. Record provider retries/cache/load limitations and
all failures; a successfully completed campaign is not by itself a passed quality
or latency release gate.
