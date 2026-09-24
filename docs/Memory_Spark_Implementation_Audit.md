# Memory Spark implementation audit

This audit describes the local deterministic cell implemented in this repository. It is evidence for the functional prototype and does not claim that a credential-free local process satisfies production launch gates.

## Current evidence

- The source `docs/Memory_Spark_Full_Specification_v1.0.docx` contains 63 normative resource routes and 55 acceptance cases. `scripts/audit_spec_routes.py` reads that source directly through Pandoc, and also accepts the checked-in Markdown extraction when a host does not have Pandoc.
- The route audit parses section 19.2 of the full specification and checks the FastAPI route table. It currently reports all 63 normative routes represented by 117 application routes, including the documented authentication, interview, media, context, evidence, manuscript, commerce, publication, export, fulfilment, deletion, event, and audio boundaries.
- The Python suite currently has 101 tests, including one named regression test for each of the 55 document acceptance cases in `tests/test_full_acceptance.py`. `scripts/run_acceptance_evidence.py` runs AT-001 through AT-055 and writes the case-by-case result to `docs/Memory_Spark_Acceptance_Evidence.md`. The remaining suite covers the original journey, project isolation, invitations, consent, resumable uploads, cue provenance, trial accounting, sponsored checkout, revision conflicts, policy epochs, cursor pagination, creation and payment idempotency, edition hashes, print proof invalidation, deletion tombstones, provider switches, support-grant scope, restart recovery, browser authentication cookies, CSRF protection, filesystem object separation, outbox lease/ack recovery, deterministic artifacts, backup/restore validation, worker completion and safe workflow failure, and the documented contract routes.
- `make container-up` starts only the API, Supabase-backed worker, web shell, and Codex harness with Apple Container through Mocker. The API and worker use the Supabase PostgreSQL connection in `SUPABASE_DB_URL` for canonical state and the durable outbox; private filesystem objects remain below `var/memory-spark/objects`. There is no local application PostgreSQL or Temporal service in the Compose stack. `make supabase-db-check` verifies state reload, object bytes, outbox lease/ack and job completion against the configured Supabase database. The in-memory and atomic JSON adapters remain available only for explicit tests and backup/restore rehearsal. `make persistence-check` verifies the test-only adapter, and `make outbox-check` exercises the configured Supabase lease/ack boundary. `make container-health` checks API health, the Supabase storage mode, static web delivery, web-to-API routing, and a real `codex exec-server` JSON-RPC process session. `make harness-check` runs the named acceptance evidence, the complete Python suite, and route audit inside that Codex exec-server.

## Runtime implementation boundary

The runtime app and worker use the `PostgresMemoryStore` adapter against the
Supabase database selected by `SUPABASE_DB_URL`; local Supabase and hosted
Supabase are both supported. The in-memory and atomic JSON `MemoryStore`
adapters are limited to tests and explicit backup/restore rehearsal. The
following specification items remain operational or production-adapter gates
rather than claims of completion by this deterministic implementation:

- Normalized PostgreSQL data dictionary/RLS policies, managed object-storage service durability, production key recovery, and measured RPO/RTO. The current cell provides a Supabase PostgreSQL transactional state boundary with row locking, a separate outbox table, filesystem object keys, complete JSON metadata/blob backup and restore, and a lease/ack dispatcher boundary for job recovery. An optional Temporal worker path remains available in code but is not started by the default container stack.
- Real regional identity, payment, ASR/OCR, context-provider, renderer, email/SMS, and supplier integrations.
- Staff MFA, key management, encryption at rest, live rate limiting, device matrix coverage, assistive-technology review, load targets, and legal/processor activation decisions.
- Real provider latency, availability, device recording, print production, and cross-region transfer evidence required by AT-012 and AT-053 through AT-055.

Those boundaries are surfaced in the API and README as demo-provider or operations decisions; they are not hidden behind a claim that the local mock is production-ready.
