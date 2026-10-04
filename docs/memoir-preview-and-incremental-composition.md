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

The initial snapshot still requires authenticated source reads, so request admission is quick relative to composition, not guaranteed instantaneous during a Supabase outage. Existing source limits remain: at most 1,000 memories and 120,000 source characters. Increasing a timeout cannot guarantee a provider response; retries and explicit failures remain necessary. The original preview repair was committed to local main and the memoir services restarted with explicit approval. No remote push occurred. The existing signed-in browser session confirmed immediate loading and a live indexing timeout; the omitted bearer token was never retrieved or used.

The live runtime diagnosis subsequently isolated an unreachable configured provider. A synthetic Codex turn completes initialize/thread-start/turn-start in 0.2 seconds but receives no model reply. Both worker-internal provider health and tiny response requests fail with `ConnectTimeout`; the known local provider port has no listener. Composer-only TCP admission now fails within five seconds without sending sources to an unreachable endpoint. This produces `PREVIEW_PROVIDER_UNAVAILABLE` as a terminal job state, preserving checkpoints and requiring an explicit retry once connectivity is restored. It does not increase the model budget or guess a replacement endpoint.

## Recommendation for every five completed rounds

**Recommend every five completed rounds as an incremental draft checkpoint cadence, with quiet background work and a visible saved-draft status. Do not automatically publish, charge, alter human edits, or interpret the cadence as storytelling completion.** The cadence is an application event policy, not a ChatGPT scheduled automation.

Before the new local feature implementation, the integration did not do this: preview generation is requested at the backend-confirmed free limit (currently 20); its packet uses `prior_state.kind = none`, revision 0 and the entire authorized source snapshot. A changed snapshot produces a fresh sample rather than a chapter-by-chapter incremental update. The skill already defines `new_context`, prior manuscript revisions, protected replacement proposals and incremental examples, but the application does not bind them into a durable recurring composer workflow.

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

Before enabling the cadence, choose its product scope explicitly. Recommended first scope: opt-in private sample/draft updates during interview, preserving the current free allowance and package entitlement rules. A full manuscript still needs explicit storytelling/composition authorization. The original skill blocked initial composition before the configured free limit and blocks `new_context` with `prior_state = none`; a round-5 bootstrap draft therefore requires an explicit host policy/schema gate for an authorized private draft checkpoint. Do not forge `free_rounds_completed` at five while the allowance remains twenty. If product policy instead retains the first sample at round 20, milestones 5/10/15 can prepare grounded indexes only, followed by incremental sample updates after the first sample.

Implementation scope for a subsequent approved task: round identity/project ledger and transactional outbox; early-draft gate decision; source/rights version manifest and current prior-state bindings; autonomous trusted Temporal activities and checkpoint storage; chapter dependencies/revision CAS and protected-edit proposals; saved-draft UI; replay, restart, edit, revocation, locale, concurrency and guest-transfer regression tests. The preview-only commits did not enable five-round triggers. The subsequent authorized feature implementation below remains local and has not been rolled out.


## Subsequent authorized local implementation

The later user instruction explicitly authorized private prose checkpoints and stage readiness, while reserving rollout for a separate confirmation. The working tree now contains:

