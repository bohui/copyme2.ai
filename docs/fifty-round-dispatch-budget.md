# Synthetic fifty-input dispatch accounting

`scripts/fifty_round_dispatch_budget.py` provides accounting transitions for the
separate fifty-input adapter. It has no transport, application, authentication,
native service, database, or provider dependency. Its tickets never grant
permission to dispatch. All receipts say `evidence_mode: synthetic`,
`live_execution_authorized: false`, `native_boundary_verified: false`, and
`actual_provider_requests: null`. A simulated contact count cannot establish
zero actual provider use or any other real provider count.

This slice starts at merged PR29 main
`b8dee2d84ac01fb374dc41c112dbef121ba4039c` (tree
`43f38181ca57d8a3bc2c452fc98f1600843590ef`). It leaves the passive proposal and
legacy 80-send/900-second/60-second actor and guard unchanged. The proposed
600-send/7,200-second envelope remains unapproved. No token or monetary limit is
implemented or inferred.

## API and ownership

`CampaignDispatchBudget.create(reservation_root=..., proposal=..., scope=...)`
validates the exact unapproved proposal and creates one exclusive journal named
`<run_id>.jsonl` in an existing task-owned registry directory. It records the
scope, proposed stops, and stage caps before returning. A pre-existing file,
including a closed, empty, or interrupted reservation, blocks creation. There is
no reopening, deserialization, recovery, or reset API. The owner must use one
fixed registry root and ledger for the whole campaign; a different directory is
a different registry and is not a supported way to resume a campaign. This is
not a machine-wide or multi-host approval registry.

Scope contains exactly `run_id`, `case_id`, `owner_id`, `project_id`,
`source_revision`, `source_tree`, `source_sha256`, `account_binding`, and `roles`.
Every known stage has a role entry with `model_alias`, `wire_model`, and
`reasoning`. These declarations must preserve the proposal's per-role alias and
reasoning policy. Source/account/model comparisons establish consistency of
synthetic metadata only; they do not verify installed source, credentials, alias
resolution, account ownership, or a real send boundary.

The flow is:

1. `begin_worker(WorkerKey(...), correlation=...)` reserves a stage slot and
   returns an opaque worker ticket
2. `reserve_send(worker_ticket, continuation_ordinal=...,
   observed_scope=...)` reserves a global send slot and returns an opaque send
   ticket; the first continuation is 1 and subsequent ones must be consecutive
3. `mark_started(send_ticket)` records one synthetic fixture contact
4. `settle(send_ticket, completion)` requires exactly `response_id`,
   `wire_model`, `input_tokens`, and `output_tokens`; the ID must be unique,
   model must match, and usage must contain nonnegative literal integers
5. Repeat steps 2–4 for any tool continuations, then
   `finish_worker(worker_ticket)` closes that logical worker operation
6. `stop(reason)` fences future reservations; `close()` fences and closes the
   journal; `receipt()` returns an independent snapshot

`declared_send_scope(worker_ticket)` exposes the expected synthetic metadata for
fixture construction. It is not an observation or authorization. `ledger.deadline`
and `send_ticket.deadline` expose monotonic deadlines for the synthetic adapter's
bounded waits. The latter is the smaller of the whole-run deadline and the
request deadline measured from reservation.

## Keys, repairs, and counters

`WorkerKey(stage, round_number, checkpoint_round=None, preparation_id=None,
attempt=1)` uses only structured identity fields. Trace/job/request correlation
IDs cannot change the logical identity or permit replay. The adapter classifies
stage from structured worker payload fields, never prompt text.

- Ordinary stages bind one round in 1–50; locale is restricted to round 1
- Composer preparation/draft/review bind a checkpoint at 5, 10, ..., 50, with
  `round_number == checkpoint_round`
- Preparation requires its 64-hex fingerprint, which already includes
  event/configuration/policy/base data in the canonical composer. Reuse of this
  fingerprint anywhere in the campaign is refused, even at another checkpoint
- Family/draft/review attempts may advance consecutively from 1 to 3. All other
  stages permit only attempt 1. Every semantic repair consumes another worker
  slot; every continuation consumes another global send slot

One active worker and one active send are permitted. Stage and preparation caps
are independent of the shared send cap. Counters never decrement or refund after
failure, cancellation, deadline, unknown usage, or shutdown. Reservation count,
fixture-started contacts, valid synthetic completions, and unsettled reservations
are distinct receipt fields. Synthetic token totals are reporting only.

## Failure, persistence, and cleanup

Scope mismatch, malformed or duplicate identities, unsupported stages, exhausted
caps, nonfinite/backward time, elapsed deadlines, invalid completion or unknown
usage permanently fence the campaign. `fail(ticket, reason)` and `stop(reason)`
accept only fixed content-free reasons such as `quota`, `provider_error`,
`cancelled`, and `usage_unknown`. Model responses, prompts, secrets, and arbitrary
exception messages are neither accepted as evidence nor written to the journal.

The journal uses exclusive non-following creation, private new-file mode,
complete writes, and fsync before returning reservation tickets. Creation also
fsyncs the registry directory before returning so the new reservation name is
durable. Write/fsync failure, including cancellation or interruption, is sticky,
prevents later reservations, and never releases a consumed slot. Cancellation
and interruption are re-raised after the fence is set. Separate processes cannot
acquire the same reservation. Forked copies
cannot operate the parent's ledger; threaded transitions are serialized.

`close()` does not await, cancel, drain, or verify any application or transport
operation. It fences first, records pending work as uncertain, and attempts to
close its descriptor even if the final journal write fails. It performs ordinary
filesystem writes, not a timed asynchronous cleanup. The adapter separately owns
bounded cancellation/drain and resource evidence. Deadlines are checked at
transitions; this ledger has no timer that can interrupt an outstanding send.
Those limitations must remain visible in any future real adapter review.

## Validation and remaining gates

The synthetic tests exercise separate-process reservation conflicts, forked
ownership, threaded contention, preparation replay, repairs, global/stage caps,
scope/type mismatches, unknown usage, cancellation, deadlines, duplicate
settlement, partial/failed journal writes, and cleanup uncertainty. No provider,
native application service, credential, or database is used.

Real use remains blocked pending numerical approval, exact-source review,
verified per-role native configuration and single-account consumer binding,
security and resource checks, an actual upstream reservation/settlement hook,
and bounded transport cancellation plus independently verified accounting and
process exit. Constructing this ledger, receiving a ticket, supplying JSON,
calling `mark_started`, or setting an external readiness flag satisfies none of
those gates. Broader #14 quality, judge calibration, variant, token, and cost
acceptance remains open.
