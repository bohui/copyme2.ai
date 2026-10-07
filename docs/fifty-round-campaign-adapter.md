# Fifty-round synthetic execution adapter

This is executable offline tooling, not a live launch command. The existing
`CanonicalEvaluationDriver` completes all 50 original inputs and reads ten saved
draft checkpoints in the integration test. Its storage, runtime orchestration,
and Temporal dependencies are synthetic. This establishes sequencing and
interface compatibility, not actual PostgreSQL durability or model quality.
The historical ten-turn 80-request/900-second/60-second launcher is unchanged.

## Interfaces

`FiftyRoundSyntheticAdapter.create(plan=..., reservation_root=..., replies=...)`
accepts one blocked single-case plan and data-only `SyntheticWorkerReply` fixtures.
It creates exactly one `CampaignDispatchBudget` for every role, preserving the
immutable proposed caps and declared role policy. It cannot load authentication,
connect a socket, accept a provider callback, or switch to a live transport.
Only `http://campaign.synthetic.invalid/internal/codex/turn` is accepted, entirely
inside its `httpx.AsyncBaseTransport` implementation. Every fixture continuation
reserves a send slot before a synthetic contact and completion. Reusable HTTP
clients borrow the transport; the campaign owner calls `finish()` once.

The production callback shapes are preserved:

- Pass `before_round` and `observe_progress` to `CanonicalEvaluationDriver.run_case`
- Wrap its coroutine with `supervise` to bound the whole run
- Use the same transport in the foreground runtime and background worker/composer
- Bind `background_job(round_number=..., job_id=...)` around a trusted synthetic
  activity, not from untrusted request JSON
- Bind `semantic_attempt(stage=..., attempt=...)` around explicit repair loops;
  identical Family prompts can legitimately be retried. Changed diagnostic IDs
  or story text do not create a new logical attempt
- Call `finish(result)` after the driver or `finish()` after failure/cancellation

Stage classification uses actual `WorkerTurnInput` fields. Missing `agent_role`
means collector, as in the real foreground HTTP client. Timeline and composer
require a bound background job. The correlation uses normalized string
`round_id`, run/case/trace IDs. Composer requests may omit Family/evaluation
fields exactly as `composer_call` does. Canonical broad workspace, timeline,
locale and composer use false Family payloads; collector and focused passes
retain the campaign's Family mode. That payload policy does not alter account
entitlements. Locale alone can omit the project/evaluation in round one, matching
the existing language-intake client.

Tests invoke the actual foreground `_worker_turn` and `composer_call` clients,
plus the actual canonical driver and lane dispatch loop using closed synthetic
dependencies. No native Temporal server, database, provider or account is used.

## Failure and receipt meaning

Source/case/input/trace mismatches, unsupported stages, duplicate logical workers,
wrong models, unbound background work, cap exhaustion, malformed checkpoints,
unknown usage, quota errors and deadlines stop the campaign. Original input bytes
are checked against the pinned dataset. Progress cannot rewrite completed source
readbacks, skip rounds, or replace integer counters with floats or booleans.
A complete result also requires completed collector, broad workspace and canonical
extraction worker evidence for every round; readback JSON alone is insufficient.

Timeout/cancellation uses bounded `asyncio.wait`, fences further reservations,
cancels child tasks, then drains for 50 ms. Noncooperative tasks remain explicitly
uncertain; late success never settles/refunds a reservation. Completion also
requires a durable closed journal and no pending tasks. Journal fsync itself is
ordinary synchronous filesystem I/O, not a hard timed cleanup guarantee.

Receipts retain the full immutable unapproved proposal alongside reservation,
synthetic-start, completion, worker-stage, role/account-declaration and uncertainty
counts. `provider_requests_started` stays null. Synthetic checkpoint readbacks
never set `native_durable_checkpoints_verified`; native cleanup, role/account
binding, browser/login/recovery, the normal free-account 20-round limit and model
quality remain unverified. The isolated 50-input fixture is not a subscription or
billing change. Even `completed_synthetic` leaves live readiness false and
acceptance unestablished.

## Exact remaining production wiring

The following code/environment work is still required before a real campaign:

1. Bind the shared session to actual trusted lane claims and explicit semantic
   repair loops. The existing background `MemoryEventWorker` and composer client
   have no campaign correlation callback today. They must not infer rounds or
   repair identity from narrative text or diagnostic IDs. This can be implemented
   and tested offline with a no-op-by-default hook, after coordinating ownership.
2. Supply a separate real transport at the actual upstream send boundary,
   including continuations and cancellations. This fixture transport and ledger
   tickets cannot do that. The existing actor is hard-bounded to the historical
   experiment and cannot be repurposed by changing a readiness Boolean.
3. Admit only an explicitly approved numeric envelope and verified native
   consumer/account/per-role model binding. Proposed 600 sends, 100 preparations,
   7,200 seconds, 60 seconds/send, concurrency one remain proposals. The 511/361
   logical-call maxima do not guarantee completion, cost, or token bounds.
4. Run the canonical driver with fresh owned PostgreSQL/Temporal resources and
   independently verify original source/event readbacks, ten saved checkpoints,
   lowest-level counts, bounded actor/process cleanup and immutable source/config.
5. Run browser/login/recovery and normal free-account 20-round tests separately.

The source-only cloud slice does not close #12/#14 or complete the user's one
50-round Mac campaign. It adds no five-case/250-round execution, paid-route
fallback, live judge, voice, credential handling, service startup or deployment.
