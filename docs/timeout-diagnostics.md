# Evaluation timeout diagnostics

The closed run `6fd8b614-4e8b-4e4d-b3a4-ffb0963983fd` on PR48 head
`b3c6cd5a69b4fdcff07cc5ae100f5e08ccea0d06` stopped before finishing round 1.
Owned collector diagnostics identify the local whole-execution deadline:
app-server cancellation at 120,049 ms and worker timeout at 120,050 ms. Three
client sends were charged, two HTTP 200 responses completed, and one remained
unresolved. That attempt brought cumulative prior/current charges to 31. No provider outage, quota
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

## Response phases and cancellation progress

The later approved 180-second run `6a70df63-7149-4a08-b2f9-017d89508b55`
on `39449148778e2a48c84bdde5cc702a0a8ee43d44` also stopped before a completed
round. Three HTTP 200 responses completed in 14.689, 11.622 and 21.280 seconds.
The fourth send remained unfinished for 131.648 seconds when the actual collector
deadline expired. Cumulative accounting is now **35 charged / 2 unresolved**;
those charges and original owner receipts remain unchanged. Headers/connect
wait, body stall, terminal SSE without EOF and upstream behavior remain
indistinguishable in that run's retained metadata. Its safe assessment has
SHA-256 `5ad45c47d15a555752938deb0e1a1e485d53bf19ea2fd9adbf49cb059258803a`.

Every newly admitted send now keeps a content-free response observation: headers
arrival/status, first/last raw byte-chunk arrival, aggregate bytes/chunks, fixed
allowlisted SSE event counts, terminal category/timestamps, HTTP EOF, failure
phase/class and cleanup status/class. These are guarded-client timings, not
provider-generation timings. An owned stream wrapper delegates the same bytes
and close calls, observing EOF immediately before HTTPX's automatic close;
EOF remains distinguishable if that close fails. Completed body bytes still
reach Codex only after the original full-response, status, size, journal and
deadline checks. A terminal event or `[DONE]` marker is **diagnostic metadata**,
never proof of semantic success or authority to stop reading before HTTP EOF.

SSE observation parses only complete frames, including split CR/LF, UTF-8 and
multiline data. Duplicate JSON keys, nonfinite numbers, malformed JSON and
mismatched event/type fields cannot supply terminal evidence. Completed data
frames are decoded strictly as UTF-8 before JSON parsing; JSON byte autodetection
must not turn UTF-16/32 or invalid UTF-8 into false terminal evidence. A DONE
marker has its own bounded count/timestamps, preserves any typed terminal
outcome, and never creates a conflict with that outcome. Contradictory typed
terminal events still produce a conflicting category. Event/line buffers
are capped at 256 KiB each; oversized frames are counted as omitted. Arbitrary
names and fields are never retained; unknown types receive a fixed count.
Fixed counters saturate with explicit truncation. A combined delimiter scan
and 16,384-line per-response limit bound diagnostic work; once that limit is
reached, SSE counts are explicitly partial and no later terminal category is
inferred. Aggregate byte/chunk observations and original response reading
continue unchanged. Nonfinite/backward monotonic
times are discarded with an invalid-timestamp flag. Buffers are cleared and
observations sealed at close. At most two bounded observation revisions are
journaled per send, including on cancellation. The initial revision precedes
the original accounting gate; a single final correction records failure fields
if that gate rejects or later cleanup changes the observation. The latest
durable revision supplies the final observation; a failed correction keeps
the journal explicitly nondurable and preserves the primary failure. A journal failure stops admission and preserves
the original failure; a successful diagnostic write cannot extend the existing
deadline or complete/refund a reservation.

Byte/chunk counts and arrival times include the size-rejected final chunk,
before the unchanged response-size guard rejects it. Those rejected bytes are
neither copied into diagnostic buffers nor parsed, retained or forwarded; SSE
counts are marked partial with a fixed response-size reason. This distinguishes
an oversized single block from a response that supplied no bytes.

A separate private app-server observer counts turn starts/completions, additional
turn starts, known message/reasoning delta events, and tool notifications by fixed
operation/status. It counts distinct opaque tool IDs using only bounded in-memory
hashes (256 IDs), and repeated starts for a fixed allowlist of tool names.
Unknown names receive a fixed unlisted count, never a guessed repeated-name
claim. Counts are bounded to 4,096 progress events with explicit truncation;
ID/turn hashes are cleared on closure. The observer processes queued items once
and requires the exact current thread/turn. It supplies neither tool authority
nor evidence that a tool's claimed effect actually persisted.

Worker progress is bound to the exact original input and executing task, sealed
in the worker's `finally` block, and copied into the owned dispatch binding.
Cancellation retains these counts without exporting the trajectory, prompt,
reply, arguments, outputs, private reasoning, identifiers, headers or error
text. No renderer callback is needed. Mutated/foreign progress cannot enter the
trusted browser/runner timeout sidecar; late callbacks cannot change sealed
counts. Trajectory recording and fail-closed acceptance remain unchanged.

Synthetic tests prove that buffering withholds even a terminal SSE frame until
HTTP EOF, and that healthy EOF preserves identical bytes. This demonstrates
the diagnostic boundary and the intentional complete-response guard, **not a
protocol defect or the cause of the live expiry**. Forwarding, terminal
acceptance, model/reasoning selection, retries, timeouts and caps are unchanged.
No new live attempt, service or database allocation is part of this repair.
