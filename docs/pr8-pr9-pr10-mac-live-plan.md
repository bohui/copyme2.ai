# Mac live acceptance and landing plan

Status on 2026-10-05: **native validation and the approved local Langfuse
repair are complete**. The user approved the local fix/restart and temporary
host caps. One synthetic root, child span and numeric score passed fresh API
and database readback; no model, judge or photo-search call was made. The
[repair report](langfuse-mac-timestamp-repair-20261005.md) records applied
configuration, exact IDs, preservation and rollback. Browser confirmation of
that canary is still unverified. The combined candidate includes the exact
PR3/PR9/PR10 heads and merged PR8. Tested code is
`c1f5e296d6f2dd921c5474dc7c613abc1968b8fc`; independent review remains in cloud.
Native results remain 1,194 passes, four live-only skips, zero failures/errors.
This plan does not establish full acceptance. The user's later instruction
changes ordering: **land the reviewed integration, then run five separate
50-round datasets on exact main and fix/review/retest observed bugs**. The
[current disposition](landing-issue-disposition-20261005.md) supersedes any
earlier implication that the whole live workload must precede landing.
Parent confirmation of the final reviewed head/disposition remains required.

The new `scripts/canonical_evaluation.py` callback passes native default and
nondefault cadence through normal UserStorage/runtime/private-worker and
PostgreSQL/Temporal lanes. It retains originals and trajectories, awaits durable
coverage/checkpoints and rejects reused projects, malformed inputs, unbounded
settle timeouts and live labels. It is a **fixture callback, not a complete live
five-case command**. New request/token budget components pass controlled
provider tests, but the actual-provider accounting adapter and price/hard-spend
verification remain missing. See the new receipt and G1/G3 follow-up bodies.

## Initial diagnosis of the empty local Langfuse pages

The following diagnosis records the state **before** the approved repair.
The historical bad scores and absent historical traces remain; new canary
records now ingest with correct timestamps.

The requested project exists. Read-only ClickHouse queries found zero
`traces`, `observations` and `events_full` rows, and 3,750 API scores referencing
411 absent trace IDs. Every score's timestamp and creation timestamp is
`9999-12-31 23:59:59.000`; all fall outside the current date window. PostgreSQL
has zero project evaluators, evaluation rules, job configurations/executions
and evaluation templates. API scores are not configured evaluator jobs.
The temporary browser reached the local web service but redirected to
sign-in; the user's existing browser filters/session were not inspected.

