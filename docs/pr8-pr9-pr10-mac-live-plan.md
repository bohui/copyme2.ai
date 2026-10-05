# Mac live acceptance and landing plan

Status on 2026-10-05: **planning and read-only diagnosis only**. No new model,
judge, photo-search or telemetry-write request was made. Shared configuration,
credentials and data were not changed. The combined candidate includes the
exact PR3/PR9/PR10 heads and merged PR8. Tested code is
`c1f5e296d6f2dd921c5474dc7c613abc1968b8fc`; cloud rereview was requested for
documentation head `2c8d4b7db27aea09b1a4f03203df436e1f3b926b`.
Native results remain 1,194 passes, four live-only skips, zero failures/errors.
This plan does not establish full acceptance.

## Why the local Langfuse pages are empty

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

The smallest proposed repair is to enable
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
The proposed target is a new `users.d/zz-langfuse-numeric-datetime.xml` fragment,
with rollback by removing only that fragment. It is not installed. Persisting
it across container recreation also needs a deployment declaration; any
required recreation/restart is outside the current authorization and must be
explicitly approved before proceeding. This requires permission to change
shared configuration. It does not
repair corrupted historical scores or recreate missing traces. Keep those
rows untouched; recovery from retained original ingestion data is a separate
operation requiring its own verified source and approval. Do not write guessed
timestamps or remount existing data into an older server.

## Existing setup: names/status, no values

| Component | Current evidence |
| --- | --- |
| Provider | Existing Mac `MEMORY_SPARK_LLM_BASE_URL`, `MEMORY_SPARK_LLM_MODEL`, `MEMORY_SPARK_LLM_API_KEY` are present; no new provider probe was sent, so current reachability, quota and price remain unverified |
| Composer | `MEMORY_SPARK_MEMOIR_COMPOSER_MODEL`, `MEMORY_SPARK_LLM_REASONING_EFFORT`, `MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT` are present; no model substitution is proposed |
| Private workers | `MEMORY_SPARK_CODEX_WORKER_URL/SECRET` and `MEMORY_SPARK_PHOTO_WORKER_URL/SECRET` are absent from the checked Memoir file/current process; task test services were cleaned up; existing shared-worker configuration was not established |
| Langfuse | Local web, PostgreSQL and ClickHouse respond; existing `LANGFUSE_COPYME2AI_PUBLIC_KEY/SECRET_KEY` names are configured in the local provider setup; previously valid authentication was not rechecked or transferred; Memoir/current task process has no tracing keys |
| Judge | No judge configuration was found in the checked sources; the five-case runner explicitly reports no judge endpoint; calibration is `requires-human-review` with no reviewer/date |
| Isolation | Current task checkout has no copied `.env`; offline supervision deliberately strips provider/tracing credentials and cannot be used as the live launcher |

Presence is not readiness. Existing provider credentials can be reused on the
Mac after bounded authorization; they do not supply the missing canonical
driver, calibrated judge, worker isolation, token/spend cap or tracing repair.
Automatic approval review rejected loading complete container environments
because they could contain secrets. Diagnosis continued through supported
read-only clients; no rejected inspection was retried indirectly.

## Remaining acceptance checks

1. Finish independent cloud review of the combined candidate and documentation
   corrections, and required CI. Preserve all canonical MemoryEvent, accepted
   narrator-source, attributed/timing veto, null-claim, cN association and
   private-metadata stripping contracts.
2. After the approved Langfuse repair, publish **one synthetic root, one child
   observation and one numeric score**, with no provider/judge call. Flush,
   then fetch their exact IDs through supported public APIs and check the
   current version's `events_full`/score records, timestamps, parent linkage,
   score value and project identity. Confirm the same records in the user's
   browser with an explicit time window. Submission/authentication alone is
   not durable evidence. No automatic evaluator is created by this canary.
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

These are **proposed existing-runner commands, not executed commands**. Supply
existing approved configuration only in the task process environment. No
secrets belong in arguments, receipts, repository files or cloud transfers.

