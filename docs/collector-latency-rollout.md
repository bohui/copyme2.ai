# Collector latency: opt-in source change (issue #53)

## Status and scope

The [12 October merged-main verification](verification/issues53-55-live-20261012.md)
adds a current-head 42-generation comparison, a real normal-route proxy/Supabase
smoke, and explicit issue 55 discovery/citation cases. The matched pilot improved
median first text from 15.4415s to 4.2915s and in-memory save from 21.988s to
5.6555s. Candidate durable-SQL/proxy acceptance and broader browser checks remain
open. Defaults remain disabled and issue 53 is not ready for closure.

This change supplies **off-by-default candidates**, not release acceptance or a
latency SLA. Normal generation retains its model, maximum effort and full legacy
prompt. Gateway keys, credentials, other agent routes, customer data, schema and
transport are unchanged. The bounded [quality-first follow-up](test-evidence/issue53-quality-first-resolution-20261011.md)
records exploratory live comparisons: prompt-only stopped on a timeout; routing-only
completed but increased median usable-save time. Configured same-model/effort policy
was verified read-only. Neither pilot passed release acceptance; do not enable a
candidate or claim semantic equivalence from schema success alone.

The [PR 58 follow-up](test-evidence/issue53-pr58-follow-up-20261012.md) fixes a
fixed-introduction/save-readiness race and verifies first/later/resumed normal
replies through a real production web proxy. It also confirms that the current
low alias changes the Codex request shape. With explicit user approval, the local
gateway now exposes the separate `gpt-5.6-luna-memoir-low` experiment, reusing the
same underlying model and existing low-effort key. Normal collector defaults are
unchanged. Provisioning the alias does not approve or establish a rollout.

The [compatible-route comparison](test-evidence/issue53-compatible-route-report-20261012.md)
then saved all 42 planned generations on pinned Linux Codex 0.156.1, including
first/later/resumed, Family/reference/long-stress and rollback cases in both
languages. With the full legacy prompt retained, its 20 matched pairs improved
median first public text from 16.375s to 3.678s and in-memory save from 22.520s
to 4.884s. This passes a frozen exploratory latency rule, not release acceptance:
semantic-quality and candidate real API/SQL/proxy gates remain, as do context/cache
confounds and the recorded full-suite verification limitations. Defaults stay off.

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
| `MEMORY_SPARK_COLLECTOR_MODEL` | empty | Override only collector route; `gpt-5.6-luna-memoir-low` is a local opt-in experiment requiring acceptance before rollout |
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
python3 scripts/profile_first_reply.py conversation --candidate-model gpt-5.6-luna-memoir-low --candidate-effort low --candidate-prompt-version legacy --timeout 120 --deadline 1200 --review
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

`--extended` adds matched short/long-stress/Family/public-reference cases and an
actual candidate-history rollback per language: 42 foreground generations, at
most 84 app-server turns, within the same timeout/deadline and failure gate.
The two rollback generations are not matched latency pairs. This remains a small
synthetic exploratory campaign, not representative semantic-quality acceptance.
The freeze includes the local app-server version, or unavailable; pin it alongside
the application source. Do not equate host and deployed Codex versions. Images
without Git report the revision as unavailable; independently verify the deployed
source hash against a pinned checkout in the operator receipt. Matched history
copies use archive semantics to retain Linux tenant ownership, not just modes.

For the secondary, opt-in normal-route real-proxy rendering/save/reload check:

```sh
python3 scripts/smoke_conversation_proxy.py --origin http://127.0.0.1:3010 --timeout 120
```

This freezes three generated replies and uses a fresh anonymous memoir. It leaves
the synthetic account/project and saved replies available for readback. It does
not change services, route settings or customer sessions. A passing smoke does
not establish candidate latency/quality acceptance.
