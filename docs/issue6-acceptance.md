# Issue 6 acceptance and verification

Source: https://github.com/bohui/copyme2.ai/issues/6, read in full with all comments on 2026-10-04 (updated 2026-10-04T01:07:30Z; no comments). All 56 user stories and the Implementation/Testing Decisions remain requirements. This matrix records planned behavioral coverage, not passing results.

## Dependency and isolation

This branch is stacked on PR 3's reviewed committed head `d8ef614c0af4a15b41d6cc9b1ed1b1cc9ef35198`. It requires its completed-round ledger, transactional draft outbox, receipt-scoped broker snapshot, and stage-aware commit RPC. PR 3 must land or be reviewed as a dependency; a changed base requires rebase and renewed review. No PR 3 merge is part of this task.

Checkout: `/tmp/memoir-issue6`, branch `codex/issue6-shared-events`. The dirty primary checkout and PR 5 are excluded. New migrations will be additive, following parent coordination; initial schema and PR 3 migrations will not be rewritten. No production/customer database, shared container services, public deployment, new credentials, or payment is involved.

## Agreed seams and TDD

The issue itself agrees three seams, satisfying `/Users/bohuihan/.agents/skills/tdd/SKILL.md`'s seam agreement rule:

1. Authenticated story workflow: accept narrator input, deliver or fail its reply, drive the existing background worker, read/edit canonical events, read saved private draft.
2. Shared application service/RPC and migration boundary on real disposable PostgreSQL: transactions, RLS, expected revisions, outbox, links, migration replay, transfer.
3. Browser workspace: event tag editing, reload, coverage/updating/retry display, premium visibility.

External model responses and clocks may be controlled. Internal application validation, dispatch, storage, dependencies, and rendering are exercised together. Controlled provider outcomes are labelled; skipped/unavailable checks are never passes. Each vertical slice adds a failing observable test, implements only that behavior, then reruns it. Mapping precedes implementation, while executable tests are added one slice at a time.

## Story-to-scenario map

| Stories | Observable scenario | Seam |
| --- | --- | --- |
| 1, 2 | Accepted narration creates durable processing work; an acknowledgement yields no events but completes processing. | Story + PostgreSQL |
| 3, 8, 9, 11 | One reply creates separate canonical events in supported stages/years; undated/unplaced facts remain saved. | Story |
| 4, 5, 43 | Several replies enrich the same canonical event; a late detail updates its older dependent section and timeline uses the same ID. | Story |
| 6, 7 | Similar wording/year/place alone never merges distinct events; ambiguous candidate matches remain unresolved. | Story |
| 10, 12, 13 | Explicit/approximate/age/range/unknown placement keeps expressions and basis; a long interval remains one period. | Story + PostgreSQL |
| 14, 15, 16, 17, 28, 44 | Authorised stage/year correction preserves ID, increments revision, dirties both groups, and survives delayed extraction; stale edits conflict. | Story + PostgreSQL + browser |
| 18, 19 | Competing accounts retain attribution and exact original source versions/spans; generated prose never becomes testimony. | Story |
| 20 | Closing/reloading returns canonical events and persisted drafts from authorised records. | PostgreSQL + browser |
| 21, 47 | Delayed bounded partition preparation leaves conversation usable and respects concurrency limit. | Story worker |
| 22, 23, 24, 25, 37 | Before/at five and ten rounds and nondefault cadence; retries/failed replies/edits/greetings/jobs do not count; allowance twenty remains independent; no purchase/formal-book side effects. | Story + PostgreSQL |
| 26, 34 | Overlap with unchanged evidence preserves exact section bytes/revisions; coherent assembly and word ceiling remain enforced. | Story composer |
| 27, 48 | Source edits/link removals/deletion/revocation immediately invalidate dependencies; surviving evidence rebuilds; incompatible late output is rejected. | Story + PostgreSQL |
| 29 | Required extraction gap keeps milestone pending, including out-of-order completion; snapshot/coverage labels reflect settled inputs. | Story worker |
| 30, 31, 32 | Eligible saved draft is immediately available during update; coverage, progress and safe retry state are visible; failed review never becomes ready. | Story + browser |
| 33 | Human-edited/approved/locked text is retained and affected changes become a proposal tied to its base revision. | Story composer |
| 35, 36 | Chinese, English, and transcribed voice share the event contract; source language is retained independently of output locale. | Story |
| 38, 39, 40 | Explicit relationship and relevant established-relative correction update tree; unrelated narration leaves it unchanged. | Story |
| 41 | Event/source/project references and unauthorised edits are rejected; non-Family internal indexing grants no premium display/tree access. | Story + PostgreSQL + browser |
| 42 | Capability-authorised guest transfer preserves event/source/cursor/manuscript identity; replay adds no rounds/intents/milestones. | PostgreSQL + story |
| 45 | Accepted-source/outbox atomicity survives disconnect/restart/replay without repeat testimony; cursors only advance on committed success. | PostgreSQL + worker |
| 46 | Failed preparation/render/review retry reuses successful fingerprinted tasks and preserves manuscript revision fencing. | Story worker |
| 49 | Replayable migration preserves legacy IDs/aliases, provenance, privacy/print flags, original sources/person links and manuscript references; ambiguous matches remain unresolved. | PostgreSQL migration |
| 50 | Assertions use agreed public seams and durable outcomes, with provider-only response control. | All |
| 51, 52 | While one lane run is held, milestones ten/fifteen/twenty and intervening inputs coalesce; exactly one catch-up uses latest claim-time target in each lane. | Existing worker + PostgreSQL |
| 53 | Failed six-through-ten attempt after saved five remains pending; next run through twenty includes six-through-twenty without duplicated committed work. | Worker |
| 54 | Durable narrator acceptance survives failed assistant delivery; retry reuses source/input identity while completed-round allowance is unchanged. | Story + PostgreSQL |
| 55, 56 | Controlled deadline/lease expiry fences a stalled/crashed worker; replacement becomes eligible without a new user turn; late completion cannot overwrite it. | Worker + PostgreSQL + Temporal |

## Required verification record

Record exact commands/results and environment identity for each completed slice. Real PostgreSQL migration/transaction checks and real Temporal/outbox/recovery/browser integration are required where feasible. Provider simulation is not live semantic verification. Remaining environment limits must remain explicit blockers, not silently skipped acceptance criteria.

Baseline on isolated pinned PR 3: `python3 -m pytest -q tests/test_private_rounds_postgres.py` under reviewed isolated execution: **7 passed**, real disposable PostgreSQL, 2026-10-04. Approved execution resolves the sandbox shared-memory restriction without modifying shared services.
