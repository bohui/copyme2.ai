# Runtime contract

## Observed source and authority boundaries

Baseline: `bohui/copyme2.ai` main at
`67ed64e395c0e5414e2d8cca4e648edc0c0562a9`. Source checkout was independently
observed on `test/manual1` at `b8c178745093251806de4081645256dc887ed0b6`.

| Source | What it establishes |
| --- | --- |
| `apps/api/conversation_phase.py`, `PhaseState` / `resolve_phase` | Explicit `comfort`, `explore`, `shape`; no `paused` phase. Shape is a narrator choice, independent of completion. |
| `skills/memoir-composer/SKILL.md`, trigger B | `storytelling_complete` authorizes composition to begin. |
| `skills/memoir-composer/references/runtime-contract.md`, candidate output | The composition candidate always has `status=draft`, including a generated formal memoir. |
| `skills/memoir-composer/scripts/lib.mjs`, `plan` / validation | Structural composition gates; the baseline supplied no durable full-composition receipt. |
| `apps/api/lifetime_memory_contracts.py`, `allowed_use` | Existing uses are `conversation`, `extraction`, `composition`; none silently grants adaptation. |

The baseline completion gap is addressed by the separately documented
[formal workflow](formal-workflow.md): actual RPCs, an additive migration,
authenticated routes and a provider-free extractive worker. The migration has
not been applied to an existing service. Game generation, review, commit and
delivery interfaces below remain **proposed host interfaces**, not existing
endpoints or feature flags. A missing interface returns `blocked`; it must not be
filled by a model inventing an authorization field. No root `AGENTS.md` or
repository `.agents/skills` existed in this baseline. `apps/web/AGENTS.md` was
read; its Next.js guidance applies when future work changes web code. Local
`~/.agents/skills/writing-for-agents` informed the package structure.

## Authority and data boundaries

`request.schema.json` is a **server-only**, authenticated snapshot. It contains
the chosen formal manuscript and chapters, immutable original evidence spans,
server-reviewed lines, permitted people and local asset registry. It also carries:

- Current phase and phase revision, project and actor scope.
- Completion receipt: composition run ID, manuscript ID/revision/digest, exact
  chapter ID/revision/digest coverage, original-evidence manifest digest, validation
  digest, zero pending chapters and zero blocking findings. The host verifies
  receipt provenance, successful run ownership and durable atomic creation.
- Separate consent receipt: `purpose=game_adaptation`, chosen manuscript binding,
  private audience, active status, consent revision and current policy epoch.
  Existing composition permission cannot create this receipt.
- Policy, correction and revocation epochs, source manifest and asset registry.
- Job ID, fencing token and expected game artifact revision.

Hashes are lowercase SHA-256. The local fixture convention hashes canonical JSON
(UTF-8, sorted keys, compact separators, finite numbers, Unicode unescaped).
Chapter digests hash exact UTF-8 text; manuscript digests hash its ordered chapter
descriptors and text. The original-evidence manifest hashes the ordered evidence
records. These conventions do not assert an existing product hashing format;
an eventual adapter must translate from its verified canonical representation.

The host's approved lines contain original evidence spans and a span from the
chosen chapter, plus a server-resolved editorial review receipt. A model cannot
add its own line to this authority list. Candidate grounding maps each browser
text ID to exactly one approved line and requires exact text equality. The local
validator checks linkage and quote spans; host editorial review establishes
paraphrase entailment, attribution and the absence of unsupported implications.
Each dialogue line also binds `npc_person_id` to the specific permitted NPC;
`person_ids` lists mentioned people and cannot by itself authorize presentation
by one of them. A line approved for one NPC cannot be reassigned to another.

`candidate.schema.json` remains server-only. It binds the complete request digest,
line map, NPC-to-canonical-person map, game data and a final author review receipt
to a candidate digest. The host verifies that reviewer's authority and the exact
reviewed content. `game.schema.json` is the only browser projection; never return
the request, candidate, reviewer identity, errors with source text, or debug dumps.

## Required host bindings

| Proposed capability | Obligation |
| --- | --- |
| Read current adaptation authority | Authenticate project ownership/authorized helper scope; read PhaseState, immutable manuscript, durable completion, separate consent, current epochs and permitted originals. |
| Review grounded lines | Resolve original lineage and exact manuscript version; record permitted wording, aliases, editorial entailment, sensitive-person grants and attribution; authenticate review receipts. |
| Review adaptation | Show all scenes, aliases, art and dialogue; record author approval of the candidate content digest. An editorial review is not author approval. |
| Claim adaptation job | Derive the logical idempotency key from frozen authority excluding job ownership; serialize the project lane; issue a monotonically fenced lease. |
| Commit private game | In one transaction recheck all authority, expected artifact revision, active consent and job fence; compare-and-swap; persist immutable output and replay result. |
| Deliver private game | Authenticate every access and recheck authority before returning only the approved browser projection. Enforce private storage and no-store responses. |
| Invalidate adaptation | On correction, source/rights change, consent withdrawal, phase exit or manuscript change, fence running jobs, withhold delivery and discard stale candidates under retention policy. |

