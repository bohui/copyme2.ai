# First-reply conversation locale persistence

The local fix makes conversation language a durable host decision in the existing private user profile. It does not add a table or migration, enable composition policies, restart services, commit, push or deploy other pending features.

## Cause and evidence

The supplied screenshot was materialized into `output/locale-debug/user-screenshot.png` and its pixels inspected. It shows a Chinese interface and first assistant reply, followed by an English second assistant reply. No personal text from that screenshot is included here.

The previous runtime's streaming first-reply branch changed the in-memory profile but did not save it before visible generation. Persistence belonged to optional workspace enrichment, after releasing the conversation lease. A follow-up could therefore read an empty profile and use the default English request language. Collector/workspace profile markers could also replace `preferred_language`. The browser hydrated the private profile only for permanent accounts, leaving anonymous reloads dependent on the demo project mirror. These code paths explain the observed drift; fixtures reproduce the failed-enrichment/second-turn case. The screenshot alone does not identify which path ran in the original session.

## Behavior

- The host reads the earliest eligible original narrator reply, excluding synthetic opening/continue prompts, assistant text, instruction wrappers and attachment-only placeholders. History retrieval uses an owner filter and ascending stable order, with bounded pagination; it never substitutes the newest reply when the bound is exceeded.
- Under the existing renewable cross-replica conversation lease, the host saves `preferred_language` and a versioned `conversation_language` record before starting the visible model turn. This record includes revision, source, original detected locale, frozen fallback and original reply identity. Failed persistence prevents generation.
- Initialized conversations reuse that decision across later text, mixed-language replies, runtime restarts, interrupted workspace work and replayed first-reply hints. An ambiguous first reply freezes its supplied UI fallback; later text does not reopen detection.
- Normal collector/background profile markers cannot update locale state. Generic workspace profile writes preserve the current private locale. Private profile hydration applies to anonymous and permanent sessions. Browser revision checks and project/owner guards reject stale reads, project-mirror responses and old workspace results.
- Explicit profile/language-selector actions and conservative standalone language-change requests remain authoritative. They advance the private locale revision. Resetting the profile to Automatic restores the recorded first decision, including an ambiguous first reply's original fallback.
- Resume reads backfill missing state from the earliest authorized reply, with a fresh profile read under the lease so a concurrent explicit setting wins. Existing guest transfer SQL carries the JSON state, preserves an existing account preference under its default merge policy and makes capability retries idempotent. No SQL change was necessary.

## Legacy limitation

Older `preferred_language` values contain no provenance: they may have come from a human setting or an automatic model marker. The fix preserves an unmarked saved preference rather than guessing that it was automatic, while recording the earliest reply's detected locale separately. A conversation already carrying an incorrect old English preference may therefore require one explicit Chinese profile selection. Missing preferences backfill automatically; initialized records never redetect from the latest message. This is a deliberate conservative limit, not a claim that every historical preference can be repaired automatically.

## Changed code and verification

Locale changes are in `apps/api/conversation_locale.py`, `agent_storage.py`, `codex_runtime.py`, `agent_routes.py`, `supabase_routes.py`, `apps/web/client/memoir/client.js` and `skills/memoir-memory-context/SKILL.md`. Shared files also contain other pending work; whole-file diffs must not be treated as an isolated locale deployment.

Regression coverage includes first/second turn, failed enrichment, restart, hint replay, earliest-history backfill, original-wrapper filtering, manual override/reset, ambiguous fallback, cross-replica contention, stale hydration, account switching, owner-filtered pagination and SQL guest transfer/retry. Existing runtime fixture adapters now implement profile persistence; lease-loss fixtures explicitly represent a resumed initialized conversation.

Two real-browser locale tests pass against synthetic authentication/model boundaries. They exercise Chinese followed by English and English followed by Chinese, mixed-language replies after reload, anonymous private-profile hydration, stale background markers, and a manual profile selector override. Screenshots inspected: `output/locale-debug/stable-zh-CN.png` and `stable-en-AU.png`. Nine related recall/readiness browser checks also passed. The isolated frontend was stopped after testing.

The frontend production build, JavaScript syntax check and `git diff --check` pass. All 104 JavaScript tests pass. The full Python result is recorded in `output/locale-debug/validation.md` after final verification. Live provider responses and production account history were not accessed; model behavior is covered by controlled fixtures. No credential was retrieved from chat or persisted by this work.
