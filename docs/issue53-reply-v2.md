# Small foreground replies and background continuity

`MEMORY_SPARK_COLLECTOR_PROMPT_VERSION=reply-v2` is an opt-in server setting.
It requires `MEMOIR_TWO_LANES=1` and the database's separately approved two-lane
rollout. Strategy can be disabled, shadow or active; all use the same small
response instructions. The existing default and rollback contracts remain
`compact-v1` and `two-lane-v1`. API and worker must run matching code.

The baseline's active English comfort instructions contain 22,412 Unicode
characters, before the separate dispatch, schema and context. The new response
instructions plus dispatch total 1,986 characters and are checked against a
strict 2,000-character limit.
This is not a token count or a promise that original narration fits in 2k.
The source-only privacy review remains a separate foreground model request.
Repair additions, schemas, data and native retries must be measured separately.
For example, the no-photo/no-queued-question schema is 1,453 compact JSON
characters before adding any evidence or dialogue.

## Foreground contract

The model returns acknowledgement, question, reason, a supplied hint index or
null, an exact unique current-source quote or null, and the semantic `work` hint.
Exact queued-question resolutions are offered only when their evidence exists.
Indexed hints use the same eligibility rules as the active strategy transaction;
other queued questions retain their text for answer-backed retirement without
becoming selectable. Historical-news acknowledgements keep their existing exact
schema choices. Photo fields appear only when authorized photos are available,
and preserve the existing narrator-evidence association validation and save path.
The host binds source identities, versions and hint IDs and converts the typed
proposal into the existing complete validated reply/plan. Unexpected fields,
foreign names, fabricated/ambiguous quotes and inconsistent no-question intent
are rejected. An explicitly stated current narrator name can be committed
immediately even when the same message adds story facts; existing manual-name
authority still applies. The saved name update participates in replay identity.
Language selection stays in its existing immediate host-owned path. Policy-ready
saved replies replay without resolving later generation settings. New reply-v2
generation rejects missing two-lane configuration before accepting narration;
JSON failures return the controlled configuration error and streams terminate
with their existing safe error event.

The worker validates the complete governed packet before projecting its model
input. The projection retains current original testimony, the complete uncovered
tail, pinned controls and authorized retrieved originals. Its conversation brief
uses the accepted B summary with its coverage watermark and original-source
references, actual delivered-question context and current authorized hints.
The underlying checkpoint/manifest, source-version, policy and publication checks
remain authoritative. A missing summary never creates fictitious coverage or
discards the raw tail. The trace records the projected input's hash separately.

## Durable background handoff

The reply transaction records `reply-v2` as its execution contract. The existing
timeline lane is already durably woken by source acceptance; its page exposes
the new contract only after the matching reply is saved. The foreground work
hint remains until a separate, tested replacement owns B admission. A pending
decision still yields; a pure greeting/stop keeps the no-model `reply_only` path.
Stops after new story facts retain extraction work.

For saved `reply-v2` sources, the existing B extraction call also proposes
bounded people, unresolved references and commitments. It never proposes
privacy controls, names, language or permissions. Validation binds exact evidence
to the admitted original window, resolving only explicitly null unique spans;
incorrect explicit spans and omitted required offset fields are rejected.

The canonical page transaction validates these rows, commits the existing
extraction/hints and then writes continuity without changing the model's input
digest during validation. All steps roll back together on failure. Its receipt
binds the complete result, including continuity, so a changed replay cannot
drop or replace proposals. Existing lane ownership, source/policy checks and
current manual authority still apply. A source correction or withdrawal fences
the stale page. Selective summaries and future plans reuse existing B work;
there is no new foreground or brief-writing model request.

## Publication and acceptance

The new managed prompt sources are interviewer `reply` and author-timeline
`continuity`, plus an update to the existing governed repair-code prompt. They
require source review on main and genuine Langfuse publication
and pin checks before live use. Offline tests read draft sources through the
existing controlled test fixture; they do not establish published versions or
live quality. Do not enable the candidate simply because the byte/character or
mocked contracts pass.

Acceptance must compare actual bilingual opening, later and genuinely resumed
responses at fixed route/effort settings, including long narration, corrections,
stop/privacy intent, sibling ages, image-viewing roles and queued confirmations.
Run B concurrently and verify delayed/retried work, eventual continuity/summary
state, strict evidence, replay and next-turn correctness. Keep first meaningful
text, validated question, completion/save/unlock, all failures and B lag distinct.
The target remains meaningful text within five seconds where possible, otherwise
ten; a generic acknowledgement alone does not establish acceptance.

## Review readiness — 22 October 2026

The opt-in implementation covers the shared generated-turn path, host conversion,
evidence-preserving input projection and atomic descriptive-continuity handoff.
The compatible foreground work hint remains deliberately in place. Removing it
requires a separately tested replacement for B admission.

The focused unit/native suite passed 461 checks. After fixing saved-reply
configuration recovery, the final runtime replay passed 20 checks, including
bilingual photo persistence, stale-source rejection and configuration rejection
before source acceptance. An additional governance/runtime run passed 76 checks
and failed 32 old configuration cases. The same 32 case IDs fail on an isolated
archive of unchanged main at `29396b6`: their fixtures reference removed runtime
methods (`_resolve_language`, `_home`, `_ensure_composer_provider`). These remain
baseline test failures; the broader suite is not all green.
The required `make test-place-research` gate passed 591 JavaScript, 429
API/database and 95 standalone checks. All completed native runs cleaned their
task-owned databases; the failed sandbox launch was separately reconciled.

| Gate | Status |
| --- | --- |
| Compiled responder instructions below 2,000 characters | Pass: 1,986 including dispatch |
| Typed conversion, evidence, durable handoff, replay and photo regression coverage | Pass in the focused and final runtime replays |
| Required place/photo/news regression gate | Pass: 591 JavaScript, 429 API/database, 95 standalone |
| Published prompt pins and matching serving runtime | Pending merge/publication and runtime verification |
| Matched live bilingual first/later/resumed latency and semantic quality | Pending; no reply-v2 live calls in this verification |
| Concurrent B lag, recovery and eventual next-turn state | Pending live acceptance |
| Five-second target / ten-second fallback | Unverified |

Issue #53 acceptance remains inconclusive. The candidate remains disabled by
default until the live gates pass.