- Deterministic per-stage narrator word equivalents: each Han character counts once; other Unicode word tokens count once. Interpolation is 0→0%, 100→10%, 300→30%, 1000→50%, capped at50%. Red applies below300, amber300–999 and green from1000. Mira assigns each committed response to a stage; assistants, synthetic greetings, duplicate row IDs and legacy instruction wrappers are excluded. Fresh reads reflect edits, deletions and reassignment. The UI describes context volume, not chapter quality.
- Independent validated server configuration: `MEMORY_SPARK_FREE_RECALL_ROUNDS=20`, `MEMORY_SPARK_PRIVATE_DRAFT_CADENCE=5`, `MEMORY_SPARK_PRIVATE_DRAFTS_ENABLED=true`. No admin UI or change to default allowance. Configurations such as7 free rounds with3-round draft cadence are covered by tests.
- A new unapplied migration, `202610020002_private_draft_rounds.sql`, adds stable client turn identity, project/stage assignment, a project completed-round ledger and an atomic outbox. Assistant-only greetings are saved without advancing the allowance or ledger. Retries resolve the original committed turn. Edits/deletions generate invalidation events without incrementing rounds. Capability-checked guest attachment preserves turn/project/stage identities and replay does not create extra milestones. Old unassigned account history is not silently assigned to a project.
- An API-owned broker uses the existing server-only Supabase credential through a receipt-scoped RPC. It verifies the receipt's owner/project, drains durable events, then acknowledges only after the private SQLite job transaction commits. Composer workers receive opaque job IDs and bounded authorized packets, never Supabase keys or stored browser tokens. The API rechecks the receipt/source snapshot before generation and before commit.
- The existing Temporal worker dispatches private jobs autonomously. SQLite maintains job deduplication, a renewable lease, at most three composition attempts, validated phase checkpoints, milestone history and manuscript revision/source-epoch fencing. Only one run per project can compose at a time. New unchanged rounds can arrive during generation; queued milestones coalesce. Offline-provider failures are terminal until explicit retry, and failed Temporal runs remain restartable.
- The initial five-round packet uses the explicit host-authorized private gate with truthful5/20 counters. Later packets use `new_context`, the previous manuscript/revision/index, new original responses and a two-round overlap. Original evidence remains available for validation/review. Canonical event/period IDs carry forward; altered references are pruned. Saved samples remain private and publication authorization stays false.
- Response-stage indexing is captured upstream: `202610020004_response_stage_index.sql` gives every saved response a stage or `unplaced`, stores stage order, and indexes project/stage retrieval. Known stages commit atomically with the exchange; private context extraction assigns stages to continuations even without a place cue. Composer sources preserve stage/capture order and expose a stage-to-source lookup. Stage, text or capture-order changes create new source versions; deletion leaves surviving versions stable. Both regular previews and private checkpoints reuse validated prior indexes, sending only new/changed responses, affected surviving evidence and optional bounded overlap to the index call. Invalidated IDs remain available for repair without retaining deleted summaries. This migration is also unapplied.
- The latest reviewed saved sample is readable in a quiet workspace disclosure even before chapter unlock. New jobs show a compact updating state; interview typing remains available. Transient failures permit explicit retry. Source changes hide unsafe prior previews and fence/prune obsolete job packets and checkpoints. Human-locked stored drafts retain their revision and receive a proposed replacement; the current private preview is read-only, so no new editing/reconciliation UI was added.

### Local follow-up: bounded draft/review context

The local composer follow-up now keeps the canonical full request inside the
application for planning, validation, source-rights checks and persistence, but
projects only the new, changed, affected and two-round overlap evidence into
`draft` and `review` model packets for `new_context` jobs. Canonical event and
period manifests, dirty/carry-forward chapter IDs, the prior manuscript and
the immutable source manifest preserve the evidence boundary without resending
the entire transcript. If a compact attempt fails deterministic validation or
editorial readiness, one bounded full-context repair is used before the
existing three-attempt ceiling; this is a quality fallback, not a silent
relaxation. The packet benchmark receipt is
`var/memoir-five-case-evaluation/composer-incremental-packet-benchmark-20261003.json`.

### Rollout requirements and remaining scope

These changes are uncommitted and have not restarted the API, web or workflow worker. The new migration must be applied through the existing authorized deployment path, then the API/worker/web must be rebuilt or restarted with their updated configuration and composer bundle. Rollout needs the user's confirmation. An existing API `SUPABASE_SECRET_KEY` is required for autonomous receipt verification; it stays in the API and is never passed to the composer.

The configured model provider remains unreachable. Deterministic fixtures validate the pipeline, but a successful live sample/recurring run cannot be demonstrated until the authorized provider endpoint becomes reachable. No replacement endpoint or credential has been guessed. Full-book composition remains explicit. Per-chapter task fan-out, source retrieval beyond the existing1000-memory/120000-character bound, an editable private manuscript UI, proposal approval/rollback UI, photo-rights/glossary event producers, and resuming pre-migration unassigned history are future scope. The implementation checkpoints validated index/draft/review phases; it does not claim a complete chapter-task engine or independently prove model entailment beyond its evidence-review pass.
