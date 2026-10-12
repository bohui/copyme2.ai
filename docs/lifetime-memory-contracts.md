# Lifetime memory: W0 contracts and migration boundary

Issue #60 implementation baseline: cc068523208842e2accde8d623a060a04143e78c.
This document is an implementation plan, not evidence of completed W1–W6 or production rollout.

## Authority and transport

The owner/product unique database conversation maps explicitly to an original project.
The browser, execution thread, checkpoint, and generated profile cannot choose this mapping.
Identity v1 carries owner, conversation, product and original project; evidence IDs are unchanged.
Execution fence v1 carries identity, policy epoch, source revision, execution generation,
phase revision, preference revision and the existing renewable lease token. Publication checks
all of these against current database state, under the same ordering lock as correction.
No generated projection is personal testimony. Claims retain exact original source/version/span,
asserted/inferred status, uncertainty, time meaning, use permission and contradiction/correction
edges; translations are attributed separate fields. Existing canonical event infrastructure remains authoritative.
Receipts retain source-accepted versus conversation-saved and client-turn identity; maintenance
never modifies commercial rounds, billing, or draft eligibility.

Context budget v1 declares a model, finite window, finite input allowance and output headroom.
The initial offline counter uses serialized UTF-8 bytes as a conservative ordinary byte-level
text-token bound; all instructions and metadata are included and framing has a declared 1,024-token default headroom. Only byte-level tokenizer-compatible models may use this counter; provider integration must validate that compatibility.
This is a deterministic fixture bound, not a quality/latency/cost SLA or a production model default.

## Phase adapter agreed with #59

Transport conversation_phase v1 unchanged:
{schema_version:1, phase:comfort|explore|shape, selection:automatic|explicit,
preferred_phase:null|comfort|explore|shape, paused:boolean, revision:integer>=0,
reason:phase-owner-defined enum, source_turn_id:null|UUID}.
#59 owns validation and behavior. Memory does not infer phase, reset an absent phase,
convert explicit to automatic, or reconstruct preferences from summaries. Pinned state,
checkpoint publication, identity mappings, guest transfer and cold resume preserve both
phase and preference revisions; stale automatic work cannot overwrite newer explicit intent.

## Read/write inventory and obligations

- agent_routes / conversation_recovery: authenticated entry, accepted-versus-saved receipts,
  retry/readback. Resolve canonical identity before accepting arbitrary project arguments.
- agent_storage / SQL acceptance and edit RPCs: original sources/versions, source sequences,
  ordered events, project policy epoch, source processing outbox. These remain required.
- codex_runtime / codex_worker_service / interview_plan: execution context, thread selection,
  recent memory and full collection views. Replace lifetime injection with one bounded builder.
- user_agent_turn_lease / fenced commit: cross-replica lease remains the commit authority;
  thread pointer installation belongs to that same fenced transaction.
- extraction / canonical composer / interview question pool: required canonical processing
  retains durable outbox; dependent projections use source/epoch fences before publication.
- task_queue / profile / photos / news: optional reconstructible enrichment; failures are visible
  and cannot retract an already saved conversation receipt or become testimony.
- codex_artifacts / artifact-link retry: optional accelerator, tenant-scoped incremental manifests;
  never required for canonical recovery or reported as a complete backup when incomplete.
- realtime_routes session_config/create_call: separate direct WebRTC context channel currently
  consumes profile/user-wide recent memory. Govern or exclude prior personal context until
  revocable; a collector-only fence is not a product-wide privacy guarantee.

## Read-only inventory and proposed migration

Run `python scripts/lifetime_memory_inventory.py --input EXPLICIT_FIXTURE.json`.
Input is an array of owner_id, projects, source_ids, turn_ids, project-scoped evidence [{project_id,source_id,client_turn_id}], thread_pointer and optional
conversation_phase/preference_revision. The script has no database/network access and no default
production source. It returns collisions, untouched IDs/pointers and mapping_required for any
existing project, including a sole project; it never chooses newest/largest/current-looking.
Zero-project new-account creation may proceed atomically. Existing mapping requires an explicit,
inventory-backed reviewed mapping. Multi-project history stays in its scoped legacy adapter,
unchanged. Proposed SQL is additive and will be tested only in isolated synthetic PostgreSQL.

## Compatibility and rollback

Start disabled; legacy routes keep original project/source/turn IDs. Never hide a backfill in
startup or migration. Turning off governed execution must not lose newly accepted evidence:
canonical sources/receipts remain readable via paginated adapters; disposable projections can be
ignored. Keep additive identity/mapping rows and accepted evidence during rollback. Do not drop
new canonical tables or revert schema destructively. Historical mapping reversal requires its
approved mapping log and readback test, not ID rewriting. Features whose privacy depends on
governed context must fail closed rather than fall back to unsafe full-history prompts.

Production migration/backfill/activation, historical reassignment, retention deletion, paid model
calls and real-data evaluations require separate approval. Retention/GC is a proposal only;
withdrawal invalidates future use without claiming historical backup erasure. Synthetic semantic,
English/Chinese rare-fact/ambiguous-name/correction/abstention evaluation precedes any separately
approved live provider/spend-ceiling trial. Record queue/retrieval/model timings independently.
