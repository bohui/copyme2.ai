# Shared backend readiness for native Memoir

Audit and additive adapter implementation: 7 October 2026. Baseline: `662f356`.

This is a source-code and local-fixture register, not a production readiness or
live-device certificate. All paths below are relative to `/api/v1/memoir`.
Existing `/v1` paths continue to use the same handlers. Every new private route
uses the existing verified Supabase bearer boundary, explicit owner filters and
existing RLS tables. None uses `X-Account-Id`, `MemoryStore`, a service-role user
identity, a second turn ledger or a new migration.

## What this change supplies

### Guest transfer recovery retention

After a successful `POST /user/conversation-transfer`, the API now returns
`{"prepared": true, "expires_in": 3600}`. The addition occurs only when the
existing RPC returns the boolean `prepared: true`. Its original capability
token, project, message snapshot, retry behavior and attach transaction are
unchanged; the token is not echoed in the response. The duration matches the
checked-in prepare RPC's one-hour creation/refresh TTL in
`202610020001_guest_transfer_storage_owner.sql`.

`expires_in` is a conservative client retention cap for temporary secure
recovery state, not an authoritative expiry timestamp or promise that attach
will succeed. A client should apply a safety margin (the native client uses
60 seconds) and keep the same capability on an uncertain attach. Elapsed
request time, expiry, a previous claim and server validation can still reject
it. Server-side attach checks remain authoritative. No migration or additional
capability storage/read permission was introduced.

### Turn reconciliation

`GET /agent/turns/{client_turn_id}?project_id={project_id}` accepts a UUID and the
existing bounded project-ID syntax. Its typed OpenAPI response is:

```json
{
  "schema_version": 1,
  "client_turn_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "project_id": "project-a",
  "state": "conversation_saved",
  "conversation_saved": true,
  "server_turn_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  "source_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  "source_version": "1",
  "source_sequence": "3",
  "conversation_sequence": "1790000000000000123",
  "project_ordinal": "3",
  "narrator_text": "I lived near the river.",
  "reply": "What do you remember?",
  "source_status": "active",
  "source_processing_state": "pending",
  "enrichment_state": "unknown",
  "recall_status": {
    "rounds_completed": 4,
    "free_rounds": 20,
    "payment_required": false,
    "paid": false
  }
}
```

- `not_found` means no owned source or committed exchange was observed. It
  **does not** prove no request is running, that admission failed, or that a new
  turn ID is safe. The endpoint returns 200 with empty nullable fields for an
  unknown turn, including a turn owned by another user or project
- `source_accepted` means canonical narrator evidence exists, but no committed
  exchange was observed. Never label it as a saved assistant reply
- `conversation_saved` is backed by the existing `user_memory` record. Recovery
  does not generate, commit, increment quota or start a draft. `server_turn_id`
  is that record's durable ID, **not** the runtime stream's ephemeral `turn_id`
- `source_sequence` is the canonical narrator-source sequence;
  `conversation_sequence` is the existing memory ordering sequence. They are
  different clocks. Both, source versions and project ordinals remain decimal
  strings, including values outside JavaScript's safe integer range
- `project_ordinal` comes from `user_completed_round`. A greeting has no narrator
  source or completed-round ordinal, and its narrator text is null
- `source_processing_state` describes evidence extraction only. The durable
  tables do not expose complete place/family workspace completion by client turn
  ID, so `enrichment_state` is explicitly `unknown`. Refresh workspace snapshots
- Withdrawn sources expose neither narrator text nor assistant reply. A changed
  source exposes current text and suppresses the old assistant reply, including
  when a memory read raced with a correction
- Recall state is authoritative **current user-wide** state, not a frozen
  per-turn quota snapshot. Reads across tables are conservative snapshots, not a
  newly introduced atomic database transaction

A storage failure returns 503 with `TURN_RECEIPT_UNAVAILABLE`, retaining the
shared `error.code/message/retryable/request_id` envelope and `X-Request-ID`.
Provider bodies and credentials are not included in these new error messages.

### Canonical project discovery

`GET /user/projects?limit=50&after_project_id=project-a` returns:

```json
{
  "schema_version": 1,
  "items": [
    {
      "project_id": "project-b",
      "source_sequence": "3",
      "event_sequence": "2",
      "policy_epoch": "1"
    }
  ],
  "next_after_project_id": null
}
```

This reads `user_memoir_project`, which **already exists** in the shared-memory
migration and is created atomically by `accept_user_narrator_source`. It is not
another project index. Page sizes are 1–100, in ascending project-ID order.
Sequence/revision fields are strings. Project IDs are owner-scoped; identical
project IDs under two accounts are independent projects.

