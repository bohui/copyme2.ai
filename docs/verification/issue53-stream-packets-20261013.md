# Issue 53: stream delivery regression, 13 October 2026

The new legacy authority safeguard adds a database check to each actual private
worker stream send. Small queued model fragments were each sent separately,
amplifying the remote database cost before the complete acknowledgement reached
the API. Bounded packet batching fixes this delivery regression without changing
the collector's model, reasoning, prompt, proposal validation or public events.
Issue 53 remains open: the normal collector still uses maximum reasoning, and
the low-route release gate is not established by this small follow-up.

## Observed current behavior

The running API/worker selected `gpt-5.6-luna-pooled`, requested `max`, and used
the `legacy` prompt; collector overrides were empty. A fresh synthetic Chinese
name turn through the existing web proxy produced first meaningful text at
18.302s and `conversation_saved` at 26.630s. Preparation reached the reply phase
at 2.344s. The command was:

```sh
python3 scripts/profile_first_reply.py first-turn --origin http://127.0.0.1:3010 --timeout 60
```

A separate disposable Linux worker and temporary API process tested the patch
with the same max/legacy configuration and real Supabase persistence. First text
arrived at 18.964s and saving completed at 21.957s. This second observation used
direct API HTTP rather than the web proxy. These are single, unpaired provider
observations, so they do **not** establish an end-to-end latency improvement.
They show that eliminating delivery amplification does not eliminate upstream
generation delay.

The current synthetic opening instructions contain 35,179 characters versus
roughly 27k in the original issue investigation. The compact candidate contains
18,901 characters. Neither prompt was shortened or enabled in this fix.

## Delivery fix and causal check

`turn_events` can pack already queued, ordered NDJSON frames into sends bounded
at 64 KiB. The private legacy collector endpoint opts in. No batching timer,
waiting for later model output, JSON fragment publication, artificial
acknowledgement or public transport change is introduced. A single oversized
frame retains existing behavior. Other execution roles retain their current
packet behavior.

Each actual packet still passes `LegacyStreamingResponse`'s database authority
guard through send completion. Later packets are rechecked in new transactions;
batching does not cache permission or hold an authority lock during generation.
Queue backpressure, terminal ordering and cancellation cleanup remain intact.

The regression test drives the real worker HTTP endpoint, substitutes controlled
model output, and waits for a validated acknowledgement while generation remains
blocked. Before the fix, its 54-character acknowledgement required 56 authority
checks and failed the packet-count assertion. After the fix it needs at most four
checks, and an adoption between packets still rejects the terminal output.

```sh
python3 -m pytest -q tests/test_lifetime_worker_admission.py::test_worker_stream_does_not_charge_an_authority_roundtrip_per_queued_character
```

A controlled-output timing check ran the same worker endpoint against the real
database guard for a synthetic owner, with zero provider calls:

| Acknowledgement language | Unbatched first text | Batched first text | Authority checks at first text, before → after |
| --- | ---: | ---: | ---: |
| Chinese | 3.231s | 0.379s | 35 → 3 |
| English | 4.364s | 0.354s | 55 → 3 |

This isolates delivery overhead. It is an ASGI/real-SQL measurement with controlled
model output, **not** live conversational latency or browser paint. Reusing one
response connection still measured 76–123ms for most individual authority guards,
with a 436ms initial connection/check in the separate ten-guard sample.

## Existing low route: current API and durable-save smoke

Read-only configuration and exact-key hash matching verified that the existing
`gpt-5.6-luna-memoir-low` alias uses the same underlying `gpt-5.6-luna` model and
an active key enforcing `low`. The baseline key still enforces `max`. No provider
configuration, consumer allowlist or key policy was changed.

The disposable worker/API used the batching patch and collector-only settings:

```text
MEMORY_SPARK_COLLECTOR_MODEL=gpt-5.6-luna-memoir-low
MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=low
MEMORY_SPARK_COLLECTOR_PROMPT_VERSION=legacy
```

The pre-dispatch freeze capped the corrected pilot at six foreground generations,
60s per generation and 420s overall. It used fresh synthetic accounts, a fresh HTTP
connection per turn, real Linux tenant execution and normal Supabase saving. Each
saved receipt was read back independently and checked for the exact complete
narrator text and reply. Reposting the same turn returned the cached reply.

| Language / case | First visible text | Validated reply | Conversation saved |
| --- | ---: | ---: | ---: |
| Chinese / first | 6.963s | 8.311s | 8.389s |
| Chinese / later story | 6.118s | 8.385s | 8.469s |
| Chinese / resumed correction | 6.641s | 8.877s | 8.948s |
| English / first | 5.651s | 11.172s | 11.248s |
| English / later story | 10.231s | 11.676s | 11.746s |
| English / resumed correction | 7.823s | 10.232s | 10.309s |

All six had one question. Public synthetic replies retained the stated name and
language, respected uncertain years, and adopted the correction from sister to
mother. The Chinese correction asked whether the earlier statement about not
telling the parents meant the father, presenting that as a clarification. No
clear new unsupported event, date or actor appeared in this limited review.

The initial low-route pilot generated and saved one Chinese opening, then its
readback harness incorrectly addressed `status` rather than the receipt's `state`
field. That check failed and the attempt stopped. Its identity was
`a3560928-6f34-408c-851f-dbdad73a6551` / `project_79257aa14ce7`; timings were not
retained. It is not counted as a passing pilot. The corrected pilot's identities
were `b497b960-e6f7-4a26-8dc5-7e1b190b7357` / `project_597e1e7f4970` and
`777858ee-2717-4c47-bb16-42f09199cdb8` / `project_54150c47ce20`.

Across this follow-up, nine foreground generations were dispatched: two max-route
opening observations, the stopped one-generation low pilot, and the corrected
six-generation low pilot. Replays are not new generation. Optional workspace work
uses normal orchestration; exact upstream request/retry counts are unavailable.
Shared low-key provider records cannot be joined exactly to these application
turns and also include background traffic.

This is a current real-API/SQL smoke, not a matched release comparison. It does
not establish semantic equivalence, private-plan/workspace quality, a production
percentile, candidate web-proxy/browser behavior, or switching a pre-rollout
max-route thread to low. Broader photo, pause, Family, reference, long-story,
language-switch and rollback acceptance remains necessary before rollout.

## Verification and retained limitations

- Collector, preparation, profiler, streaming and worker authority suite: **119 passed**.
- Worker, subscription diagnostics, workspace latency and Compose configuration:
  **106 passed** in separate files.
- Real PostgreSQL send/adoption boundary, unbatched and batched: **2 passed**.
- `git diff --check`: passed.

The original macOS PostgreSQL bootstrap failed because shared-memory IDs were
exhausted. Initial stock-container attempts could not reach the default guest
network/forwarded port. Both packet variants passed after a test-only transport
adaptation used a fresh stock PostgreSQL 18.3 container on the existing reachable
network. SQL migrations, assertions and the production guard were unchanged; the
fixture container was removed. This is targeted verification, not a full-suite
result.

The source was a dirty checkout based on `599bb80`, including concurrent workspace
trace edits preserved by this task. The corrected live pilot's SHA-256 for
`turn_stream.py`, `codex_worker_service.py`, `codex_runtime.py`, `interview_plan.py`
and `turn_progress.py`, concatenated in that order, was
`ad6a9b51c3a50576425aeca75b6b03c71420c911f39b749ebbc133e7b63dd82c`.

All disposable workers and temporary API processes were stopped; temporary
credential files were removed. Synthetic saved memoirs remain for readback.
The running API/worker settings were not changed or restarted, and the low
collector candidate remains disabled. No customer memoir was modified.