ClickHouse is **26.9.8.3**, from an unpinned `latest` image. Deployed Langfuse
serializes scores as integer milliseconds and events as integer microseconds.
ClickHouse changed JSON numeric DateTime interpretation in 26.8 to seconds.
The current `input_format_read_datetime_number_as_raw_value` default is zero.
Existing query logs show 2,334 DateTime64-overflow insert failures on October 4,
including `INSERT INTO events_full`, most recently at 14:52:16 UTC. No new
ingestion was attempted during diagnosis. A read-only millisecond probe
reproduced year 9999; a query-local compatibility setting decoded both units
correctly as October 4, 2026.
[ClickHouse documents the compatibility setting](https://clickhouse.com/docs/reference/data-types/datetime64).
Langfuse's current [reference Compose file](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml)
pins ClickHouse 25.12. No downgrade or persistent setting change was performed.
Sanitized [database evidence](test-evidence/langfuse-mac-readonly-20261005.json)
records the observed results and limits.

The initial repair proposal was to enable
`input_format_read_datetime_number_as_raw_value=1` **only for Langfuse's
ingestion database user/client**. Query-log metadata identifies that user as
`langfuse`; it is managed by `users_xml` and inherits `default`. Its deployment
declares data/log mounts but no user-config mount. A proposed credential-free
user fragment would inherit the current profile and change only that setting:

```xml
<clickhouse>
  <profiles>
    <langfuse_numeric_datetime>
      <profile>default</profile>
      <input_format_read_datetime_number_as_raw_value>1</input_format_read_datetime_number_as_raw_value>
    </langfuse_numeric_datetime>
  </profiles>
  <users>
    <langfuse><profile replace="replace">langfuse_numeric_datetime</profile></langfuse>
  </users>
</clickhouse>
```

This follows [ClickHouse's profile inheritance and configuration merge rules](https://clickhouse.com/docs/concepts/features/configuration/settings/settings-profiles).
The approved implementation installs that fragment through a read-only
Compose file mount, along with a second fragment bounding startup concurrency.
The six local Langfuse services were restarted, and the separately approved
temporary host caps resolved startup's open-file exhaustion. The linked repair
report specifies both fragments, their verified effective values and rollback.
It does not repair corrupted historical scores or recreate missing traces. Keep those
rows untouched; recovery from retained original ingestion data is a separate
operation requiring its own verified source and approval. Do not write guessed
timestamps or remount existing data into an older server.

## Existing setup: names/status, no values

| Component | Current evidence |
| --- | --- |
| Provider | Existing Mac `MEMORY_SPARK_LLM_BASE_URL`, `MEMORY_SPARK_LLM_MODEL`, `MEMORY_SPARK_LLM_API_KEY` are present; no new provider probe was sent, so current reachability, quota and price remain unverified |
| Composer | `MEMORY_SPARK_MEMOIR_COMPOSER_MODEL`, `MEMORY_SPARK_LLM_REASONING_EFFORT`, `MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT` are present; no model substitution is proposed |
| Private workers | `MEMORY_SPARK_CODEX_WORKER_URL/SECRET` and `MEMORY_SPARK_PHOTO_WORKER_URL/SECRET` are absent from the checked Memoir file/current process; task test services were cleaned up; existing shared-worker configuration was not established |
| Langfuse | The local stack is healthy after the approved restart; existing `LANGFUSE_COPYME2AI_PUBLIC_KEY/SECRET_KEY` were used privately in the canary process, verified the exact existing project, and passed durable API/database readback; no tracing credentials were copied into the task checkout |
| Judge | No judge configuration was found in the checked sources; the five-case runner explicitly reports no judge endpoint; calibration is `requires-human-review` with no reviewer/date |
| Isolation | Current task checkout has no copied `.env`; offline supervision deliberately strips provider/tracing credentials and cannot be used as the live launcher |

Presence is not readiness. Existing provider credentials can be reused on the
Mac after bounded authorization; they do not supply the missing canonical
driver, calibrated judge, worker isolation or token/spend cap.
Automatic approval review rejected loading complete container environments
because they could contain secrets. Diagnosis continued through supported
read-only clients; no rejected inspection was retried indirectly.

## Remaining acceptance checks

1. Finish independent cloud review of the combined candidate and documentation
   corrections, and required CI. Preserve all canonical MemoryEvent, accepted
   narrator-source, attributed/timing veto, null-claim, cN association and
   private-metadata stripping contracts.
2. **Completed API/database gate:** one synthetic root, child observation and
   numeric score passed exact-ID readback after publication exited, including
   timestamps, root markers, parent/score linkage, value and project identity.
   No provider/judge call or automatic evaluator was created. **Pending browser
   gate:** confirm those same records in the user's browser with an explicit
   time window. The repair report and sanitized receipt contain the exact IDs.
3. Close the four configured-provider follow-up skips: current-message and
   earlier-context prompts in en-AU and zh-CN; one ephemeral Codex turn each.
   The narrow question oracle is deterministic; general conversational
   usefulness still needs reviewed semantic evidence.
4. Run an eight-turn canonical source-evidence pilot: four independent veto
   scenarios in each locale (mixed allowed/withdrawn claims, attributed
   recollection, vetoed timing evidence, global veto). Check exact original
   sources, allowed-event survival, withheld-event absence, and no private
   metadata persisted. Null/malformed claims remain controlled deterministic
   tests rather than asking a live model to emit malformed output.
5. Run five fresh synthetic datasets of exactly 50 accepted conversation
   rounds each: Harbour, Chengdu, Perth, Kunming and Sydney. Verify all seven
   life stages and seven skills, positive/negative invocation and output
   grades, entitlement/project boundaries, grounded places/dates/relationships,
   photo source/rights labels, canonical corrections/revocations, private draft
   coverage, stable unchanged writing, review-only consent, and persisted UI
   state after reload. Record every failure/unavailable result separately.
   Check all ten possible five-round private checkpoints per case, including
   round-5 progress; those 50 milestones are not 50 model requests.
6. Verify durable Langfuse root/step/score linkage for **all 250 full-run
   rounds**, tied to exact code, fixture and rubric hashes. Calibrate and run
   the approved judge separately for tool choice, grounding, recovery,
   repetition, stopping, instruction following and output quality. Semantic
   scores are advisory and cannot override deterministic failures.

**Current harness gap:** `run_memoir_five_case_evaluation.py` uses `CaseStorage`,
not `UserStorage`; runtime selects canonical processing with
`isinstance(storage, UserStorage)`. Its composer requests use empty canonical
events and direct legacy composition, with only checkpoints 20/25/50. It does
not run the production accepted-source/Temporal lane. Its judge and durable
readback status are always unavailable/not verified. A green invocation of
this script alone cannot establish Issue6 canonical live acceptance. Extend
the agreed authenticated story/native PostgreSQL/Temporal seam with TDD and
cloud review before paid canonical execution; do not weaken its assertions.

## Commands and bounded request plan

The legacy five-case live command is diagnostic only and is not proposed as
canonical acceptance. Do not run it as the post-merge full acceptance command.
The native-tested callback is not a complete executable live launcher; G1/G3
must supply and review that command first. Offline supervision strips configured
provider/tracing credentials and must not be reused as a live launcher.

The smallest proposed first paid scope is eight bilingual source-claim pilot
inputs plus four ephemeral follow-up cases. It includes no judge/photo call or
composer checkpoint. Proposed ceilings are 80 **actual provider** requests,
400,000 total input tokens, 80,000 total output tokens and 1,000 output tokens
per request, plus a verified US$2 gateway cap or a verified worst-case price
below US$2. These are a reviewable proposal, **not approved or currently
verified live enforcement**. Existing models/protocols must honor the caps;
no silent model substitution is permitted. See the
[G3 agent-ready proposal](test-evidence/proposals/g3-provider-budget-and-calibrated-judging.md).

`RequestLimitedTransport` enforces a separate worker HTTP ceiling across roles
and clients. `BudgetedProvider` reserves input/output before concurrent calls,
validates reported usage and blocks after unknown/interrupted/over-bound usage.
Its adapter must measure a conservative input bound and enforce the output cap
at the actual upstream provider boundary. A worker HTTP count, Codex turn count,
120/300-second timeout or concurrency of one does not prove model usage or cost.
No actual-provider adapter, exact billing rates or gateway monetary cap have
yet been verified. Missing judge configuration/calibration remains unavailable.

After the reviewed pilot, derive a separate numerical envelope for the five
50-round datasets, ten cadence checkpoints per dataset, judging and any
approved photo/search fan-out. Count every provider/tool/retry/background call,
pin exact main and retain unavailable/failing outcomes. Do not extrapolate the
legacy runner's 15 sampled checkpoints to canonical acceptance.

Use fresh task owners/projects, object-store/Codex directories, loopback API/
Next ports and task Temporal SQLite. Native PostgreSQL retains the supported
UUID Apple Container fixture, no shared mounts/ports, TCP disabled and exact
cleanup. Coordinate heavy work; at most one fixture container and one Temporal
process run concurrently. No shared customer worker, new credential, production
migration or further shared restart is authorised by this live-run plan.

## Approval boundaries and landing

The **Langfuse timestamp repair, local restart, one zero-provider canary and
temporary host caps** were explicitly approved and completed. The profile is
scoped to `langfuse`, with its prior value (zero) recorded for rollback; the
3,750 historical bad score rows retain their full logical-row fingerprint.
Historical-row recovery is excluded. Paid execution needs a separate explicit
hard budget and ready, reviewed canonical/judge harness; unknown prices are
not a basis for approving logical input counts as a spend cap. A new judge endpoint/model
and human calibration sign-off must be supplied rather than inferred.

Draft [integration PR11](https://github.com/bohui/copyme2.ai/pull/11) is published
from this validation branch to main, linking PR3, PR9, PR10 and Issues2/6.
It already contains all three PR heads plus
PR8; merging the old heads into one another adds no missing code. Keep the old
PRs open until parent confirms the final reviewed head and disposition. Land
that one combined candidate, then run exact-main acceptance under its approved
numerical budget. Keep incomplete Issues2/6 open and link their concrete gaps;
full live/browser/judge/durable-tracing acceptance is still incomplete. If main moves,
deliberately integrate it into this candidate, review the delta and rerun the
affected acceptance. Only after an approved combined landing coordinate closing
the incorporated PRs. Do not merge them independently, retarget them, deploy,
or production-migrate as part of this task.
