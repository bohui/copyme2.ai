# Issue 76 implementation

This records the implementation on `codex/issue76-orchestration`, based on main `533e7a4` after #75/#78 and #77/#80. It is not a deployment or feature-enablement receipt. [Specification](Memoir_Skill_Execution_Map_Spec.md); [test evidence](test-evidence/issue76-skill-orchestration-20261017.md).

## One logical owner, independent runners

The runtime inventory and admission contract are [background_skills.py](../apps/api/background_skills.py). `execution_map()` includes all ten catalog entries, their actual execution type, lane, modes, triggers, cadence owner, domain gates, recovery semantics and disabled-path compatibility. Readiness exposes the same code-backed map; catalog presence is never an execution receipt.

Lane A remains the immediate governed conversation. Lane B is logical ownership of background skills, not one process or serial queue:

| Runner | Existing authority retained |
|---|---|
| Timeline/profile | Canonical lane claims, publication fences, bounded source windows, source/version attribution and #75 field authority |
| Composer | Existing completed-round cadence, extraction-complete snapshot, checkpoints and canonical manuscript commits |
| Historical research | After-delivery registration, A lease release, separate persisted research claim, source verification and public-context cache |
| Grouping | Authenticated project/action reference, public-place validation, request deduplication and bounded deterministic/geocoding service |
| Photos | Authenticated project/turn reference, bounded independent photo pool, process-local jobs/cursors and optional public-result persistence |

Memory requests call shared admission at their bounded transport boundary. Grouping dispatches through the shared owner. Photo transport and after-reply registration use that owner's admission/progress contract while retaining their domain-specific caches, validation and capacity. There is no second legacy/new research launch, generic new job platform, global background mutex or merged personal/public store.

Exactly two entries are periodic: composer and memory-context. The map references the existing `private_draft_cadence` and SQL `lifetime_profile_due_round` authorities; it does not calculate a competing due decision. Defaults remain composer 5/10/15/20/... and profile 1/5/10/20/30/.... Other work requires source/change/action rules. Retries and polling are not schedules. Manual profile fields/stops, explicit UI language selection, canonical event attribution and flag-off A place compatibility remain unchanged.

Family extraction is still unwired. Localization has no runtime skill dispatch. Game generation remains unbound/unavailable. Research and optional photo-model flags are not enabled by this change. A provider-backed service is not automatically a fresh LLM invocation.

## Delivered mode and explicit game action

`read_lifetime_current_mode` reads the latest delivered A outcome and validates its current source/reply, policy, preference and execution revisions plus active strategy rollout. A future/shadow B proposal, an undelivered saved reply, a stale outcome or a client-provided mode cannot become current authority. Existing A/B model contracts are reused without another classifier or user mode selector.

The dedicated game button sends a metadata-only authenticated action. The existing completion/edition/consent eligibility reader now also requires current delivered shape. Passing mode/action checks does not enable generation or replace independent entitlement/evidence/consent bindings. Responses and localized UI explain unavailability; no game model/job is started.

## Progress is evidence, not eligibility

[Migration 005](../supabase/migrations/202610170005_background_skills.sql) stores bounded operation metadata separately from canonical facts and public caches. Browser roles cannot write applied-skill receipts. Actual canonical commits publish saved transitions transactionally; model/optional-service observation cannot authorize facts or replace publication fences.

- `queued` means an actual pending canonical obligation, not a running model.
- `running` records admitted transport/service work. Downstream provider timing remains opaque.
- `completed` means a response/service completion before a separately required persistence boundary.
- `saved` requires the relevant canonical writer or successful persisted research publication.
- `cached` identifies actual saved-checkpoint/photo reuse, not another model pass.
- `skipped` records actual reply-only/profile skip decisions, including manual confirmation, automatic stop, no targets or no evidence.
- `failed` records failed work/commit or interrupted/expired observation; it does not fabricate a save.

Timeline place extraction is an embedded responsibility in the same model pass. Its separate saved receipt has zero additional model requests. Grouping is deterministic. Provider-service model invocation/accounting is unknown unless separately observed; it is not inferred from flags or returned photos. Canonical saves survive optional telemetry loss with invocation/count fields explicitly unknown, not fabricated zero/true values.

Stable snapshot/page/source-window identities survive lease retries. Owner/project, source/version, turn and coverage correlate late updates. Existing runner receipts remain recovery authorities: a progress row does not make a photo cursor durably resumable. Readback is paged with project/owner-bound cursors. UI upserts receipts, recovers after reload and does not force uncorrelated work onto the latest reply. Canonical composer coverage comes from server receipts, not a guessed newest turn or invented completion of preceding phases.

Thinking steps use localized operation labels/statuses and execution types. Private question candidates, prompts, plans, source text, publication tokens and reasoning are not exposed or cached in traces. Thinking-off behavior remains supported.

## Verification and limits

Tests use the existing authenticated conversation/action APIs, real PostgreSQL migrations/claims/writers, actual Lane B runners and source UI. Auth/payment/provider/model boundaries are controlled where noted in the [test receipt](test-evidence/issue76-skill-orchestration-20261017.md). This proves contracts and persistence behavior, not live model semantic quality, production migration success or enabled disabled integrations.