There is no canonical empty-project creation/title/mode/editorial-settings
mutation in this patch. A local new-project ID becomes discoverable after its
first accepted narrator source. Do not claim an empty local project has been
saved to the account. Legacy `POST /projects` remains an incompatible demo-store
boundary and is not a native persistence substitute.

### Paginated project history

`GET /user/projects/{project_id}/history?limit=50&cursor={opaque_cursor}` returns:

```json
{
  "schema_version": 1,
  "project_id": "project-a",
  "policy_epoch": "1",
  "items": [
    {
      "server_turn_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      "client_turn_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "kind": "agent",
      "created_at": "2026-10-07T05:00:00+00:00",
      "source_sequence": "3",
      "conversation_sequence": "1790000000000000123",
      "source_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      "source_version": "1",
      "source_status": "active",
      "narrator_text": "I lived near the river.",
      "reply": "What do you remember?"
    }
  ],
  "next_cursor": null
}
```

The first request gets the latest 50 committed exchanges, ascending within that
page. The next cursor fetches an older page using stable `(created_at,id)`
keyset pagination. This survives a newer insertion without shifting the older
page. Cursors are owner/project-bound seek hints, not authorization tokens;
changing their contents never bypasses the owner filter. Cross-owner or
cross-project cursors return 422 `INVALID_HISTORY_CURSOR`. Missing or unowned
canonical projects return the same 404. Storage failures return safe 503
`PROJECT_HISTORY_UNAVAILABLE` errors.

History includes both `agent` and `agent_greeting`, excludes unrelated notes,
and strips recognized legacy prompt wrappers. Greetings have null narrator
text. Where canonical evidence exists, it is authoritative for current text and
withdrawal status. Backfilled sources whose turn ID is a legacy memory ID are
also resolved. Source-accepted, uncommitted input remains a receipt concern,
not a falsely completed history item.

This is coarse snapshot refresh, not a change feed or full account export.
Refresh pages on foreground/re-authentication and after correction; do not use
the cursor to ignore tombstones or policy changes. `policy_epoch` identifies
policy/source-change invalidation but does not add a multi-request snapshot
transaction or frozen cursor. Old unassigned OAuth memories and guest-only
attachment records are still available through `/user/conversations`; silently
assigning them to a new native project would invent source ownership/history.
A reviewed backfill or explicitly read-only legacy archive is required.

### Source-linked draft inspection

`GET /user/projects/{project_id}/sources/{source_id}` reads the canonical
`user_narrator_source` by its UUID, with owner and project filters. It does not
require a Family timeline entitlement or confuse canonical narrator-source IDs
with the account-wide collection's conversation-memory IDs. The source's
foreign key binds it to the existing canonical owner/project. Successful shape:

```json
{
  "schema_version": 1,
  "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  "project_id": "project-a",
  "version": "1",
  "sequence": "3",
  "text": "I lived near the river.",
  "source_kind": "narrator_chat",
  "status": "active",
  "language": "en-AU",
  "created_at": "2026-10-07T05:00:00+00:00"
}
```

`source_kind` also permits `narrator_transcript`. Versions and sequences remain
exact decimal strings. This returns only the current active source. Missing or
unowned sources return 404. Withdrawn sources return 410 `SOURCE_WITHDRAWN`
without text. Supply `?expected_version={reference.version}` for a citation: a
changed version returns 409 `SOURCE_REVISION_CONFLICT` without disclosing the
replacement as if it were the evidence cited by an older draft. Omitting the
version explicitly reads current evidence. Storage failure returns safe 503
`SOURCE_UNAVAILABLE`. This endpoint does not disclose old revoked versions,
original attachment binaries or unrelated account sources.

### Authenticated historical photograph browsing

`GET /agent/places/{project_id}/photos` accepts the existing query parameters:
`place`, `period`, `latitude`, `longitude`, `cursor`, `refresh`. A coordinate pair
is required when either coordinate is supplied. It verifies the canonical
Supabase project first, then delegates to the **same `PhotoPages` instance and
`photo_response` worker transport** as the browser path.

JSON and `Accept: application/x-ndjson` retain the current public-photo shapes:
`items`, `count`, `target_count`, `search_center`, `shortfall`, `status`,
`searching`, `failures`, `next_cursor`. Failed delivery may return the established
minimal `{items: [], status: "UNAVAILABLE"}` representation. Preserve each item's
`source_url`, rights/allowed actions, date expression, requested period and
`search_fallback` labels (`none`, `gps`, `gps_time`). No v8 filtering, discovery,
deduplication or main-branch fallback logic was copied or changed.