Completion, exact-edition consent and metadata eligibility are implemented by the
formal workflow. Adaptation evidence review, game jobs, game persistence and
delivery remain unimplemented. A passing local
fixture check is neither a signed receipt nor a database transaction. Do not
connect a browser or provider to the fixture validator as an authorization service.

## Checked-in harness registration

`apps/api/memoir_story_game.py` loads this repository's `SKILL.md` and exposes
`story_game_admission` and `build_story_game_prompt`. `apps/api/codex_runtime.py`
registers those symbols and loads `STORY_GAME_SKILL`, following place-journey's
repository path convention. Existing `trajectory_evaluation.build_skill_manifest`
automatically discovers and hashes this directory; no separate catalog is present.
This registration is exercised by `tests/test_memoir_story_game.py`.

Admission rejects absent/invalid phase authority and Comfort/Explore. Shape-only
discovery returns `persisted_authority_required`. The authenticated eligibility
RPC resolves persisted completion and consent but always returns `available=false`
because game runtime bindings remain absent. Prompt construction raises before any
provider invocation; completion and consent booleans from chat/profile/browser
cannot enable it. The skill is never appended to collector/workspace prompts.
The worker role allowlist and deterministic task kinds remain unchanged, preventing
a caller from bypassing this blocked seam through a new `story_game` role.

Next integration: adapt verified formal receipts and separately approved evidence
to the game request contract. Add a bounded worker role/job whose claim and commit
share the same fences, with a verified Astra model binding; return the browser
projection through a private endpoint after author review. Add the Shape control
and fixed renderer only after those gates pass integration tests. Do not accept
the synthetic request JSON directly from an API client as authority. Repository
registration needs no `install_skill` or personal Codex installation; none was run.

## Dispatch, races and delivery

Offer and invoke the feature only after the host verifies Shape and completion;
request separate adaptation consent before generation. Recheck on the server even
if a hidden/disabled UI control already gates access. Returning to Explore or
Comfort withholds the feature and fences outstanding work; it does not introduce
a paused phase. Require fresh author review after invalidation, even on reentry.

The proposed game job lifecycle is `queued → drafting → review_required → validated
→ committed`, with `blocked`, `cancelled`, `failed` or `superseded` terminal outcomes.
These are game-job states, not changes to PhaseState. Exact replay returns the
stored logical outcome. Retry only transient failures, at most twice per task;
reuse completed work with identical dependencies. Do not retry denied permission,
missing completion, unsupported facts or failed review as provider errors.

The local `idempotency_key` excludes job ownership but includes manuscript, consent,
phase, evidence, assets and epochs. The candidate digest includes the job fence via
the full request digest. Another worker taking ownership therefore invalidates
late output even when the logical job key is unchanged. Production must enforce
this atomically; comparing two files merely exercises the invariant.

Consent and privacy checks occur at claim, before any generation, before final
commit and on every delivery. A revision or policy race rejects the old write;
never last-write-wins. Revocation blocks existing artifacts as well as new jobs.
Access loss during play must unmount and clear client memory via a host session
check/lease and invalidation event. Do not use service-worker caches, public CDNs,
localStorage, IndexedDB or offline downloads for personalized packages. Already
delivered bytes cannot be recalled from a user who saved them; promise future
access invalidation, not retroactive erasure from their device.

## Fixed browser renderer

The game is bounded declarative data: two to eight connected side-scrolling scenes,
a controllable generic author, two to sixteen aliased NPCs, deterministic reviewed
dialogue, coordinates and safe asset keys. Opaque IDs are random per release,
unrelated to database/source IDs, names or hashes of private facts. The validator
rejects exact overlap with server identifiers; the host must generate IDs itself
to prevent encoded identifiers that an equality check cannot recognize. The host maps
asset keys to reviewed, bundled local raster assets; package data cannot choose a
path or URL. Unknown keys fail closed. No generated JS/HTML, expressions, plugins,
remote URLs, network scripts, open-ended NPC chat, photo likeness or voice cloning.

Render text as text nodes. Use bounded coordinates and fixed transition actions.
Keyboard/touch movement, interaction, escape/close, a text-only equivalent and a
reduced-motion transition are renderer responsibilities. Schema declarations do
not prove those behaviors work. Further implementation must read the repository's
current web instructions and test actual lifecycle cleanup.

The user's Astra model preference remains a requirement for future binding, not
an API identifier. Do not change model allowlists or start provider calls until
the product verifies support. This skill does not authorize applying migrations,
installation, restart, new credentials, service purchases, deployment or publication.
