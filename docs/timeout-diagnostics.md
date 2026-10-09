# Evaluation timeout diagnostics

The closed run `6fd8b614-4e8b-4e4d-b3a4-ffb0963983fd` on PR48 head
`b3c6cd5a69b4fdcff07cc5ae100f5e08ccea0d06` stopped before finishing round 1.
Owned collector diagnostics identify the local whole-execution deadline:
app-server cancellation at 120,049 ms and worker timeout at 120,050 ms. Three
client sends were charged, two HTTP 200 responses completed, and one remained
unresolved. Total prior/current charges remain 31. No provider outage, quota
failure, upstream cancellation or final original-source PostgreSQL state is
established; successful conversation commit was not reached.

The pure plan now exposes native effective worker budgets without importing
the allocating worker service. The unchanged defaults are 120 seconds for the
collector, organiser, memory context and author timeline; 240 for workspace
and composer index/prepare/review; and 600 for composer draft. Native evaluation
does not inherit the worker timeout environment override. Owned worker records
also record the actual selected execution budget and monotonic dispatch/finish
times. These dispatch timings include worker lock acquisition; they do not
claim to measure the exact instant the internal timeout context begins.

Native campaign plans accept an explicit `--collector-timeout-seconds 180`.
Omission retains 120 seconds. The value must be a finite number from 0.001
through 240 seconds; invalid values fail before allocation and are never
silently clamped. Execution revalidates the entire saved plan, including its
deadline diagnostics, and passes the selected value only to collector workers.
Other native roles use explicit defaults, so the normal product's environment
override cannot supersede the plan. Product defaults, environment policy and
240-second clamp remain unchanged. Request counts and case/global clocks retain
their existing enforcement. The separately approved 180-second selection is
configuration for parent-owned evaluation admission; a longer window has not
been proven to resolve the original failure.

Each existing bounded send reservation carries its monotonic reservation time.
A durable `send_started` entry records admission immediately before wire access;
completed responses carry completion time and elapsed milliseconds. These times
include local journal overhead and are client-boundary timings, not upstream
generation latency. A start records attempted admission, including uncertainty
if its journal write subsequently fails; it does not prove remote receipt.
Unresolved entries retain their charge and lack a completion timestamp. The
extra durable write rechecks the existing deadline before any socket access.
No request, case or global cap is increased, reset, refunded or bypassed.

The browser's owned failure future carries a fixed timeout sidecar selected
from the last sixteen owned worker records. A separate bounded dispatch binding
retains the authorized role and exact correlation, including author-timeline
job context and composer checkpoint context after the activity context resets.
The query must be the exact original base round or the full registered context;
foreign jobs/checkpoints, mutated records and extra fields are rejected.
The sidecar includes only correlation, role, timeout
classification/origin, actual deadline-expiry evidence, effective seconds, elapsed milliseconds and worker-local
started/completed/unresolved counts. It contains no exception text, payload,
provider fields, browser-supplied cause or arbitrary error attributes. Failure
evidence remains readable when admission is stopped; pending and successful
turns still require every original browser check. The runner independently
reads the same owned source into round and terminal receipts for failures
throughout the round, including returned workspace results rejected by strict
readback and background settlement failures. Its generic
failure and stop classification remains present alongside the timeout cause.

Timeout names alone do not prove expiry. The real worker retains its actual
asyncio timeout context, bound to the exact input object and executing task.
Only its expired context proves `worker_execution_deadline`. An immediate
HTTPX timeout records `transport_timeout`, and other timeout errors without
expired context record `unknown_timeout`; both explicitly report
`worker_deadline_expired: false`. Arbitrary exception attributes cannot supply
this evidence. The diagnostics preserve cancellation and all original guards;
the explicit native collector selection changes only its execution budget.

Synthetic tests exercise the real bounded worker, SubscriptionRun/Transport,
owned worker transport and browser future seam: two fixed successful responses
followed by a third call blocked on an asyncio.Event. They require timeout,
inner cancellation, 3 started / 2 completed / 1 unresolved, terminal closure,
restart fencing and no fourth send. Other cases reject hostile/mismatched
metadata and cover journal failure and deadline expiry before wire access.
Issued-session tests additionally exercise accelerated real timeout contexts
for author timeline/composer, ended activity context, foreign job/checkpoint
rejection and transport/unknown timeout origins with zero model sends. Temporal
startup and generated worker content are synthetic seams; no native command runs.
Configuration tests cover default/explicit propagation, invalid inputs, saved
plan drift, environment precedence, the issued collector timer and diagnostics,
and unchanged case/global clocks, using synthetic storage and no model sends.
Owned source/protocol seams are synthetic; these results establish neither a
native app-server campaign nor PostgreSQL persistence or provider behavior.

The V6 binding is additive and preserves every prior V6 object, V1–V5
auditor/proof, original dataset, expected data and strict acceptance guards.
Independent cloud review and any future evaluation admission remain parent
owned. This repair authorizes no replay, model call, database allocation,
migration, shared service change, deployment or merge.

Retained proof identities (existing receipts are read-only):

- Diagnosis SHA-256:
  `e3676d888b7c51fe8146f263ce6e1cbf6ed523cacf0e32d3f10b089bb87716b6`.
- Run receipt SHA-256 listed inside that diagnosis:
  `453af7b8d91a09021d336b865ca12aa8e9a86bb70fa5044116a71cd6989ce2ea`.
- Terminal cleanup SHA-256:
  `9b3b10d28bbd768c9f3435d749d30ee519e4398f4d9383f34c00d8aea5bc839a`.

The delegated request associated the receipt hash with the diagnosis filename;
the two distinct identities above preserve the actual binding.