Cursor ownership is `{verified user_id}:{project_id}`, so matching project IDs
in different accounts cannot reuse a private cursor. Public discovery/cache
may still be shared, as before. A project has to have an accepted source before
this canonical owner check succeeds. The existing `GET /user/profile` exposes
account-wide `memory_places`; that scope must remain visible in the native UI.

## Readiness register

“Adapter ready” means supported by code and local contract fixtures. Deployment,
real-database acceptance, native-device QA and release gates remain separate.
Owners below are responsible engineering/product roles, not assigned people.

| Experience                         | Canonical seam and persistence                                                                                                                   | Scope / retry or revision contract                                                  | Status and next owner                                                                                                |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Account and guest continuity       | Supabase identity; `/user/conversation-transfer`, `/attach`; durable transfer RPCs and private objects                                           | Verified identity and capability; same-token attach retry; quiesce pending workers  | Existing adapter; native auth/link/cancel/device acceptance required. Identity + native                              |
| Project list / resume              | New `/user/projects`, `/user/projects/{id}/history`; existing canonical project/source/memory tables                                             | RLS + explicit owner/project filters; typed keyset pages; exact sequence strings    | Adapter ready for source-backed projects; empty metadata/legacy assignment blocked. Backend + product                |
| Interview and greetings            | `/agent/turn`, `/agent/greeting`, new `/agent/turns/{id}`; atomic commit/round ledger                                                            | Stable client UUID, owner lease, committed replay; receipt is read-only             | Recovery adapter ready; full payload admission conflict contract remains blocked below. Backend                      |
| Dictation / speech                 | `/story/transcriptions`, `/story/question-audio`; current provider/storage path                                                                  | Bounded compatibility flow; current base64 request body                             | Foreground compatibility only; resumable binary media and asset-job API absent. Media + native                       |
| Live voice                         | `/realtime/calls`                                                                                                                                | Authenticated SDP; no persistent transcript/turn receipt                            | Gated; cannot claim saved voice conversation. Voice/backend                                                          |
| Life stages / collection           | `/story/readiness`, `/agent/collection/{project}`, `/organise`, `/agent/tasks/{id}`; canonical memories plus configured SQLite task queue        | Collection expected revision/fingerprint; sources intentionally account-wide        | Existing read/organise adapter; durable task DB operations and provenance acceptance required. Backend + product     |
| Places / historical photos         | `/agent/place-journey`, `/user/profile`, new `/agent/places/{project}/photos`; Supabase profile/place state, shared public photo worker/cache    | Verified owner project, owner+project cursor, existing v8 fallback and rights       | Adapter ready; map/group demo routes not ported. Native + photo QA                                                   |
| Personal sources                   | `/user/attachments`; Supabase private bucket                                                                                                     | Bearer-owned path; 50 MiB stream limit; no operation-ID upload dedupe/resume        | Small explicit compatibility upload only; source linking/resumable protocol blocked. Media                           |
| Family people / portraits          | `/agent/family-context`, `/agent/family-context/{project}/people/{person}/photo`; canonical Family document/private storage                      | Family entitlement, owner scope and expected revision                               | Existing adapter; native conflict/portrait acceptance required. Family/backend                                       |
| Timeline / corrections             | `/story/events`, `/story/events/{project}/{event}`; shared canonical events/source versions                                                      | Family entitlement; expected revision and correction statement                      | Existing adapter; event conflicts/uncertain-date UI required. Native + backend                                       |
| Private draft                      | `/story/private-draft`, `/story/private-draft/retry`, new `/user/projects/{project}/sources/{source}`; canonical composer lanes/source manifests | Source/policy/revision fencing; host-authorized checkpoint policy                   | Read adapter exists; worker readiness required. Do not invent storyteller opt-in. Product + backend                  |
| Preview / manuscripts              | `/story/preview`, `/story/preview/{job}`; canonical shared draft lanes                                                                           | Existing owner-scoped status/retry                                                  | Read-only canonical preview possible; generic chapters/edit/edition APIs remain legacy-gated. Editorial/backend      |
| Packages / purchases               | `/story/plans`, `/story/state`, `/story/checkout`, Stripe webhook; shared story entitlement                                                      | Server Stripe entitlement and idempotent webhook                                    | Display existing status only for native release; store receipt/restore/refund integration absent. Commerce + product |
| Finished books / print             | Legacy edition/artifact/print APIs                                                                                                               | Broad API presence is not durable fulfilment                                        | Gated pending durable owner/editorial/rights and real supplier integration. Editorial + commerce                     |
| Settings / privacy / collaboration | `/agent/profile`, `/user/profile`; Supabase profile; other consent/invite/export/delete paths mixed/legacy                                       | Profile writes leased, no general field revision CAS; no verified all-store erasure | Profile/locales readable; public release blocked on real deletion/export/consent/sharing. Privacy + backend          |

