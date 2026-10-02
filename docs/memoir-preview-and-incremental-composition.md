# Preview recovery and incremental composition recommendation

## Delivered preview fix

The former `/v1/story/preview` request performed indexing, drafting (up to three candidates), evidence review and rendering synchronously. The worker bounded each composer invocation to its usual 120-second chat-turn budget. The API waited up to 135 seconds per invocation and mapped any worker HTTP error to `PREVIEW_UNAVAILABLE` / HTTP503. A successful preview requires at least three model calls, so even individually successful calls could exceed the frontend proxy's 240-second budget.

Sanitized local worker logs contained **two `/internal/codex/turn` HTTP504 responses**. This confirms that the worker timeout failure mode exists. Legacy access logs do not contain phase or request correlation, so they cannot establish which phase or exact user request produced those responses. The user's supplied screenshot confirms the error/retry card, but contains no timing evidence. The fix adds phase, elapsed time, HTTP status and exception-class telemetry; it never logs packet text, responses, credentials, URLs or exception messages.

Changes:

- Immediate visible spinner, polite live status, `aria-busy`, and disabled preparing action. English/Chinese copy includes slow progress, temporary connection failure, paused polling, changed sources and expired authentication. Reduced-motion users receive a static indicator.
- POST authenticates and loads the authorized snapshot, returns a saved matching sample or HTTP202 with a job ID. Model generation is detached from the browser HTTP request. GET status is owner-scoped and resumes eligible unfinished work with fresh authenticated storage.
- The existing private SQLite task volume contains deduplicated preview intents and validated request/draft/review checkpoints. No bearer token or worker credential enters the persisted payload. An API task owns the short-lived authenticated storage object only while executing, then closes it.
- An independent 240-second composer phase budget, 255-second API-to-worker transport limit, smaller indexing instructions, structured output schemas, and separate bounded composer packet size. Chat budgets and input limits retain their existing behavior.
- Automatic transient retry is limited to three actual composition attempts, with backoff. Waiting for an active conversation lease does not consume a model attempt. Two local candidate repairs remain the skill limit. Manual retry keeps successful checkpoints. A token and expiry fence checkpoint/terminal writes. The Supabase user-turn lease still renews throughout execution and fences final storage access.
- Source/locale/skill fingerprints invalidate cache and checkpoints. The current sources are checked again before saving; changed or revoked sources refuse a late candidate. The ready artifact remains in the existing private RLS memory store. Composer runs never increment the conversation-round counter.
- Background previews participate in the existing pending-delivery check before guest account transfer.

The browser uses one request at a time, polls a known job rather than repeatedly submitting it, retries temporary polling failures three times and pauses automatic polling after 15 minutes. A progress button checks the same job. A lost initial response can safely repeat POST because server admission deduplicates the snapshot.

### Current limits

This change uses the current API + private task volume architecture. After a hard API crash, an expired claim resumes on the next authenticated POST/GET; it does **not** introduce a credential-bearing autonomous worker. Graceful shutdown requeues immediately. A hard-crash claim can take up to 15 minutes to expire. Running work normally continues when the tab closes, but a restart or expired user session requires fresh authentication before further execution. This is deliberately narrower than the autonomous recurring policy below.

The initial snapshot still requires authenticated source reads, so request admission is quick relative to composition, not guaranteed instantaneous during a Supabase outage. Existing source limits remain: at most 1,000 memories and 120,000 source characters. Increasing a timeout cannot guarantee a provider response; retries and explicit failures remain necessary. A real-user live-provider preview has not been replayed with the user's omitted bearer token. No running service has been rebuilt or restarted, pushed, or deployed.

## Recommendation for every five completed rounds

**Recommend every five completed rounds as an incremental draft checkpoint cadence, with quiet background work and a visible saved-draft status. Do not automatically publish, charge, alter human edits, or interpret the cadence as storytelling completion.** The cadence is an application event policy, not a ChatGPT scheduled automation.

The current integration does not do this: preview generation is requested at the backend-confirmed free limit (currently 20); its packet uses `prior_state.kind = none`, revision 0 and the entire authorized source snapshot. A changed snapshot produces a fresh sample rather than a chapter-by-chapter incremental update. The skill already defines `new_context`, prior manuscript revisions, protected replacement proposals and incremental examples, but the application does not bind them into a durable recurring composer workflow.

### Completed round definition

One completed round is a unique persisted narrator input plus its successful, persisted assistant response, committed atomically by the backend. Text and transcribed voice both count once after successful commit; opening greetings, assistant-only content, partial streams, failed turns, transport retries, queued composition jobs and rereads do not count. A duplicate client turn ID must resolve to the original commit, not create another round. Editing an old input creates a source revision/change event without increasing the completed-round total.

The existing `user_recall_usage` trigger counts committed `kind = agent` rows and supports the current account-level free allowance. Retain that billing/allowance counter. Add an explicit **project-owned round ledger** with round/turn ID, monotonic source sequence, input source/version, assistant commit and actor/subject. Imported guest rounds require stable identity mapping and an idempotent transfer event; imports must not manufacture duplicate five-round milestones. Do not use displayed chat length or `count / 2`.

