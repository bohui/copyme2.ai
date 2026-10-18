# Collector latency: opt-in source change (issue #53)

The legacy collector and comparison profiling modes described below were removed
on 18 October 2026. Current collector prompt settings are `compact-v1` (default)
and `two-lane-v1`. For current HTTP first-response measurements, run
`python3 scripts/profile_first_reply.py first-turn --origin http://localhost:3010`.
The canonical controlled profiler uses a simulated model; use the HTTP profiler
for provider-inclusive timings. The historical `collector` and `conversation`
commands below are no longer supported.

## Prompt publication cleanup — 19 October 2026

At the user's request, 17 canceled optimization/rollback versions were backed
up locally and deleted individually from Langfuse. The four affected interviewer
artifacts are pinned to their unchanged original v1; extract-with-hints retains
its pre-experiment v2. Genuine earlier versions and all application prompt text
remain unchanged. The older version numbers below describe historical actions.

Prompt content now goes through Git review before publication. The installed
post-merge hook synchronizes a pulled, current `main`; feature branches cannot
publish. Identical text reuses the existing version and leaves matching files
untouched. The hook, manual retry, main/dirty-tree guards, uncertain-create
recovery and exact receipt readback are covered by 32 focused tests; all 70
managed artifacts pass their remote prompt checks. No new model calls or prompt
versions were created during this cleanup. See the README's versioned prompt
workflow for installation and retry commands.

## PR #87 complete prompt rollback — 19 October 2026

The user clarified that all prompt changes should be reverted for later manual
review, including the conflict fixes retained in the selective rollback below.
All 70 managed prompt source files now match the PR base (`7ef394b`) byte for
byte. The affected collector/runtime/lane prompt assembly code also matches that
base. The PR's foreground prompt tests are removed and the original composition
tests are restored; the separate background-effort tests and non-prompt fixes
remain.

The exact original text was verified against Langfuse, published as new versions
where needed, then fetched and exported with matching receipts. Guidance remains
v4; collector-plan and governed-continuity are v5, background-memory v4, and
extract-with-hints v5. The version receipts intentionally record the new immutable
versions even though the prompt content is identical to the earlier baseline.
Lane A remains on the previously restored local pooled/max route. No live model
generation or manual prompt-quality review was performed.

All **408** focused prompt, schema, execution, attribution and background-profile
workflow tests pass, including the disposable PostgreSQL cases. All 70 artifacts
pass `make prompt-check`. The local API, private worker and
checkpoint worker were reloaded and their mounted runtime prompts and assembly
files match the baseline. API, frontend, private-worker and photo-worker health
checks returned HTTP 200 after alias refresh.

## PR #87 selective prompt rollback (superseded) — 19 October 2026

The prompt and model-context optimizations from PR #87 are reverted. This
supersedes the 18 October prompt experiments below. The interviewer guidance is
byte-for-byte identical to the PR base (`7ef394b`); the other four affected
artifacts restore the earlier detailed policy with only schema-consistency
clarifications retained:

- Lane A returns only an immediate candidate when its schema permits one;
  future question pools and place extraction remain Lane B work.
- The place extension is requested only when the supplied schema includes it.
- Two-lane extraction uses the combined schema, new-event null IDs and no person
  IDs without an authorised registry. The shared timeline/service/grounding
  components are restored, including the existing events-only schema override.

Lane B again receives the complete validated packet, including both original
preference locations, with its full byte count included in budget checks. The
data-only skills/instruction and web/image suppression options are removed.
The separate governed-runtime isolation flags and explicit per-lane effort
selection remain. Map recovery/localisation, checkpoint model support and the
workflow fixture fixes are retained. Lane A's local `max` selection is unchanged.

Langfuse versions were published first, then fetched, exported and checked with
their receipts: interviewer guidance/collector-plan/governed-continuity v4,
background-memory v3 and timeline extract-with-hints v4. All 70 managed artifacts
pass `make prompt-check`. The focused prompt, composition, continuity, schema
and execution run passes **375 tests**; the disposable PostgreSQL attribution
and background-profile workflows pass another **50 tests**. Restoration checks failed against the
shortened prompts before export and passed afterward. No live-model quality
comparison was run.

The local API, private worker and checkpoint worker were reloaded. Each loads
the verified restored prompt receipts and full interviewer policy with Lane A
still pooled/max. API, frontend, private-worker and photo-worker health checks
returned HTTP 200 after service-alias refresh.

## Lane A max-effort rollback — 19 October 2026

At the user's request, the local collector selects
`MEMORY_SPARK_COLLECTOR_MODEL=gpt-5.6-luna-pooled` with
`MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=max`, superseding the high-effort
selection below. The Memoir consumer can access this existing route. Read-only
inspection of the active gateway key confirms the same `gpt-5.6-luna` model and
enforced `max`; the dedicated high route would continue enforcing `high` even
with a different requested effort. No gateway policy change is needed.