```sh
.venv/bin/python scripts/run_memoir_five_case_evaluation.py \
  --mode live --env-file /dev/null --preflight-only --publish-langfuse \
  --run-id mac-integrated-preflight --output-root output/live-acceptance

.venv/bin/python scripts/run_memoir_five_case_evaluation.py \
  --mode live --env-file /dev/null --cases harbour-copper-notebook \
  --max-rounds 5 --case-concurrency 1 --timeout 120 --composer-timeout 300 \
  --publish-langfuse --run-id mac-integrated-pilot --output-root output/live-acceptance

MEMORY_SPARK_RUN_LIVE_INTERVIEW_TESTS=1 .venv/bin/python -m pytest -q \
  tests/test_interview_followups.py -k live_followup

.venv/bin/python scripts/run_memoir_five_case_evaluation.py \
  --mode live --env-file /dev/null --max-rounds 50 --case-concurrency 1 \
  --timeout 120 --composer-timeout 300 --publish-langfuse \
  --run-id mac-integrated-full --output-root output/live-acceptance
```

`--mode pilot` is a fixture mode; real pilots require `--mode live`.
Preflight performs health/authentication reads but no story-model turn.
Use unique run IDs and preserve prior attempts. No resume retry is included
in this budget. The canonical driver and judge integration do not yet have
approved executable commands; finalize their bounded interface before use.

| Planned work | Logical boundary count |
| --- | --- |
| Telemetry canary | 1 root + 1 child + 1 score; zero model/judge/photo requests |
| Initial live smoke | 5 conversation turns; no planned photo/composer action |
| Canonical veto pilot | 8 story inputs; driver pending |
| Four follow-up regressions | 4 direct ephemeral Codex turns |
| Full five-case run | 250 conversation turns; 10 positive private photo-worker requests; existing runner has 15 composer checkpoints |
| Combined planned storyteller/model-turn inputs | 267; not an upstream provider-request or token cap |
| Proposed judge batch | At most 4 calibration examples + 13 pilot trajectories + 250 full trajectories = 267 HTTP judgments; requires integration/configuration/review |

The judge class defaults to 1,200 requested output tokens per call, so that
proposed batch requests at most **320,400 output tokens** if the provider
honors the limit. Judge input/reasoning tokens and all storyteller/composer
token limits are unbounded by these commands. Composer indexing batches and
up to three draft/review attempts, focused recovery, Codex/provider retries,
and photo search/source-page fan-out add requests. The runner records private
worker boundaries but currently reports provider tokens/cost as unavailable.
Its 120/300/45-second turn/composer/photo limits and concurrency 1 are not
spend limits. No defensible total token maximum, unit price or dollar budget
is known; no new charge was incurred by these read-only checks. Require a
verified provider/gateway hard cap and usage measurement before approving a
paid full run. The runner does not stop on every failed grade automatically.

Use only fresh task project IDs, user fixtures, object-store/Codex directories,
loopback API/Next ports and task Temporal SQLite. Native PostgreSQL must retain
the supported disposable UUID AppleContainer fixture, no shared mounts/ports,
TCP disabled and exact task cleanup. Do not use a shared worker with durable
customer storage. Model gateway requests consume existing shared quota, and
approved Langfuse writes use the existing shared tracing stack. No production
database, shared restart, migration, billing/voice call or new credential is
part of this plan.

## Approval boundaries and landing

The immediate concrete approval is the **Langfuse-only timestamp compatibility
repair plus the one zero-provider telemetry canary and readback**, using
existing local authentication. Keep the profile scoped to `langfuse`, preserve
the known prior value (zero) for rollback, and stop
if application requires an unapproved restart or wider configuration change.
Historical-row recovery is excluded. Paid execution needs a separate explicit
hard budget and ready, reviewed canonical/judge harness; unknown prices are
not a basis for approving 267 inputs as a spend cap. A new judge endpoint/model
and human calibration sign-off must be supplied rather than inferred.

Publish one draft integration PR from this validation branch to current main,
linking PR3, PR9, PR10 and Issues2/6. It already contains all three PR heads plus
PR8; merging the old heads into one another adds no missing code. Keep the old
PRs open. Finish review/CI, harness readiness, live five-case/browser/judge and
durable-tracing gates before marking full acceptance or merging. If main moves,
deliberately integrate it into this candidate, review the delta and rerun the
affected acceptance. Only after an approved combined landing coordinate closing
the incorporated PRs. Do not merge them independently, retarget them, deploy,
or production-migrate as part of this task.