## Gates intentionally not papered over

1. **Whole-command idempotency and admission.** Existing narrator-source admission
   rejects changed text/kind. Current committed replay checks `user_memory`
   before validating changed input, and concurrent duplicate requests may do
   redundant model work before final commit deduplication. Language/prompt/full
   command identity is not durably hashed. A reviewed extension of the existing
   atomic admission/ledger transaction is required; this patch deliberately does
   not create a second hash/receipt store. Native must preserve its exact original
   command and ID and reconcile first; do not advertise exactly-once generation
2. **Project/editorial migration.** The existing canonical project table holds
   source/event counters and policy epoch, not all legacy title/mode/chapter,
   invitation or edition entities. A migration decision/backfill must preserve
   existing source/project IDs and ownership before exposing those mutations
3. **Enrichment and snapshot semantics.** A receipt confirms commit independently
   of workspace enrichment. A source may already be accepted on disconnect;
   stopping display is not server cancellation. Existing runtime source_sequence
   numeric fields remain backward-compatible; mobile must not sort unsafe
   numbers from old responses and should use exact recovery fields
4. **Privacy and media.** Resumable binary upload, attachment/historical-version source inspection,
   scoped data export, durable consent operations, and all-store account erasure
   remain missing or unverified. Private drafts keep the documented host policy;
   a user opt-in variant needs coordinated durable policy rollout
5. **Operations and commerce.** No deployment, migration application, production
   model call, store account, purchase or publication was made. Persisted worker
   recovery, availability, backups/restore, storefront rules and device evidence
   are still release requirements

## Verification

`tests/test_conversation_recovery_api.py` uses `httpx.MockTransport` behind the
real `UserStorage` query methods and a fresh authenticated storage client for
each request. It verifies owner/project filtering on every read, no mutation or
model/worker execution for receipts/history, accepted vs committed state,
repeated lost-response recovery, exact bigint values, greetings, source
correction/withdrawal, legacy source mapping, typed OpenAPI, safe errors,
pagination under newer insertion, timestamp ties, scoped/malformed cursors,
real no-token auth rejection, current-source inspection without Family entitlement,
stale citation conflicts, revoked/cross-owner source denial, and photo cursor isolation/provenance/streaming
through shared fixture-only search.

TDD evidence: the initial new recovery tests produced 19 failures / 1 pass
(missing routes); all 20 passed after implementation. The four photo adapter
tests likewise failed before the adapter and passed after. Follow-up contract
coverage extends these cases. Source-detail TDD produced 7 missing-route failures
and 2 non-disclosure passes before implementation. Existing route/storage/account-history/photo and
stream/transfer suites are run alongside them; final counts are recorded by the
implementation handoff.

The disposable PostgreSQL ownership/idempotency fixtures were attempted but
skipped because this executor lacks `initdb`, `pg_ctl` and `psql`. No customer
Supabase was substituted. A fresh HTTP client proves no new local state is
needed by this adapter; it is **not** evidence of a production restart/restore,
real RLS enforcement or two-physical-device acceptance. Run the existing
`test_shared_memory_events_postgres.py`, `test_private_rounds_postgres.py` and
`test_agent_commit_postgres.py` with the supported disposable PostgreSQL fixture
before beta, then perform isolated web/mobile same-account and two-account
smoke tests against the intended deployment.

## Generated schema drift gate

Run `python scripts/check_mobile_openapi.py` in the repository Python test
environment. Check mode never writes the snapshot. After reviewing a deliberate
API change and its paired runtime DTO/tests, regenerate with
`python scripts/check_mobile_openapi.py --write`.

`packages/contracts/openapi.snapshot.json` contains 36 selected canonical mobile
operations plus their transitive referenced schemas. It is generated from the
production router definitions without starting ASGI lifespans or calling any
storage, worker, network or provider. Documentation/order-only noise is removed;
route/schema removal, new required fields, enum narrowing and other contract
changes require explicit review. Unrelated legacy paths stay outside this
allowlist and their runtime handlers are unchanged. Existing loose dictionary
responses and NDJSON are not magically typed by OpenAPI: their runtime Zod and
transport fixtures remain required alongside this drift check.