### Durable dispatch and checkpoints

In the same transaction as the round commit, write an outbox event for each newly crossed milestone (5, 10, 15, ...), scoped by project and locale. Deduplicate `(project, policy version, milestone)` and persist the last accepted/completed milestone. Retry outbox dispatch until acknowledged. Jobs carry opaque IDs, expected revisions and authorized source manifests; model workers receive bounded source packets through a trusted activity, never a stored browser token.

Use the existing Temporal/outbox infrastructure for autonomous dispatch; the present authenticated-poll recovery mechanism is not sufficient for work that must continue after every session closes. The trusted execution boundary needs explicit current authorization, tenant isolation, source access and revocation checks. Do not simply give the composer broad service-role access. API/runtime restarts must recover from durable jobs without relying on a remembered user token.

Persist validated event index, outline, source summary with original references, stable chapter IDs, per-chapter draft candidate, evidence review, length report, artifact hash and the completed milestone. Cache each phase/chapter by exact input hash including skill/model/counter version, policy, locale, glossary, media rights and base chapter revision. Only completed checkpoints advance progress. Exactly repeated milestone + fingerprint returns the recorded result.

### Incremental context, overlap and concurrency

For milestone 10, treat rounds 6–10 as **new evidence**, together with the saved outline/event index and original sources for affected events. Supply a small overlap of the last one or two prior completed rounds to resolve pronouns and unfinished narratives, plus relevant earlier evidence retrieved by original references. Overlap is context, not a second batch of new testimony. Never recursively summarize generated prose into factual authority.

Regenerate affected chapter drafts; carry unaffected chapters forward. Earlier evidence remains retrievable: a new detail at round 30 can revise an event first discussed at round 2. Canonical event IDs and source-to-chapter dependencies prevent repeated stories from becoming duplicate life events. One run may update several chapters when evidence crosses periods; do not force one chapter per five-round batch.

Serialize **commits** per project+locale with a renewable, fenced run lease and manuscript revision compare-and-swap. Capture an immutable snapshot, then release interview write locks during slow generation. Allow the narrator to continue chatting. If rounds 10 and 15 arrive while round-5 composition is running, coalesce queued work to the latest authorized snapshot while retaining milestone history. Do not silently throw away an individual source/correction event. A candidate cannot commit over a newer manuscript revision or changed policy epoch; reconcile affected work against the latest state.

### Retry, edit and invalidation policy

Retry timeouts, rate limits and transient persistence failures with bounded exponential backoff and jitter. Resume successful phases, rather than redoing a whole book. Allow at most two candidate repairs before a review-needed terminal state. Record safe error codes and durations. A stalled run must expose a recoverable state; quiet background work must not mean invisible failure.

Version corrections, deletions, privacy/consent changes, glossary, locale, media rights and caption changes as durable invalidation events. A five-round cursor alone misses them. Mark affected candidates/translations stale immediately, and refuse late outputs. Rights withdrawal and deletions bypass cadence/debounce. Prune restricted checkpoint bytes under the application's deletion/retention policy, not only visible artifacts.

Retain human-edited and approved revisions exactly. Save a proposed replacement against the exact base revision for protected chapters; merging it requires editorial/user approval. Keep chapter IDs stable through title/order changes, with explicit lineage for splits or merges. A source correction can make a protected edition ineligible for reuse; a lock never grants permission to expose revoked content.

### Saved-draft preview and policy scope

Render the latest validated, authorized **saved draft** immediately when the user opens preview. Show its update milestone/time and a compact “updating” status if a newer run exists; provide an explicit retry for a blocked run. Keep the last usable revision while a new candidate is processed, except when source/privacy revocation makes that revision unsafe. Never show a half-written or unreviewed candidate as ready.

Before enabling the cadence, choose its product scope explicitly. Recommended first scope: opt-in private sample/draft updates during interview, preserving the current free allowance and package entitlement rules. A full manuscript still needs explicit storytelling/composition authorization. The skill currently blocks initial composition before the configured free limit and blocks `new_context` with `prior_state = none`; a round-5 bootstrap draft therefore requires an explicit host policy/schema gate for an authorized private draft checkpoint. Do not forge `free_rounds_completed` at five while the allowance remains twenty. If product policy instead retains the first sample at round 20, milestones 5/10/15 can prepare grounded indexes only, followed by incremental sample updates after the first sample.

Implementation scope for a subsequent approved task: round identity/project ledger and transactional outbox; early-draft gate decision; source/rights version manifest and current prior-state bindings; autonomous trusted Temporal activities and checkpoint storage; chapter dependencies/revision CAS and protected-edit proposals; saved-draft UI; replay, restart, edit, revocation, locale, concurrency and guest-transfer regression tests. No five-round triggers were enabled by this preview fix.
