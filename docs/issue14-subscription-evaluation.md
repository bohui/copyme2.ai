# Separately bounded progressive subscription evaluation

This opt-in path implements the revised evaluation scope: two fixed synthetic
15-turn EN/CN conversations, one case and one client send at a time, at most 160
total client HTTP requests and an absolute 30-minute run deadline. Those numerical
bounds were approved for this evaluation. Smaller explicit bounds are supported;
larger ones are rejected by the session/launcher. No new provider/account/paid API
or credit purchase is part of this path.

The user removed the strict token-limit requirement and requested the existing
subscription route. This path does not assert a token, currency, subscription
headroom or actual-upstream-request bound. Gateway-internal retries are invisible;
closing a connection cannot prove already-running upstream work stopped. These
limitations are present in receipts, not inferred away by concurrency or timeout.

## Source components

- `issue14_subscription_transport.py`: one serialized client-to-LiteLLM request
  gate shared across all roles/cases/continuations. Each attempt reserves a
  durable journal entry before contact, is never refunded, and is fenced across
  restart. Error/cancellation/missing journal/deadline permanently stops further
  client sends. Every continuation counts even when request metadata repeats.
  Outgoing requests are privately frozen, without caller extensions, transport
  retries, redirects, ambient proxies or persistent keepalive. Response bytes and
  the whole operation are bounded; these are resource limits, not token caps.
- `issue14_subscription_session.py`: task-owned loopback forwarding endpoint,
  normal application runtime/worker graph and a single-slot Temporal worker.
  Every role uses the same forwarding seam. Trusted worker-boundary metadata
  connects collector, timeline, composer phases and background activity IDs to
  the active round. Other owners/projects/models/modalities are rejected.
  A task-owned scoped broker orders extraction before composition, independent
  of PostgreSQL JSON key order, and rejects foreign receipts/lanes.
- `issue14_subscription_runner.py`: separate explicit `subscription_progressive`
  mode. It awaits actual original-source extraction and saved drafts at 5/10/15,
  drains bookkeeping, fails on unsettled/failed state, and retains partial saved
  evidence with null experiment outputs on failure. It does not call the old
  driver with a fake mode or alter its five-turn live guard.
- `run_issue14_subscription_evaluation.py`: default plan-only command; explicit
  execution bootstraps only the disposable Mac Postgres/Temporal fixture. It
  requires an exact clean reviewed Git HEAD, pinned existing Codex/Temporal
  executables, a cached stock PostgreSQL image and the existing application
  gateway credential inherited privately. There is no credential argument,
  credential discovery, automatic install, shared-service restart or production
  migration. Plans and logs omit credentials and provider exception bodies.
  Source verification rejects hidden Git index flags and independently hashes
  every tracked blob. It does not rely on a clean `git status` alone.

The fixed client route is `http://192.168.66.1:4000/v1/responses`.
Collector/workspace/context use the existing `gpt-5.6-luna-pooled` alias with max
effort; timeline/composer use `memoir-luna-low` with low effort. These are client
aliases, not independently proven wire-model/billing identities. Task-local Codex
retry/stream retry and websocket settings are disabled; shared configuration is
unchanged. Private task homes never migrate an inherited customer home.

## Native handoff

The exact independently reviewed source commit must be checked out cleanly. Run
the plan command first, specifying run UUID, source revision, fresh output path
outside the checkout, existing Codex/Temporal absolute paths and SHA-256 pins,
`--max-client-requests 160`, and `--max-elapsed-seconds 1800`. It has no provider
contact or resource allocation. Only the separately authorized one-shot Mac
process may add `--execute-existing-subscription`.

The existing application environment must privately supply
`MEMORY_SPARK_LLM_BASE_URL` and `MEMORY_SPARK_LLM_API_KEY`. No key belongs in chat,
argv, Git, a receipt or a handoff artifact. Missing private inheritance is a
specific setup blocker; the launcher does not invent an alternative credential.
It checks any supplied model/effort configuration against the existing profiles.
Alternatively, the authorized one-shot process can receive the verified existing
file path using `--existing-app-env`. The loader accepts only an owner-owned
regular file with mode 0400/0600, parses without shell expansion or interpolation,
and imports only the provider configuration allowlist. Plan-only never reads it.
The file and credential are never rewritten or copied into receipts.

The native fixture uses actual temporary PostgreSQL RPCs and actual loopback
Temporal, with the existing synthetic `PostgresRest` REST/auth/entitlement facade.
Distinct synthetic owner/project UUIDs and default-free entitlement are used.
This is not production authentication/RLS coverage. Only the recorded UUID
container, task SQLite files, worker homes and loopback listeners are owned;
cleanup never searches for or stops unrelated services.
The existing pressure-level-1 gate and exclusive native heavy-resource lease
remain in force. An existing or unverified UUID-container name prevents allocation.
The unchanged fixture's process adapter is narrowly fenced for this one-shot
process: only a confirmed successful create permits one stop attempt. Failed or
uncertain creation never authorizes stopping a possibly pre-existing container;
uncertainty is retained for explicit reconciliation.
The isolated Mac process uses the application's existing
`MEMORY_SPARK_DISABLE_PRIVDROP=1` fixture option; no Linux setpriv/chown identity
is introduced on macOS, and no shared OS/service setting is changed. Sanitized
task model/effort variables match the wire-client aliases so saved composer
fingerprints do not silently describe a different model.

Retain `plan.json`, `receipt.json`, the content-free reservation journal and the
saved checkpoint readbacks. An incomplete/cancelled/capped run is not resumable or
automatically restarted under a different UUID. Native exit/cleanup evidence must
be inspected before any separately authorized retry.
The local receipt is atomically updated after completed rounds. Any enclosing
native cleanup failure invalidates experiment outputs even if all turns finished.

## Acceptance boundaries

Source and synthetic-loopback tests do not prove a native evaluation occurred.
The result preserves actual saved outcomes when execution is authorized, but
the readback bridge still labels its provenance and semantic limits explicitly.
Human review covers factual entailment, transitions, chronology and language.
Chapter-wide word limits, original event entailment and bilingual matching
provider/reasoning cohorts require their full application evidence.

No judge, photo, geocoding request, Langfuse upload or evaluation-rule activation
is enabled here. The four managed rules remain disabled. Raw outcomes can be
reviewed locally; dataset experiment publication is a separate explicit step.

The historical strict Issue 14 budget adapters/receipts/source inventory remain
unchanged and their unfulfilled ACs remain open. Source contract v3 separately
checks the reviewed current runtime, native fixtures, dataset, skills and SQL,
while v1/v2 tests use verified immutable historical evidence. See
`issue14-source-contract-v3.md`. A passing source gate is not a native execution
receipt or semantic acceptance; exact-head review and applicable checks still
apply before merge and the native resource preflight still applies before a run.
