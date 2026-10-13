# Formal composition and adaptation authority

This implementation adds a real, private formal-draft workflow upstream of the
game. It is an **extractive first version**: one neutral chapter per current
canonical event, containing the exact original narrator passages in its frozen
evidence plan. It does not synthesize prose, invent transitions or run a model.
The result remains a draft. Completion does not require or imply publication.

The existing cadence-driven private checkpoint pipeline is unchanged. Its
`complete_lifetime_memoir_lane` operation cannot mint a formal receipt. Formal
editions have their own revision, immutable contents and completion receipt.

## Actual interfaces

The additive migration is
`supabase/migrations/202610130002_formal_memoir_authority.sql`. It is authored for
review and disposable synthetic testing; it has not been applied to existing
Supabase, production or user data. No installation or service restart occurred.

Authenticated endpoints registered by `apps/api/agent_routes.py`:

| HTTP endpoint | Purpose |
| --- | --- |
| `POST /v1/agent/projects/{project_id}/formal-memoir` | Explicitly authorize a formal run using `expected_phase_revision`, formal `expected_revision` and UUID `request_id`. |
| `GET /v1/agent/projects/{project_id}/formal-memoir` | Read metadata for the current run and edition. No manuscript/source prose. |
| `PUT /v1/agent/projects/{project_id}/story-game/consent` | Grant or revoke private adaptation consent using `edition_id`, `expected_digest`, expected consent revision and `action`. |
| `GET /v1/agent/projects/{project_id}/story-game/eligibility` | Read current completion/consent gates. `available` remains false, even when `authority_eligible` is true. |

All four use the existing authenticated user storage connection. The database
resolves ownership from `auth.uid()`; the browser cannot provide an owner, source
inventory, chapters, completion flag or validation assertion. Responses use
`Cache-Control: no-store`. Metadata is a point-in-time status, never a bearer
capability or permission to deliver game content.

The trusted worker endpoint is
`POST /v1/agent/internal/formal-memoirs/{run_id}/advance`, authenticated with the
existing `X-Codex-Worker-Secret`. It processes at most eight chapters per call.
`apps/api/formal_memoir.py` performs the same bounded operation through the broker.
The returned run may remain pending; the worker invokes advance again to resume.
There is no new scheduler, automatic background dispatch, UI control or provider
binding in this change. No new credential is introduced or populated.

## Persisted authority

`begin_formal_memoir` acquires the owned project authority, requires current Shape
and ready policy, and freezes the complete intended plan before any output is
accepted. It requires finished canonical extraction. Every active canonical event
must be covered; invalid or oversized evidence blocks initiation instead of being
silently truncated. V1 bounds are 128 chapters, eight exact evidence spans per
chapter, and 2,000 characters per span. These are explicit acceptance limits,
not performance claims. Incomplete privacy policy or excluded/paused topics block
this deterministic first version pending a richer reviewed plan.

Service-only claim, bounded chapter read, stage, release and complete RPCs enforce
leases and fencing. A release preserves validated stages and invalidates the old
token. A retry resumes at the first unfinished ordinal. The chapter wire format is
documented by `schemas/formal-chapter.schema.json`; its fixture is entirely invented
and is server-only. PostgreSQL independently reconstructs the exact expected
chapter from the frozen plan and current originals. A caller's validation boolean
cannot replace this check.

`complete_formal_memoir` requires every intended chapter and current authority,
then persists the immutable edition, advances its canonical formal head and saves
the completion receipt in one transaction. Receipt coverage and digests are
computed by the database, with zero pending chapters and blocking findings. Exact
replay returns the persisted result. No legacy private root, partial chapter set,
model completion sentence or synthetic JSON fixture establishes completion.

Hashes in this database contract use SHA-256 over UTF-8 PostgreSQL `jsonb::text`
for structured values. They are distinct from the offline game fixture's compact,
sorted JSON convention. A future game adapter must verify the database receipt
first and derive the game snapshot explicitly; it must never relabel one digest
as the other.

Separate consent uses the purpose `game_adaptation`, the exact formal edition and
digest, a private audience and a compare-and-swap consent revision. Composition
permission is not adaptation consent. Revocation remains possible outside Shape
and after an edition becomes stale. The consent revision is project-global:
every consent change invalidates prior grants at that fence. Revoking an older
edition therefore also requires a fresh grant for a newer edition before it can
be eligible again. This conservative behavior is explicit and tested.
Source corrections, withdrawal, changed policy
or preferences, phase changes and new editions invalidate old authority. Final
commits recheck current state under the same project lock.

Formal operations lock project, profile and lifetime identity before formal
rows. Preference triggers already own the identity row and purge under that
lock without requesting project or profile again. Other invalidation paths
take project, profile and identity before purging. This preserves the existing
private-publication lock order. Purging, stale-token invalidation and edition
deactivation stay in the preference transaction; rollback restores them together.
Status reads also lock identity before reading run and edition metadata.

## Remaining game and delivery work

Formal completion and top-level consent are necessary gates. They do not resolve
per-person permissions, sensitive facts, approved aliases, factual line review,
author approval of a game digest, game jobs or a playable renderer. The game
request/candidate schemas remain offline conventions until that adapter exists.

No owner-facing manuscript or game-content delivery route is added. A future read
path must guard the actual network send against concurrent correction/revocation;
a successfully completed read RPC is insufficient. The bounded edition reader is
service-only for a trusted adapter and persistence testing. Direct table access
is denied to application roles. Game provider dispatch and existing model/worker
allowlists remain unchanged, including the unverified product Astra model ID.
