# Private game runtime contract

The production adapter is `apps/api/story_game_routes.py`,
`apps/api/story_game_runtime.py` and the consolidated reset baseline
`supabase/migrations/202610180001_initial_schema.sql`. Formal composition and
consent already live in `202610180001_initial_schema.sql`. Applying a migration
and deploying these sources are separate from passing disposable tests.

## Authority and source evidence

Every job binds the owned project, policy epoch, source inventory, preferences,
execution generation, current delivered Shape reply, immutable formal edition,
manuscript digest and separate consent revision. `story_game_context` takes the
same project/profile/lifetime locks as formal composition and verifies current
full completion plus exact-edition consent. No client-supplied source list,
completion flag, person ID or candidate JSON is authority.

The provider sees only the claimed edition's original-backed chapter blocks.
`stage_story_game` resolves the stored chapter and block, requires each quote to
be an exact, unambiguous substring, and derives original source/version/offsets
from the verified formal chapter. Factual scene titles and person labels must
also occur in that quote. Extra fields, unsupported quotes, duplicate person
labels, HTML and unsupported art keys are rejected. The model cannot approve its
own output. A completed provider response is a proposal, never a publication.

The initial runtime supports exactly two scenes and two represented people.
Private server-side person records bind the exact passage to an opaque adaptation
person ID; they do not claim to be a resolved genealogical family tree. The author
must confirm that the two source descriptions identify distinct adults and grant
permission for their exact passages before publication. Unknown ages, minors or
uncertain identity cannot be approved through this version. Aliasing does not
anonymize names or relationships inside a source quote; the review shows both.

## Jobs, review and private publication

`begin_story_game` serializes the project and reuses an existing current job.
Each request UUID replays only its original authority. A new request can replace
stale work after fresh completion and consent. States are `pending`, `running`,
`review_required`, `published`, `failed`, `stale`. Claims use a fresh fencing token,
a 180-second lease and at most three attempts; a busy lease cannot dispatch twice.
Read, stage, publish and delivery all recheck current authority. A late worker
cannot stage after a replacement claim or consent/source change.

The host constructs all browser IDs, generic aliases, allowlisted scenery and
bounded coordinates. The review includes every scene title, alias, quotation,
protagonist and scenery choice. Publication requires the exact database candidate
digest and two separate person permission confirmations. The database derives the
authenticated reviewer and records the candidate, permissions, purpose and private
audience atomically. Replaying the same approved candidate returns stored state.
The browser cannot replace reviewed content at publication.

Production digests use SHA-256 of UTF-8 PostgreSQL `jsonb::text`; the offline
`request.schema.json` / `candidate.schema.json` fixtures use their own sorted,
compact JSON conventions. The fixture validator remains a design/development aid,
not the runtime authorization service. `game.schema.json` describes the actual
browser projection.

## Interfaces

All routes below use the existing authenticated project owner and `no-store`.

| Route under `/v1/agent/projects/{project_id}` | Purpose |
| --- | --- |
| `GET /story-game` | Read completion, consent and adaptation metadata. |
| `POST /formal-memoir` | Explicitly begin a complete extractive formal edition. |
| `POST /formal-memoir/advance` | Advance the owner's current run by at most eight chapters. |
| `PUT /story-game/consent` | Grant/revoke separate consent for the exact edition and digest. |
| `POST /story-game` | Begin/replay a job and perform one bounded proposal attempt. |
| `GET /story-game/{game_id}?review=true` | Privately review the vetted candidate and person descriptions. |
| `POST /story-game/{game_id}/publish` | Approve the exact candidate and specific person permissions. |
| `GET /story-game/{game_id}` | Deliver the approved browser projection. |

All service-only claim/input/stage/fail operations deny authenticated and anonymous
roles. Direct game-table access is denied to application roles. The old collector
prompt-construction seam stays closed: only this separate authenticated workflow
can generate games. Internal strategy plans and the generic worker/task allowlists
cannot bypass these routes.

## Delivery, invalidation and renderer

`StoryGameResponse` holds the authority transaction through the actual bounded
HTTP send. Consent/source revocation and delivery serialize on the same locks;
a successful earlier RPC alone is insufficient. Source/edition/consent changes
purge candidates and reviews, fence workers and withhold future reads. A changed
current delivered strategy also rejects access. Read errors return coarse status
messages without source content. Read requests never return server source IDs,
source offsets, authority, review receipts or provider metadata to the player.

The Shape-only dialog requests fresh status on open, every 15 seconds while
visible, and before remount after visibility change. Failure, access loss, project
switch, phase exit, close and revocation clear the renderer and abort requests.
No localStorage, IndexedDB, offline download, public link or game telemetry is
used. Already delivered bytes cannot be recalled from a person who saved them;
revocation controls subsequent access and the active application's display.

The renderer accepts only bounded declarative `game` data. Two connected scenes
have fixed transitions, clamped movement, generic CSS silhouettes and reviewed
text. It provides keyboard and touch controls, close/Escape, text equivalence and
no automatic camera animation. Every factual string is rendered as text, never
HTML. Per-instance abort listeners, animation cancellation and timer cleanup
prevent old views from writing into a new owner/project. No generated JS, paths,
URLs, plugins, open-ended NPC chat, likeness or voice cloning is supported.

The provider model is the existing verified composer gateway configuration, with
one strict-schema response, a bounded input/output and a deadline. Display names
such as Astra are not API bindings. No engine dependency, remote art service or
new credential is introduced. Acceptance evidence is tracked separately; do not
infer a live deployment or completed end-to-end evaluation from source files.
