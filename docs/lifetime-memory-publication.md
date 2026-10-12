# Governed publication boundary (opt-in integration, not activated)

The opt-in adapter requires a server-owned transactional PostgreSQL connection.
PostgREST alone cannot keep a transaction open across an HTTP send. Deployment and
configuring persistent database access remain separately approved rollout work.
The repository optional dependency `lifetime-memory` supplies psycopg; tests use
an isolated synthetic local database, not a configured Supabase service.

The linearization boundary is completed ASGI send versus correction transaction
commit. Lock the project, authoritative profile, then lease; validate the immutable
per-body fence; await the actual send; close/rollback. Queue insertion, producer
completion and a prior RPC check are not publication. Dequeued text, final results,
saved receipts containing personal context and nonstream JSON need this same guard.
No old queued body may inherit a newer fence. Bytes already delivered or buffered
in the network cannot be recalled, and this implementation does not claim otherwise.

Send duration is at most two seconds by default, at most five by configuration,
and shorter than the remaining lease by 100 ms. Lock acquisition is separately
bounded. Disconnect, timeout and cancellation close the connection and release
locks. Never wait for producer work or another RPC while holding the send guard.

Lock graph:
- publication/capture: project -> profile -> lease; read identity after locks
- existing interview acceptance: project -> profile
- phase/plan publication: project -> profile -> lease
- direct preference write: profile -> identity revision, never project
- policy invalidation: project -> profile -> identity -> disposable continuity
No identity mutator may subsequently acquire profile. A fresh empty profile row is
created under project before the fence is captured, so absence cannot bypass locking.

The additive epoch trigger clears the disposable execution pointer and removes typed
continuity projections when policy changes. It does not erase canonical sources,
receipts, or historical backups. Prior user-wide unprovenanced generated memory must
not be fed to governed execution. Collector integration guards actual outer ASGI sends and both worker/in-process
request admission. Direct personal-context WebRTC is disabled in the governed mode
until equivalently revocable. Composer, collection jobs and additional read routes
have their own acceptance gates in `lifetime-memory-integration.md`.

The isolated cold-open helper supports one compatible resume and one canonical
cold fallback for typed state errors. The integrated collector currently always
uses canonical cold execution in a fresh ephemeral home; it does not claim compatible
engine resume has been demonstrated. Authentication/provider errors remain explicit.
Returned thread IDs are only candidates; installation occurs in the same valid
fenced transaction as the reply commit.
