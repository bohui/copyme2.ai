# Issue 14: additive opt-in denial at application entry points

This source-only slice follows the loopback [protocol prerequisite](issue14-inactive-provider-protocol.md).
It demonstrates refusal before dispatch. It does not enforce real-provider token
or currency budgets, install a native HTTP interceptor, authorize an evaluation,
or complete issue 14.

## Scope and defaults

`apps/api/issue14_execution_admission.py` owns a process-local, immutable,
registered deny-only policy. A policy's run UUID and source revision cannot be
replaced through ordinary attribute assignment; the registration also rejects
forged or tampered objects. Policies can close, but cannot enable live use.
No environment variable, serialized JSON, boolean, or caller `live_ready` label
creates permission. Even a valid owned policy fails with the fixed reason
`provider_capability_unverified`.

Normal app instances use the existing default, `issue14_admission=None`, and
retain their current behavior. None is allowed only by the ordinary app's
optional hook. The dedicated issue 14 launcher requires a policy and refuses
missing/foreign policies too. Request metadata cannot switch an opted-in instance
back into ordinary application mode.

The only edited existing application files are:

- `apps/api/codex_agent.py`: optional constructor-owned policy; refusal before
  native subprocess/home creation, stdio sends, requests and turns.
- `apps/api/codex_runtime.py`: optional constructor-owned policy; refusal before
  top-level turns, worker HTTP, workspace extraction, language intake and task
  publication. The policy is propagated to each of its native connection sites.
- `apps/api/codex_worker_service.py`: optional dedicated-worker policy; refusal
  before worker execution, identity/home/config work, composer provider probes,
  and native execution. Its HTTP turn route checks before starting either JSON
  or streaming tasks and returns terminal 403 with
  `X-Error-Code: ISSUE14_ADMISSION_DENIED` for opted-in refusal.
  Direct `/internal/tasks` publication also refuses before reading task-store
  configuration or contacting that service; it cannot bypass `runtime.publish_task`.

All three policies are explicit trusted constructor arguments; no deployed worker
is reconfigured here. The existing global worker keeps its default None. No
MemoryEventWorker, composer/preparation orchestration, existing launcher/bridge,
judge class, semantic-judge CLI, evaluator, dataset or provider settings are edited.

## Dedicated blocked entry point

`scripts/run_issue14_evaluation.py` accepts a run UUID, source revision, and role.
It creates a deny-only policy, prints a content-free blocked receipt, and exits 3.
There is no execute/approve/live switch. Its callable `run_evaluation` also
requires admission before any supplied runtime, worker or judge factory can run.
It never calls those factories, reads provider configuration, constructs a judge,
or imports a launcher that might do so. This deliberate absence of an execution
path cannot be converted into live authority by a flag.

```sh
python scripts/run_issue14_evaluation.py \
  --run-id 11111111-1111-4111-8111-111111111111 \
  --source-revision c72f9953b012a57202e17e1cfe50da59ee49fba8
```

The new entry point is the pre-configuration boundary. Directly constructing an
ordinary or opted-in runtime/worker retains the constructors' existing configuration
behavior; the opted-in hooks stop dispatch and subsequent home/provider work.
Tests use explicit synthetic configuration and isolate environment lookups.
This is not a claim that ordinary application code or existing judge programs
have been globally disabled.

## Evidence and limits

`tests/test_issue14_execution_admission.py` covers:

- Every admitted role still denied; missing, invented, mismatched, closed and
  tampered policy objects cannot grant access.
- Native subprocess traps and absent homes prove refusal before native startup;
  direct stdio/request/turn calls refuse too.
- Independently counted disposable loopback worker endpoints receive zero
  contacts for opted-in app paths, including absent/mismatched request metadata.
- Collector, workspace, language, extraction, organiser and each composer phase
  refuse before home/config/provider probe/native execution.
- Dedicated worker JSON and streaming requests fail before a turn task starts.
- Direct dedicated-worker task publication produces zero task-store configuration
  reads and zero contacts to an independently counted disposable sink.
- A judge factory is never created by the new launcher; the existing general judge
  class and judge CLI remain unmodified and outside this enforcement claim.
- Ordinary runtime HTTP request shape, native stdio and worker behavior remain
  available with their existing defaults, using synthetic stubs only.

The existing fifty-round source-pin test already failed on the original main's
composer digest. This delta additionally changes three source-pinned app files,
so the old derivation must remain unavailable until separately coordinated
review. No source pin or historical canary limit is silently changed here.

Receipts always say deny-only, `live_ready=false`,
`actual_provider_requests=null`, and
`real_provider_token_or_cost_limits_verified=false`. They contain no body,
credential, testimony, private reasoning or provider exception text. Denial
does not establish provider output limits, pricing, usage correctness, in-flight
cancellation, process-wide network isolation, or complete native accounting.

## Still required before any live work

Independently reviewed lowest-level actual-send interception of every relevant
call/continuation/retry; complete input and output/reasoning capability for the
existing authorized route/account/wire model; verified pinned rates or an existing
hard money cap; and explicit numerical live-budget approval. Photos remain
separate. Judging also requires the authorized endpoint/model and named human
calibration reviewer/date/examples. Passing denial tests cannot satisfy these
requirements or authorize credentials, spending, telemetry uploads, deployment,
or production migration.
