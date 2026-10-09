# Bounded trajectory evidence

The closed live run `899930ff-95ba-4c5c-8a86-916de3bca509` on PR47 head
`bc3f2223474657e85a1406517da56f04f53bc5b2` retained 512 steps and dropped
482. Strict runtime readback rejected it. The discarded event identities and
categories were not retained; no specific live category or contribution from
duplicate notifications can be inferred from the surviving collector rollup.
This fix is a separate branch stacked over that exact PR47 head.

The recorder keeps two bounded forms of evidence:

- The ordered `steps` list retains requests/responses, item and turn lifecycle,
  tool inputs/results/failures, application validation and persistence facts,
  and all unknown or malformed protocol events. Its default cap remains 512.
  Audit omissions still set `limits.overflowed` and increment
  `limits.dropped_steps`. The unchanged strict runtime guard rejects them even
  if `final.status` is completed. A fixed category histogram also describes
  local omissions; imported omissions are identified as `external` because
  upstream category completeness is not assumed.
- Four plain transport notifications use fixed counters: agent message deltas,
  command output deltas, reasoning text deltas and reasoning summary deltas.
  Each must have an exact recognized method, a string delta, only allowlisted
  scalar transport fields, and no request ID or additional fields. Notifications
  with error, status, retry, pending, lifecycle or unknown fields retain full
  audit treatment. Unknown methods never bypass the cap.

The additive `telemetry` object has schema `memoir-trajectory-telemetry/1`,
`retention: counts_only`, per-method counts, total `compacted_events`, and
explicit `omitted_payloads`. It stores no delta text, item identifiers, content
hashes, samples or per-item index. Its four counter buckets cannot grow with
stream cardinality. The existing local redaction and export minimization still
apply to retained audit facts. The application receives complete messages and
streams text as before; the recorder alone changes delta retention.

Queued notifications were already recorded by `handle_event`. Consuming them
in `turn` now reuses that evidence. Direct arrivals are recorded once. This is
an arrival-path correction, with no payload/ID deduplication: repeated identical
tool events remain distinct, including failed events.

Collector, workspace, focused recovery and worker-failure imports now receive
the whole worker trajectory. They preserve compacted transport counts and
worker-local audit overflow even when the outer step list has room. Contradictory
or malformed accounting becomes an explicit bounded error record and fails
readback. Omitted legacy fields and explicitly present null fields are distinct:
null limits, telemetry or overflow summaries fail closed. A record carrying
telemetry or overflow evidence must include valid limits. An overflow histogram
must use fixed categories, positive integer counts, agree with the dropped-step
total and accompany an overflow flag. Genuine legacy step-only workers remain
supported. Aggregate
audit saturation remains an error, rather than eviction of earlier evidence or
an increase to an unbounded budget. `finish` remains separate from the step cap;
it never proves audit completeness by itself.

Tests use synthetic stdio notifications, fixed worker HTTP responses, actual
runtime orchestration, in-memory storage and owned SQLite jobs. They cover
normal and adversarial streams, five worker imports, queued/direct lifecycle
and failures, overflow propagation, malformed accounting, privacy, streaming
and nonstreaming runtime persistence/readback, and failure receipts. They do
not establish real PostgreSQL/RLS or live-provider/campaign acceptance.

The authorized retained terminal metadata, request journal and task accounting
contain no recoverable JSON-RPC method counts. The collector's 51 high-level
rollup records are not a runtime protocol trace; no workspace rollup survived.
Presence or absence of legacy `codex/event/*` notifications remains unknown.
The exact-v2 synthetic flood results do not prove prevention of that particular
live overflow. Unknown methods continue to receive strict audit treatment.

The opt-in native complete-round test now defines ten cases: HTTP and streaming
for legacy evidence, noisy evidence, worker audit overflow, null limits and null
telemetry. Valid noisy cases require 1,988 compacted/omitted deltas, real artifact
and workspace persistence, strict admission, canonical lane settlement and a new
storage facade for the final canonical readback. Negative cases require strict
rejection before canonical lane work. These native cases remain unrun in this
task. After source review, the parent must coordinate a fresh task-owned
PostgreSQL allocation and exclusive lease, full exact-Git checkout verification,
the existing native backend/opt-in flags and owned cleanup. The shared synthetic
worker uses MockTransport; no provider or evaluation-owner resource is needed.

Changing these runtime modules requires a new V6 source binding. The original
V1–V5 proofs, original inputs/expected data, previous V6 commit identities and
failed-run attribution must remain preserved. The new binding proves source
integrity only. Independent cloud review and any future live-run admission
remain parent-owned gates; this work does not resume the closed run or claim
its 28 already charged requests or zero completed rounds have changed.
