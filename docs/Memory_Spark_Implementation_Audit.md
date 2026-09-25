# Memory Spark implementation audit

This audit describes the local deterministic cell implemented in this repository. It is evidence for the functional prototype and does not claim that a credential-free local process satisfies production launch gates.

## Current evidence

- The source `docs/Memory_Spark_Full_Specification_v1.0.docx` contains 63 normative resource routes and 55 acceptance cases. `scripts/audit_spec_routes.py` reads that source directly through Pandoc, and also accepts the checked-in Markdown extraction when a host does not have Pandoc.
- The route audit parses section 19.2 of the full specification and checks the FastAPI route table. It currently reports all 63 normative routes represented by 117 application routes, including the documented authentication, interview, media, context, evidence, manuscript, commerce, publication, export, fulfilment, deletion, event, and audio boundaries.
- The Python suite currently has 101 tests, including one named regression test for each of the 55 document acceptance cases in `tests/test_full_acceptance.py`. `scripts/run_acceptance_evidence.py` runs AT-001 through AT-055 and writes the case-by-case result to `docs/Memory_Spark_Acceptance_Evidence.md`. The remaining suite covers the original journey, project isolation, invitations, consent, resumable uploads, cue provenance, trial accounting, sponsored checkout, revision conflicts, policy epochs, cursor pagination, creation and payment idempotency, edition hashes, print proof invalidation, deletion tombstones, provider switches, support-grant scope, restart recovery, browser authentication cookies, CSRF protection, filesystem object separation, outbox lease/ack recovery, deterministic artifacts, backup/restore validation, worker completion and safe workflow failure, and the documented contract routes.
- `make container-up` starts the API, private per-user Codex worker, local legacy worker, web shell, and Codex harness with Apple Container through Mocker. The connected story flow uses Supabase Auth, RLS-protected `user_profile`/`user_memory` rows, private Storage, and renewable cross-replica Codex turn leases; it does not use an application-owned Postgres state row or outbox. `make persistence-check` verifies the explicit local adapter. `make container-health` checks API health, the Supabase user-memory storage mode, static web delivery, web-to-API routing, and a real `codex exec-server` JSON-RPC process session. `make harness-check` runs the named acceptance evidence, the complete Python suite, and route audit inside that Codex exec-server.

## Runtime implementation boundary

The connected story runtime uses the authenticated Supabase user-data boundary;
the in-memory and atomic JSON `MemoryStore` adapters remain only for the
legacy specification routes, tests, and explicit backup/restore rehearsal. The
following specification items remain operational or production-adapter gates
rather than claims of completion by this deterministic implementation:

- Normalized product tables beyond the current user-profile/user-memory prototype, managed object-storage service durability, production key recovery, and measured RPO/RTO. The current cell uses Supabase RLS for user-owned records and keeps the legacy project adapter local. An optional Temporal worker path remains available for that retired adapter but is not started by the default container stack.
- Real regional identity, payment, ASR/OCR, context-provider, renderer, email/SMS, and supplier integrations.
- Staff MFA, key management, encryption at rest, live rate limiting, device matrix coverage, assistive-technology review, load targets, and legal/processor activation decisions.
- Real provider latency, availability, device recording, print production, and cross-region transfer evidence required by AT-012 and AT-053 through AT-055.

Those boundaries are surfaced in the API and README as demo-provider or operations decisions; they are not hidden behind a claim that the local mock is production-ready.