The existing `two-lane-v1` selector and prompt artifacts are retained to isolate
the effort change. Background extraction and composition continue using their
independent low route. The checkpoint worker uses the pooled collector alias
for checkpoint indexing, which the existing model allowlist already supports.
The API, private worker and checkpoint worker were recreated; their running
collector configuration reads back pooled/max/two-lane-v1. API, web, private
worker and photo-worker health checks returned HTTP 200 after alias refresh.

Canonical execution, per-turn effort selection and Lane A prompt checks pass:
**83 passed**. A pre-change run of the broader configuration and canonical
execution suites recorded **73 passed, 42 failed**; the older configuration
tests include calls to removed `_home` APIs. These failures preceded this
configuration change. No live model generation or question-quality comparison
was run, so improved question quality is not established by this rollback.

## Lane A recall-quality follow-up — 18 October 2026

That follow-up selected `gpt-5.6-luna-memoir-high` with collector effort `high`.
The sibling gateway has an independent collector key enforcing the same Luna
model and high effort; the background key continues to enforce low. Local API,
private worker and background checkpoint worker settings were read back after reload. Collector
defaults in `.env.example` remain opt-in.

The collector's reviewed byte-bound allowlist now includes the verified high
alias. Migration `202610180002_collector_high_checkpoint.sql` admits the same
exact alias for canonical checkpoints. It changes only that function's model
list and preserves security, grants and evidence/lease checks. Disposable SQL
tests cover checkpoint publication, retained originals, stale claims, unsupported
models and service-only access. The migration was applied through tracked
Supabase migration history and those function grants were read back unchanged.
On 19 October, the same allowlist entry was folded into
`202610180001_initial_schema.sql` and the standalone follow-up was removed.
Fresh installs and later resets now use that single migration. This consolidation
did not reset or apply migrations to the configured database.
Consolidation checks returned 22 passes, including Supabase CLI push/replay/reset
on disposable PostgreSQL. The existing story-game foreign-key index and reset
table-inventory checks still fail; both were reproduced before consolidation.
The background worker receives the collector settings for checkpoint indexing;
its extraction/profile/summary/composer calls keep their independent low route.

The reported reply was a second Lane A attempt: the first returned continuity
text different from its quoted evidence. That correctly failed validation and
caused another full generation. The retry asked about family reports of birth
or early childhood, although the packet already contained the birth year/month.
The compact guidance had lost the explicit supplied-fact reuse rule and did not
clearly require an accessible recall cue.

Langfuse guidance v3 restores supplied-fact reuse and asks for one contextual,
open memory cue without inventing childhood residence or sensory details.
Governed-continuity v3 adds an exact text/quote example. Both were published as
new Langfuse versions, fetched back, exported with receipts and remotely checked.
Compiled Lane A instructions are 7,340–8,265 characters across supported modes.

Two isolated gateway Responses replays used the same narrator evidence, privacy
pins and output schema. Both passed the production output validator and codex-lb
logs independently confirmed effective `high`:

| Prompt | First complete acknowledgement | Complete result | Question direction |
| --- | --- | --- | --- |
| Previous guidance v2 | 4.349s | 5.478s | Asked whether family described the birth. |
| Recall guidance v3 | 5.130s | 6.172s | 提到承德，您脑海里最先浮现的是什么画面？ |

These measure the isolated gateway replay, excluding application/SQL preparation
and browser paint. One sample per prompt cannot establish a general quality or
latency effect. High effort alone did not fix this example; the revised prompt
produced the intended recall cue. No matched low/high quality evaluation was run.
Trace IDs: previous prompt `858f0c053ab7a40335f018835b4c1691`; recall prompt
`f9a930b93b0d441149be3afa829493bb`.

The separate Chengde photo-search diagnostic returned zero items and
`UNAVAILABLE`: Flickr `robots_denied`, Google/SerpAPI `source_unavailable`, and
Library of Congress `http_403`. The Google discovery step found leads, but
original-page verification did not yield accepted photos. This photo path has
model web search disabled and does not use the data-only extraction runtime.
The upstream photo-source failures remain unresolved.

Verification: 381 prompt, grounding, continuity, lane and photo regression tests;
seven focused disposable SQL checks; all 70 Langfuse artifact checks; gateway
`make agent-ci` and seven model-route tests passed. Gateway/API/web-proxy/private-worker/
photo-worker health checks returned 200 after Mocker service aliases were refreshed.
A wider SQL run exposed four pre-existing failures: story-game foreign-key index
coverage, reset-table inventory, and stale profile/strategy fixtures. All four
were reproduced with the follow-up migration excluded in a baseline-only control.

To roll back effort alone, select `gpt-5.6-luna-memoir-low` with `low`, reload
API and private worker, and refresh Mocker aliases. Keep the verified v3 recall
and quotation guidance.

## Local Lane A update — 18 October 2026

The initial local trial selected
`MEMORY_SPARK_COLLECTOR_MODEL=gpt-5.6-luna-memoir-low` and
`MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=low`. The existing `two-lane-v1`
selector remained enabled. The recall-quality follow-up above supersedes this
trial's local effort selection. These were local operator overrides.

That trial's foreground contract was 6,546–7,471 characters, depending on language
and strategy, instead of the earlier 13–21k. It requests one immediate question,
does not request background place extraction in either two-lane path, and keeps
current-source citation, attribution, uncertainty and privacy rules. General
agent tool definitions are disabled in governed runtimes; an isolated native
request capture confirmed an empty tools list without calling a provider.
The changed Langfuse prompt exports have verified immutable version receipts.

Exactly three approved synthetic collector turns were run, with no additional
background model calls. All passed the production output validators:

| Case | First complete acknowledgement | Complete question/result |
| --- | --- | --- |
| Chinese name-only, real HTTP/proxy/SQL | 9.164s | reply_complete 10.841s; conversation_saved 11.006s |
| English story, isolated production collector | 5.304s | 6.196s |
| Chinese story, isolated production collector | 3.816s | 4.717s |

The HTTP collector stage took about 4.9s; context preparation preceded it by
about 4.9s. The isolated collector checks do not include API/SQL or browser paint.
Langfuse confirms `reasoning.effort=low` and the same underlying `gpt-5.6-luna`
model for all three calls. Input was 5,421–5,837 tokens; reasoning was 175–343
tokens. The earlier 32.084s trace used max effort and 3,871 reasoning tokens.
These are unmatched small-sample observations, not a production latency or
semantic-quality acceptance claim. End-to-end 4–5s remains unmet.

Trace IDs: HTTP `6cf366476c1a3eb624d5db04d621872d`, English
`921b8da7749976d3d06bbe1e0a9773f3`, Chinese
`4dbf4c941cdc81fff3f9d1c942b798fa`.

Focused prompt, continuity, schema and engine checks: 265 passed. A broader
runtime/lane check had 210 passed and 7 failures involving old question-pool
receipts and strategy fixtures. Legacy Codex suites had 271 passed and 68
failures, including tests calling removed runtime/worker APIs. These unrelated
failures were not changed. Compilation, `git diff --check`, and the provider's
`make agent-ci` passed.

Local rollback: clear the collector model and effort overrides on API and
private worker, leaving the current valid prompt version and lane flags intact,
then recreate those services and refresh Mocker service aliases. Historical
acceptance records below describe earlier experiments, not this local update.

## Local Lane B update — 18 October 2026

Bounded background extraction, summary and profile calls now explicitly request
their configured `MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT` (default `low`);
composition uses its independent composer setting (also default `low`). An
explicit worker-constructor override still takes precedence. The global effort,
Lane A configuration, model aliases and gateway/key policies are unchanged.

Data-only background runtimes omit the skills catalog and disable web search
and local-image tools. Research jobs and other runtimes retain their existing
capabilities. Installed Codex 0.156.1 still advertises `request_user_input`;
unsupported tool requests remain rejected by the existing connection handler.

The two-lane extraction template is pinned to verified Langfuse version 3. It
omits agent/service administration prose while retaining the shared grounding
component verbatim, plus event identity, recurring-period, stage, chronology,
person-ID and permission rules. Standalone extraction keeps its existing agent
and service instructions. All four extraction output-schema hashes are unchanged.
The largest full instruction set fell from 13,436 to 8,768 characters.

The full canonical worker packet and its privacy fence are unchanged. Only after
validation does the native model view omit the duplicate payload preferences;
the complete authoritative policy remains in `lane_context.preferences`.
Budget checks count that actual model view. Replaying the supplied example
offline reduced its model packet from 6,079 to 4,715 characters (local tokenizer
estimate: 1,977 to 1,498 text tokens), with all testimony and privacy pins intact.

A no-provider capture through the actual worker branch confirmed requested
`low`, no skills catalog or web/image tools, unchanged canonical transport, and
one complete policy copy. No new live-model quality or latency benchmark was run.
Prompt receipt checking, compilation, whitespace checks and the provider's
`make agent-ci` passed. Focused, contract and disposable-SQL workflow runs passed
410 distinct tests, including 50 attribution/profile workflows.
Those workflow fixtures now supply the strategy proposal required by the current
combined schema; production validators were not relaxed. A broader shared-event
SQL suite still has eight legacy-entry-point fixture failures (36 passed).
The affected local API/background/private-worker services were reloaded, Mocker
aliases refreshed, and API/private-worker/web-proxy health checks returned 200.

## Status and scope

The [13 October stream-delivery follow-up](verification/issue53-stream-packets-20261013.md)
fixes per-fragment database authority overhead with bounded private-worker
packets, retaining a fresh authority check for each actual send. Controlled
real-SQL delivery improved from 3.231/4.364s to 0.379/0.354s. A current six-turn
low/legacy API/Supabase smoke also passed exact-source readback and idempotent
replay, with first text at 5.651–10.231s. This is limited, unpaired evidence;
normal max/legacy still took about 19s in the isolated patched check. Running
services and collector defaults remain unchanged, and release acceptance is open.

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
